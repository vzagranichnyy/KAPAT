import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "klipper_extras"))
from kapat import pa_analysis_core as core  # noqa: E402


SLOW_V = 1.92
FAST_V = 19.24


def _make_k_window(k, true_k, k_index, rate_hz=2000, slow_s=1.0, fast_s=0.25,
                    cycles=3, lag_gain=0.5, lp_tau=0.01, seed=0):
    """Build one K's worth of samples the way Klipper's collector would
    hand them back: a continuous slice of (t, force) covering `cycles`
    slow/fast/slow legs back to back, plus the exact rising/falling
    print-time lists register_lookahead_callback would have recorded.

    The synthetic force is the commanded step waveform time-shifted by
    lag_gain*(true_k - k) seconds (positive => under-compensated => force
    arrives late), low-passed through a fixed (K-independent) melt-time-
    constant, plus noise — a direct test of what phase_lag_ms/
    integral_area are built to measure (a time shift), not a full
    physical simulation.

    Returns (t_lo, t_hi, rising, falling, t_slice, f_slice) all on a
    shared "absolute sweep time" axis that starts at k_index*100 seconds
    (arbitrary offset per K, the way successive K's windows never
    overlap in a real sweep).
    """
    dt = 1.0 / rate_hz
    period = slow_s + fast_s
    t0 = k_index * 100.0  # keep each K's window far apart, like a real sweep
    t = t0 + np.arange(0, cycles * period + slow_s, dt)

    command = np.full_like(t, SLOW_V)
    rising, falling = [], []
    for c in range(cycles):
        rise_t = t0 + slow_s + c * period
        fall_t = rise_t + fast_s
        command[(t >= rise_t) & (t < fall_t)] = FAST_V
        rising.append(rise_t)
        falling.append(fall_t)

    lag_s = lag_gain * (true_k - k)
    shifted = np.interp(t - lag_s, t, command,
                         left=command[0], right=command[-1])
    lp = np.zeros_like(t)
    lp[0] = shifted[0]
    for i in range(1, len(t)):
        lp[i] = lp[i - 1] + (shifted[i] - lp[i - 1]) * (dt / lp_tau)
    force = lp + np.random.default_rng(seed).normal(0, 0.05, size=t.shape)

    return t[0], t[-1], rising, falling, t, force


def _build_sweep(ks, true_k, cycles=3, **kwargs):
    windows, transitions = [], []
    t_parts, f_parts = [], []
    for i, k in enumerate(ks):
        t_lo, t_hi, rising, falling, t_slice, f_slice = _make_k_window(
            k, true_k, i, cycles=cycles, seed=i, **kwargs)
        windows.append((t_lo, t_hi))
        transitions.append((rising, falling))
        t_parts.append(t_slice)
        f_parts.append(f_slice)
    t_all = np.concatenate(t_parts)
    f_all = np.concatenate(f_parts)
    order = np.argsort(t_all)
    return t_all[order], f_all[order], windows, transitions


def test_phase_lag_crosses_zero_near_true_k():
    true_k = 0.04
    ks = [0.0, 0.02, 0.04, 0.06, 0.08]
    t_all, f_all, windows, transitions = _build_sweep(ks, true_k)
    result = core.analyse_sweep_segments(
        t_all, f_all, ks, windows, transitions,
        slow_v=SLOW_V, fast_v=FAST_V, slow_half_s=1.0, fast_half_s=0.25,
        cycle_period_s=1.25)
    assert result.phase_fit is not None, result.notes
    assert abs(result.phase_fit.k_opt - true_k) < 0.02, (
        result.phase_fit, [r.phase_lag_ms for r in result.per_k])


def test_integral_area_crosses_zero_near_true_k():
    true_k = 0.05
    ks = [0.0, 0.025, 0.05, 0.075, 0.10]
    t_all, f_all, windows, transitions = _build_sweep(ks, true_k)
    result = core.analyse_sweep_segments(
        t_all, f_all, ks, windows, transitions,
        slow_v=SLOW_V, fast_v=FAST_V, slow_half_s=1.0, fast_half_s=0.25,
        cycle_period_s=1.25)
    assert result.integral_fit is not None, result.notes
    assert abs(result.integral_fit.k_opt - true_k) < 0.02, (
        result.integral_fit, [r.integral_area for r in result.per_k])


def test_argmin_with_parabolic_finds_valley():
    ks = np.array([0.0, 0.02, 0.04, 0.06, 0.08])
    cost = np.array([5.0, 2.0, 0.5, 1.5, 4.0])  # valley near 0.04-ish
    k_opt = core.argmin_with_parabolic(ks, cost)
    assert k_opt is not None
    assert 0.03 < k_opt < 0.05


def test_multi_cycle_windows_produce_one_result_per_k():
    # cycles=3 (vs 1) should still yield exactly one KResult per K —
    # smoke test that multiple transitions within a window are all used
    # rather than only the first.
    true_k = 0.04
    ks = [0.0, 0.04, 0.08]
    t_all, f_all, windows, transitions = _build_sweep(ks, true_k, cycles=3)
    result = core.analyse_sweep_segments(
        t_all, f_all, ks, windows, transitions,
        slow_v=SLOW_V, fast_v=FAST_V, slow_half_s=1.0, fast_half_s=0.25,
        cycle_period_s=1.25)
    assert len(result.per_k) == 3
    assert all(r.n_samples > 0 for r in result.per_k)


if __name__ == "__main__":
    test_phase_lag_crosses_zero_near_true_k()
    test_integral_area_crosses_zero_near_true_k()
    test_argmin_with_parabolic_finds_valley()
    test_multi_cycle_windows_produce_one_result_per_k()
    print("all Stage A core tests passed")
