#!/usr/bin/env bash
# Readiness only: never builds, recreates, stops containers or starts a stream.
set -euo pipefail
[[ ${EUID} -eq 0 ]] || { printf '%s\n' 'Ejecuta esta comprobacion con sudo.' >&2; exit 1; }
cd /srv/data/compose/astrolearner-iss-live
unset COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PATH_SEPARATOR
[[ $# -eq 0 ]] || { printf '%s\n' 'Uso: sudo ./scripts/check-browser-camera.sh' >&2; exit 1; }
curl -fsS --max-time 5 http://127.0.0.1:8092/api/status |
    python3 app/browser_camera_deployment.py stopped
printf '%s\n' 'Comprobando camara, mapa orbital y selector, sin publicar (unos dos minutos como maximo)...'
deadline=$((SECONDS + 120))
next_notice=$((SECONDS + 15))
while (( SECONDS < deadline )); do
    # Read one small local frame so the inactive publisher is not a prerequisite
    # for updating selector status. This starts no FFmpeg or YouTube session.
    if python3 app/browser_camera_deployment.py refresh 2>/dev/null &&
       timeout --kill-after=3s 12s docker compose exec --interactive=false -T iss-live \
           python -m app.browser_camera_deployment verify </dev/null 2>/dev/null; then
        printf '%s\n' 'LISTO: camara y mapa preparados. Puedes iniciar manualmente desde el portal.'
        exit 0
    fi
    if (( SECONDS >= next_notice )); then
        printf 'Aun comprobando disponibilidad; quedan unos %s segundos.\n' "$((deadline - SECONDS))"
        next_notice=$((SECONDS + 15))
    fi
    sleep 2
done
printf '%s\n' 'No se ha confirmado la disponibilidad. No iniciar todavia; comparte este resultado.' >&2
exit 1
