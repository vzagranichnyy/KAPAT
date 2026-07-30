# KAPAT — working state as of this session

Read this first. `CONTEXT.md` in this same directory is the *original*
brief from before real-hardware work started — most of it is now out of
date (the profiles/history storage design and the Analysis tab it
describes were both replaced/completed since). This file is the current
source of truth; treat `CONTEXT.md` as historical background only (still
correct about the Stage A/Stage B math ports and the general gotchas
list around nginx/Moonraker connections).

**Also critical, and easy to miss**: on *this* install (pi) there are
**two independent front-ends**, not one. "The web UI" is ambiguous —
see "Two UIs on this one printer" below before assuming which one a bug
report is about. This bit a whole session's worth of back-and-forth
once already (see that section for the story).

**Decision (2026-07-30): going forward, all work happens in the
Mainsail fork (`/home/pi/mainsail-src`), not the standalone Svelte SPA
(`web/src/` in this repo).** Don't start new feature work or bug fixes
in `web/src/` unless explicitly told otherwise — treat it as frozen/
legacy. Everything under "Two UIs on this one printer" is now the
primary reference; the standalone-SPA sections further down are kept
for history/context but are no longer where active work happens.

**Decision (2026-07-30, later the same day): a third interface,
`kapat-vue`, was built and is now the primary deliverable — and this
project is published to GitHub.** See "Third interface: standalone
kapat-vue + GitHub publishing" below for the full story. Short version:
- `/home/pi/kapat-vue` — a brand-new standalone Vue 2 + Vuetify app,
  visually identical to the KAPAT tab inside the Mainsail fork (same
  components, copied byte-for-byte where possible), but as its own
  full-screen page with no Mainsail sidebar/chrome around it. This is
  now what's actually deployed at `http://<host>/kapat/` on this
  machine — **the old Svelte SPA (`web/src/` as described throughout
  most of this file) has been deleted entirely**, both from this
  machine's nginx deployment and from the `KAPAT` GitHub repo's
  contents. Treat every mention of the Svelte app below this point as
  historical only; it no longer exists anywhere.
