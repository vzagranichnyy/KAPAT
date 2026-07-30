#!/bin/bash
# Shared deploy/backup/restore helpers for install.sh, switch-web.sh, and
# uninstall.sh -- kept in one place so the three scripts can't drift apart
# on exactly how a "web" or "mainsail" deployment is laid out on disk.
#
# Sourced, not executed directly. Expects KAPAT_DIR to already be set by
# the caller.

KAPAT_WEB_DIR="${KAPAT_WEB_DIR:-$HOME/kapat-web}"
MAINSAIL_DIR="${MAINSAIL_DIR:-$HOME/mainsail}"
MAINSAIL_STOCK_BACKUP="${MAINSAIL_DIR}.stock-backup"

# nginx location blocks are wrapped in these markers (matching the
# convention already used elsewhere in this project) so switch-web.sh and
# uninstall.sh can find and remove exactly what was added, without
# disturbing anything else in the site config.
NGINX_MARKER_BEGIN="# >>> kapat >>>"
NGINX_MARKER_END="# <<< kapat <<<"

find_nginx_site_conf() {
  grep -rl "listen" /etc/nginx/sites-available/ 2>/dev/null | head -n1
}

# Deploy the standalone kapat-vue web UI to $KAPAT_WEB_DIR and wire nginx's
# /kapat + /kapat/ locations (if nginx is present and not already wired).
deploy_kapat_web() {
  echo "==> Deploying KAPAT web UI to $KAPAT_WEB_DIR"
  mkdir -p "$KAPAT_WEB_DIR"
  rsync -a --delete "$KAPAT_DIR/web-dist/" "$KAPAT_WEB_DIR/"

  if ! command -v nginx >/dev/null 2>&1; then
    echo "    - nginx not found -- serve $KAPAT_WEB_DIR however you like"
    return 0
  fi
  local site_conf
  site_conf="$(find_nginx_site_conf)"
  if [ -z "$site_conf" ]; then
    echo "    ! couldn't find an nginx site config automatically -- add by hand:"
    echo "        location = /kapat { default_type text/html; alias $KAPAT_WEB_DIR/index.html; }"
    echo "        location /kapat/ { alias $KAPAT_WEB_DIR/; try_files \$uri \$uri/ /kapat/index.html; }"
    return 0
  fi
  if grep -q "location /kapat/" "$site_conf"; then
    echo "    - $site_conf already has a /kapat/ location -- leaving it alone"
    return 0
  fi
  # Written to a temp file and inserted with sed's `r` (read file) command
  # rather than interpolating a multi-line string into an `a\` command --
  # `a\` needs each line individually backslash-continued, which broke
  # ("extra characters after command") the first time this was tried
  # against a real nginx site config. `r` just dumps a whole file after
  # the matched line, no per-line escaping to get wrong.
  local block_file
  block_file="$(mktemp)"
  printf '    %s\n    location = /kapat {\n        default_type text/html;\n        alias %s/index.html;\n    }\n    location /kapat/ {\n        alias %s/;\n        try_files $uri $uri/ /kapat/index.html;\n    }\n    %s\n' \
    "$NGINX_MARKER_BEGIN" "$KAPAT_WEB_DIR" "$KAPAT_WEB_DIR" "$NGINX_MARKER_END" > "$block_file"
  sudo sed -i "/^server {/r $block_file" "$site_conf"
  rm -f "$block_file"
  # Verify the insert actually landed before claiming success -- a prior
  # version of this trusted `sed`'s exit unconditionally and reported
  # success even when the edit had silently failed.
  if ! grep -q "$NGINX_MARKER_BEGIN" "$site_conf" 2>/dev/null; then
    echo "    X failed to insert the /kapat location into $site_conf -- add it by hand:"
    echo "        location = /kapat { default_type text/html; alias $KAPAT_WEB_DIR/index.html; }"
    echo "        location /kapat/ { alias $KAPAT_WEB_DIR/; try_files \$uri \$uri/ /kapat/index.html; }"
  elif sudo nginx -t 2>/dev/null; then
    sudo systemctl reload nginx 2>/dev/null || sudo nginx -s reload 2>/dev/null
    echo "    v added /kapat location to $site_conf and reloaded nginx"
  else
    echo "    X nginx config test failed after edit -- check $site_conf and revert if needed"
  fi
}

# Remove the nginx /kapat block this script added (identified by the
# marker comments), if present.
remove_kapat_nginx_block() {
  command -v nginx >/dev/null 2>&1 || return 0
  local site_conf
  site_conf="$(find_nginx_site_conf)"
  [ -z "$site_conf" ] && return 0
  if ! grep -q "$NGINX_MARKER_BEGIN" "$site_conf" 2>/dev/null; then
    return 0
  fi
  echo "==> Removing /kapat nginx location from $site_conf"
  sudo sed -i "/$NGINX_MARKER_BEGIN/,/$NGINX_MARKER_END/d" "$site_conf"
  if sudo nginx -t 2>/dev/null; then
    sudo systemctl reload nginx 2>/dev/null || sudo nginx -s reload 2>/dev/null
  else
    echo "    X nginx config test failed after removing the block -- check $site_conf"
  fi
}

# Deploy the Mainsail+KAPAT fork to $MAINSAIL_DIR, the same path a stock
# Mainsail (e.g. installed via KIAUH) normally lives at -- this REPLACES
# whatever's already being served there. The first time this runs, it
# backs up whatever's currently at $MAINSAIL_DIR (presumed to be a stock
# Mainsail install) to $MAINSAIL_STOCK_BACKUP, so switch-web.sh can put it
# back later. That backup is never overwritten by later calls, so it
# always reflects the original stock install, not some earlier KAPAT state.
deploy_mainsail_kapat() {
  echo "==> Deploying Mainsail+KAPAT to $MAINSAIL_DIR"
  if [ -d "$MAINSAIL_DIR" ] && [ ! -d "$MAINSAIL_STOCK_BACKUP" ]; then
    echo "    - backing up existing $MAINSAIL_DIR -> $MAINSAIL_STOCK_BACKUP (one-time, kept for switch-web.sh/uninstall.sh)"
    cp -a "$MAINSAIL_DIR" "$MAINSAIL_STOCK_BACKUP"
  fi
  mkdir -p "$MAINSAIL_DIR"
  rsync -a --delete "$KAPAT_DIR/mainsail-dist/" "$MAINSAIL_DIR/"
  echo "    - if nginx's root for this site isn't already $MAINSAIL_DIR, point it there by hand"
}

# Restore whatever stock Mainsail was backed up before deploy_mainsail_kapat
# first ran. No-op (with a warning) if there's no backup on record, e.g.
# because Mainsail+KAPAT was the only thing ever deployed to $MAINSAIL_DIR.
restore_stock_mainsail() {
  if [ ! -d "$MAINSAIL_STOCK_BACKUP" ]; then
    echo "    ! no stock Mainsail backup found at $MAINSAIL_STOCK_BACKUP -- nothing to restore."
    echo "      $MAINSAIL_DIR (if it exists) still has the Mainsail+KAPAT build in it."
    echo "      Reinstall stock Mainsail yourself (e.g. via KIAUH) if you want it back."
    return 1
  fi
  echo "==> Restoring stock Mainsail to $MAINSAIL_DIR from $MAINSAIL_STOCK_BACKUP"
  rsync -a --delete "$MAINSAIL_STOCK_BACKUP/" "$MAINSAIL_DIR/"
}
