# KAPAT - automatic Pressure Advance calibration using a load cell
#
# Copyright (C) 2026 KAPAT contributors
# Load-cell data acquisition (get_collector/start_collecting/collect_until,
# load-cell resolution via [probe]/[load_cell], the axis-wobble PA-gate
# requirement, register_lookahead_callback for exact transition timing) is
# the pattern used by G0BL1N/autopa (AGPL-3.0):
# https://github.com/G0BL1N/autopa -- see autopa/sweep.py, whose structure
# this module's cmd_KAPAT_SWEEP mirrors closely.
#
# Analysis math (phase-lag cross-correlation, centered-window integral-area,
# linear-fit zero-crossing) is ported from CNCKitchen/PrusaPATuner
# (AGPL-3.0): https://github.com/CNCKitchen/PrusaPATuner -- see
# pa_analysis_core.py.
#
# This file may be distributed under the terms of the GNU AGPLv3 (or later)
# license.
import json
import logging
import math
import os
import re
import time

from . import pa_analysis_core as pac
from . import bd_pressure as bdp

_DEFAULT_FILAMENT_AREA = math.pi * (1.75 / 2) ** 2

# Whitelist of kvlist.js keys the get_data/set_data webhooks will read or
# write -- these back the web UI's Profiles and History tabs (and misc
# UI-configurable settings like the calibration position) as plain JSON
# files on the host (printer_data/kapat/<key>.json), replacing the
# earlier Moonraker-database-backed version so the data lives in an
# inspectable file next to printer.cfg rather than in Moonraker's DB.
_DATA_KEYS = ('profiles', 'history', 'settings')

# How many past sweeps' raw captures (.npz + .json sidecar pairs) to keep
# under printer_data/kapat/captures/ -- each one holds the full raw
# force-vs-time trace for the whole sweep, so unlike profiles/history.json
# these aren't tiny; prune old ones on every save rather than growing
# unbounded on an SBC's limited storage.
_CAPTURE_KEEP = 5

# Only letters/digits/underscore/+/- survive into a capture's on-disk
# filename (built from the filament label + temperature) -- anything
# else (spaces, slashes, dots, ..) becomes '_'. Keeps the name both
# filesystem-safe and safe as a webhook lookup key (see
# _capture_id_path, which re-validates against this same set to block
# path traversal).
_SLUG_RE = re.compile(r'[^A-Za-z0-9_+-]+')


def _slug(s):
    s = _SLUG_RE.sub('_', (s or '').strip()).strip('_')
    return s or 'unknown'