- This repo (`/home/pi/KAPAT`) is now published at
  [github.com/vzagranichnyy/KAPAT](https://github.com/vzagranichnyy/KAPAT),
  restructured around two **pre-built** web UIs (`web-dist/` = kapat-vue,
  `mainsail-dist/` = the Mainsail+KAPAT fork) instead of the old Svelte
  source tree — see that section for `install.sh`'s new `--web=`
  flag and the new `switch-web.sh`/`uninstall.sh` scripts.
- The Mainsail fork (`/home/pi/mainsail-src`) is separately published at
  [github.com/vzagranichnyy/Mainsail-Kapat](https://github.com/vzagranichnyy/Mainsail-Kapat).
- A private full-tree backup (source + `node_modules`, everything) lives
  at [github.com/vzagranichnyy/KAPAT_code](https://github.com/vzagranichnyy/KAPAT_code)
  (private repo) — re-synced on request, not automatically kept current.

There are now **three separate installs** of this project:

1. **This machine** (`pi@` on this CB2, working dir `/home/pi/KAPAT`) —
   the dev copy. Everything below "Rebuild/redeploy workflow" onward
   describes this host's *historical* Svelte-era state unless stated
   otherwise — re-read the kapat-vue section above first, since the
   actually-deployed web UI has since changed out from under most of
   that narrative.
2. **A second printer** (`biqu@bigtreetech-cb2`, a *different* physical
   board that happens to share the same default BTT hostname) — set up
   earlier by tar'ing this repo up and running `install.sh` there.
   See "Second install: biqu@bigtreetech-cb2" below for its
   install-specific state; that machine is not reachable from this
   session, so anything about its live status is only as good as what
   the user has reported back in chat.
3. **A third machine, `pi@mainsailos`** (a MainsailOS-imaged box,
   Klipper at `/home/pi/klipper`, klippy-env Python 3.9) — installed
   this session via `git clone` + `./install.sh` from the freshly
   published `KAPAT` repo, entirely over chat (this session has no
   direct access to it either; same caveat as biqu's box applies). This
   install is where the three real `install.sh` bugs described in the
   kapat-vue/GitHub section below were actually found and fixed — see
   that section, don't re-debug them from scratch if they look familiar.

## Third interface: standalone kapat-vue + GitHub publishing

### Why a third interface

After the Mainsail-fork KAPAT tab (see "Two UIs on this one printer"
below) was working and polished, the user asked for a *third*, fully
standalone version: take the KAPAT tab's design exactly as-is and turn
it into its own Vue app — full-screen, no Mainsail sidebar/topbar around
it, just the calibration UI — plus a language switcher (not present in
the Mainsail-fork tab itself, added new in the app shell around it).

### Where it lives and how it's built

`/home/pi/kapat-vue` — Vue 2.7 + Vuetify 2 + `vue-class-component`, Vite
8 (the same rolldown-backed Vite version as `mainsail-src`), built with
`PATH=/home/pi/node20/bin:$PATH npm run build` (system Node 18.20.4 is
too old, same as `mainsail-src`).

**Every `Kapat*.vue` component and every `kapat*.ts` lib file was copied
byte-for-byte** from `mainsail-src` — confirmed via grep that none of
them touch `$store`/`$socket`/`$vuetify` except in the few specific
spots enumerated below, so this was almost entirely a matter of
figuring out *exactly* what infrastructure those files lean on, and
reproducing the minimum of it standalone (not reusing Mainsail's full
Vuex store, which would have meant embedding most of Mainsail anyway):

- `Panel.vue`, `NumberInput.vue`, `ConfirmationDialog.vue` — copied
  near-verbatim (same template/CSS). `Panel.vue`'s collapse-state
  persistence was rewired from Mainsail's Vuex `gui/getPanelExpand` +
  Moonraker-database round-trip to plain `localStorage` — same visible
  behavior, no store needed.
- `BaseMixin` — trimmed to just `isMobile`/`isTablet`/`isDesktop`/
  `isWidescreen`/`viewport` (pure `$vuetify.breakpoint` reads). Grepping
  every copied file confirmed these are the *only* BaseMixin members
  anything actually calls — the real BaseMixin's dozens of other Vuex-
  backed getters (klippy state, power devices, print stats, etc.) are
  unused dead weight for this app.
- **The one genuinely new piece of infrastructure**: `kapatMoonraker.ts`,
  a minimal standalone Moonraker JSON-RPC client (`printer.objects.subscribe`
  on `extruder`/`toolhead`/`kapat`, plus `printer.gcode.script`). Needed
  because `Kapat.vue` itself (unlike every child component) *does* read
  `$store.state.printer.{kapat,extruder,toolhead}` and call
  `$socket.emitAndWait('printer.gcode.script', ...)` directly, for the
  auto-home/auto-heat preflight sequence and live sweep-status polling.
  This connects to the *normal* `ws://<host>/websocket` (nginx-proxied,
  same port as the page itself) — completely separate from
  `kapatBridge.ts`'s raw `:7125/klippysocket` connection, which was
  already self-contained and needed zero changes (`KlippyBridge` already
  defaults to `window.location.hostname`, so it "just works" as long as
  the app is served from the same host as the printer).
- `KapatLiveChart.vue`'s three view-preference settings (smoothing
  toggle, avg window, buffer seconds) — same `localStorage` treatment
  as `Panel.vue`'s collapse state, replacing Mainsail's
  `gui/saveSetting`.
- App shell (`App.vue`, new file, no Mainsail equivalent): just
  `<v-app>` → `<v-main>` → the Kapat page, plus a small fixed-position
  globe-icon button opening a language menu (`vue-i18n`, `en`/`ru`,
  persisted to `localStorage`). Locale JSON files are trimmed to just
  the `Kapat.*` / `App.NumberInput.*` / `Buttons.Cancel` keys actually
  used, not Mainsail's full translation file.

### Two real build-toolchain bugs found getting this to actually run

Both were invisible until the built bundle was tested for real (`vite
build` succeeded cleanly both times, no errors) — caught only by trying
to load the page in a browser and by running `node --check`/`acorn` on
the raw output bundle:

1. **Vite 8's Oxc-based TS transform doesn't auto-detect
   `experimentalDecorators` from `tsconfig.json`** the way esbuild used
   to. Without an explicit opt-in, `@Component`-decorated *plain `.ts`
   files* (just `base.ts` here — every other decorated class lives
   inside a `.vue` SFC, which apparently goes through a different path)
   were left with raw, untransformed decorator syntax in the output —
   `var mm=@lm class extends U{...}`, invalid at runtime, threw
   `SyntaxError: Invalid or unexpected token` the instant the browser
   tried to load the bundle, which manifested as a **silent, no-console-
   error blank page** (the very first script-tag parse failure happened
   before any of the app's own error handling could run). Root-caused
   by downloading the built bundle and running `node --check` on it,
   then `acorn.parse()` for an exact byte offset — pointed straight at
   `BaseMixin`'s `@Component` line. Fix: found the *exact* answer
   already sitting in `mainsail-src/vite.config.ts` (with its own
   comment explaining the same thing) —
   ```ts
   oxc: { decorator: { legacy: true } }
   ```
2. **Vite's default `base: '/'` bakes absolute `/assets/...` paths into
   the build**, which 404s the instant the app is served from a
   subpath (`/kapat/`, or `/kapat-vue/` during the period it briefly
   lived there — see below) instead of domain root. Fix: set
   `base: '/kapat/'` in `vite.config.ts`, matching wherever it's
   *actually* deployed at build time — this means **the dist output is
   deployment-path-specific and must be rebuilt if the path changes**
   (bit exactly this when the app was later renamed from `/kapat-vue/`
   to `/kapat/`, see below).

### One real runtime bug: stale computed getter/setter pairs

Found *after* deploying and the user reporting "sections don't collapse
any more, and Analysis looks incomplete." Root cause, confirmed by
injected-JS inspection of the live Vue instance: `Panel.vue`'s `expand`
was a `get`/`set` pair backed by a separate private field (`_expand`) —
the setter updated `_expand` correctly (confirmed directly), but the
*getter* the template reads back stayed stuck on the old value. Same
shape of bug as the two decorator issues above — something about how
this specific Vite/Oxc toolchain compiles class fields + computed
accessor pairs together doesn't preserve Vue's reactivity link between
them, even though the identical get/set-pair-over-a-private-field
pattern is used throughout `mainsail-src` itself without any problem
there (different toolchain config, most likely the same `oxc.decorator.legacy`
interaction, though never root-caused further than "avoid the pattern").
**Fix, and the pattern to use from now on in this specific project**:
plain reactive field (`expand = true`), toggled directly, persisted via
a separate `@Watch('expand')` handler instead of inside a setter — no
getter/setter pair at all. Applied to both `Panel.vue`'s `expand` and
`KapatLiveChart.vue`'s three view-settings (`smoothEnabled`/
`avgWindowMs`/`bufferSeconds`), which had the exact same shape and would
have hit the identical bug. **"Analysis looks incomplete" turned out to
be the same single bug, not two** — once `Panel.vue`'s collapse toggle
actually worked, the Analysis section's full contents were already
correct; side-by-side comparison against the live Mainsail-fork tab on
the same real capture data confirmed byte-identical segment-browser
output. (The still-empty `BdComposite`/`MetricGrid`/`ResultsPanel` panels
underneath are unrelated and expected — those read live `kapatStatus.last`
data that simply wasn't populated in Klipper's in-memory state at the
time, identically true in the Mainsail-fork tab checked side-by-side.)

A separate small cosmetic bug in the same family: `Panel.vue`'s toolbar
icon buttons (e.g. `KapatLiveChart`'s gear icon) size themselves via
`width: var(--panel-toolbar-icon-btn-width)`, a CSS custom property
Mainsail's own `App.vue` sets at the `<v-app>` root — never having been
defined here, the rule was invalid and fell back to Vuetify's default
icon-button size, visibly crowding the button into the card's rounded
corner. Fixed by setting the same variable (`48px`, matching
`panelToolbarHeight`) on this app's own `<v-app :style="cssVars">`.

### Deployment path: `/kapat-vue/` → `/kapat/` (replacing the Svelte SPA)

Initially deployed to `~/kapat-vue-web/`, nginx `location /kapat-vue/`
(and `= /kapat-vue`, same `default_type text/html` exact-match pattern
as everywhere else in this project). Once verified working end-to-end
(real live-chart data, real history, language switch, panel collapse —
all confirmed via the Chrome DevTools MCP tools against the actual
deployed URL, not just `vite preview`), the user asked to **replace the
old Svelte SPA outright**: renamed to `/kapat/` (rebuilt with
`base: '/kapat/'`, redeployed to `~/kapat-web/`, old `~/kapat-web/`
Svelte build deleted, both `/kapat-vue` nginx blocks removed and
replaced with `/kapat` ones pointing at the new directory). **The
standalone Svelte SPA no longer exists anywhere on this machine or in
the GitHub repo** — every "Two UIs on this one printer" / Svelte-SPA
section elsewhere in this file describes a UI that has since been
deleted; kept only for historical narrative.

### GitHub publishing (three repos, `vzagranichnyy` account)

Set up this session, SSH-key auth (generated fresh on this machine, no
`gh` CLI available, no sudo for installing one):

1. **[github.com/vzagranichnyy/KAPAT](https://github.com/vzagranichnyy/KAPAT)**
   (public) — this repo. Published, then later **fully restructured**:
   the old `web/` (Svelte source) directory was deleted outright and
   replaced with two **pre-built** dist folders committed directly as
   files (not source, not a separate branch):
   - `web-dist/` — kapat-vue's build output (~1.7MB), deployed to
     `~/kapat-web/`, served at `/kapat/`.
   - `mainsail-dist/` — the Mainsail+KAPAT fork's build output (~11MB),
     deployed to `~/mainsail/` (i.e. it *replaces* a stock Mainsail
     install at the same path, not an add-on).
   - `install.sh` rewritten around this: no more Node.js/npm needed on
     the target machine at all (both webs ship pre-built). New
     `--web=kapat|mainsail|both` flag (default `kapat`) picks what gets
     deployed.
   - `lib-web.sh` (new) — shared deploy/backup/restore helpers, sourced
     by all three scripts below so they can't drift apart on how a
     deployment is laid out on disk.
   - `switch-web.sh` (new) — change the active web UI after the fact,
     per explicit request ("при смене на веб возвращается стоковый
     маинсейл" — switching back to `kapat` mode restores the user's
     *original* stock Mainsail from a one-time backup
     (`~/mainsail.stock-backup`, taken automatically the first time
     `--web=mainsail` ever runs, never overwritten after that).
   - `uninstall.sh` (new) — removes the Klipper extra symlink, the web
     deployment(s), and the nginx `/kapat` block; restores the stock-
     Mainsail backup if one exists. Deliberately does NOT touch
     `printer.cfg`'s `[kapat]` section or `printer_data/kapat/` (saved
     calibration data) — prints what's left to clean up by hand instead
     of auto-deleting either.
   - README rewritten with an install/switch/uninstall quick-reference
     and 5 real screenshots (`docs/screenshots/`, from actual hardware
     runs, provided by the user as local files after the initial
     publish since pasted-into-chat images aren't reachable as files on
     disk from this session — my own browser-tool screenshots weren't
     reachable either, same limitation, worth remembering next time
     this comes up).
2. **[github.com/vzagranichnyy/Mainsail-Kapat](https://github.com/vzagranichnyy/Mainsail-Kapat)**
   (public) — the `mainsail-src` fork. `main` branch = source (squashed
   to one commit; the local clone here is shallow, which corrupted a
   normal history-preserving push — squashing sidestepped that rather
   than un-shallowing). `release` branch = pre-built `dist/` output at
   the branch root (like a `gh-pages` branch), which is exactly what
   got copied into `KAPAT`'s `mainsail-dist/` above. Upstream CI
   workflows and community-governance files (issue templates, CoC,
   FUNDING, dependabot, etc.) were stripped from `main` — built for
   `mainsail-crew`'s own infra, meaningless (or red-X-failing) on a
   personal single-maintainer fork.
3. **[github.com/vzagranichnyy/KAPAT_code](https://github.com/vzagranichnyy/KAPAT_code)**
   (private) — a full raw filesystem backup, explicitly including
   `node_modules` and everything else the two public repos deliberately
   exclude (`.claude/`, build artifacts, etc.), as insurance beyond the
   curated public repos. Pushed as a single squashed commit (same
   shallow-clone-corruption workaround as above applied to
   `mainsail-src`'s copy inside it). **Not automatically kept in sync**
   — re-push on explicit request only, don't assume it reflects
   anything more recent than whenever it was last asked for.

### Three real bugs found installing on a genuine third device (`mainsailos`)

All found and fixed *during this session*, via the user running
`install.sh` on a real MainsailOS box and pasting back the transcript —
this session has no direct access to that machine.

1. **The `[y/N]` confirmation prompt silently rejected a typed "y"** —
   `Continue? [y/N] y` immediately followed by `Aborted, nothing
   changed.`, with no error. **This is a recurrence of a bug already
   seen once before** (on `biqu@bigtreetech-cb2`, documented further
   down this file as "worked around with `--yes` rather than
   root-caused") — happening again on a *third, unrelated* device
   strongly suggested something systemic about `read -r -p "..." reply`
   + `case "$reply" in [Yy]*)` rather than a one-off fluke, but the
   exact mechanism is still not confirmed (no direct access to test on
   either box). Fixed defensively rather than re-punting to `--yes`
   again: read raw input, strip any `\r` (serial/web-console terminals
   can send one), trim whitespace, lowercase, then match an *exact*
   `y`/`yes` string instead of a glob — and print the normalized value
   back in the abort message, so a third recurrence is actually
   diagnosable instead of another mystery. Confirmed fixed live on
   `mainsailos` (prompt accepted `y` correctly after the fix).
2. **`sed`'s `a\` multi-line-continuation nginx-block insertion broke
   for real**: `sed: -e expression #1, char 36: extra characters after
   command`. Worse, **the script didn't check for this and printed
   "added /kapat location ... and reloaded nginx" anyway** — the block
   was never actually inserted, `nginx -t` still passed because the
   file was simply unchanged, and the script had no way to tell the
   difference. Fixed by writing the block to a temp file and inserting
   it with sed's `r` (read-file) command instead (no per-line escaping
   to get wrong — the same technique already used successfully
   elsewhere in this project's own manual nginx edits), plus an
   explicit `grep` check that the marker actually landed before
   declaring success.
3. **nginx site-config auto-detection picked the wrong file** —
   `find_nginx_site_conf()` did `grep -rl "listen" sites-available/*`
   and matched Debian's stock, *never-enabled* `sites-available/default`
   before ever considering the box's real, actually-enabled
   `sites-available/mainsail` (confirmed via `sites-enabled/` only
   symlinking `mainsail`, and `nginx -T`'s actual active config showing
   `mainsail`, not `default`). **This is a second, separate recurrence**
   of a bug this file *already* documents as fixed once before (see the
   "Gotchas" section far below) — it regressed because `lib-web.sh` was
   written fresh this session without carrying that lesson forward into
   the new helper function. Symptom in the browser: the `/kapat/` URL
   returned HTTP 200, but rendered nothing recognizable — `curl`
   revealed the served HTML referenced `echarts`/`overlayscrollbars`/
   `vuetify` *chunk* filenames, i.e. it was actually falling through to
   serve the box's real Mainsail root, not `~/kapat-web/` at all, because
   the edited (dead) config was never in nginx's actual load path. Fixed
   by making `find_nginx_site_conf()` walk `sites-enabled/` first
   (resolving symlinks to their real target) and only falling back to a
   blind `sites-available/` scan if that comes up empty. Confirmed fixed
   live: re-running `install.sh` after the fix correctly added the block
   to `sites-available/mainsail`, and the page rendered correctly
   (confirmed via the same curl/grep asset check that caught the bug in
   the first place).

**Net result**: `mainsailos` now has a fully working, verified install
of the `kapat` web UI (backend + `web-dist/` + working nginx block), all
three bugs above are fixed in the published repo (not just worked
around locally on that one box), and the user separately exercised
`uninstall.sh` → reinstall on that same box afterward ("веб работает
удаляю и ставлю заново для проверки" / "все отлично") — first real-world
test of `uninstall.sh`, reported working without further issues.

## What's actually deployed right now on this CB2 (pi)

- Klipper extra: symlinked at `~/klipper/klippy/extras/kapat` →
  `klipper_extras/kapat/` in this repo (3 files: `__init__.py`,
  `bd_pressure.py`, `pa_analysis_core.py`). **Live and up to date** —
  the systemd unit was last (re)started at `13:44:22` this session
  (`systemctl show klipper -p ActiveEnterTimestamp`), which postdates
  every `.py` edit made this session (last edit `13:17:30`). Since then
  there have been two *internal* Klipper restarts (`Restarting printer`
  in klippy.log, not a systemd restart — see "Last verification" below
  for why) but no new edits to any of the three files, so the running
  code is still exactly what's on disk. All previously-pending backend
  features (see git-blame/session history if you need the "why") are
  confirmed running with real data now (see "Last verification"):
  - `bd_per_k[i].lo`/`.hi` (per-K min/max, feeds `BdMetricGrid`'s
    error-bar whiskers)
  - `last.phase_fit` / `last.integral_fit` / `last.integral_legacy_fit`
    (`{k_opt, slope, intercept, r_squared}` dicts, feeds `ResultsPanel`'s
    3 fitted-line mini charts)
  - `FILAMENT=` gcode param on `KAPAT_SWEEP` and the
    `<filament>_<temp>C_<timestamp>` capture filename scheme
  - `kapat/delete_all_captures` webhook endpoint
  - `_CAPTURE_KEEP` = 5 (down from 20)
- Web UI: built from `web/src/`, deployed (plain `rsync`, not symlinked)
  to `~/kapat-web/`, served by nginx at `http://<host>/kapat/` **and**
  `http://<host>/kapat` (no trailing slash — see the nginx section
  below for why a second `location` block was needed) via
  `/etc/nginx/sites-available/mainsail` (the file that's actually in
  `sites-enabled` — NOT `default`, see gotcha below).
- Data files: `~/printer_data/kapat/{profiles,history,settings}.json`
  plus `~/printer_data/kapat/captures/<id>.{json,npz}` (raw sweep
  captures for the Analysis tab's segment browser — see below). All
  written by the Klippy extra's own webhook endpoints, NOT Moonraker's
  database and NOT browser localStorage.

## Last verification (do this again before assuming anything is stale)

```bash
# Is dist actually built from current src? (empty output = yes, up to date)
find /home/pi/KAPAT/web/src -newer /home/pi/kapat-web/index.html \( -name "*.svelte" -o -name "*.js" -o -name "*.css" \)

# Is Klipper running the current *.py? Compare these against the restart timestamp --
# the restart must be AFTER all three files' mtimes.
stat -c '%y  %n' /home/pi/KAPAT/klipper_extras/kapat/__init__.py \
                 /home/pi/KAPAT/klipper_extras/kapat/bd_pressure.py \
                 /home/pi/KAPAT/klipper_extras/kapat/pa_analysis_core.py
systemctl show klipper -p ActiveEnterTimestamp

# Any errors since the restart?
grep -iE "error|traceback|exception" ~/printer_data/logs/klippy.log | tail -40
```

**Re-run again `06:38 CEST on 2026-07-30`** (a later session, separate
from the 2026-07-29 one below): nothing on the Svelte-app/Klipper side
changed since — `find web/src -newer kapat-web/index.html` still empty,
all three `.py` mtimes identical to below, `ActiveEnterTimestamp` still
`13:44:21`, still no new `Start printer at` line past `21:05:38`, still
only the same 2 benign `kapat sweep: ... errors=0` lines and the same
known-benign `BlockingIOError`/`webhooks: socket write error` noise —
nothing new to report there. **This session's actual work was entirely
in `/home/pi/mainsail-src`** (the second UI, see "Two UIs on this one
printer" above) — that section has its own up-to-date verification
status; don't confuse the two.

Result of the **2026-07-29 session's** check (run `date` too — that
session spanned from ~13:44 to past 22:15 CEST on 2026-07-29, so "this
session" covers a lot of real sweep activity, not just the initial
restart):

- **dist up to date with src** — `find web/src -newer kapat-web/index.html`
  is still empty. No `web/src/*` file has been touched since the last
  build (most recent src edit `i18n.js` at 13:33:54; the rest of the
  App/AnalysisPanel/HistoryPanel/bridge.js edits are all ≤13:33 too).
- **Klipper `.py` files unchanged** since last check: `__init__.py`
  13:17:30, `bd_pressure.py` 12:50:23, `pa_analysis_core.py` (2026-07-28
  09:14:40, untouched this whole session). Systemd `ActiveEnterTimestamp`
  is still `13:44:21` — **but klippy.log shows two later, non-systemd
  restarts**, `Start printer at ... 21:01:45` and `...21:05:38`. These
  are Klipper's own internal `Restarting printer` (i.e. what
  `FIRMWARE_RESTART`/an MCU-error auto-recovery does), not a
  `systemctl restart` — `ActiveEnterTimestamp` doesn't move for those.
  Root cause of both: `gcode.CommandError: Unable to obtain
  'sensor_bulk_status' response` / `serialhdl.error` — a transient
  bulk-sensor (load cell) MCU comms hiccup, **not a KAPAT code issue**.
  It self-recovered both times (MCU reset commands succeeded, printer
  came back up) and every sweep run after 21:05:38 completed with
  `errors=0`. Worth knowing about if it recurs, but nothing to fix in
  this repo — flag it as a hardware/wiring thing if it happens again
  and starts failing sweeps outright instead of just triggering a
  clean auto-restart.
- **Log since the last restart (line 18768 onward) has no KAPAT-related
  errors.** The only matches for `error|traceback|exception` are: the
  `BlockingIOError: [Errno 11] Resource temporarily unavailable` at
  `gcode.py:481 _respond_raw` (happens during `M109` heating when the
  gcode-response pipe is momentarily full — a known-benign Klipper
  quirk, unrelated to kapat) and repeated `webhooks: socket write
  error <fd>` lines (a browser tab/websocket client disconnecting
  mid-session — benign, seen throughout this project whenever a client
  closes without a clean close handshake). Two `kapat sweep:` summary
  lines in this window, both `errors=0`.
- **`~/printer_data/kapat/captures/` now has REAL data** (it was empty
  at the last check-in; the delete-all button has since been exercised
  and two fresh sweeps run):
  - `unknown_210C_1785354081523.{json,npz}` — `FILAMENT=` param wasn't
    set for this run (defaults to `unknown`).
  - `ISANMATE_ABS_280C_1785355727993.{json,npz}` — **full schema
    confirmed working end-to-end on real hardware data**: sidecar JSON
    has all expected top-level meta keys (`vfr`, `vfr_low`, `tslow`,
    `tfast`, `cycles`, `ks`, `kstep`, `wobble`, `wobble_axis`, `k_opt`,
    `filament`, `temp`, `id`, `created`, `n_segments`, `n_samples`) plus
    a 112-entry `segments` list (14 K values × 8 cycles), each segment
    has `k`/`t_start`/`t_rise`/`t_fall`/`t_end`/`included`/
    `exclude_reason`/`metrics` exactly as designed. `n_samples` was
    76918 — confirms the `.npz` raw-array side is populated and sane.
    **This is real proof the capture-persistence design works**, not
    just that the endpoints don't 404.
- **`history.json` has 3 entries now** (was 1 at the last check-in).
  The two newest (`kOpt≈0.021` @280°C, `kOpt≈0.0526` @210°C) both have
  **`filament: null`** in history despite the 280°C run's capture file
  correctly recording `filament: "ISANMATE_ABS"`. Traced this to
  `App.svelte`'s `logHistory()` (around [App.svelte:169](web/src/App.svelte:169)):
  it reads the reactive `profileLabel` var at *sweep-completion* time,
  while `handleStart` (line 231) captured `profileLabel` into the gcode
  `FILAMENT=` param at *sweep-start* time — if the user changes/clears
  the filament field in the UI while a long sweep is still running,
  the capture file (start-time) and the history entry (completion-time)
  can legitimately disagree on filament. Not necessarily a bug (could
  just be what happened here — the "ISANMATE ABS" profile itself was
  saved via `profiles.json` at `20:10:38`, i.e. *after* the 20:08:45
  sweep completed, so no profile was selected yet at either start or
  completion of that run) but worth knowing if a future session sees
  capture-vs-history filament mismatches and wonders if something's
  broken.
- `profiles.json` now has one real saved profile: `"ISANMATE ABS"`
  (280°C, PA 0.021, params matching the sweep above).
- `settings.json` unchanged: `{"calibX": 0, "calibY": 0, "calibZ": 30}`.
- nginx (`/etc/nginx/sites-available/mainsail`) still has both the
  `location = /kapat` and `location /kapat/` blocks; still the file
  actually in `sites-enabled` (verified via `readlink -f`).

**Net effect: everything backend is not just "live" but now has real
capture data on disk to test the Analysis tab against.** The only
remaining unknown is purely visual (see "Not done" below) — nothing
here points to a code problem.

## Rebuild/redeploy workflow (every time you touch `web/src/`)

```bash
cd /home/pi/KAPAT/web && npm run build
rsync -a --delete /home/pi/KAPAT/web/dist/ /home/pi/kapat-web/
```
No Klipper restart needed for frontend-only changes.

## When you touch `klipper_extras/kapat/*.py`

You (the assistant) cannot run `sudo systemctl restart klipper` —
`sudo` needs an interactive password this session doesn't have. Ask the
user to run it in their own terminal, then re-check the freshness
commands above before assuming your change is live. There is no git
repo here (`git status` fails — "not a git repository"), so there's no
commit history to lean on; file mtime vs. restart timestamp is the only
way to confirm a Python change actually took effect. Always
`python3 -c "import ast; ast.parse(open(path).read())"` every edited
`.py` file before telling the user to restart.

## nginx: `/kapat` (no trailing slash) needs its own `location` block

Hit and fixed this session. A single `location /kapat/ { alias ...;
try_files ...; }` block only matches requests that already have the
trailing slash. Two *separate* problems show up if you skip the exact
match:
1. Visiting `/kapat` (no slash) either 404s or, if you're relying on
   nginx's directory-redirect behavior, silently 301s to `/kapat/` —
   not what was wanted here (explicit user request: bare `/kapat` must
   work as its own URL, no redirect).
2. If you instead add `location = /kapat { alias .../index.html; }` by
   itself **without** `default_type text/html;`, nginx picks the
   response's `Content-Type` from the **request URI's extension**, not
   from the file the alias points at. `/kapat` has no extension in the
   URI, so nginx falls back to `default_type` (`application/
  octet-stream` by default) and the browser offers the page as a
   **file download** instead of rendering it. This is exactly the bug
   the user hit and screenshotted this session ("он запускает
   скачивание файла").

The fix, now baked into both this host's nginx config **and**
`install.sh`'s auto-generated block for future installs:

```nginx
location = /kapat {
    default_type text/html;
    alias /home/pi/kapat-web/index.html;
}
location /kapat/ {
    alias /home/pi/kapat-web/;
    try_files $uri $uri/ /kapat/index.html;
}
```

`install.sh`'s nginx section (`if [ "$WITH_NGINX" -eq 1 ] ...` block)
now emits both location blocks via one `sed` insert. If `install.sh`
detects an *existing* `location /kapat/` in the target site config it
still skips re-adding anything (`grep -q "location /kapat/"` guard) —
so a printer that was set up with the OLD single-block version of
`install.sh` will **not** get auto-upgraded to the two-block form by
re-running the installer; it needs the same manual `sed`/edit applied
by hand (see "Second install" section below, this is exactly the state
`biqu@bigtreetech-cb2` is in).

## Second install: biqu@bigtreetech-cb2

Set up this session from a tarball of this repo (`/home/pi/kapat-
<timestamp>.tar.gz`, `web/node_modules`/`dist`/`.claude` excluded).
Preflight-detected paths on that machine:
- Klipper: `/home/biqu/klipper`
- klippy-env: `/home/biqu/klippy-env` (Python 3.9)
- Web deploy dir: `/home/biqu/kapat-web`
- `install.sh --yes` completed cleanly (the interactive `[y/N]` prompt
  didn't accept a typed `y` for unknown reasons on that box's terminal
  — worked around with `--yes` rather than root-caused; if this
  recurs, look at `read -r -p` behavior under whatever terminal/serial
  setup that box uses).

Still outstanding on that machine (none of this can be verified from
this session — status is only as good as what the user reports back):
- **nginx `/kapat` (no-slash) fix has NOT been confirmed applied.** The
  installer that ran there predates this session's `install.sh`
  two-block update, so it only added `location /kapat/`. A manual `sed`
  command was given to the user in chat to insert the missing
  `location = /kapat { default_type text/html; alias
  /home/biqu/kapat-web/index.html; }` block ahead of the existing one,
  followed by `sudo nginx -t && sudo systemctl reload nginx` — confirm
  this was actually run before assuming `/kapat` (no slash) works
  there.
- **`[kapat]` section still needs adding to that printer's
  `printer.cfg`** (see `docs/printer.cfg.example` in the tarball) and
  **Klipper restarted** there — the installer only places the Python
  extra + web assets + nginx block, it does not touch `printer.cfg`.
  Until both of those happen, `KAPAT_SWEEP` won't exist as a gcode
  command on that printer yet.
- No live-load-cell/sweep verification has happened on that printer at
  all yet (no history, no hardware facts known about it — don't assume
  anything about its sensor type, calibration position, or filament/K
  numbers; those are specific to `pi`'s printer, see "Known-good
  hardware facts" below).

## Two UIs on this one printer (pi) — mainsail-src, discovered this session

Until this session, `CLAUDE.md` only described the standalone Svelte SPA
(`web/src/`, deployed to `~/kapat-web/`, served at `http://<host>/kapat/`).
**That is not the only front-end.** There is a second, completely
separate implementation of the same KAPAT UI, built as a native tab
inside a *custom fork of Mainsail itself* — i.e. not a separate app you
navigate to, but a "КАРАТ" entry in the real Mainsail sidebar, sitting
next to "УПРАВЛЕНИЕ"/"КОНСОЛЬ"/etc. Nobody had written this down before;
it was found by accident when a user bug report ("поправь блоки в
профиле филамента", screenshot with Тип/Бренд/color-swatch fields) didn't
match anything in `web/src/` at all — turned out the screenshot was from
this other UI the whole time.

**Where it lives:**
- Source: `/home/pi/mainsail-src` — a full clone/fork of Mainsail
  v2.18.2 (`git log --oneline` tip is `009ae11 chore: push version
  number to v2.18.2`). **This directory IS a git repo** (unlike
  `/home/pi/KAPAT` itself) — `git status`/`git log` work fine here.
  Currently `Not currently on any branch`, with `package-lock.json`
  showing as modified (pre-existing, not from this session) plus
  whatever you've edited and not yet committed.
- KAPAT-specific files, all added on top of stock Mainsail:
  - `src/pages/Kapat.vue` — the page/route.
  - `src/components/kapat/Kapat*.vue` — one file per panel, named to
    mirror the Svelte app's components: `KapatSweepForm.vue`,
    `KapatProfilePicker.vue`, `KapatLiveChart.vue`,
    `KapatHistoryPanel.vue`, `KapatAnalysisPanel.vue`,
    `KapatBdComposite.vue`, `KapatBdMetricGrid.vue`,
    `KapatBdMetricKOptTable.vue`, `KapatResultsPanel.vue`.
  - `src/lib/kapatBridge.ts`, `kapatData.ts`, `kapatGcode.ts`,
    `kapatBdCost.ts`, `kapatChartColors.ts` — TypeScript equivalents of
    `web/src/lib/bridge.js`/`kvlist.js`/`gcode.js`/`bdCost.js`.
  - `src/lib/kapatSweepState.ts` — has NO Svelte-app equivalent, added
    this session. A plain module-level singleton (not a Vue/Vuex
    reactive store) holding a snapshot of the profile info + sweep
    params for whichever sweep is currently in flight. Exists solely
    because Mainsail's router destroys/recreates `Kapat.vue` on every
    navigation away and back (no `<keep-alive>` anywhere in this app),
    which would otherwise wipe that data mid-sweep — see "Real bug
    found and fixed" under the History-panel notes below for the full
    story.
  - Locale strings under the `Kapat.*` namespace in
    `src/locales/en.json` / `src/locales/ru.json` (both around line 520
    for `Kapat.ProfilePicker.*`).
- **It talks to the exact same backend as the Svelte app** — same
  Klipper webhook endpoints, same `printer_data/kapat/{profiles,history,
  settings}.json`, same captures dir. Editing a profile in one UI is
  immediately visible in the other (same files on disk). This is two
  front-ends over one shared backend, not two separate KAPAT installs.
- Deployed (built) output goes to `/home/pi/mainsail` — confirmed via
  `/etc/nginx/sites-available/mainsail`'s `root /home/pi/mainsail;`
  (this is the SAME nginx site file that also has the `/kapat` and
  `/kapat/` blocks for the *other* app — one nginx config, two apps).
  Reached at `http://<host>/` (the real Mainsail root), sidebar → КАРАТ
  → internal route `/kapat-tab`.

**Building it — do not use the system Node:**
```bash
node --version   # v18.20.4 on this box — CANNOT build this project.
# Vite/rolldown here needs `styleText` from node:util, added in a
# newer Node than what's installed system-wide. Fails immediately with
# "SyntaxError: The requested module 'node:util' does not provide an
# export named 'styleText'".
```
There's a separate Node 22 install specifically for this, at
`/home/pi/node20` (name is misleading — it's actually v22.14.0):
```bash
cd /home/pi/mainsail-src
PATH=/home/pi/node20/bin:$PATH npm run build   # ~3.5 minutes
rsync -a --delete /home/pi/mainsail-src/dist/ /home/pi/mainsail/
```
The build's own `npm run build.zip` sub-step (packages `dist/` into
`mainsail.zip`) fails harmlessly with `zip: not found` — the system
doesn't have the `zip` binary. Ignore it; we deploy the raw `dist/`
folder via rsync, never the zip, so this doesn't block anything.
`node_modules` is already present, no `npm install` needed unless
`package.json` itself changes.

**Bugs found and fixed here this session (all in `mainsail-src`, all
still uncommitted in its git repo as of this writing):**

1. **`src/components/inputs/NumberInput.vue` reverted typed input on
   blur instead of committing it.** This is a **shared, site-wide**
   Mainsail component — also used by `MachineSettingsPanel.vue`,
   `ToolSlider.vue`, `Extruder/PressureAdvanceSettings.vue`,
   `Extruder/FirmwareRetractionSettings.vue`,
   `Extruder/ExtruderControlPanelControl.vue`, `MiscellaneousSlider.vue`
   — i.e. NOT kapat-specific. Its `@blur` handler did
   `value = target.toString()` (silently discarding whatever was typed)
   instead of calling its own `submit()`; only pressing Enter (native
   form submit) or the spinner buttons actually committed a value. This
   is exactly the "temperature doesn't save unless you press Enter" bug
   the user reported. Fixed conservatively — added a new opt-in
   `commitOnBlur` prop (`@Prop({ default: false })`), so every
   *pre-existing* call site (the ones above) keeps its old
   revert-on-blur behavior unchanged, and only KAPAT's own usages pass
   `commit-on-blur` to get the fixed behavior:
   `KapatProfilePicker.vue` (temp + PA fields) and all 9 fields in
   `KapatSweepForm.vue` (kstart/kend/kstep/cycles/wobble/vfrLow/vfr/
   tslow/tfast). **If you ever want this fixed everywhere in Mainsail,
   the flag already exists — just add `commit-on-blur` to the other
   call sites above** (deliberately left alone this session since that
   wasn't asked for and is a bigger blast radius than the KAPAT bug fix).
2. **Filament-profile card layout was uneven** (`KapatProfilePicker.vue`):
   - The color-swatch button (Тип/Бренд/Цвет row) was
     `d-flex align-center` — vertically centered against the *whole*
     row height (label + input), landing visually between the label
     and the input instead of matching either. Changed to `align-end`
     (+ bumped 2.2rem → 2.5rem) so its bottom edge lines up with the
     Тип/Бренд input boxes' bottom edge.
   - The "use last sweep result" icon button was originally crammed
     into the PA field's own column (`d-flex align-center`), squeezing
     the PA input narrower than Temp and mismatched vertically like the
     swatch. First fix (superseded, see below): moved it into its own
     third column matching the swatch's `align-end`/2.5rem sizing.
     **This whole button was removed entirely in a later pass** (explicit
     request — "убери пункт использовать результаты последнего свипа"),
     not just realigned — see "Темп/PA row simplified" further below for
     the final state.
   - "ПРИМЕНИТЬ НА ПРИНТЕРЕ" overflowed its 1/3-width button. Shortened
     `Kapat.ProfilePicker.ApplyToPrinter` in both `ru.json` ("Применить
     на принтере" → "Применить") and `en.json` ("Apply to printer" →
     "Apply") for consistency.

**Verification status of these fixes**: round 1 (commitOnBlur +
swatch align-end) was built, deployed, and confirmed live in-browser —
typed `281` into Темп. теста without pressing Enter, clicked
"Сохранить" directly, and it correctly picked up 281 (prompted the
overwrite/save-as-new confirm as expected, instead of silently reverting
to 280). Round 2 (icon-button column move + "Применить" button rename)
was built, deployed, and its button-text half confirmed live in a later
pass; the icon-column alignment half became moot once the button was
removed outright in round 3 (see below) — no need to chase that
verification any further, the icon doesn't exist anymore.

**Incident this session (already fixed, but worth knowing why)**: while
testing the "temp field" bug live, a coordinate-scaling mismatch between
a screenshot's pixel dimensions and the browser's actual viewport size
caused one click aimed at "Отмена" to land on "Перезаписать" instead,
which really did change the saved "ISANMATE ABS" profile's temp from
280→285°C in `~/printer_data/kapat/profiles.json`. Caught immediately
and reverted by hand back to `280`/original `updated` timestamp
(`2026-07-29T20:10:38.000Z`) — confirmed correct in the file after.
**Lesson for future sessions**: when two buttons sit close together
(confirm/cancel pairs especially), prefer the browser tool's `find` →
ref-based click over raw pixel coordinates taken from a screenshot —
screenshot pixel dimensions are not guaranteed to be 1:1 with the real
page viewport, and a ref-based click doesn't have that failure mode.

**Legacy-data note (resolved)**: the original saved profile,
`"ISANMATE ABS"` (id `1785355336275`), predated the `filamentType`/
`brand` split and showed blank Тип/Бренд when selected in this UI. The
user has since re-saved it through this same UI — `profiles.json` now
has a fresh entry (id `1785359102356`, `filamentType: "ABS"`,
`brand: "Isanmate"`, `color: "#673AB7"`, `pa: 0.026`) with the full
schema populated. If you see a *different* old-style entry again in the
future (no `filamentType`/`brand` keys), same fix applies: re-save it
once through the UI.

**History panel rebuilt as a real Mainsail `v-data-table`, not custom
row-cards.** `KapatHistoryPanel.vue` was a hand-rolled "card per row"
layout (copied from the Svelte app's design) with custom sort-chips.
Rebuilt as a proper `v-data-table` matching the look of Mainsail's own
print-job History page (`HistoryListPanel.vue`) — sortable column
headers (click to sort, native to the table, the old sort-chip row is
gone), built-in pagination footer. **Column order was later changed
per a follow-up mockup** to: Тип, Бренд, Цвет, Темп. теста, Когда
(date+time, still the default sort column, just moved from 1st to 5th
position), PA (`kOpt`, bold/accent-colored like before), применено
(checkmark or `—`), and an
actions column with just two icon buttons + tooltips — **"Сохранить как
профиль" was removed entirely** per explicit request (`saveAsProfile()`
method, its `KapatProfile`-import, and the `SaveAsProfile` locale key in
both `en.json`/`ru.json` are all gone, not just hidden); Apply
(`mdiCheckCircleOutline`) and Delete (`mdiDelete`) stayed. The old
per-row "detail line" (source + K-range/VFR params summary) was also
dropped — not one of the requested columns, and kept the table honest
to what was actually asked for rather than half-migrating extra info in.

To make Тип/Бренд/Цвет possible at all, **history entries needed new
fields that didn't exist before**: previously `KapatHistoryEntry` only
had a flattened `filament: string | null` (whatever `ProfilePicker`'s
combined label happened to be at sweep-completion time — see the
existing filament-mismatch caveat elsewhere in this file, still valid).
Added `filamentType?`/`brand?`/`color?` to the interface (in both
`Kapat.vue` and `KapatHistoryPanel.vue`), and wired them end-to-end:
`KapatProfilePicker.vue` gained 3 new `@Watch`es (mirroring the existing
`derivedLabel`→`update:label` pattern) that emit `update:filamentType`/
`update:brand`/`update:color` whenever those fields change; `Kapat.vue`
tracks them in new `profileFilamentType`/`profileBrand`/`profileColor`
fields (`.sync`-bound on `<kapat-profile-picker>`) and includes them in
`logHistory()`'s entry. **Only sweeps logged from now on will have these
fields populated** — the 3 pre-existing history entries (all from
before this change) correctly show `—` for Тип/Бренд/Цвет, not a bug,
just no data to show (same "graceful `—` fallback" pattern used
everywhere else for optional fields in this project).

Built, deployed, and confirmed live: table renders with the 3 old
entries showing `—`/`—`/`—` for the new columns and real values for
Темп/PA/применено; column-header click-to-sort works; the "Применить"
tooltip shows on hover; "Сохранить как профиль" is gone from the
actions column (previously a 3rd button, now just the 2 icons).

**Uneven column spacing, fixed.** With no explicit column widths,
`v-data-table`'s underlying `<table>` uses the browser's default
`table-layout: auto`, which sizes each column by its own content and
dumps ALL leftover page width onto whatever happens to be left over —
looked like random, disproportionate gaps between headers (user
screenshotted this). Fixed by giving every header an explicit `width`
(`%`-based, roughly matching how much each column actually needs — Цвет
gets 8%, actions 14%, etc.) AND adding `table-layout: fixed` to
`.kapat-history-table` in scoped CSS — `auto` layout ignores `width`
hints once content overflows, `fixed` actually enforces them. Added
`overflow: hidden; text-overflow: ellipsis` alongside the existing
`white-space: nowrap` on `td`/`th` too, since `fixed` layout means a
too-long value now gets truncated instead of overflowing/wrecking the
row, whereas before `auto` layout just silently grew the column instead.

**Real bug found and fixed: brand-new sweeps were logging `filament:
null` and `params: null` to history EVEN WITH a real profile selected**
— exactly the scenario the "Not yet exercised" note above used to flag
as unverified, and it turned out NOT to work. Root-caused by testing
live (Vue devtools-style inspection via injected JS, reading
`Kapat.vue`'s reactive data directly) rather than guessing:

- Mainsail's router **never wraps any page in `<keep-alive>`**
  (verified: zero matches for `keep-alive` anywhere in `mainsail-src`).
  Every page component, `Kapat.vue` included, is fully destroyed and
  recreated each time you navigate to a different sidebar item and
  back — this is normal/fine for pages that only mirror Vuex state
  (which persists across navigation), but `Kapat.vue` was keeping
  several pieces of state that needed to survive an in-progress,
  multi-minute sweep purely in its own `data()`: `profileLabel`,
  `profileFilamentType`, `profileBrand`, `profileColor`, and
  `lastSweepParams`. **Reproduced directly**: selected the "Isanmate
  ABS" profile (confirmed via injected JS that `Kapat.vue`'s
  `profileFilamentType`/`profileBrand`/`profileColor`/`profileLabel`
  were all correctly populated — so the `.sync` prop-passing chain from
  `KapatProfilePicker.vue` itself was never the problem), then clicked
  to "УПРАВЛЕНИЕ" and back to "КАРАТ" — the profile-picker dropdown
  reverted to "Новый профиль" and every one of those fields reset to
  empty/default. A real sweep runs long enough that a user checking any
  other tab meanwhile is completely normal usage, not an edge case.
- **Fix**: added `src/lib/kapatSweepState.ts`, a plain module-level
  singleton (`kapatSweepState = { label, filamentType, brand, color,
  params }`) that is NOT tied to any Vue component instance and
  therefore isn't destroyed when `Kapat.vue` is. `handleStart()` now
  snapshots the current profile info + sweep params into it right
  before issuing `KAPAT_SWEEP` (replacing the old `this.lastSweepParams
  = params` local-only assignment), and `logHistory()` reads back from
  the singleton instead of `this.profileLabel`/`this.profileFilamentType`
  /etc. — so even if the page got destroyed and recreated in between,
  the snapshot taken at the moment the sweep actually started survives.
  `lastSweepParams` (the old, now-redundant local field) was deleted.
- **A second, related bug in the same area, caught while reading the
  code (not yet independently reproduced)**: `onSweepingChange`'s
  `if (this.wasSweeping && !sweeping)` guard uses `wasSweeping`, also
  page-local `data()` defaulting to `false`. If the page gets recreated
  *while a sweep is already running* (not just started-and-finished
  within one page lifetime), `wasSweeping` starts `false` on the fresh
  instance, so the eventual real true→false completion transition fails
  the `wasSweeping &&` check and **`logHistory()` never runs at all** —
  worse than the filament-null case, a silently-dropped history entry
  with no error. Fixed by seeding `this.wasSweeping = this.sweeping` in
  `created()`, so a page recreated mid-sweep correctly starts with
  `wasSweeping = true` instead of the stale default.
- **Verified**: the `.sync` chain and the destroy/recreate-on-navigation
  behavior were both directly reproduced and confirmed via injected
  JS + manual navigation (see above). The full fix (build → deploy →
  actually start a real sweep, navigate away and back, confirm the
  resulting history entry has real filament/type/brand/color/params)
  has **not** been end-to-end tested with real hardware — that requires
  homing/heating the printer, a real physical action this session
  didn't trigger unprompted. Build succeeded with no TypeScript errors
  and the page loads with zero console errors after deploy; the actual
  "does a real sweep now log correctly" check is still owed next time a
  real sweep runs (with or without navigating away mid-sweep — both
  paths should now work).

**Follow-up report: user said history STILL showed `—` for Тип/Бренд/
Цвет after the fix above.** Investigated by checking `history.json` on
disk directly — the two entries the user was looking at (`kOpt≈0.0212`
at `07:11:29Z`, `kOpt≈0.0210` at `06:32:12Z`) both still have
`params: null` too, not just missing filament fields. Checked
`kapatSweepState.ts`'s own file-creation mtime (`08:52:06 CEST` =
`06:52:12Z`) against those timestamps: the `06:32` entry unambiguously
**predates** the fix even existing (expected to be broken, not a
regression). The `07:11` entry postdates the fix's *creation*, but
whether the deployed bundle was actually live in the *user's already-
open browser tab* at the moment they clicked Start is a separate
question — a SPA never hot-swaps its own already-loaded JS just
because the server's files changed underneath it; only a fresh
page load (or hard refresh) picks up a new build. Checked whether a
service worker could be compounding this (this app ships one — see the
`PWA v1.3.0` / `generateSW` / `dist/sw.js` lines in every build log) —
**ruled out**: `navigator.serviceWorker` is `undefined` in the browser
here, because service workers require a secure context (HTTPS or
`localhost`) and this printer is reached over plain `http://<LAN-IP>/`,
so no SW can register at all on this deployment. Net conclusion: **the
fix itself is verified correct and live in the current deployed bundle**
(confirmed the exact code is present in `Kapat.vue`, confirmed via
injected JS that profile selection correctly populates the reactive
fields the fix reads from) — the 2 stale-looking entries are just old
data from before/right-at the fix's rollout, not evidence the fix is
broken. **Confirmed fixed** — the user ran a fresh sweep right after
this (id `1785399519780`, `2026-07-30T08:18:39.780Z`, K 0.015–0.05 @280°C)
and the resulting `history.json` entry has **everything populated**:
`params` (the full real sweep params dict, not `null`), `filament:
"Isanmate ABS"`, `filamentType: "ABS"`, `brand: "Isanmate"`,
`color: "#673AB7"`. This is the first real end-to-end proof the
`kapatSweepState.ts` fix actually works on real hardware, not just in
injected-JS testing. Close this out — no further verification needed
on this specific bug.

**Pixel-perfect row alignment between `KapatSweepForm.vue` and
`KapatProfilePicker.vue`'s cards (the two side-by-side cards on the
Calibrate section)**, per explicit request with a ruler/guide-line
screenshot showing they didn't line up. Root-caused and fixed by
actually measuring, not eyeballing — read both cards' rendered
`getBoundingClientRect()` via injected JS (`document.querySelector(...)`
+ reading `.top`/`.bottom` on each row), rather than guessing at CSS
values:
- `KapatSweepForm.vue`'s fields have a strict, consistent **54px
  top-to-top rhythm** per row (`.kapat-field { padding-bottom: 0.85rem
  }`, already established — see that file's own comment about why
  padding and not margin is used there, re-used below for the same
  reason).
- `KapatProfilePicker.vue`'s rows used Vuetify's `mb-3`/`mb-1`/`mb-2`/
  `mt-2` spacer utilities, which don't land on 54px and — worse —
  **adjacent block-level margins collapse to their max, not their
  sum**, so tweaking one row's class had non-obvious effects on gaps
  it wasn't supposed to touch.
- Fix: wrapped each row (or applied directly, for the last one) in a
  `.kapat-align-row-N` class using `padding-bottom` (not margin) —
  sidesteps collapsing the same way `.kapat-field` already does.
  Exact px values (13 / 6 / 6 / 17 / 8) were solved from the measured
  gaps needed to hit each target top, not guessed.
- **A second, less obvious bug surfaced mid-fix**: Vuetify's
  `.row--dense` class carries a built-in `margin: -4px` on every side.
  With no `padding-top` on the wrapper divs to contain it, each row's
  own `-4px` top margin escaped upward past its wrapper and overlapped
  the *previous* row, which initially made things measurably worse, not
  better, after the first attempt. Fixed with a second scoped-CSS pass
  zeroing just `margin-top`/`margin-bottom` on the inner `.row--dense`
  elements (left/right margins kept, since `dense` columns still rely
  on them for gutter compensation).
- **Verified precisely, not just visually**: after the fix, re-measured
  both cards' row tops via the same injected-JS technique —
  `KapatSweepForm`'s 5 target tops and `KapatProfilePicker`'s 5 actual
  tops now match to within 1px (browser sub-pixel rounding), and a
  screenshot confirms all 5 row-pairs (dropdown/Тип-Бренд-Цвет/Темп-PA/
  Save-Delete-Apply/X-Y-Z-Save ↔ Медленный поток/Быстрый поток/Время
  медленного/Время быстрого/Начать калибровку) line up cleanly.

**Follow-up: card bottoms didn't match even with all 5 row tops
aligned** — the Профиль филамента card stuck out a few px below the
Калибровка Pressure Advance card (user caught this in a follow-up
screenshot). Cause: row 5 (X/Y/Z + Save) is inherently taller than
`KapatSweepForm`'s bare "Начать калибровку" `v-btn` (number-inputs vs a
plain button), so even with identical TOP positions the two cards'
last rows don't have the same height, and the difference compounds
into the trailing `v-card-text` padding both cards add afterward.
Fixed with a **negative** `margin-bottom: -8px` on row 5 specifically
(padding can't go negative, margin can — pulls the card's own trailing
padding back up without moving row 5's top position at all). Value
was solved the same way as the row spacing above: measured both cards'
`getBoundingClientRect().bottom` via injected JS, tried `-16px` first
(overshot by 8px, would've made the profile card *shorter* than the
sweep card), corrected to `-8px`, re-measured — **both card bottoms
now match to 0px exactly**, confirmed by both direct measurement and a
screenshot.

**Calibration-position setting — added this session, then relocated
(current state: lives inside `KapatProfilePicker.vue`, NOT a separate
component).** The Mainsail fork previously had NO way to view or edit
`calibX`/`calibY`/`calibZ` at all — `Kapat.vue` loaded them from
`settings.json` in `created()` and used them silently in `handleStart`'s
`G1` move, but nothing in the UI exposed them (the Svelte SPA's
`SettingsPanel.svelte` already had this; the Mainsail fork didn't).

Went through 3 iterations before landing on the current form, each per
explicit user feedback — don't be surprised if this looks like a lot of
churn for one small feature, that's just how it happened:
1. A standalone `KapatCalibPositionPanel.vue`, its own collapsible
   panel between History and Analysis.
2. Merged into the bottom of the Профиль филамента card instead
   (explicit request, with a rough sketch) — standalone file deleted
   (`rm KapatCalibPositionPanel.vue`), content moved into
   `KapatProfilePicker.vue` below a `v-divider`, with a muted title +
   hint line above 3 `number-input`s (X/Y/Z) stacked over their own
   "Сохранить" button.
3. **Current final form** (user sent a screenshot of exactly the
   layout they wanted): divider AND the title/hint text lines were
   dropped entirely — `Kapat.CalibPosition.Title`/`.Hint` locale keys
   removed from both `en.json`/`ru.json` since nothing references them
   anymore. X, Y, Z, and the "Сохранить" button now sit in one single
   `v-row`, 4 equal `cols="3"` columns, directly under the profile's
   own Save/Delete/Apply row with no visual separator — matches the
   sketch exactly. The Save button needed an explicit
   `.kapat-calib-save-btn { height: 2.5rem !important; }` (couldn't
   just rely on `align-end` like the color swatch/old icon button did —
   Vuetify's default button height doesn't match the number-input's
   outlined-dense text-field height on its own, so the button looked
   vertically "off"/crooked next to X/Y/Z until forced to the same
   2.5rem used everywhere else in this card).

`calibX`/`calibY`/`calibZ` are props on `KapatProfilePicker`
(`.sync`-bound from `Kapat.vue`, which still owns the actual data and
still loads it in `created()`), saved via `bridge.setData('settings',
{ calibX, calibY, calibZ })` — the same "settings.json is a plain
object, not a list" exception as everywhere else. **Verified live at
each step**: iteration 1 (X `0`→`5`, confirmed written to
`settings.json`, reverted to `0`); iteration 3's layout confirmed via
screenshot to match the user's sketch pixel-for-pixel, and the
button-height fix confirmed via a follow-up zoomed screenshot after the
user flagged it as "криво" (crooked). One scare mid-session: a browser
screenshot call timed out right after a click, and the next screenshot
briefly showed an empty History table — turned out to be a transient
render glitch (page mid-reload), NOT data loss; `history.json` and
`settings.json` were both confirmed intact on disk immediately after.

**Темп/PA row simplified, and the SweepForm title changed** (both
explicit requests, same pass as the calibration-position merge):
- `KapatProfilePicker.vue`'s Темп. теста / PA row dropped its 3rd
  column entirely (the "use last sweep result" icon button, its
  `currentKOpt` prop, the `useSweepResult()` method, the `mdiTrayArrowUp`
  import, and the `.kapat-use-sweep-btn` CSS class — all deleted, not
  hidden) and now uses a plain 2-column `cols="6"`/`cols="6"` split
  instead of the old `4/4/4` grid. `Kapat.vue`'s
  `:current-k-opt="..."` binding on `<kapat-profile-picker>` was
  removed too since the prop no longer exists. The
  `Kapat.ProfilePicker.UseSweepResult` locale string is gone from both
  `en.json`/`ru.json`.
- `Kapat.SweepForm.Title` in `ru.json` changed from "Калибровка
  опережения давления" to **"Калибровка Pressure Advance"** (English
  term kept as-is inside the Russian string, per explicit request) —
  `en.json`'s title was already "Pressure Advance Calibration", left
  unchanged.

Built, deployed, and confirmed live: title reads "Калибровка Pressure
Advance"; Темп/PA fields are now equal half-width with no icon; the
calibration-position block renders correctly inside the profile card
with a divider separating it from the profile fields above; the old
standalone panel between History and Analysis is confirmed gone (no
duplicate).

**Not investigated, flagged in passing**: `/etc/nginx/sites-available/
mainsail` also has an `alias /home/pi/autopa/web/dist/;` and an
`alias /home/pi/printer_data/autopa/captures/;` block — a third,
differently-named project ("autopa") referenced in the same nginx
config. Never looked into what this is (predecessor project? unrelated
leftover?) — don't assume it's connected to KAPAT, but also don't
assume it's dead weight without checking first.

## Architecture — what changed from the original CONTEXT.md design

**Profiles/History/Captures storage.** All local state lives as real
JSON files under `printer_data/kapat/`, written via Klippy webhook
endpoints reached over the same raw klippysocket bridge
(`web/src/lib/bridge.js`) already used for the live load-cell chart —
NOT Moonraker's `server.database.*` API, NOT browser localStorage.
- `kapat/get_data` / `kapat/set_data` (key ∈ `profiles`/`history`/
  `settings`) → `printer_data/kapat/<key>.json`. Array payloads only;
  `settings.json` is an object, so `SettingsPanel.svelte` calls
  `bridge.getData`/`setData` directly instead of through
  `web/src/lib/kvlist.js`'s `loadList`/`saveList` wrappers.
- `kapat/list_captures` / `kapat/get_capture` / `kapat/delete_all_captures`
  → `printer_data/kapat/captures/<id>.{json,npz}` — see "Analysis tab"
  below for the full design.

**Web UI is a 2-tab bar, not 4.** `Calibrate` and `History` are always
in the tab bar (`App.svelte`'s `TABS`). `Analysis` only appears once
Expert mode is on (toggled inside Settings). `Settings` is NOT in the
tab bar at all — it's reached via a gear-icon button
(`SettingsButton.svelte`) in the top-right of the header, always
visible regardless of Expert mode.

**Calibrate tab layout**: `LiveChart` (full width, 224px tall) → 3-column
grid: `SweepForm` (single column of `ScrubInput` rows) | `ProfilePicker`
| `HistoryMini` (last few results, compact).

**Analysis tab** (expert-only) — order matters, matches the reference
layout described below:
`AnalysisPanel` (raw segment browser) → `BdComposite` +
`BdMetricKOptTable` (2-col grid) → `BdMetricGrid` (12-panel per-metric
trend grid) → `ResultsPanel` (recommended K + Apply button, then 3
fitted-line comparison charts).

**Settings tab** (`SettingsPanel.svelte`): theme+accent combined into
one popover button (`ThemePopover.svelte`, wraps `ThemeSwitch` +
`AccentPicker`), language switch, Expert mode toggle, calibration
position (X/Y/Z, persisted), load-cell info (`sensor_type` from
`get_status()`), Moonraker connection status, About.

**Sweep-parameter state is lifted to `App.svelte`**, not owned locally
by `SweepForm` — bound (`bind:vfr` etc.) into both `SweepForm` and
`ProfilePicker` (reads them to save into a profile's `params`, writes
them back via a `loadParams` event when you pick a saved profile).

**Auto-home / auto-heat / auto-position before a sweep** — client-side
orchestration in `App.svelte`'s `handleStart`: not homed →
`ConfirmDialog` → `G28`; always → move to configured calibration X/Y/Z;
nozzle below target-5°C → (skipped if homing's confirm was *just*
shown and accepted — see below) `ConfirmDialog` → `M109 S<temp>`
(blocks until reached); then `KAPAT_SWEEP`. On completion (success or
failure) → `M104 S0`. A `preflightBusy` flag (separate from the
server-polled `sweeping` flag) disables the Start button for the whole
sequence.
- **Confirm-dialog collapsing rule** (explicit user request): if homing
  was needed and the user confirmed it, the *separate* heat confirm is
  skipped — one popup covers both, since agreeing to home already means
  "go ahead and prep the printer." If the printer was already homed
  (no homing popup shown), the heat popup still appears on its own.
  Tracked via a local `justHomed` flag in `handleStart`.
- Home-without-checks is a confirmed, deliberate design decision (asked
  via AskUserQuestion, answered "да, так и задумывалось"): clicking
  Continue on the homing popup sends `G28` immediately with **no
  additional safety checks from the app** — verifying the bed/toolhead
  is actually clear is the user's own responsibility after seeing that
  popup.

**i18n**: `web/src/lib/i18n.js`, EN/RU, a `t` derived store used as
`$t("key", {vars})` everywhere. `bd_pressure` metric AND region names
(overshoot, rise_delay, baseline, rise_edge, plateau, fall_edge, tail,
etc.) are deliberately left untranslated — they're literal identifiers
used throughout the Python analysis code, its docstrings, and its
report output.

**Theme/accent**: `web/src/lib/theme.js`. Dark/light via `data-theme`
attribute + `:root[data-theme="light"]` override in `app.css`. 5 pastel
presets or a fully custom color via a native `<input type="color">`
swatch (solid circle matching the preset swatches, "+" icon with
`mix-blend-mode: difference` for contrast against any hue). uPlot charts
read colors via `cssVar()` at chart-creation time only — switching
theme after a chart exists won't recolor its axes (known/accepted
limitation).

**`ScrubInput.svelte`**: drag-to-scrub number input, replaces sliders
everywhere. `compact` prop: default stretches label + pins value box
far right (used in `SweepForm`); `compact` keeps the value box right
next to the label (used in `ProfilePicker`, `SettingsPanel`'s X/Y/Z).

---

## Analysis tab's raw segment browser

Fully built, end-to-end, backend through UI, styled to match
**CNCKitchen/PrusaPATuner's own segment browser** (its `static/app.js`
+ `static/index.html` were pulled from GitHub and read directly to copy
the composition/layout, not just guessed at — see
`AnalysisPanel.svelte`'s header comment for the exact source). All
backend pieces below are now live (see "Last verification" above) —
what's unverified is purely the visual/UI confirmation on a fresh
capture, not whether the code runs.

### Backend: capture persistence

`cmd_KAPAT_SWEEP` builds the FULL raw `t_rel`/`force` arrays and exact
per-cycle `(t_start, t_rise, t_fall, t_end)` boundaries before
`bd_pressure.py` reduces them to per-K medians. `_save_capture()` (in
`__init__.py`) persists all of it:

- `printer_data/kapat/captures/<id>.npz` — compressed raw `t`/`force`
  arrays only (the potentially-large part).
- `printer_data/kapat/captures/<id>.json` — sidecar with sweep meta
  (vfr/vfr_low/tslow/tfast/cycles/ks/kstep/wobble/wobble_axis/k_opt)
  PLUS a `segments` list: one entry per low-high-low cycle with its
  exact time boundaries, `included`/`exclude_reason` (the auto-quality
  gate's verdict), and its own `metrics` dict (all 13 bd_pressure
  metrics for THAT segment, not just the per-K median) — reusing
  `bd_result.per_k[i].segments[j]`, the same `BdSegment` objects
  `bd_aggregate_per_k` already computes.
- **Capture id/filename** = `<slug(filament)>_<round(temp)>C_<epoch_ms>`
  (e.g. `PETG_240C_1785319666983`). `filament` comes from an optional
  `FILAMENT=` gcode param (App.svelte passes the selected profile's
  label; Klipper has no native concept of "filament", purely a web-UI
  string). `temp` is read server-side from the extruder's actual
  *target* at sweep time (`toolhead.get_extruder().get_status()`), not
  a gcode param — so it reflects what `M109` really set, not just what
  the UI intended.
  - `_slug()` collapses anything outside `[A-Za-z0-9_+-]` to `_` —
    this charset is also what `_capture_id_path()` re-validates against
    on every lookup (path-traversal guard; a plain `isdigit()` check
    doesn't work anymore now the id isn't a bare number).
  - A separate `created` (epoch-ms int) sidecar field exists purely for
    chronological sorting — sorting the id STRING would sort by
    filament name first, which is wrong. `_prune_captures` similarly
    parses the trailing `_`-separated token (the timestamp) rather than
    sorting id strings.
- Retention: last **5** captures kept (`_CAPTURE_KEEP`), pruned on every
  save. `kapat/delete_all_captures` webhook wipes everything on demand
  (`AnalysisPanel`'s "delete all" button, native `confirm()` gate) —
  confirmed working live this session (see "Last verification").
- Capture save failures are caught and logged, never abort the sweep
  report itself.

### Backend: webhook endpoints (all in `__init__.py`)

- `kapat/list_captures` — scans `captures/*.json`, strips the (large)
  `segments` list for a lightweight dropdown listing, sorts by
  `created` descending.
- `kapat/get_capture` (param `id`) — full sidecar + npz `t`/`force`
  arrays as JSON lists. Can be a few hundred KB for a long sweep, so
  `bridge.js`'s `getCapture()` uses a 60s timeout, not the 15s default
  (`bridge.js`'s `call()` now takes an optional `timeoutMs` like
  `moonraker.js`'s `runGcode` already did).
- `kapat/delete_all_captures` — wipes the whole captures dir.

### Backend: extra per-K stats for the metric grid + fit charts

- `bd_pressure.py`'s `BdKResult` gained `lo`/`hi` dicts (min/max per
  metric across included segments in that K, alongside the existing
  `medians`) — feeds `BdMetricGrid`'s error-bar whiskers.
- `__init__.py`'s `self._last` gained `phase_fit`/`integral_fit`/
  `integral_legacy_fit`, each `{k_opt, slope, intercept, r_squared}`
  (previously only bare `k_opt` survived) — lets the frontend draw the
  actual fitted zero-crossing line, not just report the number.

### Frontend: `AnalysisPanel.svelte`

Composition mirrors PrusaPATuner's `.bd-browser` layout: capture
dropdown (+ delete-all) at top, then a 2-column area — an **11rem
vertical K list** on the left (each row: K value + color-coded
`included/total` segment-count badge, green ≥75%/yellow ≥40%/red below
— fraction-based thresholds since KAPAT's default `CYCLES=8` is much
lower than PrusaPATuner's ~16; active K highlighted, K within half a
`kstep` of `k_opt` gets a ring) — and a segment pane on the right:
prev/next nav (`◀ K=0.0250 · segment 3/8 ▶`, also bound to ←/→ keys),
an EXCLUDED banner when the current segment failed the quality gate,
5 overlay toggle checkboxes (transitions / baseline-plateau / regions /
peak-trough / value labels — `regions` defaults OFF, others ON,
matching PrusaPATuner's own defaults), the uPlot waveform chart, a
region-color legend, and **8 numbered stat cards** — the literal 1–8
region split from `bd_pressure.py`'s own module docstring (1 baseline,
2 rise_edge, 3 overshoot, 4 plateau, 5 plateau_creep, 6 fall_edge,
7 undershoot, 8 tail), each a distinct color, showing THIS segment's
own metric values (not the K's median).

Chart shading uses 5 time-window bands (some regions above share a
window: rise_edge+overshoot, plateau+plateau_creep, fall_edge+
undershoot) computed with the exact same `rise_frac`/`fall_frac = 0.2`
hardcoded fractions `bd_segment_metrics` itself uses — replicated in JS
so the shading matches what the metrics function actually measured.
Peak/trough marker positions aren't stored server-side (only the
overshoot/undershoot *magnitude* is) — reconstructed client-side via
argmax/argmin of the raw trace within the rise/fall-edge window, same
math the metric itself used.

Same bridge-readiness race-guard pattern as every other bridge-consuming
component (`$: if (bridge && !bridgeReady) { ...; load(); }`), plus a
defensive `Array.isArray(capture?.meta?.segments)` guard specifically
because a stale/pre-schema-change capture on disk WILL otherwise throw
`.filter is not a function` mid-render and leave "Загрузка захвата…"
stuck forever (hit this for real earlier this session with an old
capture left over from an earlier code version — fixed by both the
guard and deleting the stale file).

### Frontend: `BdMetricGrid.svelte`

Per-metric draw hook (`makeDrawHook(name)`, one closure per metric,
reads `bdPerK`/`metricKOpt` fresh on every `draw()` call — same pattern
as `BdComposite`'s `drawKOptLine`) draws: thin vertical whiskers from
`kr.lo[name]` to `kr.hi[name]` at each K, plus a dashed **green**
vertical line at that metric's own K_opt. The redundant flat K_opt
table that used to sit above the grid was removed (each mini chart
already labels its own K_opt inline; a proper standalone table now
lives next to `BdComposite` instead, see below).

### Frontend: `BdMetricKOptTable.svelte`

Small card next to `BdComposite`: `perMetricKOpt()` (from
`web/src/lib/bdCost.js`, the client-side mirror of
`bd_pressure.analyse_bd`'s per-metric argmin) applied to just the
*weighted* metrics (same set as `BdComposite`'s sliders, via
`defaultWeights`), rendered as a simple 2-column table. Matches
PrusaPATuner's "per-metric K_opt / argmin of each metric in isolation"
card.

### Frontend: `ResultsPanel.svelte`

Recommended-K + Apply-to-printer button + notes (this is the
safety-relevant "apply this K" action, deliberately kept in its
original place during the visual rewrite), followed by a card with 3
mini uPlot charts (phase-lag / integral-area-centered /
integral-area-legacy), each a K-vs-metric scatter + a dashed fitted
line + a green X marker at the fit's zero-crossing K_opt — drawn via a
per-chart canvas hook (`makeFitDrawHook`), not a second uPlot series
(the fit line only needs its 2 endpoints, awkward to align with uPlot's
shared-x-per-series data format; same reasoning as `AnalysisPanel`'s
region shading). Backend fields it needs (`phase_fit`/`integral_fit`/
`integral_legacy_fit`) are live now (see "Last verification") — still
degrades gracefully (scatter only, no line/marker) if a fit is `None`
(e.g. too few valid K points to fit).

### History tab — also redesigned

`HistoryPanel.svelte` went from an 8-column `<table>` (which was
visibly broken — `.results-table`'s shared CSS has zero horizontal
cell padding, so short adjacent values like K_opt and a 3-letter
filament ran together with no visible gap, e.g. "0.0212abs"; action
buttons also overflowed the viewport on the far right) to a list of
row-cards: date/time, a filament chip, temp, an applied✓/— badge, and
a large accent-colored K_opt number on one line; source+params
(ellipsis-truncated, full text on hover) + action buttons on a second
line that wraps instead of overflowing. Sorting moved from
click-the-table-header to small pill/chip buttons above the list
(`sort: when / K_opt / filament`).

## Real bugs found and fixed this project — don't reintroduce

1. **`moonraker.js`'s `call()` had a hardcoded 15s timeout applied to
   every RPC including `runGcode()`.** `G28`/`M109` routinely exceed
   15s; the promise would reject and abort the JS orchestration while
   Klipper kept executing in the background regardless. Fixed via
   `call(method, params, timeoutMs)`, `runGcode()` passing 10 minutes.
   `bridge.js` got the equivalent treatment for `getCapture()` (60s,
   since a raw capture payload can be sizable).
2. **`bridge.js`'s `call()` sent immediately even if the WebSocket
   wasn't open yet**, and child components' plain `onMount(() =>
   load())` could fire before the `bridge` prop even arrived from the
   parent (Svelte mounts children before parent `onMount` runs). Fixed
   with a queued-send-behind-`open` in `bridge.js`, and a
   `$: if (bridge && !bridgeReady) { bridgeReady = true; load(); }`
   reactive guard in every bridge-consuming component (`AnalysisPanel`,
   `ProfilePicker`, `HistoryPanel`, `HistoryMini`, `LiveChart`, ...) —
   if you add a new one, copy this pattern, not a bare `onMount(load)`.
3. **nginx served bare `/kapat` (no trailing slash) as a file download
   instead of the app** — see the dedicated nginx section above. Fixed
   with a `default_type text/html;` exact-match `location = /kapat`
   block, and `install.sh` updated to generate it for future installs.

(Bugs found in the *other* UI, `mainsail-src`, are listed separately
under "Two UIs on this one printer" above — don't miss them just
because they're not in this list.)

## Known-good hardware facts (pi's printer specifically — do NOT assume
these apply to biqu's printer, which is unverified)

- `[load_cell_probe]`, `sensor_type: ads131m02` → chip identifies
  itself as `ADS131M02` via `self.sensor.sensor_type`.
- Calibration position in `settings.json` is currently
  **X=100 Y=10 Z=30** (changed again since the last check-in, which had
  X=0 Y=0 Z=30, which itself replaced an even earlier X=115 Y=100 Z=10
  — re-check `~/printer_data/kapat/settings.json` directly if this
  matters, don't trust any of these numbers blindly; it's user-editable
  from the mainsail-src UI's Профиль филамента card now, see "Two UIs
  on this one printer", and evidently gets changed often).
- `printer.cfg`'s `[extruder]` has `max_extrude_cross_section: 200.0`
  (was 168.0) — needed for the wobble sweep's high extrude-to-travel
  ratio.
- Repeated real successful sweeps this project: ABS-ish filament,
  hotend ~280-281°C, VFR_LOW=1.92 VFR=19.24, 8 cycles, K 0.015–0.06 step
  0.005 (10 K values), composite K_opt consistently landing ≈0.021–0.022,
  `errors=0` every time, including the post-restart sweep this session.

## Gotchas from the original CONTEXT.md still worth knowing

- Two separate Moonraker connections: `:80/websocket` (normal, nginx-
  proxied) vs `:7125/klippysocket` (raw bridge — load_cell/dump_force
  AND all `kapat/*` endpoints live here — NOT proxied by nginx, browser
  must reach port 7125 directly). This applies per-printer — biqu's
  printer will need its own port 7125 reachable the same way.
- `install.sh` auto-detected the WRONG nginx site config **twice now**
  (`default` instead of the actually-enabled `mainsail`) — first here,
  then again on `mainsailos` after `lib-web.sh` was rewritten without
  carrying the lesson forward (see "Third interface: standalone
  kapat-vue + GitHub publishing" above for the full second incident).
  `find_nginx_site_conf()` in `lib-web.sh` now walks `sites-enabled/`
  first, only falling back to a blind `sites-available/` scan if that's
  empty — but if this file ever gets rewritten again from scratch,
  double-check that logic survives; it's regressed once already.
- `.chart-wrap`'s CSS height must match `LiveChart.svelte`'s
  `CHART_HEIGHT` JS constant exactly (224px both places) — a mismatch
  leaves invisible canvas overlapping whatever sits below it, silently
  eating clicks. (This is exactly why `AnalysisPanel`'s and
  `ResultsPanel`'s own charts use differently-named wrapper classes —
  `.segment-chart` / inline `height:170px` divs — instead of reusing
  `.chart-wrap`, to avoid any accidental collision with that global
  224px rule.)
- No git repo in this directory. Don't assume `git log`/`git diff`
  work; they don't.
- `systemctl show klipper -p ActiveEnterTimestamp` only reflects a real
  `systemctl restart klipper`. Klipper can also restart itself
  internally (`FIRMWARE_RESTART`, or auto-recovery after an MCU comms
  error) — klippy.log will show a fresh `Start printer at ...` line for
  these, but the systemd timestamp does NOT move. If you're checking
  whether a `.py` edit is live, compare file mtimes against BOTH: the
  systemd timestamp AND the latest `Start printer at` line in
  klippy.log (`grep -n "Start printer at" klippy.log | tail -1`) — the
  log line is the one that actually matters for "is my edit loaded."

## Not done — the real next phase

- (Resolved, kept only as a pointer) The "use last sweep result" icon
  button that an earlier pass repositioned was **removed entirely** in
  a later pass — see "Темп/PA row simplified" under "Two UIs on this
  one printer" above. No outstanding verification needed on it.
- (Resolved, kept only as a pointer) The `kapatSweepState.ts` fix for
  history entries missing `params`/`filament`/`filamentType`/`brand`/
  `color` is now **confirmed working on a real sweep** — see the
  "Confirmed fixed" update under "Real bug found and fixed" above.
  `history.json` was cleared by the user before that test sweep, so it
  currently has just the 1 fresh, fully-populated entry — don't be
  alarmed that the older entries documented earlier in this file are
  gone, that was intentional test hygiene, not data loss.
- **Decide whether to commit the `mainsail-src` changes.** It's a real
  git repo (unlike `/home/pi/KAPAT`) but nobody has asked for a commit
  yet — `NumberInput.vue`, `KapatProfilePicker.vue`,
  `KapatSweepForm.vue`, `en.json`, `ru.json` are all currently
  uncommitted working-tree changes there, alongside a pre-existing
  unrelated `package-lock.json` modification that predates this
  session.
- **The `commitOnBlur` prop on `NumberInput.vue` is currently KAPAT-only.**
  If a future request turns out to be "the temperature field on the
  [Extruder/PressureAdvance/FirmwareRetraction/MachineSettings] panel
  also doesn't save without Enter" — that's the exact same bug, same
  fix (`commit-on-blur` on that call site), not a new investigation.
- **Look into the "autopa" nginx aliases** (`/home/pi/autopa/web/dist/`,
  `/home/pi/printer_data/autopa/captures/` in the same nginx site file)
  if it ever becomes relevant — unexplored this session, unknown
  whether it's a live predecessor project or dead config.
- **(Deprioritized 2026-07-30 — work moved to the Mainsail fork, see
  the decision note at the top of this file. Kept here for reference
  only; don't pick this up unless explicitly asked to.)** Visual/UI
  confirmation pass on `pi`'s printer (the Svelte SPA at `/kapat/`,
  NOT the mainsail-src UI above) — backend is now
  confirmed live *with real data on disk* (two captures in
  `~/printer_data/kapat/captures/`, see "Last verification"), so this
  no longer needs a fresh sweep first — just open the Analysis tab at
  `http://<host>/kapat/` and confirm: the capture dropdown lists both
  `unknown_210C...` and `ISANMATE_ABS_280C...` with a
  `filament @tempC — date...` label; picking the ABS one renders the
  112-segment K list with color-coded badges; `BdMetricGrid`'s
  whiskers render (real `lo`/`hi` data exists now); `ResultsPanel`'s 3
  fit charts show a dashed line + green K_opt marker (real
  `phase_fit`/`integral_fit`/`integral_legacy_fit` dicts exist in this
  capture's history — technically these live in `kapatStatus.last`,
  not the capture sidecar, so this specifically needs checking against
  a sweep that's still the *most recent* one server-side, or a fresh
  sweep if too much time has passed and `_last` has moved on); and the
  delete-all button still works against this non-empty list. Nobody
  has actually looked at the rendered page this session — everything
  above is disk/log inspection only, not a browser check.
- **Finish bringing up biqu's printer**: confirm the manual nginx
  no-slash patch was applied, add `[kapat]` to that printer's
  `printer.cfg`, restart Klipper there, then run a first real sweep to
  establish hardware facts for that machine (sensor type, working VFR/K
  range, etc. — do not assume pi's numbers transfer).
- **Things nobody has explicitly asked for but came up in passing** —
  don't do these unless asked: linking a capture_id back to its History
  row for one-click "open this sweep's raw segments from History";
  editable/removable calibration-position presets (only one X/Y/Z
  position exists right now, not per-profile); the "area fills" /
  "plateau slope" overlay toggles PrusaPATuner has that KAPAT's segment
  browser deliberately doesn't (scope was cut for effort/value — the
  region shading + peak/trough markers + per-region stat cards already
  cover the same information without them).
