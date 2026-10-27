#!/usr/bin/env bash
# Explicit operator deployment. No package updates, backup run or publication.
set -Eeuo pipefail
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
umask 077
[[ ${EUID} -eq 0 && $# -eq 0 ]] || { printf '%s\n' 'Ejecutar este instalador con sudo, sin argumentos.' >&2; exit 1; }
bundle=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project=/srv/data/compose/astrolearner-iss-live
cd "$project"
unset COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PATH_SEPARATOR

stopped() {
    curl -fsS --max-time 5 http://127.0.0.1:8092/api/status |
        python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("live_requested") is False and d.get("ffmpeg_running") is False and d.get("status") != "en directo" else 1)'
}
normalised_hash() {
    python3 -c 'import hashlib,pathlib,sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_text().encode()).hexdigest())' "$1"
}
config_check='import sys
from app.config import Settings
try:
    s=Settings()
    s.validate()
    safe=(s.auto_start is False and s.camera_enabled and s.camera_authorized
          and s.camera_mode=="auto" and s.map_seconds==0
          and s.camera_url=="http://camera-browser:8093/camera.mjpeg"
          and s.fps==12 and s.width==1280 and s.height==720
          and s.encoder=="libx264")
except Exception:
    safe=False
sys.exit(0 if safe else "Configuracion distinta de la revisada o inicio automatico activo; no se recreara.")'
stopped || { printf '%s\n' 'Primero pulsa Detener en el portal; no se cortara un directo automaticamente.' >&2; exit 1; }
timeout 15s docker exec --interactive=false astrolearner-iss-live python -c "$config_check" </dev/null
[[ $(systemctl show homelab-backup.service -p ActiveState --value) == inactive ]] || exit 1
case $(systemctl show homelab-maintenance.service -p ActiveState --value) in active|activating|deactivating) exit 1 ;; esac
for name in homelab-backup homelab-backup-iss.py controller.py main.py preflight.py stream_pacing_probe.py; do
    [[ -f "$bundle/$name" && ! -L "$bundle/$name" ]] || exit 1
done
bash -n "$bundle/homelab-backup"
python3 -m py_compile "$bundle/homelab-backup-iss.py" "$bundle/controller.py" "$bundle/main.py" "$bundle/preflight.py" "$bundle/stream_pacing_probe.py"
legacy_backup_hash=879204625b45b081e637c865cba6d2e0a24d04dc18358a0ac1936b271e48748c
actual_backup_hash=$(normalised_hash /usr/local/sbin/homelab-backup)
new_backup_hash=$(normalised_hash "$bundle/homelab-backup")
[[ "$actual_backup_hash" == "$legacy_backup_hash" || "$actual_backup_hash" == "$new_backup_hash" ]] || {
    printf '%s\n' 'El backup instalado contiene cambios distintos. No se sobrescribira: compartir solo este hash para revisarlo.' "$actual_backup_hash" >&2
    exit 1
}

