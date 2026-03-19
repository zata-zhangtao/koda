#!/bin/sh
set -eu

caddyfile_template_path="/opt/koda/Caddyfile.template"
generated_caddyfile_path="/tmp/Caddyfile.generated"

basic_auth_plaintext_password="${CADDY_BASICAUTH_PASSWORD:-}"
basic_auth_configured_hash="${CADDY_BASICAUTH_HASH:-}"

if [ -n "$basic_auth_plaintext_password" ]; then
    basic_auth_effective_hash="$(caddy hash-password --plaintext "$basic_auth_plaintext_password")"
elif [ -n "$basic_auth_configured_hash" ]; then
    basic_auth_effective_hash="$basic_auth_configured_hash"
else
    echo "Either CADDY_BASICAUTH_PASSWORD or CADDY_BASICAUTH_HASH must be set." >&2
    exit 1
fi

# Escape sed replacement metacharacters before injecting the hash into the template.
basic_auth_escaped_hash="$(printf '%s\n' "$basic_auth_effective_hash" | sed 's/[\\/&]/\\&/g')"
sed "s/__CADDY_BASICAUTH_HASH__/$basic_auth_escaped_hash/g" "$caddyfile_template_path" > "$generated_caddyfile_path"

caddy validate --config "$generated_caddyfile_path"
exec caddy run --config "$generated_caddyfile_path" --adapter caddyfile
