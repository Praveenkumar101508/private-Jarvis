#!/bin/sh
# Substitute $IRA_DOMAIN into nginx.conf.template → /etc/nginx/nginx.conf, then start nginx.
# This pins server_name to the actual configured domain, preventing Host-header injection.

set -e

TEMPLATE="/etc/nginx/nginx.conf.template"
CONF="/etc/nginx/nginx.conf"

if [ ! -f "${TEMPLATE}" ]; then
    echo "ERROR: ${TEMPLATE} not found — check the nginx volume mount." >&2
    exit 1
fi

if [ -z "${IRA_DOMAIN:-}" ]; then
    echo "WARNING: IRA_DOMAIN is not set — defaulting server_name to ira.local" >&2
    IRA_DOMAIN="ira.local"
fi

# Replace only the IRA_DOMAIN variable; leave all other $ signs untouched.
envsubst '${IRA_DOMAIN}' < "${TEMPLATE}" > "${CONF}"

echo "nginx: server_name set to ${IRA_DOMAIN}"
exec nginx -g 'daemon off;'
