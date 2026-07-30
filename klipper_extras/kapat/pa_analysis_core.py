"""
kapat.pa_analysis_core — Stage A: core K_opt estimators, ported near-
verbatim from CNCKitchen/PrusaPATuner's src/prusa_pa_tuner/analysis.py
(functions: _resample_uniform, _detrend, _parabolic_peak, _phase_lag_ms,
_integral_area_legacy, _integral_area, _argmin_with_parabolic,
_linear_fit_zero_crossing). Formulas and comments are kept as close to the
original as possible so the two implementations can be diffed by eye.

What's DELIBERATELY NOT here yet (Stage B, next pass):
  - _bd_segment_metrics and the bd_pressure composite-cost pipeline (the
    8-region / 14-metric step-response analysis) — ~470 lines, needs its
    own dedicated port + tests.
  - The whole sweep-start / cycle-boundary DETECTION layer (_detect_
    sweep_start, _detect_pos_transitions, _detect_z_marker_anchor,
    _slice_from_force_cycles, etc. — ~1300 lines in the original). This
    exists in PrusaPATuner ONLY because Buddy doesn't expose G-code
    execution timestamps synced to the loadcell's clock, so the analyser
    has to reconstruct cycle boundaries from the signal itself.

    KAPAT does not have that problem: kapat_pa_sweep.py already records
    exact (k, cycle, t_start, t_end) triples in Klipper's print_time — the
    SAME clock load_cell/dump_force timestamps its samples on. So instead
    of detecting where each cycle started, we already know. This whole
    detection layer is structurally unnecessary for KAPAT and is not
    planned to be ported at all (not "later" — just not needed).

Coverage/dropout quality gates (KResult.coverage, .dropouts) are also
deferred to Stage B, once we decide whether KAPAT needs them at all —
they exist in PrusaPATuner to guard against UDP packet loss, which isn't
a failure mode Klipper's own transport has in the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import signal as sps


# ---------------------------------------------------------------------
# Dataclasses (trimmed subset of PrusaPATuner's KResult/FitResult — the
# coverage/dropout fields are Stage B, dropped here rather than faked)
# ---------------------------------------------------------------------
@dataclass
class KResult:
    k: float
    n_samples: int
    phase_lag_ms: float
    integral_area: float
    integral_area_legacy: float
    force_mean: float
    force_std: float


@dataclass
class FitResult:
    k_opt: float
    slope: float
    intercept: float
    r_squared: float
    method: str  # "phase_lag" or "integral"


@dataclass
class SweepAnalysisCore:
    per_k: list[KResult]
    phase_fit: FitResult | None
    integral_fit: FitResult | None
    integral_legacy_fit: FitResult | None
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------
# Verbatim ports (see PrusaPATuner's analysis.py for the original
# docstrings this is copied from — kept in full below since the reasoning
# in them is exactly why the formulas are shaped this way)
# ---------------------------------------------------------------------
def _resample_uniform(
    t: np.ndarray, y: np.ndarray, dt: float
) -> tuple[np.ndarray, np.ndarray]:
    """Linear-interpolate (t, y) onto a uniform grid with spacing dt."""
    if len(t) < 2:
        return np.array([]), np.array([])
    t0 = t[0]
    t1 = t[-1]
    n = max(2, int(np.floor((t1 - t0) / dt)) + 1)
    grid = t0 + np.arange(n) * dt
    return grid, np.interp(grid, t, y)


def _detrend(y: np.ndarray) -> np.ndarray:
    if len(y) < 4:
        return y - np.mean(y) if len(y) else y
    return sps.detrend(y, type="linear")


def _parabolic_peak(corr: np.ndarray, lags: np.ndarray) -> float:
    """Sub-sample interpolation of the cross-correlation peak.

    Fits a parabola to the peak and its two neighbours, returns the
    interpolated lag.
    """
    if len(corr) < 3:
        return 0.0
    i = int(np.argmax(corr))
    if i == 0 or i == len(corr) - 1:
        return float(lags[i])
    y0, y1, y2 = corr[i - 1], corr[i], corr[i + 1]
    denom = y0 - 2.0 * y1 + y2
    if denom == 0:
        return float(lags[i])
    delta = 0.5 * (y0 - y2) / denom
    return float(lags[i] + delta * (lags[1] - lags[0]))


def phase_lag_ms(
    force: np.ndarray, command: np.ndarray, dt: float, max_lag_s: float = 1.0
) -> float:
    """Cross-correlate force vs command, return peak lag in milliseconds.

    Positive lag => force lags the command (over-PA, K too high in some
    sign conventions; we just present the raw lag and let the linear fit
    pick zero-crossing).

    Returns NaN when the cross-correlation peak hits the ±max_lag
    boundary — that's a sign the search range was too narrow or the
    signals don't share a peak inside it (typical when the cycle period
    >= max_lag, which makes the correlation alias to the next cycle and
    pin against the boundary). Letting boundary-saturated values into the
    linear fit produces non-monotonic K-vs-lag scatter.
    """
    if len(force) < 8 or len(command) < 8:
        return float("nan")
    f = _detrend(force)
    c = _detrend(command)
    # Normalise to make r^2 ~comparable across K values
    f = f / (np.std(f) + 1e-12)
    c = c / (np.std(c) + 1e-12)
    corr = sps.correlate(f, c, mode="full")
    lags_idx = sps.correlation_lags(len(f), len(c), mode="full")
    lags_s = lags_idx * dt
    mask = np.abs(lags_s) <= max_lag_s
    if not mask.any():
        return float("nan")
    masked_corr = corr[mask]
    masked_lags = lags_s[mask]
    peak_i = int(np.argmax(masked_corr))
    # Reject boundary hits: they're aliased or noise.
    if peak_i == 0 or peak_i == len(masked_corr) - 1:
        return float("nan")
    peak_lag_s = _parabolic_peak(masked_corr, masked_lags)
    return peak_lag_s * 1000.0


def integral_area_legacy(force: np.ndarray, command: np.ndarray) -> float:
    """Legacy: integrate (F - mean) * sign(dCommand/dt) over the whole
    window.

    Equivalent to the original Snapmaker-style formulation. Kept around
    so the UI can plot it side-by-side with the centered-window form —
    on real hardware this version's "sign window" is just the accel ramp
    at each transition (well under the melt-pressure τ), so it's
    dominated by an intrinsic-τ baseline and barely moves with K. The
    centered-window `integral_area` below should show a visibly steeper
    slope vs K and a less wild zero-crossing.
    """
    if len(force) < 4 or len(command) < 4:
        return float("nan")
    f = force - np.mean(force)
    dc = np.diff(command, prepend=command[0])
    sign = np.sign(dc)
    return float(np.sum(f * sign))


def integral_area(
    force: np.ndarray,
    command: np.ndarray,
    dt: float,
    window_s: float | None = None,
    transition_idx: np.ndarray | None = None,
    directions: np.ndarray | None = None,
) -> float:
    """Snapmaker-style PA error, integrated over a window CENTERED on
    each velocity transition.

    For each slow→fast (direction +1) and fast→slow (direction −1)
    crossing of the command's mid-level, integrate (F − local_mean) over
    half_win samples on either side. Each cycle uses its OWN local mean
    (over the [t_rise-hw, t_fall+hw] span around that cycle's two
    transitions), so slow loadcell drift across a long sweep doesn't
    bias the per-K metric. Two windows that bracket the same transition
    cannot overlap: each is clipped at the midpoint between adjacent
    transitions.

    Why centered, not forward-only: forward-only windows make leads
    (force-leads-command, K < K_opt) and lags (K > K_opt) asymmetric —
    the fit slope then biases K_opt toward higher K. Centered windows are
    symmetric in lead/lag and produce a clean zero-crossing at K_opt.

    Why a NARROW window (≈ melt-pressure τ, not "as wide as fits"): too
    wide a window fills mostly with plateau samples, so the metric reads
    "average plateau bias" and drifts with loadcell zero.

    `window_s` defaults to whichever is smaller: 150 ms or half the
    shortest leg duration (so windows never bleed into adjacent
    transitions).

    `transition_idx` / `directions` (optional): supply these directly
    when you already know exact transition sample indices (KAPAT always
    does — they come straight from the manifest's per-cycle t_start/
    t_end, not from detecting them in the signal). Direction convention:
    +1 = slow→fast, -1 = fast→slow.
    """
    n = len(force)
    if n < 4 or len(command) < 4:
        return float("nan")

    if (
        transition_idx is not None
        and directions is not None
        and len(transition_idx) >= 2
    ):
        transition_idx = np.asarray(transition_idx, dtype=int)
        directions = np.asarray(directions, dtype=np.float64)
    else:
        # Fallback: mid-level crossings of the command wave (robust to
        # whatever ramp shape the firmware actually uses).
        c_lo = float(np.percentile(command, 10))
        c_hi = float(np.percentile(command, 90))
        if c_hi - c_lo < 1e-6:
            return float("nan")
        c_mid = 0.5 * (c_lo + c_hi)
        above = command > c_mid
        crossings = np.diff(above.astype(np.int8))
        transition_idx = np.where(crossings != 0)[0] + 1
        if len(transition_idx) < 2:
            return float("nan")
        directions = crossings[transition_idx - 1].astype(np.float64)

    if window_s is None:
        gaps = np.diff(transition_idx)
        min_leg_s = float(gaps.min()) * dt if len(gaps) else 0.0
        if min_leg_s <= 0:
            return float("nan")
        window_s = min(0.15, 0.5 * min_leg_s)
    half_win = max(1, int(round(0.5 * window_s / max(dt, 1e-9))))

    total = 0.0
    i = 0
    while i < len(transition_idx):
        idx_a = int(transition_idx[i])
        start_a = max(0, idx_a - half_win)
        end_a = min(n, idx_a + half_win)
        if i > 0:
            mid_prev = (int(transition_idx[i - 1]) + idx_a) // 2
            start_a = max(start_a, mid_prev)
        if i + 1 < len(transition_idx):
            mid_nxt_a = (idx_a + int(transition_idx[i + 1])) // 2
            end_a = min(end_a, mid_nxt_a)

        has_pair = i + 1 < len(transition_idx)
        if has_pair:
            idx_b = int(transition_idx[i + 1])
            start_b = max(0, idx_b - half_win)
            end_b = min(n, idx_b + half_win)
            mid_between = (idx_a + idx_b) // 2
            start_b = max(start_b, mid_between)
            if i + 2 < len(transition_idx):
                mid_nxt_b = (idx_b + int(transition_idx[i + 2])) // 2
                end_b = min(end_b, mid_nxt_b)

            local_lo = min(start_a, start_b)
            local_hi = max(end_a, end_b)
            if local_hi - local_lo >= 2:
                local_mean = float(np.mean(force[local_lo:local_hi]))
                if end_a > start_a:
                    total += (
                        float(directions[i])
                        * float(np.sum(force[start_a:end_a] - local_mean))
                        * dt
                    )
                if end_b > start_b:
                    total += (
                        float(directions[i + 1])
                        * float(np.sum(force[start_b:end_b] - local_mean))
                        * dt
                    )
            i += 2
        else:
            if end_a - start_a >= 2:
                local_mean = float(np.mean(force[start_a:end_a]))
                total += (
                    float(directions[i])
                    * float(np.sum(force[start_a:end_a] - local_mean))
                    * dt
                )
            i += 1
    return total


def argmin_with_parabolic(
    k_values: np.ndarray, cost: np.ndarray
) -> float | None:
    """K at the minimum of cost(K), with sub-step parabolic interpolation.

    Returns None if no finite cost value is available. Returns
    K[argmin] (no interpolation) when the minimum is at a boundary, or
    when the local 3-point fit is non-concave-up (noise-dominated). The
    interpolated vertex is clamped to the local 3-point K range so we
    never extrapolate beyond the sweep.
    """
    if len(k_values) == 0 or len(cost) == 0:
        return None
    finite = np.isfinite(cost)
    if not finite.any():
        return None
    k_f = k_values[finite].astype(float)
    c_f = cost[finite].astype(float)
    i = int(np.argmin(c_f))
    if len(c_f) < 3 or i == 0 or i == len(c_f) - 1:
        return float(k_f[i])
    x0, x1, x2 = float(k_f[i - 1]), float(k_f[i]), float(k_f[i + 1])
    y0, y1, y2 = float(c_f[i - 1]), float(c_f[i]), float(c_f[i + 1])
    denom = (x0 - x1) * (x0 - x2) * (x1 - x2)
    if denom == 0:
        return float(x1)
    a = (x2 * (y1 - y0) + x1 * (y0 - y2) + x0 * (y2 - y1)) / denom
    b = (
        x2 * x2 * (y0 - y1)
        + x1 * x1 * (y2 - y0)
        + x0 * x0 * (y1 - y2)
    ) / denom
    if a <= 0:
        return float(x1)
    vertex = -b / (2.0 * a)
    return float(max(min(vertex, x2), x0))


def linear_fit_zero_crossing(
    k_values: np.ndarray, y_values: np.ndarray, method: str
) -> FitResult | None:
    """Fit y = m*k + b, return k where y = 0 and the R²."""
    mask = np.isfinite(y_values)
    if mask.sum() < 2:
        return None
    k = k_values[mask].astype(float)
    y = y_values[mask].astype(float)
    if np.allclose(np.std(k), 0):
        return None
    slope, intercept = np.polyfit(k, y, 1)
    if slope == 0:
        return None
    k_opt = -intercept / slope
    y_pred = slope * k + intercept
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 1.0
    return FitResult(
        k_opt=float(k_opt),
        slope=float(slope),
        intercept=float(intercept),
        r_squared=r2,
        method=method,
    )


# ---------------------------------------------------------------------
# KAPAT-specific glue: consumes exactly the shape Klipper's load_cell
# collector + register_lookahead_callback produce (see autopa/sweep.py,
# whose windows/transitions this mirrors) — no separate manifest file,
# no Burst dataclass. `windows` is a list of (t_k0, t_k1) per K (sweep-
# relative seconds); `transitions` is a parallel list of (rising, falling)
# print-time lists, one entry per cycle, where `rising` = the slow->fast
# leg boundary and `falling` = the fast->slow leg boundary. Because these
# come from toolhead.register_lookahead_callback at G-code generation
# time, they're exact — no cycle-boundary detection needed at all (see
# module docstring for why PrusaPATuner needs ~1300 lines for that and we
# don't).
# ---------------------------------------------------------------------
def _build_command_signal(
    t: np.ndarray, transitions_k, slow_v: float, fast_v: float
) -> np.ndarray:
    """Piecewise step function over `t`: fast_v between each (rising,
    falling) pair, slow_v elsewhere. transitions_k: list of (rising,
    falling) print-time pairs for this K's cycles, already offset onto
    the same continuous timeline as `t`."""
    command = np.full_like(t, slow_v, dtype=float)
    for rising, falling in transitions_k:
        for r, f in zip(rising, falling):
            command[(t >= r) & (t < f)] = fast_v
    return command


def analyse_sweep_segments(
    t_rel: np.ndarray,
    force: np.ndarray,
    ks: list,
    windows: list,
    transitions: list,
    slow_v: float,
    fast_v: float,
    slow_half_s: float,
    fast_half_s: float,
    cycle_period_s: float,
) -> SweepAnalysisCore:
    """t_rel/force: the FULL sweep's samples (sweep-relative seconds,
    already `-= t0` by the caller — see kapat.py's cmd_KAPAT_SWEEP).
    ks/windows/transitions: parallel per-K lists, same shape as
    autopa.sweep.SweepMixin.cmd_AUTOPA_SWEEP builds them (windows in
    absolute print_time still — offset to sweep-relative inside this
    function, matching what the caller already did to t_rel)."""
    notes: list[str] = []
    per_k: list[KResult] = []
    ks_used: list[float] = []
    lags: list[float] = []
    areas: list[float] = []
    areas_legacy: list[float] = []

    for k, (t_lo, t_hi), (rising, falling) in zip(ks, windows, transitions):
        mask = (t_rel >= t_lo) & (t_rel <= t_hi)
        if not np.any(mask):
            notes.append(f"K={k:.4f}: no samples in window, skipped")
            continue
        t_k = t_rel[mask]
        f_k = force[mask]
        if len(t_k) < 8:
            notes.append(f"K={k:.4f}: too few samples ({len(t_k)}), skipped")
            continue

        command_k = _build_command_signal(t_k, [(rising, falling)],
                                            slow_v, fast_v)

        dt_est = float(np.median(np.diff(t_k))) if len(t_k) > 1 else 0.001
        grid, f_grid = _resample_uniform(t_k, f_k, dt_est)
        _, c_grid = _resample_uniform(t_k, command_k, dt_est)
        if len(grid) < 8:
            notes.append(f"K={k:.4f}: resample produced too few points, skipped")
            continue

        # transition_idx/directions for the centered-window integral_area:
        # nearest grid index to each rising (+1) / falling (-1) crossing,
        # in chronological order.
        crossings = sorted(
            [(r, 1) for r in rising] + [(f, -1) for f in falling])
        transition_idx = np.array(
            [int(np.argmin(np.abs(grid - t))) for t, _ in crossings])
        directions = np.array([d for _, d in crossings])
        half_win = max(1, int(round(min(slow_half_s, fast_half_s) / dt_est)))

        lag = phase_lag_ms(f_grid, c_grid, dt_est,
                            max_lag_s=max(0.5, cycle_period_s))
        area = integral_area(f_grid, c_grid, dt_est,
                              window_s=None,
                              transition_idx=transition_idx,
                              directions=directions) \
            if len(transition_idx) else float("nan")
        area_legacy = integral_area_legacy(f_grid, c_grid)

        per_k.append(KResult(
            k=k, n_samples=len(grid), phase_lag_ms=lag,
            integral_area=area, integral_area_legacy=area_legacy,
            force_mean=float(np.mean(f_grid)), force_std=float(np.std(f_grid)),
        ))
        ks_used.append(k)
        lags.append(lag)
        areas.append(area)
        areas_legacy.append(area_legacy)

    ks_arr = np.asarray(ks_used, dtype=float)
    phase_fit = linear_fit_zero_crossing(ks_arr, np.asarray(lags), "phase_lag")
    integral_fit = linear_fit_zero_crossing(ks_arr, np.asarray(areas), "integral")
    integral_legacy_fit = linear_fit_zero_crossing(
        ks_arr, np.asarray(areas_legacy), "integral_legacy")

    if phase_fit is None:
        notes.append("Phase-lag fit failed — insufficient data or zero slope.")
    if integral_fit is None:
        notes.append("Integral-area fit failed — insufficient data or zero slope.")

    return SweepAnalysisCore(
        per_k=per_k, phase_fit=phase_fit, integral_fit=integral_fit,
        integral_legacy_fit=integral_legacy_fit, notes=notes,
    )
