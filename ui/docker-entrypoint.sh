#!/usr/bin/env sh
set -eu

API_BASE_URL="${UI_API_BASE_URL:-/api}"
CONFIG_JS="/usr/share/nginx/html/config.js"

cat > "$CONFIG_JS" <<EOF
window.__BASELINER__ = window.__BASELINER__ || {};
window.__BASELINER__.API_BASE_URL = "${API_BASE_URL}";
EOF

exec nginx -g 'daemon off;'
