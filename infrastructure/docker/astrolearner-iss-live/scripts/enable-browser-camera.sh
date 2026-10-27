#!/usr/bin/env bash
# Operator-run production deployment. Never starts a YouTube broadcast.
set -euo pipefail
[[ ${EUID} -eq 0 ]] || { printf '%s\n' 'Ejecuta este script con sudo.' >&2; exit 1; }
project_dir=/srv/data/compose/astrolearner-iss-live
cd "$project_dir"
unset COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PATH_SEPARATOR
umask 077
[[ $# -le 2 ]] || { printf '%s\n' 'Uso: sudo ./scripts/enable-browser-camera.sh [12|20|30] [esa|astrolearner]' >&2; exit 1; }
fps_args=()
if [[ $# -ge 1 ]]; then
    case "$1" in 12|20|30) fps_args=(--fps "$1") ;;
        *) printf '%s\n' 'Solo se admiten 12, 20 o 30 FPS.' >&2; exit 1 ;;
    esac
fi
if [[ $# -eq 2 ]]; then
    case "$2" in esa|astrolearner) fps_args+=(--map-overlay "$2") ;;
        *) printf '%s\n' 'Mapa no valido: usa esa o astrolearner.' >&2; exit 1 ;;
    esac
fi
exec 9> "$project_dir/.browser-camera-deploy.lock"
flock -n 9 || { printf '%s\n' 'Ya hay otro despliegue en curso.' >&2; exit 1; }

stopped() {
    curl -fsS --max-time 5 http://127.0.0.1:8092/api/status |
        python3 app/browser_camera_deployment.py stopped
}
stopped || { printf '%s\n' 'Pulsa Detener en el portal y espera a que termine el directo.' >&2; exit 1; }
docker info >/dev/null
for other in compose.override.yaml compose.override.yml docker-compose.override.yaml docker-compose.override.yml; do
    [[ ! -e "$other" ]] || { printf '%s\n' 'Existe un override Compose adicional; revisarlo antes de desplegar.' >&2; exit 1; }
done
existing_project=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' astrolearner-iss-live)
[[ "$existing_project" == astrolearner-iss-live ]] || {
    printf '%s\n' 'El contenedor pertenece a otro proyecto; no se modificara.' >&2; exit 1;
}
prepared_env=$(mktemp "$project_dir/.env.browser-production.XXXXXX")
trap 'rm -f -- "$prepared_env"' EXIT
python3 app/browser_camera_deployment.py prepare --production .env --capture .env.camera-browser --output "$prepared_env" "${fps_args[@]}"
chmod 600 "$prepared_env"
chown --reference=.env "$prepared_env"
compose_new() {
    docker compose --project-name astrolearner-iss-live --env-file "$prepared_env" \
        -f compose.yaml -f compose.camera-browser-live.yaml "$@"
}
compose_new config --quiet

compose_current() {
    docker compose --project-name astrolearner-iss-live --env-file .env \
        -f compose.yaml -f compose.camera-browser-live.yaml "$@"
}

# Keep recovery even when Docker cannot resolve a container's historical image.
# Never commit the container: its configuration may contain runtime credentials.
preserve_image() {
    local service=$1 container=$2 reference=$3 record=$4 recovery_tag=$5
    local original selected
    original=$(docker inspect --format '{{.Image}}' "$container") || return 1
    [[ "$original" =~ ^sha256:[a-f0-9]{64}$ ]] || return 1
    printf '%s\n' "$original" > "$backup_dir/original-$record" || return 1
    if docker image inspect "$original" >/dev/null 2>&1; then
        selected=$original
        printf '%s\n' original > "$backup_dir/$record.origin" || return 1
    else
        printf 'La imagen historica de %s no esta disponible. Construyendo una recuperacion desde el codigo actual, sin recrear contenedores...\n' "$service"
        if ! compose_current build "$service"; then
            printf '%s\n' 'No se pudo construir la recuperacion. Configuracion sin cambiar; no se desplegara.' >&2
            return 1
        fi
        selected=$(docker image inspect --format '{{.Id}}' "$reference") || return 1
        [[ "$selected" =~ ^sha256:[a-f0-9]{64}$ ]] || return 1
        printf '%s\n' rebuilt-current-source > "$backup_dir/$record.origin" || return 1
    fi
    # Write the usable recovery record only after Docker confirms its tag.
    docker image tag "$selected" "$recovery_tag" || return 1
    printf '%s\n' "$selected" > "$backup_dir/$record"
}

# Preserve the old configuration and an original or explicitly rebuilt recovery
# image before deployment. The .origin records distinguish those two cases.
backup_dir=$(mktemp -d "$project_dir/.before-browser-production-$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")
chmod 700 "$backup_dir"
cp -p .env "$backup_dir/.env"
chmod 600 "$backup_dir/.env"
rollback_tag="astrolearner-iss-live:before-browser-$(date -u +%Y%m%dT%H%M%SZ)"
preserve_image iss-live astrolearner-iss-live astrolearner-iss-live:local image-id "$rollback_tag" || exit 1
old_browser_container=$(compose_new ps -aq camera-browser)
if [[ -n "$old_browser_container" ]]; then
    preserve_image camera-browser "$old_browser_container" astrolearner-iss-camera-browser:local \
        browser-image-id "astrolearner-iss-camera-browser:before-browser-$(date -u +%Y%m%dT%H%M%SZ)" || exit 1
fi
printf '%s\n' 'Copia privada de recuperacion:' "$backup_dir"
printf '%s\n' 'Construyendo solo ISS y su navegador; no se toca Homepage ni Caddy.'
compose_new build iss-live camera-browser

# Recheck after the build; someone may have pressed Start in the meantime.
stopped || { printf '%s\n' 'Se ha iniciado un directo durante la preparacion; no se recreara.' >&2; exit 1; }
mv -- "$prepared_env" .env
trap - EXIT
if ! docker compose up -d --force-recreate --wait --wait-timeout 240 camera-browser iss-live; then
    printf '%s\n' 'Despliegue incompleto. No iniciar. Para recuperar:' \
        "sudo ./scripts/rollback-browser-camera.sh '$backup_dir'" >&2
    exit 1
fi

if ./scripts/check-browser-camera.sh; then exit 0; fi
printf '%s\n' 'No se ha validado el despliegue. No iniciar. Para recuperar:' \
    "sudo ./scripts/rollback-browser-camera.sh '$backup_dir'" >&2
exit 1