[[ ! -L /run/homelab-stream-fix && ! -L /run/homelab-backup && ! -L /run/homelab-maintenance ]] || exit 1
install -d -o root -g root -m 700 /run/homelab-stream-fix /run/homelab-backup /run/homelab-maintenance
exec 9>/run/homelab-stream-fix/lock
exec 7>/run/homelab-backup/lock
exec 6>/run/homelab-maintenance/update.lock
flock -n 9 && flock -n 7 && flock -n 6 || { printf '%s\n' 'Hay otro backup, mantenimiento o instalacion en curso.' >&2; exit 1; }
# Read-only open of the existing camera lock: never truncate a user-owned path.
camera_lock="$project/.browser-camera-deploy.lock"
[[ -f "$camera_lock" && ! -L "$camera_lock" && $(stat -c %u "$camera_lock") == 0 ]] || exit 1
exec 8<"$camera_lock"
flock -n 8 || { printf '%s\n' 'Hay una prueba de camara en curso.' >&2; exit 1; }
[[ ! -L /var/lib/homelab-stream-fix ]] || exit 1
install -d -o root -g root -m 700 /var/lib/homelab-stream-fix
recovery=$(mktemp -d /var/lib/homelab-stream-fix/before-XXXXXXXX)
timer_paused=false
plan_work=''
finish() {
    result=$?
    trap - EXIT
    if [[ -n "$plan_work" ]]; then
        resolved=$(realpath -e -- "$plan_work")
        if [[ "$resolved" == "$plan_work" && "$resolved" =~ ^/srv/data/backups/daily/\.work-[A-Za-z0-9]+$ &&
              ! -L "$plan_work" && $(stat -c %u "$plan_work") == 0 ]]; then
            rm -rf --one-file-system -- "$plan_work"
        else result=1; fi
    fi
    if [[ "$timer_paused" == true ]]; then
        systemctl start homelab-backup.timer || result=1
    fi
    if [[ "$result" -ne 0 ]]; then
        printf '%s\n' 'Instalacion no validada. No iniciar el directo ni repetir comandos de mantenimiento a ciegas.' >&2
    fi
    printf 'Recuperacion privada de scripts/configuracion de imagen: %s\n' "$recovery"
    exit "$result"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if systemctl is-active --quiet homelab-backup.timer; then
    timer_paused=true
    systemctl stop homelab-backup.timer
fi
[[ $(systemctl show homelab-backup.service -p ActiveState --value) == inactive ]] || exit 1
[[ -d /srv/data/backups/daily && ! -L /srv/data/backups/daily &&
   $(stat -c %u /srv/data/backups/daily) == 0 && $(stat -c %a /srv/data/backups/daily) == 700 ]] || exit 1
plan_work=$(mktemp -d /srv/data/backups/daily/.work-XXXXXXXXXX)
python3 "$bundle/homelab-backup-iss.py" plan "$plan_work"
python3 - "$plan_work/plan.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))
if len(p['iss']) != 2 or len(p['dns']) != 1:
    sys.exit('No se han confirmado el emisor, navegador y DNS esperados. No se instalara.')
print(json.dumps({'protected_live_containers':len(p['iss']),'short_dns_snapshot':len(p['dns']),'other_containers':len(p['bulk'])}))
PY

cp -p /usr/local/sbin/homelab-backup "$recovery/homelab-backup"
if [[ -f /usr/local/libexec/homelab-backup-iss.py ]]; then
    cp -p /usr/local/libexec/homelab-backup-iss.py "$recovery/homelab-backup-iss.py"
fi
for name in controller.py main.py preflight.py stream_pacing_probe.py; do
    [[ ! -f "$project/app/$name" ]] || cp -p "$project/app/$name" "$recovery/$name"
done
docker inspect --format '{{.Image}}' astrolearner-iss-live >"$recovery/image-id"
old_image=$(<"$recovery/image-id")
[[ "$old_image" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 1
docker image tag "$old_image" "astrolearner-iss-live:before-stability-$(date -u +%Y%m%dT%H%M%SZ)"
for name in controller.py main.py preflight.py stream_pacing_probe.py; do
    install -o martin -g martin -m 664 "$bundle/$name" "$project/app/$name"
done
docker compose config --quiet
printf '%s\n' 'Construyendo solo el emisor; no se actualizan paquetes del host ni se cambian FPS...'
docker compose build iss-live
# Check the NEW image with the effective Compose environment, not just the old
# running container. Only import Settings; never execute the application/start.
timeout --kill-after=3s 30s docker compose run --rm --no-deps -T --entrypoint python \
    iss-live -c "$config_check" </dev/null
stopped || { printf '%s\n' 'Se ha solicitado un directo durante la construccion; no se recreara.' >&2; exit 1; }
install -d -o root -g root -m 755 /usr/local/libexec
install -o root -g root -m 750 "$bundle/homelab-backup-iss.py" /usr/local/libexec/homelab-backup-iss.py
install -o root -g root -m 750 "$bundle/homelab-backup" /usr/local/sbin/homelab-backup
docker compose up -d --no-deps --force-recreate --wait --wait-timeout 180 iss-live
./scripts/check-browser-camera.sh
printf '%s\n' 'Prueba local de 30 segundos con camara y musica reales, sin publicar...'
timeout --kill-after=3s 75s docker compose exec --interactive=false -T iss-live \
    python -m app.stream_pacing_probe </dev/null
printf '%s\n' 'LISTO: montaje validado y backup instalado. El backup completo sin corte sigue pendiente de comprobar en su proxima ejecucion.'
printf '%s\n' 'No se ha iniciado ninguna emision. Puede iniciarse manualmente desde el portal.'
