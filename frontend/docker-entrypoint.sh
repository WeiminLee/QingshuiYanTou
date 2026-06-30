#!/bin/sh
set -e

# Default to 1800s (30 min) to match backend AGENT_SSE_TIMEOUT
export PROXY_READ_TIMEOUT="${PROXY_READ_TIMEOUT:-1800s}"

# Substitute only the variables we explicitly want (avoids nginx vars like $uri being eaten)
envsubst '${PROXY_READ_TIMEOUT}' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf

exec nginx -g 'daemon off;'