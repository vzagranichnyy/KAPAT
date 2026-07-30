#!/bin/bash
# KAPAT installer.
#
# Usage:
#   ./install.sh                  # backend + KAPAT web UI at /kapat/ (default)
#   ./install.sh --web=mainsail   # backend + Mainsail+KAPAT fork instead
#                                 # (replaces whatever's served at $HOME/mainsail)
#   ./install.sh --web=both       # backend + both of the above
#   ./install.sh --no-nginx       # skip nginx wiring
#   ./install.sh --yes            # don't pause for confirmation after preflight
#
# Both web UIs ship pre-built in this repo (web-dist/, mainsail-dist/) --
# no Node.js/npm needed on the machine running this script.
#
# Override any auto-detected path:
#   KLIPPER_DIR=/path/to/klipper KLIPPY_ENV=/path/to/klippy-env \
#   KAPAT_WEB_DIR=/path/to/serve MAINSAIL_DIR=/path/to/mainsail ./install.sh
#
# To change your mind later about which web UI is active, use
# switch-web.sh instead of rerunning this script. To remove everything
# this script and switch-web.sh set up, use uninstall.sh.
#
# This script is meant to run unmodified on whatever machine/user account
# actually runs Klipper -- it does NOT assume $HOME is where Klipper
# lives, that nginx/systemd exist, or that the person running it is the
# same person who ran it last time. Every assumption is checked and
# reported before anything is changed; missing pieces produce a clear
# next step instead of a silent partial install.

set -u  # (not -e: we want to run every preflight check and report all
         # problems at once, not abort at the first one)

KAPAT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib-web.sh
source "$KAPAT_DIR/lib-web.sh"

WITH_NGINX=1
ASSUME_YES=0
WEB_MODE=kapat
for arg in "$@"; do
  case "$arg" in
    --no-nginx) WITH_NGINX=0 ;;
    --yes|-y) ASSUME_YES=1 ;;
    --web=*) WEB_MODE="${arg#--web=}" ;;
  esac
done
case "$WEB_MODE" in
  kapat|mainsail|both) ;;
  *)
    echo "X --web must be one of: kapat, mainsail, both (got: $WEB_MODE)"
    exit 1
    ;;
esac

PROBLEMS=0
warn()  { echo "    ! $*"; }
info()  { echo "    - $*"; }
fail()  { echo "    X $*"; PROBLEMS=$((PROBLEMS + 1)); }
ok()    { echo "    v $*"; }

echo "==> Preflight: detecting your environment"

# --- 1. Find Klipper -------------------------------------------------
find_klipper_dir() {
  if [ -n "${KLIPPER_DIR:-}" ] && [ -d "$KLIPPER_DIR/klippy/extras" ]; then
    echo "$KLIPPER_DIR"; return 0
  fi
  local candidates=()
  [ -d "$HOME/klipper/klippy/extras" ] && candidates+=("$HOME/klipper")
  # KIAUH-style multi-instance layout
  for d in "$HOME"/klipper-*; do
    [ -d "$d/klippy/extras" ] && candidates+=("$d")
  done
  # other users on the same box (common when you're 'pi' but Klipper
  # was set up under a vendor-default account like 'biqu', or vice versa)
  for d in /home/*/klipper; do
    [ -d "$d/klippy/extras" ] && candidates+=("$d")
  done
  if [ "${#candidates[@]}" -ge 1 ]; then
    # dedupe while preserving order (readarray -t + awk keeps first
    # occurrence) -- $HOME/klipper and the /home/*/klipper glob commonly
    # both match the same real path and would otherwise be reported twice
    local deduped=()
    local seen=""
    for c in "${candidates[@]}"; do
      case "$seen" in
        *"|$c|"*) ;;
        *) deduped+=("$c"); seen="$seen|$c|" ;;
      esac
    done
    candidates=("${deduped[@]}")
    echo "${candidates[0]}"
    if [ "${#candidates[@]}" -gt 1 ]; then
      warn "multiple Klipper installs found: ${candidates[*]} -- using the first;" >&2
      warn "set KLIPPER_DIR explicitly if that's the wrong one" >&2
    fi
    return 0
  fi
  return 1
}

find_klippy_env() {
  if [ -n "${KLIPPY_ENV:-}" ] && [ -x "$KLIPPY_ENV/bin/pip" ]; then
    echo "$KLIPPY_ENV"; return 0
  fi
  local base_dir="$1"  # KLIPPER_DIR, so we can guess a sibling env
  local candidates=()
  [ -x "$HOME/klippy-env/bin/pip" ] && candidates+=("$HOME/klippy-env")
  for d in "$HOME"/klippy-env-*; do
    [ -x "$d/bin/pip" ] && candidates+=("$d")
  done
  for d in /home/*/klippy-env; do
    [ -x "$d/bin/pip" ] && candidates+=("$d")
  done
  # sibling of the detected klipper dir, e.g. .../klipper -> .../klippy-env
  if [ -n "$base_dir" ]; then
    local sibling
    sibling="$(dirname "$base_dir")/klippy-env"
    [ -x "$sibling/bin/pip" ] && candidates=("$sibling" "${candidates[@]}")
  fi
  if [ "${#candidates[@]}" -ge 1 ]; then
    local seen=""
    for c in "${candidates[@]}"; do
      case "$seen" in
        *"|$c|"*) ;;
        *) echo "$c"; return 0 ;;
      esac
    done
  fi
  return 1
}

KLIPPER_DIR="$(find_klipper_dir)"
if [ -n "$KLIPPER_DIR" ]; then
  ok "Klipper found at $KLIPPER_DIR"
else
  fail "no Klipper install found (looked in \$HOME, \$HOME/klipper-*, /home/*/klipper)."
  info "set KLIPPER_DIR=/path/to/klipper explicitly and rerun."
