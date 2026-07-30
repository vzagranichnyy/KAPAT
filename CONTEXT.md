# KAPAT — context brief for continuing in Claude Code

Paste this whole file as your first message (or save as CONTEXT.md in the
repo root and point Claude Code at it) to pick up exactly where a long
planning conversation with Claude (claude.ai chat, not Claude Code) left
off. That chat could plan and write code but could not run anything on
your actual printer host — that's the point of moving to Claude Code.

## What this project is

**KAPAT** — automatic Klipper Pressure Advance calibration using a
toolhead load cell as a back-pressure sensor. No printed test patches.

Combines three sources, each for a specific piece:
- **Data acquisition** — pattern from
  [G0BL1N/autopa](https://github.com/G0BL1N/autopa): Klipper's
  `[load_cell]`/`[load_cell_probe]` already has a built-in **collector**
  (`lc.get_collector()` → `start_collecting(min_time=...)` →
  `collect_until(t_end)`) that captures samples for a time window
  *directly inside Klippy* — no custom ADC driver, no external capture
  service. Exact per-cycle rise/fall transition timing comes from
  `toolhead.register_lookahead_callback` at G-code generation time, so no
  signal-based "detect where the sweep segments are" step is needed at
  all (unlike PrusaPATuner, which has to detect this from noisy data).
- **Analysis math** — ported from
  [CNCKitchen/PrusaPATuner](https://github.com/CNCKitchen/PrusaPATuner)
  (`src/prusa_pa_tuner/analysis.py`): phase-lag cross-correlation,
  centered-window integral-area, linear-fit zero-crossing (Stage A), plus
  the full bd_pressure 8-region/13-metric step-response composite cost
  (Stage B).
- **Web UI look** — from `vzagranichnyy/KAPAT` (dark theme, orange
  accent `#f7931e`, card layout, slider rows). Rebuilt as Svelte + uPlot,
  NOT a copy of that repo's actual JS logic — only the visual design was
  taken from there; the app logic/math/data flow is original, following
  autopa's and PrusaPATuner's approaches above.

## Repo layout (as of this brief)

```
klipper_extras/kapat/
  __init__.py            # KAPAT_SWEEP / KAPAT_APPLY gcode commands, load-cell
                          # resolution, wobble-geometry sweep motion, calls
                          # into pa_analysis_core + bd_pressure, applies PA,
                          # get_status() for the frontend to poll
  pa_analysis_core.py     # Stage A: phase-lag, integral-area, linear-fit
                          # zero-crossing, argmin-with-parabolic
  bd_pressure.py          # Stage B: bd_pressure segment metrics + composite
                          # cost + per-metric K_opt

web/                      # Svelte + uPlot, builds to web/dist (static, no
                           # backend process — browser talks to Moonraker
                           # directly)
  src/lib/moonraker.js      # normal :80/websocket JSON-RPC client
  src/lib/bridge.js         # raw :7125/klippysocket bridge (this is how
                             # load_cell/dump_force is reached — see gotcha
                             # below, it is NOT the same path as /websocket)
  src/lib/gcode.js          # builds the KAPAT_SWEEP command line from form params
  src/lib/bdCost.js         # JS port of bd_pressure.py's normalise/cost/argmin
                             # math, so weight sliders recompute K_opt live
                             # without re-running the printer. Verified
                             # bit-identical to the Python version on the
                             # same synthetic input.
  src/components/
    SweepForm.svelte          # K range / flow / cycle / wobble sliders
    LiveChart.svelte           # uPlot live raw force stream
    ResultsPanel.svelte        # phase-lag / integral-area K_opt + per-K table
    BdResults.svelte           # composite K_opt, weight sliders, per-metric
                                # mini-chart grid (12 panels)

install.sh                 # preflight-checked installer (see below)
docs/printer.cfg.example
tests/
  test_pa_analysis_core.py  # Stage A tests, PASSING
  test_bd_pressure.py       # Stage B tests, PASSING
```

## Status: what's actually verified vs. not

**Verified (in the sandbox that wrote this code, NOT on real hardware):**
- `tests/test_pa_analysis_core.py` and `tests/test_bd_pressure.py` pass —
  synthetic data, both estimators and the composite cost find the correct
  K on a known-answer test signal.
- Python↔JS parity: `bdCost.js` gives a bit-identical `composite_k_opt` to
  `bd_pressure.py` on the same synthetic input.
- All Python files syntax-check and the `kapat` package imports cleanly
  standalone (outside real Klippy).
- All plain JS files pass `node --check`.
- `install.sh`'s detection logic (find Klipper dir, find klippy-env,
  dedupe duplicate paths, stale-file cleanup) tested against simulated
  fake directory layouts.

**NOT verified — genuinely untested:**
- Nothing has run on a real printer / real load cell yet. The whole
  `KAPAT_SWEEP` G-code flow (toolhead moves, collector timing, actual
  bd_pressure numbers on a real signal) is unverified beyond the unit
  tests above.
- The Svelte app has never been built successfully by Claude — every
  build attempt happened on the user's actual CB2 hardware (see gotchas).
- The interactive per-segment RAW WAVEFORM browser (click through each
  cycle, see the annotated raw trace) is explicitly NOT built. Everything
  here works from per-K *medians*, which is enough for the composite cost
  and per-metric charts but not for re-inspecting one specific cycle's
  raw trace after a sweep finishes. Would need a decision on where to
  persist raw per-segment samples (webhook payload size vs. on-disk).
- Folding this into an actual Mainsail nav tab (forked build) hasn't
  started — this ships as a standalone page at `/kapat/` today.

## Hardware/environment this has actually been tested against

BigTreeTech CB2 board, user `pi`, Klipper at `~/klipper`, klippy-env
Python **3.11** (earlier attempt hit Python 3.9.2 on a different
account/board — see gotcha below). No Node.js installed yet as of the
last message in the chat this brief comes from.

## Gotchas already hit and fixed — don't reintroduce these

1. **`@dataclass(slots=True)` breaks on Python < 3.10.** Already removed
   from `pa_analysis_core.py` — all three dataclasses are plain
   `@dataclass` now. If you add new dataclasses, do NOT add `slots=True`
   unless you've confirmed the target klippy-env's Python version.
2. **Rollup 4.x's native ARM64 binary needs glibc ≥2.34**, which older
   SBC OS images (Debian Bullseye, glibc 2.31) don't have — you get
   `ERR_DLOPEN_FAILED ... GLIBC_2.34 not found`. Fixed by pinning
   `vite: ^4.5.3` (bundles rollup 3, pure JS, no native binary) in
   `web/package.json`. Don't bump vite past the 5.x line without
   checking this again.
3. **`index.html`'s script src must be root-relative (`/src/main.js`),
   NOT include the `base: '/kapat/'` prefix** from `vite.config.js` — Vite
   adds that automatically at build time. Writing `/kapat/src/main.js`
   literally causes `Rollup failed to resolve import` because Vite looks
   for a literal `kapat/` folder under the project root.
4. **`max_extrude_cross_section` in `[extruder]` needs raising** (we used
   200 in the example config) — the sweep's wobble geometry (small XY
   move, large E move per leg) has a high extrude-to-travel ratio and
   trips Klipper's default guard. The error message tells you the exact
   ratio needed; either raise this config value or raise `WOBBLE=`.
