#!/bin/sh
# Starts only an ephemeral browser on about:blank; never changes production.
set -eu
TASK_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$TASK_ROOT"
docker info >/dev/null 2>&1 || {
    printf '%s\n' 'Ejecuta este diagnóstico con sudo en tu terminal.'
    exit 1
}
docker compose --project-name astrolearner-iss-camera-test \
    --env-file .env.camera-browser -f compose.camera-browser-staging.yaml \
    run --rm --no-deps --build camera-browser \
    python /opt/camera/browser_camera.py --diagnose
