#!/usr/bin/env bash
# Explicit operator-run preparation + local trial. Never starts a broadcast.
set -Eeuo pipefail
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
umask 077
[[ ${EUID} -eq 0 && $# -eq 0 ]] || { printf '%s\n' 'Ejecutar con sudo, sin argumentos.' >&2; exit 1; }
bundle=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project=/srv/data/compose/astrolearner-iss-live
cd "$project"
unset COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PATH_SEPARATOR
stopped() {
    curl -fsS --max-time 5 http://127.0.0.1:8092/api/status |
        python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("live_requested") is False and d.get("ffmpeg_running") is False else 1)'
}
stopped || { printf '%s\n' 'Detener primero el directo desde el portal.' >&2; exit 1; }
case $(systemctl show homelab-backup.service -p ActiveState --value) in inactive|failed) ;; *) exit 1 ;; esac
case $(systemctl show homelab-maintenance.service -p ActiveState --value) in inactive|failed) ;; *) exit 1 ;; esac
for directory in /run/homelab-fps-trial /run/homelab-backup /run/homelab-maintenance; do
    [[ ! -L "$directory" ]] || exit 1
    install -d -o root -g root -m 700 "$directory"
done
exec 9>/run/homelab-fps-trial/lock
exec 7>/run/homelab-backup/lock
exec 6>/run/homelab-maintenance/update.lock
flock -n 9 && flock -n 7 && flock -n 6 || { printf '%s\n' 'Otro backup, mantenimiento o ensayo esta en curso.' >&2; exit 1; }
camera_lock="$project/.browser-camera-deploy.lock"
[[ -f "$camera_lock" && ! -L "$camera_lock" && $(stat -c %u "$camera_lock") == 0 ]] || exit 1
exec 8<"$camera_lock"
flock -n 8 || { printf '%s\n' 'Otra prueba de camara esta en curso.' >&2; exit 1; }

# Refuse to test an old/unfixed source tree or to overwrite independent edits.
python3 - "$bundle" <<'PY'
import hashlib,pathlib,sys
bundle=pathlib.Path(sys.argv[1])
expected={
    'app/controller.py':'84e3670abc25948fcfc69be9347fabe03fd55848b7b89a8f98e9ac90223c2f4b',
    'app/main.py':'f9f7ab327e85efeab7b8309a4bfa6b6e0bb2cf49f3143e82a55d2a6fdddd9b63',
}
previous={
    'app/browser_camera.py':'1ba98fa8dd84acbc574eef78c100d988130f45a5c91348d28a13701a9de34b6f',
    'app/browser_camera_deployment.py':'44806eb326af6bd27ac2aa7a8f55911d5db8ff914dcf86e91aac2d65dbeb90a1',
    'app/browser_camera_preflight.py':'bb3c4a79102d53141ae43d44607a2f74b85c2d037df3526036b8c1aa9915ff29',
    'scripts/test-browser-camera.sh':'3d13a07014851811da2b84265448fcc9e8823854432fdad77afa7cd093f71c08',
    'scripts/enable-browser-camera.sh':'22f94beaf0f90bc59e08cdd8bcaa435f49c0ff6331588c4eccc69b7f3d4e064c',
    'compose.camera-browser-staging.yaml':'772eb316979c85a548ebf10434369e4f29c2600817be7f34613c493b3b627ff2',
}
reviewed={
    'app/browser_camera.py':'643099787e166d7af00c8da2c034ab83a78ec158cdd28b71e8ff43595b360e82',
    'app/browser_camera_deployment.py':'d92c85d656cdc9e2ba22ea1aed990804119ff713e4396b9b61e389612aa83af0',
    'app/browser_camera_preflight.py':'4a9cf594d06b473b42ce7a5a60f45dec74bed2ba50f0137a99dd55f7e460f561',
    'scripts/test-browser-camera.sh':'fbc4f17b0e470ee3cd34b385b9732bf63bff1f26a39d96a08df58921f2f0574f',
    'scripts/enable-browser-camera.sh':'b1ba041d4875e13bdfad7dd4204f1ed711f60175f8004512fb339bb60615019f',
    'compose.camera-browser-staging.yaml':'eacf5b7c66ddc9f32795df0a5f808209cd6ee2513a0f1a887dea60be950d54f7',
}
def digest(path):
    if not path.is_file() or path.is_symlink():
        sys.exit('Falta un archivo normal esperado; no se modificara.')
    return hashlib.sha256(path.read_text().encode()).hexdigest()
