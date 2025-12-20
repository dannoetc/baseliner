#!/bin/sh
# Periodically reload nginx so it picks up renewed certificates without manual restarts.
# This is a simple, low-risk approach for MVP ops.
set -eu

(
  while :; do
    sleep 6h
    nginx -s reload >/dev/null 2>&1 || true
  done
) &
