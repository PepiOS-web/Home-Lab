#!/usr/bin/env bash
# Operator-run patch installation and requested 30 FPS deployment; no publication.
set -Eeuo pipefail
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
umask 077
[[ ${EUID} -eq 0 && $# -eq 0 ]] || { printf '%s\n' 'Ejecutar con sudo, sin argumentos.' >&2; exit 1; }
bundle=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project=/srv/data/compose/astrolearner-iss-live
cd "$project"
[[ $(pwd -P) == "$project" ]] || exit 1
source_file="$bundle/scripts/enable-browser-camera.sh"
target="$project/scripts/enable-browser-camera.sh"
old_hash=f92ff395747e8b021bc30923b7f21782f15e55fc51e9cfc25f5d15b58d12d64b
new_hash=b1ba041d4875e13bdfad7dd4204f1ed711f60175f8004512fb339bb60615019f
for file in "$source_file" "$target"; do [[ -f "$file" && ! -L "$file" ]] || exit 1; done
[[ $(sha256sum "$source_file" | cut -d ' ' -f 1) == "$new_hash" ]] || exit 1
bash -n "$source_file"
camera_lock="$project/.browser-camera-deploy.lock"
[[ -f "$camera_lock" && ! -L "$camera_lock" && $(stat -c %u "$camera_lock") == 0 ]] || exit 1
exec 8<"$camera_lock"
flock -n 8 || { printf '%s\n' 'Hay otro despliegue en curso.' >&2; exit 1; }
curl -fsS --max-time 8 http://127.0.0.1:8092/api/status |
    python3 -c 'import json,sys;d=json.load(sys.stdin);sys.exit(0 if d.get("live_requested") is False and d.get("ffmpeg_running") is False else 1)'
actual=$(sha256sum "$target" | cut -d ' ' -f 1)
[[ "$actual" == "$old_hash" || "$actual" == "$new_hash" ]] || {
    printf '%s\n' 'El script tiene otros cambios; no se sobrescribira.' >&2; exit 1;
}
if [[ "$actual" != "$new_hash" ]]; then
    backup=$(mktemp -d "$project/.before-enable-image-recovery-XXXXXXXX")
    cp -p "$target" "$backup/enable-browser-camera.sh"
    prepared=$(mktemp "$project/scripts/.enable-image-recovery-XXXXXXXX")
    install -o martin -g martin -m 755 "$source_file" "$prepared"
    bash -n "$prepared"
    [[ $(sha256sum "$prepared" | cut -d ' ' -f 1) == "$new_hash" ]] || exit 1
    mv -- "$prepared" "$target"
    printf 'Script anterior conservado en: %s\n' "$backup"
fi
flock -u 8
exec 8<&-
exec "$target" 30
