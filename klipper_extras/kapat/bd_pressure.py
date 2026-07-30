"""
kapat.bd_pressure — Stage B: the bd_pressure step-response estimator.

Ported from CNCKitchen/PrusaPATuner's src/prusa_pa_tuner/analysis.py
(_bd_segment_metrics / _bd_aggregate_per_k / _bd_compute_normalised /
_bd_compute_cost and friends). Metric NAMES, the 8-region breakdown, and
the overall composite-cost design are ported faithfully to what was
directly inspected in that source and in PrusaPATuner's own UI output
(the per-K segment browser and per-metric K_opt panels). Some internal
window-sizing constants below (e.g. what fraction of the plateau counts
as "settled", the exact rise/fall threshold crossing) are this author's
own reasonable reconstruction rather than a guaranteed byte-for-byte copy
of the original thresholds — the original file is long enough that a
byte-exact port without the source physically in front of you risks
silently getting a constant wrong, which is worse than being upfront that
these specific numbers are a faithful-spirit reimplementation. If you
have upstream's exact constants and they differ, they should win.

Each low->high->low cycle (one "segment") is scored across 8 regions:
  1. low baseline   (before the rise)      -> baseline_median, baseline_noise_std
  2. rising edge     (just after rise)       -> rise_delay, rise_error_area
  3. overshoot       (peak right after rise) -> overshoot
  4. high plateau    (steady high level)     -> high_level
  5. plateau creep   (drift across plateau)  -> plateau_slope, plateau_creep
  6. falling edge    (just after fall)       -> fall_delay, fall_error_area
  7. undershoot      (dip right after fall)  -> undershoot
  8. recovery tail   (settling back down)    -> tail_area, settling_time

12 metrics total. Each is minimised (or driven to zero) at the correctly-
tuned K; the composite cost is a user-weighted sum of each metric
normalised across the swept K range, and its own K_opt is the argmin
(with parabolic sub-step interpolation, see pa_analysis_core.argmin_with_
parabolic). Each individual metric ALSO gets its own argmin, shown
side-by-side in the UI so a user can see whether every metric agrees on
roughly the same K or whether one outlier is dragging the composite
around — which is exactly why the composite exists as a weighted
combination in the first place rather than a single hard-coded formula.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .pa_analysis_core import argmin_with_parabolic

BD_METRIC_NAMES = [
    "baseline_median", "baseline_noise_std",
    "rise_delay", "rise_error_area",
    "overshoot",
    "high_level",
    "plateau_slope", "plateau_creep",
    "fall_delay", "fall_error_area",
    "undershoot",
    "tail_area", "settling_time",
]

# Which metrics should be minimised toward zero (a real physical zero,
# e.g. overshoot/undershoot/creep) vs. minimised toward whatever their
# natural low value is (e.g. noise floor, plateau level) — matters for
# normalisation: "zero-anchored" metrics are normalised against their own
# max-abs across K (so 0 always maps to 0 cost), "range" metrics are
# min-max normalised across the swept K range instead.
BD_ZERO_ANCHORED = {
    "rise_error_area", "overshoot", "plateau_slope", "plateau_creep",
    "fall_error_area", "undershoot", "tail_area",
}

BD_DEFAULT_WEIGHTS = {
    "rise_error_area": 1.0,
    "overshoot": 2.0,
    "undershoot": 2.0,
    "tail_area": 1.0,
    "plateau_slope": 0.5,
    "rise_delay": 1.0,
    "fall_delay": 1.0,
    "settling_time": 0.5,
}


@dataclass
class BdSegment:
    """One low->high->low cycle's metrics."""
    metrics: dict = field(default_factory=dict)
    included: bool = True
    exclude_reason: str | None = None


@dataclass
class BdKResult:
    k: float
    segments: list = field(default_factory=list)  # list[BdSegment]
    medians: dict = field(default_factory=dict)  # metric name -> median across segments
    lo: dict = field(default_factory=dict)  # metric name -> min across segments
    hi: dict = field(default_factory=dict)  # metric name -> max across segments
    n_segments_included: int = 0
    n_segments_total: int = 0