fi

KLIPPY_ENV="$(find_klippy_env "${KLIPPER_DIR:-}")"
if [ -n "$KLIPPY_ENV" ]; then
  ok "klippy-env found at $KLIPPY_ENV"
else
  warn "no klippy-env found -- numpy/scipy install will be skipped."
  info "if KAPAT_SWEEP later fails with ImportError, set KLIPPY_ENV=... and rerun."
fi

# --- 2. Python version inside klippy-env (dataclass slots= needs 3.10+,
#        already avoided in this codebase, but worth confirming) --------
if [ -n "$KLIPPY_ENV" ] && [ -x "$KLIPPY_ENV/bin/python" ]; then
  PYVER="$("$KLIPPY_ENV/bin/python" -c 'import sys; print("%d.%d"%sys.version_info[:2])' 2>/dev/null)"
  if [ -n "$PYVER" ]; then
    ok "klippy-env Python is $PYVER"
  fi
fi

# --- 3. nginx / systemd (optional -- degrade gracefully, don't fail) ---
HAVE_NGINX=0
HAVE_SYSTEMD=0
if [ "$WITH_NGINX" -eq 1 ]; then
  if command -v nginx >/dev/null 2>&1; then
    HAVE_NGINX=1
    ok "nginx found"
  else
    warn "nginx not found -- will skip nginx wiring, deploy the web UI anyway"
  fi
fi
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  HAVE_SYSTEMD=1
  ok "systemd found"
else
  warn "no systemd detected -- 'sudo systemctl restart klipper' won't work; restart Klipper however this box normally does it"
fi

# --- 4. write permissions on the target dirs ---------------------------
if [ -n "$KLIPPER_DIR" ] && [ ! -w "$(dirname "$KLIPPER_DIR/klippy/extras/x")" ]; then
  fail "no write permission on $KLIPPER_DIR/klippy/extras -- run as the user that owns Klipper, or with sudo"
fi

echo ""
if [ "$PROBLEMS" -gt 0 ]; then
  echo "==> $PROBLEMS blocking problem(s) found above -- fix those first, nothing has been changed yet."
  exit 1
fi

if [ "$ASSUME_YES" -ne 1 ]; then
  echo "==> Preflight OK. Will install into:"
  echo "      Klipper extra  -> $KLIPPER_DIR/klippy/extras/kapat"
  [ -n "$KLIPPY_ENV" ] && echo "      Python deps    -> $KLIPPY_ENV"
  case "$WEB_MODE" in
    kapat)    echo "      Web UI         -> $KAPAT_WEB_DIR (KAPAT web UI, at /kapat/)" ;;
    mainsail) echo "      Web UI         -> $MAINSAIL_DIR (Mainsail+KAPAT fork, replaces what's there)" ;;
    both)     echo "      Web UI         -> both $KAPAT_WEB_DIR (/kapat/) and $MAINSAIL_DIR" ;;
  esac
  read -r -p "    Continue? [y/N] " reply
  case "$reply" in
    [Yy]*) ;;
    *) echo "Aborted, nothing changed."; exit 0 ;;
  esac
fi

echo ""
echo "==> Installing Klippy extra (symlink, so 'git pull' here updates it live)"
mkdir -p "$KLIPPER_DIR/klippy/extras"
ln -sfn "$KAPAT_DIR/klipper_extras/kapat" "$KLIPPER_DIR/klippy/extras/kapat"
if [ -e "$KLIPPER_DIR/klippy/extras/kapat_pa_sweep.py" ]; then
  warn "removing stale klippy/extras/kapat_pa_sweep.py from an older KAPAT layout"
  rm -f "$KLIPPER_DIR/klippy/extras/kapat_pa_sweep.py"
fi

if [ -n "$KLIPPY_ENV" ]; then
  echo "==> numpy + scipy in klippy-env"
  "$KLIPPY_ENV/bin/pip" install --quiet numpy scipy || \
    warn "pip install failed -- install numpy/scipy in $KLIPPY_ENV by hand"
fi

case "$WEB_MODE" in
  kapat)    deploy_kapat_web ;;
  mainsail) deploy_mainsail_kapat ;;
  both)     deploy_kapat_web; deploy_mainsail_kapat ;;
esac

echo ""
echo "==================================================================="
if [ "$PROBLEMS" -gt 0 ]; then
  echo "Finished with $PROBLEMS problem(s) above -- re-read them before assuming this works."
else
  echo "Install finished cleanly."
fi
case "$WEB_MODE" in
  kapat)    echo "Open: http://<this-host>/kapat/" ;;
  mainsail) echo "Open: http://<this-host>/ (Mainsail+KAPAT, KAPAT tab in the sidebar)" ;;
  both)     echo "Open: http://<this-host>/kapat/  and  http://<this-host>/ (Mainsail+KAPAT)" ;;
esac
echo ""
echo "IMPORTANT: the browser needs TWO connections to Moonraker:"
echo "  - :80/websocket        (proxied by nginx like everything else)"
echo "  - :7125/klippysocket   (raw bridge for load_cell/dump_force --"
echo "    NOT proxied by nginx; the browser connects to port 7125 directly)"
echo "If this printer is only reachable through a proxy/tunnel that doesn't"
echo "forward 7125, everything else will work but the live chart won't."
echo ""
echo "Add a [kapat] section to printer.cfg (see docs/printer.cfg.example)"
if [ "$HAVE_SYSTEMD" -eq 1 ]; then
  echo "then: sudo systemctl restart klipper"
else
  echo "then restart Klipper however this box normally does it."
fi
