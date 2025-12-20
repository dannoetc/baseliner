#!/bin/sh
# Periodically re-render config (to flip from bootstrap cert -> LE cert) and reload nginx.
#
# Important nuance:
# - The official nginx entrypoint will "source" non-executable scripts in /docker-entrypoint.d,
#   so 10-render-template.sh can run at startup even if it isn't +x.
# - But our loop needs to execute it repeatedly. To avoid relying on executable bits, we invoke it via `sh`.
set -eu

(
  # Re-check frequently at startup so HTTPS switches quickly after issuance.
  sleep 30
  while :; do
    sh /docker-entrypoint.d/10-render-template.sh >/dev/null 2>&1 || true
    nginx -s reload >/dev/null 2>&1 || true
    sleep 5m
  done
) &