@dataclass
class BdAnalysis:
    per_k: list  # list[BdKResult]
    composite_k_opt: float | None
    metric_k_opt: dict  # metric name -> K_opt (argmin or zero-crossing)
    weights_used: dict
    notes: list = field(default_factory=list)


def _segment_windows(t, rise_frac=0.2, fall_frac=0.2, settle_tol_frac=0.1):
    """Fractional window boundaries shared by every region below, so all
    the "just after the edge" / "steady middle" / "settling tail" splits
    use one consistent convention rather than a different magic number
    per region."""
    return {
        "rise_frac": rise_frac,
        "fall_frac": fall_frac,
        "settle_tol_frac": settle_tol_frac,
    }


def bd_segment_metrics(t: np.ndarray, force: np.ndarray,
                        t_start: float, t_rise: float,
                        t_fall: float, t_end: float) -> dict | None:
    """Compute the 12 bd_pressure metrics for one low->high->low cycle.

    t/force: the FULL sweep's arrays (same convention as
    pa_analysis_core.analyse_sweep_segments) — this function slices out
    what it needs internally.
    t_start/t_rise/t_fall/t_end: exact print-time boundaries of this
    cycle (from register_lookahead_callback in kapat/__init__.py — no
    detection needed, see that module's docstring).

    Returns None if there isn't enough data in some region to compute a
    metric (rather than silently returning NaN-filled garbage that would
    quietly poison a median).
    """
    baseline_mask = (t >= t_start) & (t < t_rise)
    high_mask = (t >= t_rise) & (t < t_fall)
    tail_mask = (t >= t_fall) & (t < t_end)
    if baseline_mask.sum() < 3 or high_mask.sum() < 3 or tail_mask.sum() < 3:
        return None

    t_base, f_base = t[baseline_mask], force[baseline_mask]
    t_high, f_high = t[high_mask], force[high_mask]
    t_tail, f_tail = t[tail_mask], force[tail_mask]

    baseline_median = float(np.median(f_base))
    baseline_noise_std = float(np.std(f_base))

    high_dur = t_high[-1] - t_high[0] if len(t_high) > 1 else 0.0
    tail_dur = t_tail[-1] - t_tail[0] if len(t_tail) > 1 else 0.0

    # --- rising edge + overshoot: first rise_frac of the high window ---
    rise_edge_end = t_rise + max(high_dur * 0.2, 1e-3)
    rise_edge_mask = t_high < rise_edge_end
    plateau_mask = ~rise_edge_mask  # the rest of the high window

    if plateau_mask.sum() < 2:
        return None
    high_level = float(np.median(f_high[plateau_mask]))
    step_size = high_level - baseline_median

    # rise_delay: time from t_rise until force first crosses halfway
    # between baseline and high_level
    half_level = baseline_median + 0.5 * step_size
    crossed = np.where(f_high >= half_level)[0] if step_size >= 0 else \
        np.where(f_high <= half_level)[0]
    rise_delay = float(t_high[crossed[0]] - t_rise) if len(crossed) else \
        float(high_dur)

    # rise_error_area: |actual - ideal step| integrated over the rise edge
    dt_high = float(np.median(np.diff(t_high))) if len(t_high) > 1 else 1e-3
    ideal_rise = np.where(t_high[rise_edge_mask] >= rise_delay + t_rise,
                          high_level, baseline_median)
    rise_error_area = float(np.sum(
        np.abs(f_high[rise_edge_mask] - ideal_rise)) * dt_high) \
        if rise_edge_mask.sum() else 0.0

    # overshoot: how far the rise-edge peak exceeds high_level (signed:
    # positive step => overshoot is exceeding above; negative step (force
    # falling) => overshoot is undershooting below high_level on the way in)
    if rise_edge_mask.sum():
        edge_vals = f_high[rise_edge_mask]
        overshoot = float(max(0.0, (np.max(edge_vals) - high_level))
                          if step_size >= 0 else
                          max(0.0, (high_level - np.min(edge_vals))))
    else:
        overshoot = 0.0

    # --- plateau creep/slope: linear trend across the plateau region ---
    if plateau_mask.sum() >= 2:
        t_plateau = t_high[plateau_mask] - t_high[plateau_mask][0]
        f_plateau = f_high[plateau_mask]
        if np.std(t_plateau) > 0:
            slope, _ = np.polyfit(t_plateau, f_plateau, 1)
        else:
            slope = 0.0
        plateau_slope = float(slope)
        plateau_creep = float(slope * (t_plateau[-1] - t_plateau[0]))
    else:
        plateau_slope = 0.0
        plateau_creep = 0.0

    # --- falling edge + undershoot: first fall_frac of the tail window ---
    fall_edge_end = t_fall + max(tail_dur * 0.2, 1e-3)
    fall_edge_mask = t_tail < fall_edge_end
    settle_mask = ~fall_edge_mask

    if settle_mask.sum() < 2:
        return None
    final_baseline = float(np.median(f_tail[settle_mask]))

    half_level_fall = high_level + 0.5 * (final_baseline - high_level)
    crossed_fall = np.where(f_tail <= half_level_fall)[0] \
        if final_baseline <= high_level else \
        np.where(f_tail >= half_level_fall)[0]
    fall_delay = float(t_tail[crossed_fall[0]] - t_fall) \
        if len(crossed_fall) else float(tail_dur)

    dt_tail = float(np.median(np.diff(t_tail))) if len(t_tail) > 1 else 1e-3
    ideal_fall = np.where(t_tail[fall_edge_mask] >= fall_delay + t_fall,
                          final_baseline, high_level)
    fall_error_area = float(np.sum(
        np.abs(f_tail[fall_edge_mask] - ideal_fall)) * dt_tail) \
        if fall_edge_mask.sum() else 0.0

    if fall_edge_mask.sum():
        edge_vals_fall = f_tail[fall_edge_mask]
        undershoot = float(max(0.0, (final_baseline - np.min(edge_vals_fall)))
                           if final_baseline <= high_level else
                           max(0.0, (np.max(edge_vals_fall) - final_baseline)))
    else:
        undershoot = 0.0

    # --- recovery tail: residual area + time-to-settle-within-tolerance ---
    tol = max(abs(step_size) * 0.1, baseline_noise_std * 3.0, 1e-6)
    within_tol = np.abs(f_tail[settle_mask] - final_baseline) < tol
    settle_idx = 0
    for idx in range(len(within_tol)):
        if np.all(within_tol[idx:]):
            settle_idx = idx
            break
    else:
        settle_idx = len(within_tol)
    t_settle_region = t_tail[settle_mask]
    settling_time = float(t_settle_region[settle_idx] - t_fall) \
        if settle_idx < len(t_settle_region) else float(tail_dur)

    tail_area = float(np.sum(
        np.abs(f_tail[settle_mask] - final_baseline)) * dt_tail)

    return {
        "baseline_median": baseline_median,
        "baseline_noise_std": baseline_noise_std,
        "rise_delay": rise_delay,
        "rise_error_area": rise_error_area,
        "overshoot": overshoot,
        "high_level": high_level,
        "plateau_slope": plateau_slope,
        "plateau_creep": plateau_creep,
        "fall_delay": fall_delay,
        "fall_error_area": fall_error_area,
        "undershoot": undershoot,
        "tail_area": tail_area,
        "settling_time": settling_time,
    }


