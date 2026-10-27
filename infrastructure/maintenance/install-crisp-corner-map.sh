#!/usr/bin/env bash
# Operator-run map change only: preserves 720p/30 FPS, music and manual start.
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
stopped || { printf '%s\n' 'Primero pulsa Detener en el portal. No se cortara el directo automaticamente.' >&2; exit 1; }
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

# Require the already working 30 FPS baseline; never reset FPS silently.
timeout 15s docker exec --interactive=false astrolearner-iss-live python -c '
from app.config import Settings
import sys
s=Settings();s.validate()
sys.exit(0 if s.fps==30 and (s.width,s.height)==(1280,720) and s.auto_start is False and s.camera_enabled and s.encoder=="libx264" and s.map_seconds==0 else "La configuracion base no es la de 30 FPS revisada.")' </dev/null

python3 - "$bundle" <<'PY'
import ast,hashlib,pathlib,sys
bundle=pathlib.Path(sys.argv[1])
files={
 'app/main.py':('f9f7ab327e85efeab7b8309a4bfa6b6e0bb2cf49f3143e82a55d2a6fdddd9b63','b9d7311fedd4506256e0a2186c46c2c2029c42391aafda34a67852c485e0f937'),
 'app/corner_map.py':(None,'1607ea904a685877e43c5c1336d86fa352237108cd00c735e9999ab2531b4581'),
 'app/browser_camera.py':('643099787e166d7af00c8da2c034ab83a78ec158cdd28b71e8ff43595b360e82','8050d7f0d444efd598f66ddfd6f2204629ab124a12595893067cab4b7235c258'),
 'app/browser_local_map.py':(None,'bb4d4d93e729d9dd895a59f40173db620450b36ef31a451886c2c21194d8d6d2'),
 'app/browser_camera_deployment.py':('d92c85d656cdc9e2ba22ea1aed990804119ff713e4396b9b61e389612aa83af0','54d65799b56fb650b0a6ad89b9587706afd339a6b98a17c0c2ab61fc85f6b73f'),
 'scripts/enable-browser-camera.sh':('b1ba041d4875e13bdfad7dd4204f1ed711f60175f8004512fb339bb60615019f','ead787e1c7138e05019e3fb722bdf2cf84d6693d23c23c5127237a97141414a7'),
 'scripts/check-browser-camera.sh':('e512d544ec82244ef88a1622a8dd52bd5d60d3064bba15612590fb61eef0fe7f','cde898dba011a3e8d33dbbe98380726394dc8bb0267cd87e3e27ea5dd8966103'),
 'Dockerfile.camera-browser':('be4f87bc02e6fd682c4c41a4af0bed5d7ca5534f4154907fcb677b61cfa91b45','cacc29a7034fe452b354b87d6a47a1129f9d414b9e1d12250f86418d6b8e959c'),
 'compose.camera-browser-live.yaml':('80d0c8b3305e9e3d1f2a8c58e8949c2cea205d5ab459453f00560ac49dcec83a','ff38b748b9cb839ba2b2d17876c2ebf528c19ca397e7caa31a45aea7dee7ad8b'),
}
def digest(path):
    if not path.is_file() or path.is_symlink(): sys.exit('Archivo esperado no valido; no se instalara.')
    return hashlib.sha256(path.read_text().encode()).hexdigest()
for name,(old,new) in files.items():
    item=bundle/pathlib.Path(name).name
    if digest(item)!=new: sys.exit('El bundle no coincide con la version revisada.')
    target=pathlib.Path(name)
    if target.exists() or target.is_symlink():
        if digest(target) not in {old,new}: sys.exit('Hay cambios locales distintos; no se sobrescribiran.')
    elif old is not None: sys.exit('Falta un archivo del despliegue anterior.')
    if name.endswith('.py'): ast.parse(item.read_text())
print('Verificacion de fuentes y hashes: OK')
PY
bash -n "$bundle/enable-browser-camera.sh"
bash -n "$bundle/check-browser-camera.sh"
recovery=$(mktemp -d "$project/.before-crisp-corner-map-XXXXXXXX")
timer_paused=false
finish() {
    result=$?
    trap - EXIT
    if [[ "$timer_paused" == true ]]; then systemctl start homelab-backup.timer || result=1; fi
    printf 'Fuentes anteriores guardadas en: %s\n' "$recovery"
    [[ "$result" -eq 0 ]] || printf '%s\n' 'Mapa no validado: no iniciar hasta revisar el resultado.' >&2
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
for name in app/main.py app/corner_map.py app/browser_camera.py app/browser_local_map.py app/browser_camera_deployment.py scripts/enable-browser-camera.sh scripts/check-browser-camera.sh Dockerfile.camera-browser compose.camera-browser-live.yaml; do
    if [[ -f "$name" ]]; then
        mkdir -p "$recovery/$(dirname "$name")"
        cp -p "$name" "$recovery/$name"
    fi
    mode=664
    [[ "$name" != scripts/* ]] || mode=755
    install -o martin -g martin -m "$mode" "$bundle/$(basename "$name")" "$project/$name"
done
docker compose config --quiet
flock -u 8
exec 8<&-
./scripts/enable-browser-camera.sh 30 astrolearner
printf '%s\n' 'LISTO: mapa AstroLearner preparado, video a 720p/30 FPS. No se ha iniciado ninguna emision.'
