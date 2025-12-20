#!/bin/sh
set -eu

: "${BASELINER_DOMAIN:?BASELINER_DOMAIN is required}"

TEMPLATE="/etc/nginx/templates/baseliner.conf.template"
OUT="/etc/nginx/conf.d/baseliner.conf"

LE_CERT="/etc/letsencrypt/live/${BASELINER_DOMAIN}/fullchain.pem"
LE_KEY="/etc/letsencrypt/live/${BASELINER_DOMAIN}/privkey.pem"

BOOT_DIR="/etc/nginx/certs"
BOOT_CERT="${BOOT_DIR}/bootstrap.crt"
BOOT_KEY="${BOOT_DIR}/bootstrap.key"

mkdir -p "${BOOT_DIR}"

if [ ! -f "${BOOT_CERT}" ] || [ ! -f "${BOOT_KEY}" ]; then
  echo "[INFO] Generating bootstrap self-signed cert for ${BASELINER_DOMAIN}"
  openssl req -x509 -nodes -newkey rsa:2048 \
    -keyout "${BOOT_KEY}" \
    -out "${BOOT_CERT}" \
    -days 7 \
    -subj "/CN=${BASELINER_DOMAIN}" >/dev/null 2>&1
fi

if [ -f "${LE_CERT}" ] && [ -f "${LE_KEY}" ]; then
  export SSL_CERT="${LE_CERT}"
  export SSL_KEY="${LE_KEY}"
  echo "[OK] Using Let's Encrypt certs for ${BASELINER_DOMAIN}"
else
  export SSL_CERT="${BOOT_CERT}"
  export SSL_KEY="${BOOT_KEY}"
  echo "[WARN] Let's Encrypt cert not found yet; using bootstrap self-signed cert for ${BASELINER_DOMAIN}"
fi

if [ ! -f "$TEMPLATE" ]; then
  echo "[ERROR] Missing template: $TEMPLATE" >&2
  exit 1
fi

envsubst '${BASELINER_DOMAIN} ${SSL_CERT} ${SSL_KEY}' < "$TEMPLATE" > "$OUT"
echo "[OK] Rendered nginx site config for BASELINER_DOMAIN=$BASELINER_DOMAIN"