def bd_aggregate_per_k(t, force, ks, cycle_windows) -> list:
    """cycle_windows: parallel list to `ks`, each entry a list of
    (t_start, t_rise, t_fall, t_end) 4-tuples for that K's cycles (built
    by kapat/__init__.py directly from register_lookahead_callback's
    rising/falling lists — see cmd_KAPAT_SWEEP)."""
    results = []
    for k, cycles in zip(ks, cycle_windows):
        segments = []
        for (t_start, t_rise, t_fall, t_end) in cycles:
            m = bd_segment_metrics(t, force, t_start, t_rise, t_fall, t_end)
            if m is None:
                segments.append(BdSegment(metrics={}, included=False,
                                          exclude_reason="insufficient samples"))
            else:
                segments.append(BdSegment(metrics=m, included=True))
        included = [s for s in segments if s.included]
        medians = {}
        lo = {}
        hi = {}
        for name in BD_METRIC_NAMES:
            vals = [s.metrics[name] for s in included if name in s.metrics]
            medians[name] = float(np.median(vals)) if vals else float("nan")
            # min/max across included segments -- feeds the frontend's
            # error-bar whiskers on the per-metric grid (raw per-cycle
            # spread, not just the point estimate).
            lo[name] = float(np.min(vals)) if vals else float("nan")
            hi[name] = float(np.max(vals)) if vals else float("nan")
        results.append(BdKResult(
            k=k, segments=segments, medians=medians, lo=lo, hi=hi,
            n_segments_included=len(included), n_segments_total=len(segments),
        ))
    return results


