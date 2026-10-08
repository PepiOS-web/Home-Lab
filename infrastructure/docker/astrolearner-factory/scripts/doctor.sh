#!/usr/bin/env bash
set -Eeuo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

failed=0
port="$(sed -n 's/^ASTRO_PORT=//p' .env 2>/dev/null | tail -n 1)"
port="${port:-8090}"
if [[ ! "$port" =~ ^[0-9]+$ ]]; then
    printf '[ERROR] ASTRO_PORT no es válido en .env\n'
    exit 1
fi

check_command() {
    if command -v "$1" >/dev/null 2>&1; then
        printf '[OK] %s: %s\n' "$1" "$(command -v "$1")"
    else
        printf '[FALTA] %s\n' "$1"
        failed=1
    fi
}

printf '== AstroLearner Factory: preflight ==\n'
printf 'Host: %s\n' "$(hostname)"
printf 'CPU lógicos: %s\n' "$(nproc)"
free -h
df -h /srv/data 2>/dev/null || true

check_command docker
check_command curl

if docker compose version >/dev/null 2>&1; then
    printf '[OK] Docker Compose: %s\n' "$(docker compose version --short)"
else
    printf '[FALTA] Docker Compose o permiso para ejecutarlo\n'
    failed=1
fi

if docker compose config --quiet; then
    printf '[OK] compose.yaml válido\n'
else
    printf '[ERROR] compose.yaml no es válido\n'
    failed=1
fi

if ss -lntH "sport = :${port}" 2>/dev/null | grep -q .; then
    printf '[AVISO] El puerto %s ya está en uso\n' "$port"
else
    printf '[OK] Puerto %s libre\n' "$port"
fi

if [[ "$failed" -ne 0 ]]; then
    printf 'Preflight con incidencias. No se ha modificado el sistema.\n'
    exit 1
fi

printf 'Preflight correcto. No se ha modificado el sistema.\n'
