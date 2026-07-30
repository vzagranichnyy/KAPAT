# KAPAT — Klipper Auto Pressure Advance Tuning

Automatic Pressure Advance calibration for Klipper, using a toolhead load
cell as a back-pressure sensor. No printed test patches, no eyeballing
corners.

Three sources, combined:
- **Data acquisition** (load-cell resolution, `get_collector()`/
  `start_collecting`/`collect_until`, the axis-wobble PA-gate requirement,
  exact per-cycle transition timing via `register_lookahead_callback`) —
  pattern from [G0BL1N/autopa](https://github.com/G0BL1N/autopa)
  (`autopa/sweep.py`).
- **Analysis math** (phase-lag cross-correlation, centered-window
  integral-area, linear-fit zero-crossing, 8-region/13-metric step-response
  analysis) — ported from
  [CNCKitchen/PrusaPATuner](https://github.com/CNCKitchen/PrusaPATuner)
  (`src/prusa_pa_tuner/analysis.py`).
- **Web UI** — two options, see below.

Validated end-to-end on real hardware (ADS131M02 load cell), including the
raw-segment Analysis browser and the composite/per-metric K_opt views.

## Two web UIs — pick one (or both)

**1. KAPAT web** (`web-dist/`) — a small standalone app, just the
calibration UI, nothing else. Served at `/kapat/` alongside whatever else
already runs on the printer's web server.

**2. Mainsail + KAPAT** (`mainsail-dist/`) — a full fork of
[Mainsail](https://github.com/mainsail-crew/mainsail) with a native
**KAPAT** tab built into its sidebar. Replaces your existing Mainsail
install outright (same UI you already use, plus the KAPAT tab) rather
than running alongside it. Source: [Mainsail-Kapat](https://github.com/vzagranichnyy/Mainsail-Kapat).

Both talk to the exact same Klipper backend (this repo's `klipper_extras/`)
and the same on-disk profiles/history/captures — switching between them
doesn't lose any data.

**KAPAT web** (`/kapat/`):

<img src="docs/screenshots/kapat-web-main.png" width="600" alt="KAPAT web: Live Force chart, Pressure Advance Calibration form, Filament Profile, History">
<img src="docs/screenshots/kapat-web-analysis.png" width="600" alt="KAPAT web: Analysis segment browser with per-region stat cards and composite cost sliders">

**Mainsail + KAPAT** (sidebar tab):

<img src="docs/screenshots/mainsail-kapat-main.png" width="600" alt="Mainsail sidebar with the KAPAT tab open, Live Force chart and calibration form">
<img src="docs/screenshots/mainsail-kapat-analysis.png" width="600" alt="Mainsail KAPAT tab: Analysis segment browser">
<img src="docs/screenshots/mainsail-kapat-metrics.png" width="600" alt="Mainsail KAPAT tab: per-metric K_opt table and trend grid">

## Install

```bash
git clone https://github.com/vzagranichnyy/KAPAT.git
cd KAPAT
./install.sh                  # KAPAT web UI at /kapat/ (default)
./install.sh --web=mainsail   # Mainsail+KAPAT instead (replaces $HOME/mainsail)
./install.sh --web=both       # both
```

Both web UIs ship **pre-built** in this repo (`web-dist/`,
`mainsail-dist/`) — no Node.js/npm needed on the printer.

Then add the `[kapat]` section from `docs/printer.cfg.example` to your
`printer.cfg` and restart Klipper.

## Changing your mind later

```bash
./switch-web.sh --to=kapat     # KAPAT web UI (restores your original
                                # stock Mainsail if --web=mainsail ever
                                # replaced it)
./switch-web.sh --to=mainsail  # Mainsail+KAPAT (backs up whatever's
                                # currently at $HOME/mainsail first, once)
./switch-web.sh --to=both
```

## Removing it

```bash
./uninstall.sh
```

Removes the Klipper extra, the web UI deployment(s), and the nginx
`/kapat` location it added — restoring your stock Mainsail from the
backup `switch-web.sh`/`install.sh` took, if one exists. Leaves
`printer.cfg`'s `[kapat]` section and your saved profiles/history/captures
(`printer_data/kapat/`) alone; see the script's own output for what to
clean up by hand if you want them gone too.

## Two Moonraker connections — read this before deploying

The live force chart needs Klipper's `load_cell/dump_force` webhook, which
Moonraker only exposes on its **raw klippysocket bridge at port 7125** —
a *different* path from the normal `:80/websocket` nginx proxy. The
browser connects to `:7125/klippysocket` directly. If your printer is
only reachable through a reverse proxy/tunnel that doesn't forward 7125,
everything else works but the live chart won't connect.

## Layout

```
klipper_extras/kapat/
  __init__.py            # KAPAT_SWEEP / KAPAT_APPLY, load-cell wiring,
                          # webhook endpoints (get/set data, captures),
                          # get_status() for both frontends
  bd_pressure.py          # 8-region/13-metric step-response analysis
  pa_analysis_core.py     # phase-lag + integral-area estimators

web-dist/                 # pre-built KAPAT web UI (Vue 2 + Vuetify),
                           # served at /kapat/
mainsail-dist/             # pre-built Mainsail+KAPAT fork, replaces
                           # $HOME/mainsail

install.sh                # symlinks the extra, deploys the chosen web
                           # UI(s), wires an nginx location
switch-web.sh              # change which web UI is active later
uninstall.sh                # remove everything the above set up
lib-web.sh                  # shared deploy/backup/restore helpers
docs/printer.cfg.example
tests/
```

## License

AGPL-3.0-or-later, matching both autopa and PrusaPATuner.
