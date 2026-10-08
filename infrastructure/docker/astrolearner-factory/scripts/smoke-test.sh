#!/usr/bin/env bash
set -Eeuo pipefail

port="$(sed -n 's/^ASTRO_PORT=//p' .env 2>/dev/null | tail -n 1)"
port="${port:-8090}"
if [[ ! "$port" =~ ^[0-9]+$ ]]; then
    printf 'ASTRO_PORT no es válido en .env\n' >&2
    exit 1
fi
base_url="http://127.0.0.1:${port}"

printf 'Comprobando %s/health...\n' "$base_url"
curl --fail --silent --show-error "$base_url/health"
printf '\n'

printf 'Comprobando la página principal...\n'
curl --fail --silent --show-error "$base_url/" >/dev/null
printf 'Smoke test correcto.\n'
