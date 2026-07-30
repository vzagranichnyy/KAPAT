import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "klipper_extras"))
from kapat import bd_pressure as bd  # noqa: E402


def _make_cycle_trace(k, true_k, t0, rate_hz=2000, slow_s=1.0, fast_s=0.25,
                       overshoot_gain=8.0, seed=0):
    """One low->high->low cycle modeling real PA behavior: overshoot (a
    bulge above high_level right after the rise) appears ONLY when K is
    too HIGH (over-advance), growing monotonically past true_k; undershoot
    (a dip below the settled baseline right after the fall) appears ONLY
    when K is too LOW (under-advance), growing monotonically below
    true_k. Both are ~0 at true_k. This matches PrusaPATuner's actual
    per-metric behavior (each metric individually monotonic, often
    pinned at a sweep boundary) rather than each metric independently
    forming a valley at true_k -- only the weighted composite does that,
    by combining metrics that respond to opposite-signed mismatch.
    Returns (t, force, t_start, t_rise, t_fall, t_end) for this cycle.
    """
    dt = 1.0 / rate_hz
    t = t0 + np.arange(0, slow_s + fast_s + slow_s, dt)
    t_start, t_rise, t_fall, t_end = t0, t0 + slow_s, t0 + slow_s + fast_s, t[-1]

    baseline, high = 0.0, 10.0
    force = np.full_like(t, baseline)
    force[(t >= t_rise) & (t < t_fall)] = high
    force[(t >= t_fall)] = baseline

    mismatch = k - true_k
    overshoot_amt = max(0.0, mismatch) * overshoot_gain   # only if K too high
    undershoot_amt = max(0.0, -mismatch) * overshoot_gain  # only if K too low

    bump_rise = overshoot_amt * np.exp(
        -np.clip(t - t_rise, 0, None) / 0.03) * ((t >= t_rise) & (t < t_fall))
    bump_fall = -undershoot_amt * np.exp(
        -np.clip(t - t_fall, 0, None) / 0.03) * (t >= t_fall)

    force = force + bump_rise + bump_fall
    force += np.random.default_rng(seed).normal(0, 0.05, size=t.shape)
    return t, force, t_start, t_rise, t_fall, t_end


def _build_sweep(ks, true_k, cycles=4, cycle_period=100.0):
    """Lay out `cycles` repeats per K, K's far apart on the timeline (like
    a real sweep), and return (t_all, force_all, cycle_windows) ready for
    bd_pressure.bd_aggregate_per_k / analyse_bd."""
    t_parts, f_parts, cycle_windows = [], [], []
    for ki, k in enumerate(ks):
        windows = []
        for c in range(cycles):
            t0 = ki * 1000.0 + c * cycle_period
            t, force, ts, tr, tf, te = _make_cycle_trace(
                k, true_k, t0, seed=ki * 100 + c)
            t_parts.append(t)
            f_parts.append(force)
            windows.append((ts, tr, tf, te))
        cycle_windows.append(windows)
    t_all = np.concatenate(t_parts)
    f_all = np.concatenate(f_parts)
    order = np.argsort(t_all)
    return t_all[order], f_all[order], cycle_windows


def test_bd_segment_metrics_basic_shape():
    ks = [0.04]
    true_k = 0.04
    t_all, f_all, cycle_windows = _build_sweep(ks, true_k, cycles=1)
    ts, tr, tf, te = cycle_windows[0][0]
    m = bd.bd_segment_metrics(t_all, f_all, ts, tr, tf, te)
    assert m is not None
    assert abs(m["baseline_median"]) < 0.5
    assert abs(m["high_level"] - 10.0) < 1.0
    for name in bd.BD_METRIC_NAMES:
        assert name in m


def test_overshoot_only_grows_above_true_k_undershoot_only_below():
    true_k = 0.04
    ks = [0.0, 0.02, 0.04, 0.06, 0.08]
    t_all, f_all, cycle_windows = _build_sweep(ks, true_k, cycles=6)
    per_k = bd.bd_aggregate_per_k(t_all, f_all, ks, cycle_windows)
    by_k = {kr.k: kr for kr in per_k}
    # overshoot: ~0 at and below true_k, grows above it
    assert by_k[0.04].medians["overshoot"] < 0.5
    assert by_k[0.08].medians["overshoot"] > by_k[0.04].medians["overshoot"]
    assert by_k[0.06].medians["overshoot"] > by_k[0.04].medians["overshoot"]
    # undershoot: ~0 at and above true_k, grows below it
    assert by_k[0.04].medians["undershoot"] < 0.5
    assert by_k[0.0].medians["undershoot"] > by_k[0.04].medians["undershoot"]
    assert by_k[0.02].medians["undershoot"] > by_k[0.04].medians["undershoot"]


def test_composite_cost_finds_valley_near_true_k():
    true_k = 0.04
    ks = [0.0, 0.02, 0.04, 0.06, 0.08]
    t_all, f_all, cycle_windows = _build_sweep(ks, true_k, cycles=6)
    weights = {"overshoot": 1.0, "undershoot": 1.0}  # only the two metrics
    # this synthetic model actually drives, so the valley is unambiguous
    result = bd.analyse_bd(t_all, f_all, ks, cycle_windows, weights=weights)
    assert result.composite_k_opt is not None, result.notes
    assert abs(result.composite_k_opt - true_k) < 0.02, (
        result.composite_k_opt, [(kr.k, kr.medians) for kr in result.per_k])


def test_per_metric_k_opt_reported_for_all_metrics():
    # Real bd_pressure metrics are individually monotonic (often pinned at
    # a sweep boundary) rather than each forming its own valley at
    # true_k -- this just checks every metric gets SOME K_opt reported,
    # not that each one lands near true_k (only the composite should).
    true_k = 0.05
    ks = [0.0, 0.025, 0.05, 0.075, 0.10]
    t_all, f_all, cycle_windows = _build_sweep(ks, true_k, cycles=5)
    result = bd.analyse_bd(t_all, f_all, ks, cycle_windows)
    assert set(result.metric_k_opt.keys()) == set(bd.BD_METRIC_NAMES)
    for name, k_opt in result.metric_k_opt.items():
        assert k_opt is None or (ks[0] <= k_opt <= ks[-1]), (name, k_opt)


if __name__ == "__main__":
    test_bd_segment_metrics_basic_shape()
    test_overshoot_only_grows_above_true_k_undershoot_only_below()
    test_composite_cost_finds_valley_near_true_k()
    test_per_metric_k_opt_reported_for_all_metrics()
    print("all Stage B bd_pressure tests passed")
