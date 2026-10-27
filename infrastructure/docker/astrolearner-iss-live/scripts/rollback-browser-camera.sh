#!/usr/bin/env bash
# Restore only this deployment's configuration/image; never deletes data.
set -euo pipefail
[[ ${EUID} -eq 0 && $# -eq 1 ]] || { printf '%s\n' 'Uso: sudo ./scripts/rollback-browser-camera.sh RUTA_COPIA' >&2; exit 1; }
project_dir=/srv/data/compose/astrolearner-iss-live
cd "$project_dir"
unset COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PATH_SEPARATOR
umask 077
exec 9> "$project_dir/.browser-camera-deploy.lock"
flock -n 9 || { printf '%s\n' 'Ya hay otro despliegue en curso.' >&2; exit 1; }
backup_dir=$(realpath -- "$1")
case "$backup_dir" in
    "$project_dir"/.before-browser-production-*) ;;
    *) printf '%s\n' 'La copia no pertenece a este despliegue.' >&2; exit 1 ;;
esac
[[ -f "$backup_dir/.env" && -f "$backup_dir/image-id" ]] || exit 1
if state=$(curl -fsS --max-time 5 http://127.0.0.1:8092/api/status 2>/dev/null); then
    printf '%s\n' "$state" | python3 app/browser_camera_deployment.py stopped || {
        printf '%s\n' 'Deten el directo desde el portal antes de recuperar.' >&2; exit 1;
    }
else
    running=$(docker inspect --format '{{.State.Running}}' astrolearner-iss-live)
    [[ "$running" == false ]] || {
        printf '%s\n' 'No se puede confirmar la parada. Deten iss-live antes de recuperar:' \
            'sudo docker compose stop iss-live' >&2; exit 1;
    }
fi
old_image=$(<"$backup_dir/image-id")
[[ "$old_image" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 1
docker image inspect "$old_image" >/dev/null
if [[ -f "$backup_dir/browser-image-id" ]]; then
    old_browser_image=$(<"$backup_dir/browser-image-id")
    [[ "$old_browser_image" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 1
    docker image inspect "$old_browser_image" >/dev/null
fi
# Stop only the current sidecar. A restored overlay may start it again if needed.
docker compose stop camera-browser
cp -p -- "$backup_dir/.env" .env
chmod 600 .env
docker image tag "$old_image" astrolearner-iss-live:local
if [[ -n "${old_browser_image:-}" ]]; then
    docker image tag "$old_browser_image" astrolearner-iss-camera-browser:local
fi
docker compose config --quiet
docker compose up -d --force-recreate --wait --wait-timeout 240 iss-live
printf '%s\n' 'Configuracion e imagen anteriores recuperadas; no se ha iniciado una emision.'
