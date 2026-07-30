#!/bin/bash
# Change which KAPAT web UI is active, after install.sh has already been
# run at least once (Klipper extra + Python deps aren't touched here --
# only the web frontend).
#
# Usage:
#   ./switch-web.sh --to=kapat     # KAPAT web UI at /kapat/
#                                  # (restores your original stock Mainsail
#                                  # to $HOME/mainsail if it was ever
#                                  # replaced by --to=mainsail below)
#   ./switch-web.sh --to=mainsail  # Mainsail+KAPAT fork (replaces
#                                  # whatever's currently at $HOME/mainsail)
#   ./switch-web.sh --to=both      # both at once
#
# Override paths the same way install.sh accepts them:
#   KAPAT_WEB_DIR=/path MAINSAIL_DIR=/path ./switch-web.sh --to=...

set -u

KAPAT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib-web.sh
source "$KAPAT_DIR/lib-web.sh"

TARGET=""
for arg in "$@"; do
  case "$arg" in
    --to=*) TARGET="${arg#--to=}" ;;
  esac
done

case "$TARGET" in
  kapat|mainsail|both) ;;
  *)
    echo "Usage: ./switch-web.sh --to=kapat|mainsail|both"
    exit 1
    ;;
esac

case "$TARGET" in
  kapat)
    deploy_kapat_web
    restore_stock_mainsail
    ;;
  mainsail)
    deploy_mainsail_kapat
    ;;
  both)
    deploy_kapat_web
    deploy_mainsail_kapat
    ;;
esac

echo ""
echo "Switched. Open:"
case "$TARGET" in
  kapat)    echo "  http://<this-host>/kapat/" ;;
  mainsail) echo "  http://<this-host>/  (Mainsail+KAPAT, KAPAT tab in the sidebar)" ;;
  both)     echo "  http://<this-host>/kapat/  and  http://<this-host>/" ;;
esac
