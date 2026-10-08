#!/usr/bin/env bash
set -Eeuo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

if [[ "${EUID}" -ne 0 ]]; then
    printf 'Ejecuta este script con sudo: sudo ./scripts/bootstrap.sh\n' >&2
    exit 1
fi

if [[ ! -f .env ]]; then
    install -m 600 .env.example .env
    printf 'Creado .env desde .env.example\n'
fi

if grep -qx 'ASTRO_MODEL=qwen3.5:2b-q4_K_M' .env; then
    sed -i 's/^ASTRO_MODEL=qwen3.5:2b-q4_K_M$/ASTRO_MODEL=qwen3.5:4b-q4_K_M/' .env
    sed -i 's/^ASTRO_CONTEXT_LENGTH=4096$/ASTRO_CONTEXT_LENGTH=6144/' .env
    sed -i 's/^ASTRO_MAX_SOURCE_CHARS=12000$/ASTRO_MAX_SOURCE_CHARS=9000/' .env
    printf 'Actualizada la configuración inicial al modelo auditado de 4B\n'
fi

read_env_value() {
    local key="$1"
    local default_value="$2"
    local allowed_pattern="$3"
    local line value
    line="$(grep -E "^${key}=" .env | tail -n 1 || true)"
    value="${line#*=}"
    if [[ -z "$line" ]]; then
        value="$default_value"
    fi
    if [[ ! "$value" =~ $allowed_pattern ]]; then
        printf 'Valor no válido para %s en .env\n' "$key" >&2
        exit 1
    fi
    printf '%s' "$value"
}

puid="$(read_env_value PUID 1000 '^[0-9]+$')"
pgid="$(read_env_value PGID 1000 '^[0-9]+$')"
astro_model="$(read_env_value ASTRO_MODEL qwen3.5:4b-q4_K_M '^[A-Za-z0-9._:/-]+$')"
tts_voice="$(read_env_value ASTRO_TTS_VOICE es_ES-davefx-medium '^[A-Za-z0-9._-]+$')"
astro_port="$(read_env_value ASTRO_PORT 8090 '^[0-9]+$')"

install -d -m 750 -o "$puid" -g "$pgid" \
    /srv/data/appdata/astrolearner/runtime \
    /srv/data/appdata/astrolearner/voices
install -d -m 750 /srv/data/appdata/astrolearner/ollama

docker compose config --quiet
docker compose pull ollama
docker compose build studio

docker compose up --detach ollama
for _ in $(seq 1 30); do
    if docker compose exec -T ollama ollama list >/dev/null 2>&1; then
        break
    fi
    sleep 2
done
printf 'Descargando modelo local %s (una sola vez)...\n' "$astro_model"
docker compose exec -T ollama ollama pull "$astro_model"

printf 'Descargando voz local %s...\n' "$tts_voice"
docker run --rm --user "$puid:$pgid" \
    --volume /srv/data/appdata/astrolearner/voices:/models \
    astrolearner-factory:local \
    python -m piper.download_voices \
    --data-dir /models \
    "$tts_voice"

docker compose up --detach
docker compose ps

printf '\nAstroLearner Factory iniciado en http://127.0.0.1:%s\n' "$astro_port"
printf 'Desde Windows abre un túnel SSH:\n'
printf '  ssh -L %s:127.0.0.1:%s homelab\n' "$astro_port" "$astro_port"