5. **Two separate Moonraker connections, not one.** `:80/websocket`
   (normal JSON-RPC, nginx-proxied) is NOT the same path as
   `:7125/klippysocket` (raw Klippy webhooks bridge — this is the ONLY
   place `load_cell/dump_force` is reachable). The browser must reach
   port 7125 directly; nginx does not proxy it in a typical Mainsail/
   Fluidd install. If KAPAT is only reachable through a reverse proxy/
   tunnel that doesn't forward 7125, the live chart specifically will
   fail to connect even though everything else (sweep triggering, status
   polling, apply) works fine.
6. **npm has no registry access in the sandbox this was built in** — the
   Svelte app's actual `npm install && npm run build` has never
   successfully completed by Claude; every real build happened on the
   user's own hardware. Don't assume the web UI builds cleanly just
   because the source passed `node --check` — that only catches syntax
   errors, not real dependency-resolution or build-time issues.
7. **`install.sh` auto-detects `KLIPPER_DIR`/`KLIPPY_ENV`** by checking
   `$HOME/klipper`, `$HOME/klipper-*`, and `/home/*/klipper` (same for
   klippy-env) — it dedupes when these overlap (fixed a bug where the
   same real path got reported twice). If Klipper lives somewhere
   nonstandard, override with `KLIPPER_DIR=... KLIPPY_ENV=... ./install.sh`.
8. There is an old, fully superseded architecture's leftover file,
   `klippy/extras/kapat_pa_sweep.py`, that may still exist on the user's
   box from an earlier iteration — `install.sh` now deletes it
   automatically on install, but if you see it referenced anywhere,
   it's dead code from a design that was replaced (a Flask+Moonraker-
   websocket backend, abandoned in favor of the in-Klippy collector
   approach).

## Design decisions worth knowing before changing things

- **bd_pressure composite is the headline K_opt** (matches PrusaPATuner
  convention); phase-lag and integral-area are reported alongside as
  cross-checks, not the primary number.
- **Individual bd_pressure metrics are expected to be monotonic across
  the sweep, often pinned at a sweep boundary** (e.g. `overshoot` only
  grows when K is too high, `undershoot` only when K is too low) — only
  the *weighted composite* forms an interior valley. This is by design,
  confirmed against the real PrusaPATuner UI screenshots the user shared
  (per-metric K_opt values scattered near sweep edges, composite landing
  in the middle). Don't "fix" a monotonic individual metric — that's
  correct.
- **Stage B's internal window-sizing constants** (rise/fall edge
  fraction, settling tolerance) are a reasonable reconstruction of
  PrusaPATuner's approach, not a guaranteed byte-exact copy of upstream's
  exact thresholds — flagged explicitly in `bd_pressure.py`'s docstring.
  If you get access to PrusaPATuner's literal source again, worth
  diffing against.
- Everything is licensed AGPL-3.0-or-later, matching both upstream
  sources.

## Suggested first steps in Claude Code

1. Read `README.md` and `klipper_extras/kapat/__init__.py` first.
2. Confirm Node.js is installed on the actual host (`node --version`) —
   as of this brief it was NOT yet installed; see `install.sh`'s
   preflight output for the exact install command it suggests.
3. Run `./install.sh` for real and actually watch it build the Svelte
   app for the first time — this has never fully succeeded before now.
4. Once installed, add `[kapat]` to `printer.cfg` (see
   `docs/printer.cfg.example`), restart Klipper, and try `KAPAT_SWEEP`
   with a small K range on real hardware for the first time.
5. Report back anything that breaks — expect the first real-hardware run
   to surface something the unit tests couldn't catch (timing edge cases,
   real noise floor, real collector API behavior).