def bd_compute_normalised(per_k: list, metric_names=None) -> dict:
    """metric name -> np.ndarray of normalised values, one per K (same
    order as per_k). Zero-anchored metrics divide by max(|value|) across
    K (so a true 0 stays 0); range metrics min-max normalise to [0, 1]."""
    if metric_names is None:
        metric_names = BD_METRIC_NAMES
    normalised = {}
    for name in metric_names:
        raw = np.array([kr.medians.get(name, float("nan")) for kr in per_k])
        finite = np.isfinite(raw)
        if not finite.any():
            normalised[name] = raw
            continue
        if name in BD_ZERO_ANCHORED:
            denom = np.max(np.abs(raw[finite]))
            normalised[name] = np.abs(raw) / denom if denom > 0 else raw * 0.0
        else:
            lo, hi = np.min(raw[finite]), np.max(raw[finite])
            span = hi - lo
            normalised[name] = (raw - lo) / span if span > 0 else raw * 0.0
    return normalised


def bd_compute_cost(normalised: dict, weights: dict) -> np.ndarray:
    """Weighted sum of normalised per-metric values -> composite cost per K."""
    total = None
    for name, weight in weights.items():
        if name not in normalised or weight == 0:
            continue
        contrib = np.nan_to_num(normalised[name], nan=0.0) * weight
        total = contrib if total is None else total + contrib
    return total if total is not None else np.array([])


def analyse_bd(t, force, ks, cycle_windows,
                weights: dict | None = None) -> BdAnalysis:
    weights = dict(BD_DEFAULT_WEIGHTS) if weights is None else weights
    notes = []
    per_k = bd_aggregate_per_k(t, force, ks, cycle_windows)
    per_k_ok = [kr for kr in per_k if kr.n_segments_included > 0]
    if len(per_k_ok) < 3:
        notes.append("bd_pressure: fewer than 3 usable K values, "
                     "composite cost not computed")
        return BdAnalysis(per_k=per_k, composite_k_opt=None,
                          metric_k_opt={}, weights_used=weights, notes=notes)

    ks_arr = np.array([kr.k for kr in per_k_ok])
    normalised = bd_compute_normalised(per_k_ok)
    cost = bd_compute_cost(normalised, weights)
    composite_k_opt = argmin_with_parabolic(ks_arr, cost) if len(cost) else None

    metric_k_opt = {}
    for name in BD_METRIC_NAMES:
        raw = np.array([kr.medians.get(name, float("nan")) for kr in per_k_ok])
        if not np.isfinite(raw).any():
            metric_k_opt[name] = None
            continue
        metric_k_opt[name] = argmin_with_parabolic(ks_arr, np.abs(raw)
                                                    if name in BD_ZERO_ANCHORED
                                                    else raw)

    return BdAnalysis(per_k=per_k, composite_k_opt=composite_k_opt,
                      metric_k_opt=metric_k_opt, weights_used=weights,
                      notes=notes)
