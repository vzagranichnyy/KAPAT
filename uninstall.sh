#!/bin/bash
# Remove everything install.sh / switch-web.sh set up:
#   - the Klipper extra symlink
#   - the KAPAT web UI deployment ($KAPAT_WEB_DIR) and its nginx location
#   - the Mainsail+KAPAT deployment at $MAINSAIL_DIR -- restored to your
#     original stock Mainsail if a backup was taken (see lib-web.sh),
#     otherwise left alone with a warning (nothing to restore FROM)
#
# Does NOT touch:
#   - printer.cfg's [kapat] section (edit/remove that yourself, then
#     restart Klipper)
#   - your calibration data under printer_data/kapat/ (profiles/history/
#     captures) -- shown below in case you want to remove it by hand
#
# Usage:
#   ./uninstall.sh
#   ./uninstall.sh --yes    # don't pause for confirmation

set -u

KAPAT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib-web.sh
source "$KAPAT_DIR/lib-web.sh"

ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y) ASSUME_YES=1 ;;
  esac
done

find_klipper_dir() {
  if [ -n "${KLIPPER_DIR:-}" ] && [ -d "$KLIPPER_DIR/klippy/extras" ]; then
    echo "$KLIPPER_DIR"; return 0
  fi
  [ -L "$HOME/klipper/klippy/extras/kapat" ] && { echo "$HOME/klipper"; return 0; }
  for d in "$HOME"/klipper-* /home/*/klipper; do
    [ -L "$d/klippy/extras/kapat" ] && { echo "$d"; return 0; }
  done
  return 1
}

KLIPPER_DIR="$(find_klipper_dir)"

echo "==> This will remove:"
[ -n "$KLIPPER_DIR" ] && echo "      Klipper extra  -> $KLIPPER_DIR/klippy/extras/kapat (symlink)"
echo "      Web UI         -> $KAPAT_WEB_DIR"
if [ -d "$MAINSAIL_STOCK_BACKUP" ]; then
  echo "      Mainsail       -> $MAINSAIL_DIR restored from stock backup"
elif [ -d "$MAINSAIL_DIR" ]; then
  echo "      Mainsail       -> $MAINSAIL_DIR left as-is (no stock backup on record)"
fi
echo "      nginx          -> /kapat location block, if present"
echo ""
echo "    NOT touched: printer.cfg's [kapat] section, printer_data/kapat/"
echo "    (your saved profiles/history/captures)"
echo ""

if [ "$ASSUME_YES" -ne 1 ]; then
  read -r -p "    Continue? [y/N] " reply
  case "$reply" in
    [Yy]*) ;;
    *) echo "Aborted, nothing changed."; exit 0 ;;
  esac
fi

if [ -n "$KLIPPER_DIR" ] && [ -L "$KLIPPER_DIR/klippy/extras/kapat" ]; then
  echo "==> Removing Klipper extra symlink"
  rm -f "$KLIPPER_DIR/klippy/extras/kapat"
else
  echo "    - no Klipper extra symlink found, skipping"
fi

if [ -d "$KAPAT_WEB_DIR" ]; then
  echo "==> Removing $KAPAT_WEB_DIR"
  rm -rf "$KAPAT_WEB_DIR"
fi

remove_kapat_nginx_block

if [ -d "$MAINSAIL_STOCK_BACKUP" ]; then
  restore_stock_mainsail
  rm -rf "$MAINSAIL_STOCK_BACKUP"
elif [ -d "$MAINSAIL_DIR" ]; then
  warn_msg="no stock Mainsail backup found -- $MAINSAIL_DIR still has the Mainsail+KAPAT build in it."
  echo "    ! $warn_msg"
  echo "      reinstall stock Mainsail yourself (e.g. via KIAUH) if you want it back."
fi

echo ""
echo "==================================================================="
echo "Uninstalled. Remaining manual steps:"
echo "  - remove the [kapat] section from printer.cfg, then restart Klipper"
if [ -d "$HOME/printer_data/kapat" ]; then
  echo "  - delete $HOME/printer_data/kapat if you don't want to keep your"
  echo "    saved profiles/history/captures"
fi