for name, known in expected.items():
    if digest(pathlib.Path(name)) != known:
        sys.exit('El montaje no coincide con la correccion de estabilidad revisada; no se probara.')
for name, known in previous.items():
    if digest(bundle/pathlib.Path(name).name) != reviewed[name]:
        sys.exit('El contenido del bundle no coincide con la revision; no se ejecutara.')
    if digest(pathlib.Path(name)) not in {known,reviewed[name]}:
        sys.exit('Hay cambios de codigo distintos de los revisados; no se sobrescribiran.')
PY
bash -n "$bundle/enable-browser-camera.sh"
sh -n "$bundle/test-browser-camera.sh"
python3 - "$bundle" <<'PY'
import ast,pathlib,sys
for name in ('browser_camera.py','browser_camera_deployment.py','browser_camera_preflight.py'):
    ast.parse((pathlib.Path(sys.argv[1])/name).read_text())
PY

# Check the RUNNING image too; never instantiate a Controller or call YouTube.
timeout 15s docker exec --interactive=false astrolearner-iss-live python -c '
from pathlib import Path
from types import SimpleNamespace
from app.config import Settings
from app.controller import Controller
import sys
s=Settings(); s.validate()
ctx=SimpleNamespace(settings=s,music_path=Path("/tmp/not-read.wav"),video_label_path=s.status_dir/"video-source.txt")
cmd=Controller._ffmpeg_command(ctx,"/tmp/not-created.flv")
safe=(s.auto_start is False and s.fps==12 and s.map_seconds==0 and s.camera_enabled
      and s.encoder=="libx264" and "http://127.0.0.1:8092/map.mjpeg" not in cmd
      and "[1:a]" in cmd[cmd.index("-filter_complex")+1])
sys.exit(0 if safe else "Primero validar el arreglo a 12 FPS; no se ejecutara el ensayo.")' </dev/null

[[ ! -L /var/lib/homelab-fps-trial ]] || exit 1
install -d -o root -g root -m 700 /var/lib/homelab-fps-trial
recovery=$(mktemp -d /var/lib/homelab-fps-trial/before-XXXXXXXX)
env_hash=$(sha256sum .env | cut -d ' ' -f 1)
timer_paused=false
finish() {
    result=$?
    trap - EXIT
    [[ $(sha256sum .env | cut -d ' ' -f 1) == "$env_hash" ]] || {
        printf '%s\n' 'La configuracion cambio durante la prueba; revisar antes de emitir.' >&2; result=1;
    }
    if [[ "$timer_paused" == true ]]; then systemctl start homelab-backup.timer || result=1; fi
    printf 'Recuperacion privada de fuentes: %s\n' "$recovery"
    printf '%s\n' 'No se han activado 30 FPS en produccion ni se ha iniciado una emision.'
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
for name in app/browser_camera.py app/browser_camera_deployment.py app/browser_camera_preflight.py scripts/test-browser-camera.sh scripts/enable-browser-camera.sh compose.camera-browser-staging.yaml; do
    mkdir -p "$recovery/$(dirname "$name")"
    cp -p "$name" "$recovery/$name"
    mode=664
    [[ "$name" != scripts/* ]] || mode=755
    install -o martin -g martin -m "$mode" "$bundle/$(basename "$name")" "$project/$name"
done
# The test script takes this same lock itself. Release it without leaving a
# parent-held descriptor that would make the child fail its lock acquisition.
flock -u 8
exec 8<&-
printf '%s\n' 'Ensayo aislado a 30 FPS. No pulses Iniciar en el portal durante la prueba.'
./scripts/test-browser-camera.sh 30
printf '%s\n' 'PRUEBA LOCAL APROBADA. Revisar el resultado antes de activar 30 FPS para un directo.'
