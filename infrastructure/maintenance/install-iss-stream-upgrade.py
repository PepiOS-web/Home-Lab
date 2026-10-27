#!/usr/bin/env python3
"""Operator-run, pinned upgrade. Never starts/stops a public broadcast."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path('/srv/data/compose/astrolearner-iss-live')
MUSIC = Path('/srv/data/appdata/astrolearner-iss-live/music')
CONTAINER = 'astrolearner-iss-live'
CAMERA = 'astrolearner-iss-live-camera-browser-1'
EXPECTED_FILES = {
    'app/controller.py', 'app/main.py', 'app/control_page.py', 'app/video_switcher.py',
    'app/browser_camera.py', 'app/presentation.py', 'app/stream_dashboard.py',
    'app/dashboard_sources.py', 'app/melodic_playlist.py', 'app/stream_upgrade_preflight.py',
}


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def run(command, *, timeout=180):
    environment = {k: v for k, v in os.environ.items() if not k.startswith('COMPOSE_')}
    # Compose interpolation: no inherited or on-disk auto-start can publish.
    environment['ISS_LIVE_AUTO_START'] = 'false'
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout,
                            env=environment)
    if result.returncode:
        raise RuntimeError('Una comprobación o comando Docker falló; no se muestran registros privados')
    return result.stdout.strip()


def compose(*args, timeout=180):
    return run(['docker', 'compose', '--project-name', 'astrolearner-iss-live',
                '--env-file', '.env', *args], timeout=timeout)


def status():
    with urllib.request.urlopen('http://127.0.0.1:8092/api/status', timeout=5) as response:
        return json.load(response)


def stopped():
    try:
        value = status()
    except (OSError, ValueError):
        # Recovery must also work when the API/container did not start.
        identifiers = run(['docker', 'ps', '-aq', '--filter', 'name=^/astrolearner-iss-live$'])
        if not identifiers:
            return
        state = json.loads(run(['docker', 'inspect', '--format={{json .State}}', CONTAINER]))
        if state.get('Running') is False and state.get('Restarting') is False:
            return
        raise RuntimeError('No se puede confirmar una parada segura; no se modificará el servicio') from None
    if value.get('live_requested') is not False or value.get('ffmpeg_running') is not False:
        raise RuntimeError('El directo está activo: pulsa Detener en el portal antes de instalar. No se ha cortado automáticamente.')


def safe_target(name):
    if not name.startswith('app/') or not name.endswith('.py') or '..' in Path(name).parts:
        raise RuntimeError('Ruta del paquete no permitida')
    target = ROOT / name
    if target.is_symlink() or target.resolve().parent != (ROOT / 'app').resolve():
        raise RuntimeError('Destino fuera del directorio esperado')
    return target


def replace_file(source, target, owner, mode=0o644):
    descriptor, temporary = tempfile.mkstemp(prefix='.stream-upgrade-', dir=target.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output, source.open('rb') as original:
            shutil.copyfileobj(original, output)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode)
        os.chown(temporary, *owner)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def diagnose():
    keys = ('state', 'ready', 'captured_frames', 'last_frame_age_seconds',
            'capture_fps', 'player_error', 'error_stage', 'error_code')
    code = ("import json,urllib.request; d=json.load(urllib.request.urlopen("
            "'http://127.0.0.1:8093/health',timeout=5)); "
            f"print(json.dumps({{k:d.get(k) for k in {keys!r}}}))")
    print(run(['docker', 'exec', CAMERA, 'python', '-c', code], timeout=10))


def install(bundle):
    stopped()  # Before even changing source files or building images.
    manifest = json.loads((bundle / 'manifest.json').read_text())
    files = manifest['files']
    if set(files) != EXPECTED_FILES:
        raise RuntimeError('El paquete no contiene exactamente los módulos revisados')
    runtime = json.loads(run(['docker', 'exec', CONTAINER, 'python', '-c',
        "import json;from app.config import Settings;s=Settings();"
        "print(json.dumps({'auto_start':s.auto_start,'camera':s.camera_enabled,'fps':s.fps,'width':s.width,'height':s.height}))"]))
    if runtime['auto_start'] or not runtime['camera'] or runtime['fps'] != 30 or runtime['width'] != 1280 or runtime['height'] != 720:
        raise RuntimeError('Se requiere autoarranque desactivado y perfil de cámara 1280×720 a 30 FPS; no se cambiará automáticamente.')
    if not {'iss-live', 'camera-browser'} <= set(compose('config', '--services').splitlines()):
        raise RuntimeError('Falta el servicio de cámara en Compose')
    for name, pins in files.items():
        target, source = safe_target(name), bundle / name
        if digest(source) != pins['after']:
            raise RuntimeError('El paquete no coincide con sus hashes revisados')
        if target.exists():
            if pins['before'] is None or digest(target) != pins['before']:
                raise RuntimeError('Los archivos del servidor han cambiado; se conserva todo y se requiere revisar la diferencia')
        elif pins['before'] is not None:
            raise RuntimeError('Falta un predecesor esperado')
    audio = bundle / 'music' / 'astrolearner-melodic-hour-v1.wav'
    if digest(audio) != manifest['music_sha256']:
        raise RuntimeError('La sesión musical no supera su comprobación de integridad')
    if digest(audio.with_suffix('.json')) != manifest['music_manifest_sha256']:
        raise RuntimeError('El manifiesto musical no coincide')
    destination = MUSIC / audio.name
    if destination.exists() or destination.with_suffix('.json').exists():
        raise RuntimeError('Ya existe esa versión musical; no se sobrescribirá')
    env = ROOT / '.env'
    if env.is_symlink() or not MUSIC.is_dir() or MUSIC.is_symlink():
        raise RuntimeError('Las rutas de configuración o música no son las esperadas')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    recovery = ROOT / ('.before-stream-upgrade-' + stamp)
    recovery.mkdir(mode=0o700)
    owner = (MUSIC.stat().st_uid, MUSIC.stat().st_gid)
    for name in files:
        target = ROOT / name
        if target.exists():
            backup = recovery / name
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
    shutil.copy2(env, recovery / 'private.env')
    preferences = MUSIC / 'presentation.json'
    if preferences.exists():
        shutil.copy2(preferences, recovery / 'presentation.json')
    tags = {}
    for service, container in (('iss-live', CONTAINER), ('camera-browser', CAMERA)):
        image = run(['docker', 'inspect', '--format={{.Image}}', container])
        tag = f'astrolearner-{service}:before-stream-upgrade-{stamp.lower()}'
        run(['docker', 'image', 'tag', image, tag])
        tags[service] = tag
    (recovery / 'rollback-images.json').write_text(json.dumps(tags))
    lines = [line for line in env.read_text().splitlines() if not line.startswith('ISS_BROWSER_MAP_OVERLAY=')]
    lines.append('ISS_BROWSER_MAP_OVERLAY=none')
    (recovery / 'planned.env').write_text('\n'.join(lines) + '\n')
    (recovery / 'planned-presentation.json').write_text(json.dumps({'dashboard_enabled': True,
        'recorded_fallback_enabled': False, 'music_style': 'melodic'}) + '\n')
    journal = {'env_sha256': [digest(env), digest(recovery / 'planned.env')],
               'env_owner': [env.stat().st_uid, env.stat().st_gid],
               'preferences_sha256': [digest(preferences) if preferences.exists() else None,
                                       digest(recovery / 'planned-presentation.json')],
               'files': files}
    (recovery / 'installed.json').write_text(json.dumps(journal))
    print('Copia privada de reversión:', recovery, flush=True)
    try:
        for name in files:
            replace_file(bundle / name, ROOT / name, owner)
        for source in (audio, audio.with_suffix('.json')):
            replace_file(source, MUSIC / source.name, owner)
        compose('config', '--quiet')
        compose('build', 'iss-live', 'camera-browser', timeout=600)
        # No OAuth, portal, Docker socket or external network in this probe.
        run(['docker', 'run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
             '--security-opt', 'no-new-privileges:true', '--cpus', '3', '--memory', '1g',
             '--tmpfs', '/tmp:rw,size=256m,mode=1777',
             '--mount', f'type=bind,src={destination},dst=/probe/music.wav,readonly',
             '--mount', f'type=bind,src={destination.with_suffix(".json")},dst=/probe/music.json,readonly',
             'astrolearner-iss-live:local', 'python', '-m', 'app.stream_upgrade_preflight',
             '--music', '/probe/music.wav', '--seconds', '30'], timeout=90)
        stopped()
        # Only this non-secret setting changes; all private values stay intact.
        env_owner = (env.stat().st_uid, env.stat().st_gid)
        replace_file(recovery / 'planned.env', env, env_owner,
                     mode=(recovery / 'private.env').stat().st_mode & 0o777)
        replace_file(recovery / 'planned-presentation.json', preferences, owner, mode=0o600)
        stopped()
        compose('up', '-d', '--no-deps', '--force-recreate', '--wait', '--wait-timeout', '180',
                'camera-browser', 'iss-live', timeout=210)
        stopped()
        print('INSTALADO, SIN PUBLICAR. Inicia manualmente desde el portal. Comprueba señal y panel antes de anunciarlo.')
        diagnose()
    except Exception:
        print('La instalación no ha concluido. No se ha iniciado ninguna emisión. Reversión disponible en:', recovery, file=sys.stderr)
        raise


def rollback(recovery):
    stopped()
    if recovery.parent != ROOT or not recovery.name.startswith('.before-stream-upgrade-') or recovery.is_symlink():
        raise RuntimeError('Directorio de reversión no permitido')
    journal = json.loads((recovery / 'installed.json').read_text())
    preferences = MUSIC / 'presentation.json'
    if ((ROOT / '.env').is_symlink() or preferences.is_symlink()
            or digest(ROOT / '.env') not in journal['env_sha256']
            or (digest(preferences) if preferences.exists() else None) not in journal['preferences_sha256']):
        raise RuntimeError('La configuración cambió desde la instalación; no se sobrescribirá')
    owner = (MUSIC.stat().st_uid, MUSIC.stat().st_gid)
    for name in journal['files']:
        target = safe_target(name)
        actual = digest(target) if target.exists() else None
        if actual not in {journal['files'][name]['before'], journal['files'][name]['after']}:
            raise RuntimeError('El código cambió después de instalar; reversión automática rechazada')
    for name in journal['files']:
        old = recovery / name
        if old.exists():
            replace_file(old, ROOT / name, owner)
        # New modules may remain unused, retaining all files for recovery.
    original_env = recovery / 'private.env'
    replace_file(original_env, ROOT / '.env', tuple(journal['env_owner']),
                 mode=original_env.stat().st_mode & 0o777)
    if (recovery / 'presentation.json').exists():
        replace_file(recovery / 'presentation.json', MUSIC / 'presentation.json', owner)
    elif (MUSIC / 'presentation.json').exists():
        # Preserve the new preferences for inspection, outside the active name.
        shutil.move(str(MUSIC / 'presentation.json'), str(recovery / 'unused-presentation.json'))
    tags = json.loads((recovery / 'rollback-images.json').read_text())
    for service, tag in tags.items():
        current = 'astrolearner-iss-live:local' if service == 'iss-live' else 'astrolearner-iss-camera-browser:local'
        run(['docker', 'image', 'tag', tag, current])
    compose('up', '-d', '--no-deps', '--force-recreate', '--wait', '--wait-timeout', '180',
            'camera-browser', 'iss-live', timeout=210)
    stopped()
    print('REVERTIDO, SIN PUBLICAR. Se han conservado las imágenes y la música nuevas para revisión.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('diagnose', 'install', 'rollback'))
    parser.add_argument('--bundle', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--recovery', type=Path)
    args = parser.parse_args()
    if os.name != 'posix' or os.geteuid() != 0:
        parser.error('Ejecuta este instalador con sudo en homelab')
    if ROOT.resolve() != ROOT or not ROOT.is_dir() or (ROOT / 'app').is_symlink():
        parser.error('No se ha encontrado el proyecto esperado')
    import fcntl
    lock = os.open(ROOT / '.stream-upgrade.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock)
        parser.error('Ya hay una instalación en curso')
    try:
        if args.action == 'diagnose':
            diagnose()
        elif args.action == 'install':
            install(args.bundle.resolve())
        elif args.recovery is not None:
            rollback(args.recovery.absolute())
        else:
            parser.error('Falta --recovery para la reversión')
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(str(error) if isinstance(error, RuntimeError) else 'Comprobación fallida; no se muestran datos privados', file=sys.stderr)
        return 1
    finally:
        os.close(lock)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
