#!/bin/sh
set -eu

: "${BASELINER_DOMAIN:?BASELINER_DOMAIN is required}"

TEMPLATE="/etc/nginx/templates/baseliner.conf.template"
OUT="/etc/nginx/conf.d/baseliner.conf"

if [ ! -f "$TEMPLATE" ]; then
  echo "[ERROR] Missing template: $TEMPLATE" >&2
  exit 1
fi

# Render template -> conf.d
envsubst '${BASELINER_DOMAIN}' < "$TEMPLATE" > "$OUT"
echo "[OK] Rendered nginx site config for BASELINER_DOMAIN=$BASELINER_DOMAIN"
