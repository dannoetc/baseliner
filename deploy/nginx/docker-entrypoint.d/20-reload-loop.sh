#!/bin/sh
set -eu

(
  sleep 30
  while :; do
    /docker-entrypoint.d/10-render-template.sh >/dev/null 2>&1 || true
    nginx -s reload >/dev/null 2>&1 || true
    sleep 5m
  done
) &
