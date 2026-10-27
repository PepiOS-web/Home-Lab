#!/usr/bin/env bash
# Operator-only deployment: do not interrupt or start a public broadcast.
set -Eeuo pipefail
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
umask 077
[[ ${EUID} -eq 0 && $# -eq 0 ]] || { printf '%s\n' 'Ejecutar con sudo, sin argumentos.' >&2; exit 1; }
bundle=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project=/srv/data/compose/astrolearner-iss-live
cd "$project"
[[ $(pwd -P) == "$project" ]] || exit 1
unset COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PATH_SEPARATOR
stopped() {
    curl -fsS --max-time 8 http://127.0.0.1:8092/api/status |
        python3 -c 'import json,sys;d=json.load(sys.stdin);sys.exit(0 if d.get("live_requested") is False and d.get("ffmpeg_running") is False else 1)'
}
stopped || { printf '%s\n' 'Primero pulsa Detener en el portal. No se interrumpira automaticamente una emision activa.' >&2; exit 1; }
for service in homelab-backup.service homelab-maintenance.service; do
    case $(systemctl show "$service" -p ActiveState --value) in inactive|failed) ;; *) exit 1 ;; esac
done
for directory in /run/homelab-backup /run/homelab-maintenance; do
    [[ ! -L "$directory" ]] || exit 1
    install -d -o root -g root -m 700 "$directory"
done
exec 7>/run/homelab-backup/lock
exec 6>/run/homelab-maintenance/update.lock
flock -n 7 && flock -n 6 || { printf '%s\n' 'Hay otro backup o mantenimiento en curso.' >&2; exit 1; }
camera_lock="$project/.browser-camera-deploy.lock"
[[ -f "$camera_lock" && ! -L "$camera_lock" && $(stat -c %u "$camera_lock") == 0 ]] || exit 1
exec 8<"$camera_lock"
flock -n 8 || { printf '%s\n' 'Hay otro despliegue en curso.' >&2; exit 1; }
for other in compose.override.yaml compose.override.yml docker-compose.override.yaml docker-compose.override.yml; do
    [[ ! -e "$other" ]] || { printf '%s\n' 'Existe un override adicional no revisado.' >&2; exit 1; }
