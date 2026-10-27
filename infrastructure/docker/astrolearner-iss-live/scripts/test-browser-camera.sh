#!/bin/sh
# Operator-run bounded test. Never stops or starts the production livestream.
# At >=20 FPS, pauses only its browser after confirming the live is already stopped.
set -eu
TASK_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$TASK_ROOT"
test "$#" -le 1 || { printf '%s\n' 'Uso: sudo ./scripts/test-browser-camera.sh [12|20|30]'; exit 1; }
ISS_CAMERA_TEST_FPS=${1:-12}
case "$ISS_CAMERA_TEST_FPS" in
    12|20|30) ;;
    *) printf '%s\n' 'Solo se admiten pruebas a 12, 20 o 30 FPS.'; exit 1 ;;
esac
export ISS_CAMERA_TEST_FPS
docker info >/dev/null 2>&1 || {
    printf '%s\n' 'Se necesita acceso Docker. Ejecuta este script con sudo en tu terminal.'
    exit 1
}
exec 9> "$TASK_ROOT/.browser-camera-deploy.lock"
flock -n 9 || { printf '%s\n' 'Ya hay otro despliegue o prueba en curso.'; exit 1; }
stopped() {
    curl -fsS --max-time 5 http://127.0.0.1:8092/api/status |
        python3 app/browser_camera_deployment.py stopped
}
require_stopped() {
    stopped || { printf '%s\n' 'Produccion activa o sin estado verificable; prueba cancelada sin detener el directo.' >&2; exit 1; }
}
wait_stopped() {
    remaining=$1
    while [ "$remaining" -gt 0 ]; do
        require_stopped
        sleep 1
        remaining=$((remaining - 1))
    done
}
stopped || { printf '%s\n' 'Pulsa Detener en el portal antes de probar.'; exit 1; }
test -f .env.camera-browser || {
    printf '%s\n' 'Falta .env.camera-browser; configura el permiso antes de probar.'
    exit 1
}
compose() {
    docker compose --project-name astrolearner-iss-camera-test \
        --env-file .env.camera-browser -f compose.camera-browser-staging.yaml "$@"
}
production_compose() {
    docker compose --project-name astrolearner-iss-live --env-file .env \
        -f compose.yaml -f compose.camera-browser-live.yaml "$@"
}
compose config --quiet
printf 'Objetivo de prueba: 1280x720 a %s FPS, sin publicar.\n' "$ISS_CAMERA_TEST_FPS"
production_browser_paused=false
cleanup() {
    result=$?
    trap - EXIT
    if ! compose stop >/dev/null 2>&1; then
        printf '%s\n' 'No se pudo detener staging; prueba no aprobada. Revisa los contenedores de prueba antes de continuar.' >&2
        result=1
    fi
    if [ "$production_browser_paused" = true ]; then
        if production_compose start camera-browser; then
            printf '%s\n' 'Navegador de produccion restaurado con su configuracion anterior; no se ha iniciado un directo.'
        else
            printf '%s\n' 'No se pudo restaurar el navegador. Ejecuta: sudo docker compose start camera-browser' >&2
            result=1
        fi
    fi
    exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
compose build
stopped || { printf '%s\n' 'Se ha iniciado un directo; prueba cancelada.'; exit 1; }
if [ "$ISS_CAMERA_TEST_FPS" -ge 20 ]; then
    production_browser=$(production_compose ps -q --status running camera-browser)
    if [ -n "$production_browser" ]; then
        require_stopped
        printf '%s\n' 'Pausando solo el navegador de produccion durante la prueba, para no duplicar su carga.'
        production_browser_paused=true
        production_compose stop camera-browser
    fi
fi
require_stopped
compose up -d --wait --wait-timeout 180
require_stopped
printf '%s\n' 'Comprobando captura de NASA en el servidor (hasta 90 s)...'
ready=false
for attempt in $(seq 1 45); do
    require_stopped
    if compose exec --interactive=false -T camera-browser python /opt/camera/browser_camera.py --check </dev/null 2>/dev/null; then
        ready=true
        break
    fi
    wait_stopped 2
done
if [ "$ready" != true ]; then
    compose exec --interactive=false -T camera-browser python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8093/health").read().decode())' </dev/null || true
    printf '%s\n' 'No se recibió vídeo válido. No se ha cambiado producción.'
    exit 1
fi
printf '%s\n' 'Prueba local de 100 s: cámara → corte → respaldo → recuperación, con H.264/AAC continuo.'
require_stopped
compose exec --interactive=false -T camera-staging python -m app.browser_camera_preflight </dev/null &
probe_pid=$!
camera_selected=false
for attempt in $(seq 1 25); do
    require_stopped
    # Do not wait for a camera state after an encoder that has already failed.
    if ! kill -0 "$probe_pid" 2>/dev/null; then
        wait "$probe_pid"
        exit 1
    fi
    if python3 - <<'PY'
import json, sys, urllib.request
try:
    with urllib.request.urlopen('http://127.0.0.1:8094/api/status', timeout=2) as response:
        state=json.load(response)
    sys.exit(0 if state.get('video_mode') == 'camera' else 1)
except Exception:
    sys.exit(1)
PY
    then
        camera_selected=true
        break
    fi
    wait_stopped 2
done
if [ "$camera_selected" = true ]; then
    # Ensure the probe has sampled the first camera state before making the cut.
    wait_stopped 3
    compose stop camera-browser
    wait_stopped 6
    compose start camera-browser
else
    printf '%s\n' 'No se seleccionó la cámara; la prueba finalizará sin aprobar el despliegue.'
fi
while kill -0 "$probe_pid" 2>/dev/null; do
    wait_stopped 1
done
wait "$probe_pid"
printf '%s\n' 'Prueba terminada. Configuracion de produccion sin cambios; se detendra staging y se restaurara su navegador si se pauso.'