class Kapat:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self.name = config.get_name()

        # config defaults -- all overridable per-run as KAPAT_SWEEP gcode
        # params, same names, matching autopa's convention
        self.vfr = config.getfloat('vfr', 19.24, above=0.)
        self.vfr_low = config.getfloat('vfr_low', 1.92, above=0.)
        self.tslow = config.getfloat('tslow', 1.0, above=0.1, maxval=10.)
        self.tfast = config.getfloat('tfast', 0.25, above=0.05, maxval=10.)
        self.cycles = config.getint('cycles', 8, minval=3, maxval=40)
        self.kstart = config.getfloat('kstart', 0.0, minval=0.)
        self.kend = config.getfloat('kend', 0.08, minval=0.)
        self.kstep = config.getfloat('kstep', 0.005, above=0.)
        self.warmup = config.getfloat('warmup', 4.0, minval=1., maxval=30.)
        self.maxfilament = config.getfloat('maxfilament', 400., above=0.)
        self.wobble_axis = config.get('wobble_axis', 'Y').strip().upper()
        if self.wobble_axis not in ('X', 'Y'):
            raise config.error(
                "kapat: wobble_axis must be X or Y (Z does not trigger "
                "Klipper's pressure-advance gate)")
        self.wobble = config.getfloat('wobble', 0.05, minval=0.)
        self.accel = config.getfloat('accel', 1000., above=0.)
        self.apply_default = config.getboolean('apply', True)

        self._load_cell = None
        self._last = {}
        self._activity = {'state': 'idle'}
        self._cancel_requested = False

        # printer_data/kapat/ next to printer_data/config/printer.cfg --
        # derived from the running config file's path rather than
        # hardcoding ~/printer_data, so this still works under KIAUH's
        # multi-instance layout (printer_data_2, etc).
        config_file = self.printer.get_start_args().get('config_file', '')
        config_dir = os.path.dirname(config_file)
        printer_data_dir = os.path.dirname(config_dir) if config_dir else ''
        if not printer_data_dir:
            printer_data_dir = os.path.expanduser('~/printer_data')
        self._data_dir = os.path.join(printer_data_dir, 'kapat')
        self._captures_dir = os.path.join(self._data_dir, 'captures')

        self.printer.register_event_handler('klippy:ready', self._handle_ready)
        self.printer.register_event_handler('load_cell:tare', self._on_lc_event)
        self.printer.register_event_handler('load_cell:calibrate',
                                             self._on_lc_event)

        self.gcode.register_command('KAPAT_SWEEP', self.cmd_KAPAT_SWEEP,
                                     desc=self.cmd_KAPAT_SWEEP_help)
        self.gcode.register_command('KAPAT_APPLY', self.cmd_KAPAT_APPLY,
                                     desc=self.cmd_KAPAT_APPLY_help)

        webhooks = self.printer.lookup_object('webhooks')
        webhooks.register_endpoint('kapat/get_data', self._handle_get_data)
        webhooks.register_endpoint('kapat/set_data', self._handle_set_data)
        webhooks.register_endpoint('kapat/list_captures',
                                    self._handle_list_captures)
        webhooks.register_endpoint('kapat/get_capture',
                                    self._handle_get_capture)
        webhooks.register_endpoint('kapat/delete_all_captures',
                                    self._handle_delete_all_captures)
        webhooks.register_endpoint('kapat/cancel_sweep',
                                    self._handle_cancel_sweep)

    # -- load cell resolution (mirrors autopa/__init__.py) -------------------
    def _handle_ready(self):
        if self._load_cell is not None:
            return
        probe = self.printer.lookup_object('probe', None)
        if probe is not None and hasattr(probe, '_load_cell'):
            self._load_cell = probe._load_cell
        else:
            lc = self.printer.lookup_object('load_cell', None)
            if lc is not None:
                self._load_cell = lc

    def _on_lc_event(self, load_cell):
        self._load_cell = load_cell

    def _get_load_cell(self, gcmd):
        if self._load_cell is None:
            self._handle_ready()
        if self._load_cell is None:
            raise gcmd.error("kapat: no load cell found; requires "
                             "[load_cell] or [load_cell_probe]")
        return self._load_cell

    # -- shared helpers --------------------------------------------------
    def _filament_area(self):
        extruder = self.printer.lookup_object('toolhead').get_extruder()
        return getattr(extruder, 'filament_area', _DEFAULT_FILAMENT_AREA)

    def _vol_to_lin(self, vfr):
        return vfr / self._filament_area()

    def _lin_to_vol(self, lin):
        return lin * self._filament_area()

    def _get_pa(self):
        extruder = self.printer.lookup_object('toolhead').get_extruder()
        return extruder.get_status(self.reactor.monotonic()).get(
            'pressure_advance', 0.)

    def _set_pa(self, value):
        self.gcode.run_script_from_command(
            "SET_PRESSURE_ADVANCE ADVANCE=%.6f" % value)

    def _check_extrude_temp(self, gcmd):
        extruder = self.printer.lookup_object('toolhead').get_extruder()
        status = extruder.get_status(self.reactor.monotonic())
        if not status.get('can_extrude', False):
            raise gcmd.error("kapat: extruder too cold to extrude (%.1fC) - "
                             "heat the hotend first" %
                             (status.get('temperature', 0.),))

    def _set_busy(self, state, eta_s):
        self._activity = {'state': state, 'eta_s': float(eta_s),
                          'started': self.reactor.monotonic()}

    def _clear_busy(self):
        self._activity = {'state': 'idle'}

    # -- KAPAT_SWEEP -----------------------------------------------------
    cmd_KAPAT_SWEEP_help = (
        "Calibrate pressure advance with an in-air slow/fast extrusion "
        "square wave, measured against a load cell. Reports K_opt from "
        "bd_pressure composite (headline), phase-lag, and integral-area "
        "estimators and applies it live (APPLY=0 to skip). Args: VFR "
        "VFR_LOW TSLOW TFAST CYCLES KSTART KEND KSTEP WARMUP WOBBLE_AXIS "
        "WOBBLE ACCEL APPLY WEIGHTS=name:val,name:val (bd_pressure metric "
        "weight overrides).")

    def cmd_KAPAT_SWEEP(self, gcmd):
        import gc
        import numpy as np

        lc = self._get_load_cell(gcmd)
        toolhead = self.printer.lookup_object('toolhead')
        self._check_extrude_temp(gcmd)

        # FILAMENT is purely cosmetic (Klipper has no notion of a
        # "selected filament profile" -- that's a web-UI construct) --
        # only used to name the raw capture on disk, see _save_capture.
        filament = gcmd.get('FILAMENT', '').strip()

        vfr = gcmd.get_float('VFR', self.vfr, above=0.)
        vfr_low = gcmd.get_float('VFR_LOW', self.vfr_low, above=0.)
        fast = self._vol_to_lin(vfr)
        slow = self._vol_to_lin(vfr_low)
        if fast <= slow:
            raise gcmd.error("kapat: VFR must be > VFR_LOW")
        tslow = gcmd.get_float('TSLOW', self.tslow, above=0.1, maxval=10.)
        tfast = gcmd.get_float('TFAST', self.tfast, above=0.05, maxval=10.)
        cycles = gcmd.get_int('CYCLES', self.cycles, minval=3, maxval=40)
        kstart = gcmd.get_float('KSTART', self.kstart, minval=0.)
        kend = gcmd.get_float('KEND', self.kend, minval=0.)
        kstep = gcmd.get_float('KSTEP', self.kstep, above=0.)
        if kend < kstart:
            raise gcmd.error("kapat: KEND must be >= KSTART")
        warmup = gcmd.get_float('WARMUP', self.warmup, minval=1., maxval=30.)
        maxmm = gcmd.get_float('MAXFILAMENT', self.maxfilament, above=0.)
        wobble_axis = gcmd.get('WOBBLE_AXIS', self.wobble_axis).strip().upper()
        if wobble_axis not in ('X', 'Y'):
            raise gcmd.error("kapat: WOBBLE_AXIS must be X or Y")
        wobble = gcmd.get_float('WOBBLE', self.wobble, minval=0.)
        accel = gcmd.get_float('ACCEL', self.accel, above=0.)
        apply_ = bool(gcmd.get_int('APPLY', int(self.apply_default),
                                    minval=0, maxval=1))
        axis_idx = {'X': 0, 'Y': 1}[wobble_axis]

        period = tslow + tfast
        ks = []
        k = kstart
        while k <= kend + 1e-9:
            ks.append(round(k, 6))
            k += kstep

        slow_mm = slow * tslow
        fast_mm = fast * tfast
        per_k = slow_mm + cycles * (fast_mm + slow_mm)
        warmup_extra = (warmup - 1.0) * slow_mm
        total_mm = per_k * len(ks) + warmup_extra
        if total_mm > maxmm:
            raise gcmd.error(
                "kapat sweep would extrude %.0fmm over %d K values "
                "(> MAXFILAMENT %.0f); reduce CYCLES / widen KSTEP / lower "
                "speeds" % (total_mm, len(ks), maxmm))

        if wobble > 0.:
            est = toolhead.get_status(self.reactor.monotonic())
            if wobble_axis.lower() not in est.get('homed_axes', ''):
                raise gcmd.error(
                    "kapat: %s axis not homed -- home it before KAPAT_SWEEP "
                    "(the PA-gate wobble moves %s), or pass WOBBLE=0 (no PA "
                    "will be exercised on current Klipper)" %
                    (wobble_axis, wobble_axis))
            extruder = toolhead.get_extruder()
            max_leg_e = max(slow * tslow * warmup, slow * tslow, fast * tfast)
            need_ratio = max_leg_e / wobble
            max_ratio = getattr(extruder, 'max_extrude_ratio', None)
            if max_ratio is not None and need_ratio > max_ratio:
                raise gcmd.error(
                    "kapat: a %.3fmm %s wobble with up to %.2fmm of filament "
                    "per leg exceeds max_extrude_cross_section (ratio %.1f "
                    "> %.3f). Raise max_extrude_cross_section in [extruder], "
                    "or raise WOBBLE." %
                    (wobble, wobble_axis, max_leg_e, need_ratio, max_ratio))

        orig_pa = self._get_pa()
        windows = []
        transitions = []
        collector = lc.get_collector()
        t0 = toolhead.get_last_move_time()
        collector.start_collecting(min_time=t0)
        wobbling = wobble > 0.
        old_accel = toolhead.get_status(
            self.reactor.monotonic()).get('max_accel') if wobbling else None

        def _leg(e_amt, dur, target):
            if wobbling:
                f = (wobble / dur) * 60.
                self.gcode.run_script_from_command(
                    "G1 %s%.4f E%.4f F%.2f" % (wobble_axis, target, e_amt, f))
            else:
                self.gcode.run_script_from_command(
                    "G1 E%.4f F%.0f" % (e_amt, (e_amt / dur) * 60.))

        gc.collect()
        self._cancel_requested = False
        self._set_busy('sweep', 0.5 + len(ks) * (tslow + cycles *
                       (tfast + tslow)) + (warmup - 1.) * tslow)
        try:
            toolhead.dwell(0.5)
            self.gcode.run_script_from_command("G90")
            self.gcode.run_script_from_command("M83")
            if wobbling:
                self.gcode.run_script_from_command(
                    "SET_VELOCITY_LIMIT ACCEL=%.0f" % accel)
            base = toolhead.get_position()[axis_idx] if wobbling else 0.
            hi_pos = base + wobble
            lo_pos = base
            wob = [False]

            def _next_target():
                wob[0] = not wob[0]
                return hi_pos if wob[0] else lo_pos

            for ki, kv in enumerate(ks):
                if self._cancel_requested:
                    raise gcmd.error("kapat: sweep cancelled by user")
                self._set_pa(kv)
                t_k0 = toolhead.get_last_move_time()
                rising, falling = [], []
                lead = tslow * (warmup if ki == 0 else 1.0)
                _leg(slow * lead, lead, _next_target())
                for c in range(cycles):
                    if self._cancel_requested:
                        raise gcmd.error("kapat: sweep cancelled by user")
                    toolhead.register_lookahead_callback(
                        lambda pt, a=rising: a.append(pt))
                    _leg(fast * tfast, tfast, _next_target())
                    toolhead.register_lookahead_callback(
                        lambda pt, a=falling: a.append(pt))
                    _leg(slow * tslow, tslow, _next_target())
                t_k1 = toolhead.get_last_move_time()
                windows.append((t_k0, t_k1))
                transitions.append((rising, falling))
            t_end = toolhead.get_last_move_time()
            samples, errs = collector.collect_until(t_end)
        finally:
            self._clear_busy()
            try:
                collector.is_started = False
            except Exception:
                logging.exception("kapat: collector release failed")
            try:
                self._set_pa(orig_pa)
            except Exception:
                logging.exception("kapat: failed to restore PA")
            if wobbling and old_accel:
                try:
                    self.gcode.run_script_from_command(
                        "SET_VELOCITY_LIMIT ACCEL=%.0f" % old_accel)
                except Exception:
                    logging.exception("kapat: failed to restore accel")

        if not len(samples):
            raise gcmd.error("kapat: no samples captured (errors=%s)" % (errs,))

        arr = np.asarray(samples, dtype=float)
        t_rel = arr[:, 0] - t0
        force = -(arr[:, 2] - arr[:, 3])
        windows_rel = [(a - t0, b - t0) for a, b in windows]
        transitions_rel = [([r - t0 for r in rs], [f - t0 for f in fs])
                            for rs, fs in transitions]

        result = pac.analyse_sweep_segments(
            t_rel, force, ks, windows_rel, transitions_rel,
            slow_v=vfr_low, fast_v=vfr,
            slow_half_s=tslow, fast_half_s=tfast, cycle_period_s=period)

        # cycle_windows: per-K list of (t_start, t_rise, t_fall, t_end)
        # 4-tuples, one per low->high->low cycle -- built directly from
        # the same rising/falling print-times recorded above via
        # register_lookahead_callback, no separate detection pass needed
        # (see bd_pressure.py's module docstring).
        cycle_windows = []
        for (t_k0, t_k1), (rising, falling) in zip(windows_rel, transitions_rel):
            cycles_list = []
            for i in range(len(rising)):
                t_start = falling[i - 1] if i > 0 else t_k0
                t_end = rising[i + 1] if i + 1 < len(rising) else t_k1
                cycles_list.append((t_start, rising[i], falling[i], t_end))
            cycle_windows.append(cycles_list)

        bd_weights = self._bd_weights_override(gcmd)
        bd_result = bdp.analyse_bd(t_rel, force, ks, cycle_windows,
                                    weights=bd_weights)

        capture_id = None
        try:
            # Actual extruder target at sweep time (not a gcode param) --
            # M109 already set this before KAPAT_SWEEP ran, so this is
            # the real temp the sweep was measured at, not just whatever
            # the web UI intended to request.
            extruder_temp = toolhead.get_extruder().get_status(
                self.reactor.monotonic()).get('target', 0.)
            capture_id = self._save_capture(t_rel, force, cycle_windows,
                                             bd_result.per_k, {
                'vfr': vfr, 'vfr_low': vfr_low, 'tslow': tslow,
                'tfast': tfast, 'cycles': cycles, 'ks': ks, 'kstep': kstep,
                'wobble': wobble, 'wobble_axis': wobble_axis,
                'k_opt': bd_result.composite_k_opt,
                'filament': filament, 'temp': extruder_temp})
        except Exception:
            logging.exception("kapat: failed to save raw capture")

        self._report_sweep(gcmd, result, bd_result, meta={
            'vfr': vfr, 'vfr_low': vfr_low, 'tslow': tslow, 'tfast': tfast,
            'cycles': cycles, 'ks': ks, 'kstep': kstep, 'errs': errs,
            'wobble': wobble, 'wobble_axis': wobble_axis, 'apply': apply_,
            'orig_pa': orig_pa, 'capture_id': capture_id})

    def _bd_weights_override(self, gcmd):
        # WEIGHTS=name1:val1,name2:val2 gcode param overrides individual
        # BD_DEFAULT_WEIGHTS entries; unlisted metrics keep their default.
        raw = gcmd.get('WEIGHTS', None)
        weights = dict(bdp.BD_DEFAULT_WEIGHTS)
        if not raw:
            return weights
        for pair in raw.split(','):
            if ':' not in pair:
                continue
            name, val = pair.split(':', 1)
            name = name.strip()
            if name in bdp.BD_METRIC_NAMES:
                try:
                    weights[name] = float(val)
                except ValueError:
                    pass
        return weights

    def _report_sweep(self, gcmd, result, bd_result, meta):
        wob = meta['wobble']
        wob_desc = ("%s-wobble %.3fmm" % (meta['wobble_axis'], wob)
                    if wob > 0. else "PURE-E (no PA!)")
        lines = ["kapat sweep: VFR_LOW=%.2f VFR=%.2f mm3/s, %dx(%.2f/%.2fs), "
                 "%d K, %s, errors=%s" %
                 (meta['vfr_low'], meta['vfr'], meta['cycles'], meta['tslow'],
                  meta['tfast'], len(meta['ks']), wob_desc, meta['errs'])]
        if wob <= 0.:
            lines.append("  WARNING: WOBBLE=0 -> extrude-only moves, Klipper "
                         "applied NO pressure advance; K_opt is meaningless.")

        lines.append("  K         phase_lag_ms   integral_area   n_samples")
        for r in result.per_k:
            lines.append("  %-9.4f %-14.2f %-15.3f %d" %
                         (r.k, r.phase_lag_ms, r.integral_area, r.n_samples))

        # bd_pressure composite is the headline number when available
        # (matches PrusaPATuner convention) -- phase-lag/integral-area are
        # reported alongside as cross-checks, not silently dropped.
        k_opt = None
        k_opt_source = None
        if bd_result.composite_k_opt is not None:
            k_opt = bd_result.composite_k_opt
            k_opt_source = "bd_pressure composite"
            lines.append("  bd_pressure composite K_opt = %.4f" % k_opt)
        if result.integral_fit is not None:
            lines.append("  integral-area K_opt = %.4f (R^2=%.3f)" %
                         (result.integral_fit.k_opt,
                          result.integral_fit.r_squared))
            if k_opt is None:
                k_opt, k_opt_source = result.integral_fit.k_opt, "integral-area"
        if result.phase_fit is not None:
            lines.append("  phase-lag K_opt     = %.4f (R^2=%.3f)" %
                         (result.phase_fit.k_opt, result.phase_fit.r_squared))
            if k_opt is None:
                k_opt, k_opt_source = result.phase_fit.k_opt, "phase-lag"
        for n in result.notes:
            lines.append("  note: %s" % n)
        for n in bd_result.notes:
            lines.append("  note: %s" % n)

        if bd_result.per_k:
            lines.append("  bd_pressure per-K (segs included/total):")
            for kr in bd_result.per_k:
                lines.append("    K=%-8.4f %d/%d  overshoot=%.3f undershoot=%.3f" %
                             (kr.k, kr.n_segments_included, kr.n_segments_total,
                              kr.medians.get('overshoot', float('nan')),
                              kr.medians.get('undershoot', float('nan'))))
        if bd_result.metric_k_opt:
            lines.append("  bd_pressure per-metric K_opt:")
            for name, v in bd_result.metric_k_opt.items():
                lines.append("    %-20s %s" %
                             (name, ("%.4f" % v) if v is not None else "n/a"))

        if k_opt is not None:
            ks = meta['ks']
            edge = meta['kstep'] * 0.5
            if k_opt <= ks[0] + edge:
                lines.append("  WARNING: K_opt at LOW edge of [%.3f, %.3f] -- "
                             "lower KSTART and re-run." % (ks[0], ks[-1]))
            elif k_opt >= ks[-1] - edge:
                lines.append("  WARNING: K_opt at HIGH edge of [%.3f, %.3f] -- "
                             "raise KEND and re-run." % (ks[0], ks[-1]))

        if k_opt is not None and k_opt >= 0. and wob > 0. and meta['apply']:
            self._set_pa(k_opt)
            lines.append("  Applied (%s): SET_PRESSURE_ADVANCE ADVANCE=%.4f" %
                         (k_opt_source, k_opt))
        elif meta['apply']:
            lines.append("  not applied: no usable K_opt")

        def _fit_dict(fit):
            if fit is None:
                return None
            return {'k_opt': fit.k_opt, 'slope': fit.slope,
                    'intercept': fit.intercept, 'r_squared': fit.r_squared}

        self._last = {
            'k_opt': k_opt,
            'k_opt_source': k_opt_source,
            'capture_id': meta.get('capture_id'),
            'phase_lag_k_opt': (result.phase_fit.k_opt
                                if result.phase_fit else None),
            'integral_area_k_opt': (result.integral_fit.k_opt
                                   if result.integral_fit else None),
            # Full fit params (not just k_opt) so the frontend can draw
            # the fitted line itself, not only report the number.
            'phase_fit': _fit_dict(result.phase_fit),
            'integral_fit': _fit_dict(result.integral_fit),
            'integral_legacy_fit': _fit_dict(result.integral_legacy_fit),
            'bd_composite_k_opt': bd_result.composite_k_opt,
            'bd_metric_k_opt': bd_result.metric_k_opt,
            'bd_weights': bd_result.weights_used,
            'per_k': [{'k': r.k, 'phase_lag_ms': r.phase_lag_ms,
                       'integral_area': r.integral_area,
                       'integral_area_legacy': r.integral_area_legacy,
                       'n_samples': r.n_samples}
                      for r in result.per_k],
            'bd_per_k': [{'k': kr.k,
                          'n_segments_included': kr.n_segments_included,
                          'n_segments_total': kr.n_segments_total,
                          'medians': kr.medians,
                          'lo': kr.lo, 'hi': kr.hi}
                         for kr in bd_result.per_k],
            'notes': result.notes + bd_result.notes,
            'applied': k_opt is not None and k_opt >= 0. and wob > 0.
                       and meta['apply'],
        }
        gcmd.respond_info("\n".join(lines))

    # -- KAPAT_APPLY -------------------------------------------------------
    cmd_KAPAT_APPLY_help = "Apply a specific K (or the last sweep's K_opt if K= is omitted)."

    def cmd_KAPAT_APPLY(self, gcmd):
        k = gcmd.get_float('K', None)
        if k is None:
            k = self._last.get('k_opt')
        if k is None:
            raise gcmd.error("kapat: no K given and no previous sweep result "
                             "to apply")
        self._set_pa(k)
        gcmd.respond_info("kapat: applied SET_PRESSURE_ADVANCE ADVANCE=%.4f" % k)

    # -- status (polled by the frontend via printer.objects.subscribe) ------
    def get_status(self, eventtime):
        sensor = getattr(self._load_cell, 'sensor', None)
        return {
            'has_load_cell': self._load_cell is not None,
            'load_cell_name': getattr(self._load_cell, 'name', None),
            'sensor_type': getattr(sensor, 'sensor_type', None),
            'activity': dict(self._activity, now=float(eventtime)),
            'last': self._last,
        }

    # -- local JSON storage for the web UI's Profiles/History tabs -------
    # Reached over the same klippysocket bridge as load_cell/dump_force
    # (see web/src/lib/bridge.js) -- keeps the data as a real file on the
    # host (printer_data/kapat/<key>.json) instead of Moonraker's DB.
    def _data_path(self, key):
        if key not in _DATA_KEYS:
            raise self.printer.command_error("kapat: invalid data key %r" % (key,))
        return os.path.join(self._data_dir, '%s.json' % (key,))

    def _handle_get_data(self, web_request):
        key = web_request.get_str('key')
        path = self._data_path(key)
        try:
            with open(path) as f:
                value = json.load(f)
        except (IOError, OSError, ValueError):
            value = []
        web_request.send({'value': value})

    # Reached over the same webhook bridge as get_data/list_captures --
    # NOT a gcode command. KAPAT_SWEEP occupies the gcode queue for its
    # entire duration (minutes), so a *new* gcode command sent while it's
    # still running would just queue up and only execute after the sweep
    # finishes -- useless for cancellation. Webhook endpoints, in
    # contrast, run independently of the gcode queue (the same mechanism
    # already lets the live force chart poll status *while* a sweep is
    # running), so this can actually take effect immediately: it just
    # flips a flag that cmd_KAPAT_SWEEP's own loop checks every cycle.
    def _handle_cancel_sweep(self, web_request):
        self._cancel_requested = True
        web_request.send({'ok': True})

    def _handle_set_data(self, web_request):
        key = web_request.get_str('key')
        value = web_request.get('value')
        path = self._data_path(key)
        os.makedirs(self._data_dir, exist_ok=True)
        tmp_path = path + '.tmp'
        with open(tmp_path, 'w') as f:
            json.dump(value, f)
        os.replace(tmp_path, path)
        web_request.send({'ok': True})

    # -- raw sweep captures for the Analysis tab's segment browser -------
    # Persists the FULL raw t/force arrays cmd_KAPAT_SWEEP already builds
    # (previously discarded once bd_pressure.py reduced them to per-K
    # medians) in a compressed .npz, plus every individual segment's exact
    # (t_start, t_rise, t_fall, t_end) boundaries AND its own bd_pressure
    # metrics/inclusion verdict (bd_result.per_k[i].segments[j] -- the
    # same BdSegment objects bd_aggregate_per_k already computed, just not
    # previously exposed past their per-K median) in a JSON sidecar. This
    # mirrors PrusaPATuner's segment browser, which shows one segment's
    # own metrics/exclusion reason at a time, not just the K-level median.
    def _save_capture(self, t, force, cycle_windows, bd_per_k, meta):
        import numpy as np

        os.makedirs(self._captures_dir, exist_ok=True)
        created_ms = int(time.time() * 1000)
        # <filament>_<temp>C_<timestamp> -- human-readable on disk (ls
        # sorts filament/temp before you even open one), while 'created'
        # below (a plain int) is what listing actually sorts by, so a
        # filament-name mismatch across captures can't scramble the
        # "most recent first" ordering the way sorting by this string
        # would.
        capture_id = '%s_%dC_%d' % (
            _slug(meta.get('filament')), round(meta.get('temp') or 0),
            created_ms)

        npz_path = os.path.join(self._captures_dir, '%s.npz' % capture_id)
        # np.savez* silently appends ".npz" to any path that doesn't
        # already end with it -- naming the temp file "<id>.npz.tmp.npz"
        # (rather than "<id>.npz.tmp") keeps that behaviour from breaking
        # the atomic os.replace() below.
        tmp_npz_path = npz_path + '.tmp.npz'
        np.savez_compressed(
            tmp_npz_path,
            t=np.asarray(t, dtype=np.float32),
            force=np.asarray(force, dtype=np.float32),
        )
        os.replace(tmp_npz_path, npz_path)

        # NOTE: named "segments" (not "cycles") deliberately -- `meta`
        # already carries the CYCLES-per-K gcode param as an int under
        # the key 'cycles' (see the call site), and re-using that name
        # here for the per-segment list would silently clobber it.
        segments = []
        for kr, cycles_for_k in zip(bd_per_k, cycle_windows):
            for (t_start, t_rise, t_fall, t_end), seg in zip(
                    cycles_for_k, kr.segments):
                segments.append({
                    'k': kr.k, 't_start': t_start, 't_rise': t_rise,
                    't_fall': t_fall, 't_end': t_end,
                    'included': seg.included,
                    'exclude_reason': seg.exclude_reason,
                    'metrics': seg.metrics or None,
                })

        sidecar = dict(meta)
        sidecar.update({
            'id': capture_id,
            'created': created_ms,
            'n_segments': len(segments),
            'n_samples': int(len(t)),
            'segments': segments,
        })
        json_path = os.path.join(self._captures_dir, '%s.json' % capture_id)
        tmp_json_path = json_path + '.tmp'
        with open(tmp_json_path, 'w') as f:
            json.dump(sidecar, f)
        os.replace(tmp_json_path, json_path)

        self._prune_captures()
        return capture_id

    def _prune_captures(self):
        try:
            names = os.listdir(self._captures_dir)
        except OSError:
            return
        ids = {n.split('.', 1)[0] for n in names
               if n.endswith('.json') or n.endswith('.npz')}
        # id = "<filament>_<temp>C_<timestamp>" -- sorting the id STRING
        # would sort by filament name first (wrong: alphabetical, not
        # chronological). The timestamp is always the last '_'-separated
        # token, so sort on that instead. Falls back to 0 (pruned first)
        # for any id that somehow doesn't parse.
        def _created_of(cap_id):
            tail = cap_id.rsplit('_', 1)[-1]
            return int(tail) if tail.isdigit() else 0
        ordered = sorted(ids, key=_created_of, reverse=True)
        for stale_id in ordered[_CAPTURE_KEEP:]:
            for ext in ('.json', '.npz'):
                try:
                    os.remove(os.path.join(self._captures_dir,
                                            stale_id + ext))
                except OSError:
                    pass

    def _handle_delete_all_captures(self, web_request):
        try:
            names = os.listdir(self._captures_dir)
        except OSError:
            names = []
        deleted = 0
        for name in names:
            if not (name.endswith('.json') or name.endswith('.npz')):
                continue
            try:
                os.remove(os.path.join(self._captures_dir, name))
                deleted += 1
            except OSError:
                pass
        web_request.send({'ok': True, 'deleted': deleted})

    def _capture_id_path(self, capture_id, ext):
        # capture_id is "<filament>_<temp>C_<timestamp>" (see
        # _save_capture) -- _SLUG_RE's charset (plus the literal 'C' and
        # '_' separators, already inside that set) is what actually
        # blocks path traversal here; isdigit() would reject every real
        # id now that it's not a bare timestamp.
        if not capture_id or _SLUG_RE.search(capture_id):
            raise self.printer.command_error(
                "kapat: invalid capture id %r" % (capture_id,))
        return os.path.join(self._captures_dir, capture_id + ext)

    def _handle_list_captures(self, web_request):
        try:
            names = os.listdir(self._captures_dir)
        except OSError:
            names = []
        captures = []
        for name in names:
            if not name.endswith('.json'):
                continue
            try:
                with open(os.path.join(self._captures_dir, name)) as f:
                    sidecar = json.load(f)
            except (IOError, OSError, ValueError):
                continue
            # Listing is for a dropdown of past sweeps -- drop the
            # (potentially large) per-segment metrics list here; a
            # specific capture's full detail comes from get_capture.
            sidecar.pop('segments', None)
            captures.append(sidecar)
        captures.sort(key=lambda c: c.get('created', 0), reverse=True)
        web_request.send({'captures': captures})

    def _handle_get_capture(self, web_request):
        import numpy as np

        capture_id = web_request.get_str('id')
        json_path = self._capture_id_path(capture_id, '.json')
        npz_path = self._capture_id_path(capture_id, '.npz')
        try:
            with open(json_path) as f:
                meta = json.load(f)
        except (IOError, OSError, ValueError):
            raise self.printer.command_error(
                "kapat: capture %r not found" % (capture_id,))
        try:
            with np.load(npz_path) as npz:
                t = npz['t']
                force = npz['force']
        except (IOError, OSError, ValueError):
            raise self.printer.command_error(
                "kapat: capture %r data missing" % (capture_id,))

        web_request.send({
            'meta': meta,
            't': t.tolist(),
            'force': force.tolist(),
        })


def load_config(config):
    return Kapat(config)