done
[[ $(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' astrolearner-iss-live) == astrolearner-iss-live ]] || exit 1
compose_current() {
    docker compose --project-name astrolearner-iss-live --env-file .env \
        -f compose.yaml -f compose.camera-browser-live.yaml "$@"
}
runtime_fingerprint() {
    timeout 15s docker exec --interactive=false astrolearner-iss-live python -c '
import dataclasses,hashlib,json,sys
from app.config import Settings
s=Settings();s.validate()
if s.auto_start or s.fps!=30 or s.block_seconds!=39000 or not s.camera_enabled:
    sys.exit("La configuracion no corresponde a la base manual de 30 FPS y 10h50 revisada.")
print(hashlib.sha256(json.dumps(dataclasses.asdict(s),default=str,sort_keys=True).encode()).hexdigest())' </dev/null
}
original_runtime=$(runtime_fingerprint)
compose_current config --quiet
python3 - "$bundle" <<'PY'
import ast,hashlib,pathlib,sys
bundle=pathlib.Path(sys.argv[1])
files={
 'app/controller.py':('84e3670abc25948fcfc69be9347fabe03fd55848b7b89a8f98e9ac90223c2f4b','eb7c8686e1f8fe14a6b847d38c95d5695b6d92cce617405e8269461548739fe9'),
 'app/youtube.py':('1a6abf96199a0f8a4354abfd66ac45e1bbc9c5747d04ee2579f4808f045e9ac4','3883aec4d2e1291b897dd5a2024c2bcf7dfab2c9ef99661c7b086de45d6723e8'),
 'app/state.py':('140cd8ad971a1f8af2b8f5840b3684297f9a358e3d5f3b481209676e251c44a8','d5fcd5da174141ce0f3eb78dbe3d681666325c3e0e8a9662517e661ec5b1f81b'),
 'app/recovery_preflight.py':(None,'bd0e33763add2e28b410d53280255f8c33f0ab9e0b9dae37ffe288c9e8f4b788'),
}
def digest(path):
    if not path.is_file() or path.is_symlink(): sys.exit('Archivo esperado no valido; no se instalara.')
    return hashlib.sha256(path.read_text(encoding='utf-8').encode()).hexdigest()
for name,(old,new) in files.items():
    item=bundle/pathlib.Path(name).name
    if digest(item)!=new: sys.exit('El paquete no coincide con la version revisada.')
    target=pathlib.Path(name)
    if target.exists() or target.is_symlink():
        if digest(target) not in {old,new}: sys.exit('Hay cambios locales distintos; no se sobrescribiran.')
    elif old is not None: sys.exit('Falta un archivo del despliegue anterior.')
    ast.parse(item.read_text(encoding='utf-8'))
print('Verificacion de fuentes y hashes: OK')
PY
recovery=$(mktemp -d "$project/.before-output-recovery-XXXXXXXX")
timer_paused=false
finish() {
    result=$?
    trap - EXIT
    if [[ "$timer_paused" == true ]]; then systemctl start homelab-backup.timer || result=1; fi
    printf 'Copia privada de recuperacion: %s\n' "$recovery"
    [[ "$result" -eq 0 ]] || printf '%s\n' 'Actualizacion no validada. No iniciar hasta revisar el resultado; la copia contiene las fuentes e imagen anteriores.' >&2
    exit "$result"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if systemctl is-active --quiet homelab-backup.timer; then
    timer_paused=true
    systemctl stop homelab-backup.timer
fi
case $(systemctl show homelab-backup.service -p ActiveState --value) in inactive|failed) ;; *) exit 1 ;; esac
cp -p .env "$recovery/.env"
chmod 600 "$recovery/.env"
printf '%s\n' "$original_runtime" > "$recovery/runtime.fingerprint"
original_image=$(docker inspect --format '{{.Image}}' astrolearner-iss-live)
[[ "$original_image" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 1
if ! docker image inspect "$original_image" >/dev/null 2>&1; then
    printf '%s\n' 'Construyendo recuperacion desde las fuentes anteriores, sin recrear contenedores.'
    compose_current build iss-live
    original_image=$(docker image inspect --format '{{.Id}}' astrolearner-iss-live:local)
fi
[[ "$original_image" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 1
rollback_tag="astrolearner-iss-live:before-output-recovery-$(date -u +%Y%m%dT%H%M%SZ)"
docker image tag "$original_image" "$rollback_tag"
printf '%s\n' "$rollback_tag" > "$recovery/image-tag"
for name in controller.py youtube.py state.py recovery_preflight.py; do
    if [[ -f "app/$name" ]]; then cp -p "app/$name" "$recovery/$name"; fi
    install -o martin -g martin -m 664 "$bundle/$name" "$project/app/$name"
done
compose_current build iss-live
printf '%s\n' 'Prueba RTMP local: corte, reconexion al mismo video simulado y limite de 24 s. Sin red externa, volumenes ni credenciales.'
timeout 80s docker run --rm --network none --read-only \
    --tmpfs /tmp:rw,size=64m,mode=1777 --memory 384m --cpus 1 --pids-limit 128 \
    --security-opt no-new-privileges:true --cap-drop ALL --entrypoint python \
    astrolearner-iss-live:local -m app.recovery_preflight
stopped || { printf '%s\n' 'Se ha iniciado una emision durante las pruebas; no se recreara.' >&2; exit 1; }
cmp -s .env "$recovery/.env" || { printf '%s\n' 'La configuracion cambio durante la preparacion; no se recreara.' >&2; exit 1; }
compose_current up -d --no-deps --force-recreate --wait --wait-timeout 180 iss-live
[[ $(runtime_fingerprint) == "$original_runtime" ]] || { printf '%s\n' 'La configuracion efectiva difiere de la anterior.' >&2; exit 1; }
stopped || exit 1
printf '%s\n' 'LISTO: recuperacion del mismo directo y rotacion a las 10h50 instaladas. FPS, camara, mapa, musica y sesiones sin cambiar. Inicia manualmente desde el portal.'
