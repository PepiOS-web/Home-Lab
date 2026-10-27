#!/usr/bin/env bash
# Operator-run only. Never interrupt or start a public emission automatically.
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
stopped || { printf '%s\n' 'El directo sigue activo. Pulsa Detener en el portal cuando quieras actualizar; no lo cortare automaticamente.' >&2; exit 1; }
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
flock -n 8 || { printf '%s\n' 'Hay otro despliegue de camara en curso.' >&2; exit 1; }
for other in compose.override.yaml compose.override.yml docker-compose.override.yaml docker-compose.override.yml; do
    [[ ! -e "$other" ]] || { printf '%s\n' 'Hay un override no revisado; no se modificara.' >&2; exit 1; }
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
if s.auto_start or not s.control_token or s.fps!=30 or not s.camera_enabled:
    sys.exit("La configuracion no corresponde a la base manual de 30 FPS revisada.")
print(hashlib.sha256(json.dumps(dataclasses.asdict(s),default=str,sort_keys=True).encode()).hexdigest())' </dev/null
}
original_runtime=$(runtime_fingerprint)
compose_current config --quiet
python3 - "$bundle" <<'PY'
import ast,hashlib,pathlib,sys
bundle=pathlib.Path(sys.argv[1])
files={
 'app/main.py':('b9d7311fedd4506256e0a2186c46c2c2029c42391aafda34a67852c485e0f937','c8ab62d6274d744ddb6e44de007fa6d30afd3fdff00bc4ab15b4694802e97591'),
 'app/control_auth.py':('de5baedd16f607ece8722fe52125b9f577abdd80871285e2a198ef449ee58d5b','d124305795ce89c4463568039d1e2c0e516fbe51fafe1e523f27f85ce4e2c360'),
 'app/control_page.py':('3d138af6508ec55a5df460b5914d6bc94521e4319e11a68fc6324ed8ef9732dd','0931dcb0e9a66e4c8fd7fa2769aebc84147750ef93dfc61d7886be1e7a8108c5'),
 'app/control_sessions.py':(None,'bd7c776653ca31f9d873f209f9e66642ebb7f304ef2d8b6ef735b5a18b5cad74'),
}
def digest(path):
    if not path.is_file() or path.is_symlink(): sys.exit('Archivo no valido; no se instalara.')
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
recovery=$(mktemp -d "$project/.before-control-sessions-XXXXXXXX")
timer_paused=false
finish() {
    result=$?
    trap - EXIT
    if [[ "$timer_paused" == true ]]; then systemctl start homelab-backup.timer || result=1; fi
    printf 'Copia privada de recuperacion: %s\n' "$recovery"
    [[ "$result" -eq 0 ]] || printf '%s\n' 'Actualizacion no validada. No iniciar el directo hasta revisar el resultado.' >&2
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
    printf '%s\n' 'Reconstruyendo imagen de recuperacion desde las fuentes anteriores, sin recrear contenedores.'
    compose_current build iss-live
    original_image=$(docker image inspect --format '{{.Id}}' astrolearner-iss-live:local)
fi
[[ "$original_image" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 1
rollback_tag="astrolearner-iss-live:before-control-sessions-$(date -u +%Y%m%dT%H%M%SZ)"
docker image tag "$original_image" "$rollback_tag"
printf '%s\n' "$rollback_tag" > "$recovery/image-tag"
for name in main.py control_auth.py control_page.py control_sessions.py; do
    if [[ -f "app/$name" ]]; then cp -p "app/$name" "$recovery/$name"; fi
    install -o martin -g martin -m 664 "$bundle/$name" "$project/app/$name"
done
printf '%s\n' 'Construyendo solo ISS; no se cambia camara, mapa, musica, OAuth ni configuracion.'
compose_current build iss-live
stopped || { printf '%s\n' 'Alguien ha iniciado un directo: no se recreara el servicio.' >&2; exit 1; }
cmp -s .env "$recovery/.env" || { printf '%s\n' 'La configuracion ha cambiado durante la preparacion; no se recreara.' >&2; exit 1; }
compose_current up -d --no-deps --force-recreate --wait --wait-timeout 180 iss-live
[[ $(runtime_fingerprint) == "$original_runtime" ]] || { printf '%s\n' 'La configuracion efectiva no coincide con la anterior.' >&2; exit 1; }
stopped || exit 1
curl -fsS --max-time 8 http://127.0.0.1:8092/session |
    python3 -c 'import json,sys;sys.exit(0 if json.load(sys.stdin)=={"authenticated":False} else 1)'
printf '%s\n' 'LISTO: sesiones privadas preparadas. Recarga el portal con Ctrl+F5 y autoriza el navegador una vez. No se ha iniciado ninguna emision.'
