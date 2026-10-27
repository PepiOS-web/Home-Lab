#!/usr/bin/env python3
"""Private, fail-closed snapshots for the ISS services kept online by backup.

The CLI has fixed production source paths. It never prints Docker inspect,
credentials, file contents, or an exception containing private file contents.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path

ISS_ROOT = Path("/srv/data/appdata/astrolearner-iss-live")
DNS_ROOT = Path("/srv/data/appdata/adguardhome")
STATUS_ROOT = Path("/srv/data/appdata/homelab-status")
BACKUP_ROOT = Path("/srv/data/backups/daily")
PROJECT = "astrolearner-iss-live"
PROJECT_LABEL = "com.docker.compose.project"
SERVICE_LABEL = "com.docker.compose.service"
ID = re.compile(r"[0-9a-f]{64}\Z")
SPACE_RESERVE = 2 * 1024 ** 3


class BackupError(RuntimeError):
    """A static message safe for the system journal."""


@dataclass(frozen=True)
class Stamp:
    device: int
    inode: int
    mode: int
    uid: int
    gid: int
    size: int
    modified: int
    changed: int


def stamp(path: Path) -> Stamp:
    value = path.lstat()
    return Stamp(value.st_dev, value.st_ino, value.st_mode, value.st_uid,
                 value.st_gid, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def inventory(root: Path, *, iss: bool) -> dict[str, Stamp]:
    """Ignore only documented disposable caches, never persistent unknown data."""
    result: dict[str, Stamp] = {}
    if not root.exists() and not root.is_symlink():
        return result
    if not stat.S_ISDIR(root.lstat().st_mode):
        raise BackupError("El origen del snapshot no es un directorio normal.")
    if iss:
        children = {item.name for item in root.iterdir()}
        if children - {"music", "nasa", "secrets", "status"}:
            raise BackupError("Hay datos ISS nuevos sin una politica de copia definida.")
        nasa = root / "nasa"
        if nasa.exists() and not nasa.is_symlink():
            if {item.name for item in nasa.iterdir()} - {"videos", "epic"}:
                raise BackupError("Hay datos NASA nuevos sin una politica de copia definida.")

    def visit(path: Path) -> None:
        relative = path.relative_to(root).as_posix()
        if iss and (relative == "status" or relative == "nasa/epic"):
            value = stamp(path)
            if not stat.S_ISDIR(value.mode):
                raise BackupError("Una cache ISS no es un directorio normal.")
            # Preserve the writable directory's identity/permissions but not its
            # constantly changing contents, size or timestamps.
            result[relative] = Stamp(value.device, value.inode, value.mode,
                                     value.uid, value.gid, 0, 0, 0)
            return
        if iss and relative != "." and (
            path.name.endswith((".tmp", ".tmp.mp4", ".download", ".part"))
            or path.name.startswith((".live-metadata-", "lofi-"))
        ):
            raise BackupError("Hay una generacion ISS en curso; se reintentara la copia.")
        value = stamp(path)
        if not (stat.S_ISREG(value.mode) or stat.S_ISDIR(value.mode)):
            raise BackupError("El snapshot contiene un enlace o archivo especial no permitido.")
        result[relative] = value
        if stat.S_ISDIR(value.mode):
            for child in sorted(path.iterdir()):
                visit(child)

    visit(root)
    return result


def private_json(path: Path, value: object) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(value, output)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def load_json(path: Path) -> object:
    if path.stat().st_size > 16 * 1024 * 1024:
        raise BackupError("Un JSON del snapshot supera el limite permitido.")
    try:
        def reject_constant(_: str) -> None:
            raise ValueError("Non-JSON constant")
        return json.loads(path.read_bytes(), parse_constant=reject_constant)
    except (ValueError, UnicodeError):
        raise BackupError("Un JSON del snapshot esta incompleto o no es valido.") from None


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_iss(root: Path) -> None:
    """Validate complete tokens and cross-file media manifests, not just tar exit."""
    for path in root.rglob("*.json"):
        value = load_json(path)
        if path.name == "youtube-token.json":
            if not isinstance(value, dict) or any(
                not isinstance(value.get(key), str) or not value[key]
                for key in ("refresh_token", "client_id", "client_secret", "token_uri")
            ):
                raise BackupError("La copia del token OAuth no es recuperable.")
    for path in (root / "music").glob("*.wav"):
        try:
            with wave.open(str(path), "rb") as audio:
                frames = audio.getnframes()
                rate = audio.getframerate()
                size = frames * audio.getnchannels() * audio.getsampwidth()
                if frames <= 0 or rate <= 0 or size > path.stat().st_size:
                    raise BackupError("Un WAV del snapshot esta incompleto.")
                audio.setpos(frames - 1)
                if len(audio.readframes(1)) != audio.getnchannels() * audio.getsampwidth():
                    raise BackupError("Faltan las ultimas muestras de un WAV del snapshot.")
                duration = frames / rate
        except (wave.Error, EOFError):
            raise BackupError("Un WAV del snapshot no es valido.") from None
        sidecar = path.with_suffix(".json")
        if sidecar.is_file():
            metadata = load_json(sidecar)
            if not isinstance(metadata, dict) or abs(float(metadata.get("duration_seconds", -1)) - duration) > .1:
                raise BackupError("El WAV no coincide con los metadatos de su sesion.")

    videos = root / "nasa" / "videos"
    cached_hashes: dict[str, str] = {}

    def validate_asset(value: object) -> None:
        if not isinstance(value, dict):
            raise BackupError("El manifiesto NASA no es valido.")
        filename, expected = value.get("filename"), value.get("sha256")
        if not isinstance(filename, str) or Path(filename).name != filename or "/" in filename or "\\" in filename:
            raise BackupError("El manifiesto NASA contiene una ruta no permitida.")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise BackupError("Falta la integridad de un recurso NASA.")
        path = videos / filename
        if not path.is_file():
            raise BackupError("Falta un recurso referenciado por NASA.")
        if filename not in cached_hashes:
            cached_hashes[filename] = file_hash(path)
        actual = cached_hashes[filename]
        if actual != expected:
            raise BackupError("Un recurso NASA no coincide con su manifiesto.")

    manifest = videos / "manifest.json"
    if manifest.is_file():
        value = load_json(manifest)
        if not isinstance(value, dict) or not isinstance(value.get("items"), list):
            raise BackupError("El manifiesto NASA no es valido.")
        for item in value["items"]:
            validate_asset(item)
        if "playback_video" in value:
            validate_asset(value["playback_video"])
    loop = videos / "astrolearner-nasa-loop.json"
    if loop.is_file():
        validate_asset(load_json(loop))
    playlist = videos / "playlist.ffconcat"
    if playlist.is_file():
        if playlist.stat().st_size > 1024 * 1024:
            raise BackupError("La lista NASA supera el limite permitido.")
        for line in playlist.read_text(encoding="utf-8").splitlines():
            if line.startswith("file "):
                match = re.fullmatch(r"file '/data/nasa/videos/([a-zA-Z0-9_.-]+)'", line)
                if not match or not (videos / match[1]).is_file():
                    raise BackupError("La lista NASA referencia un recurso no recuperable.")


def copy_file(source: Path, destination: Path) -> None:
    # GNU cp preserves ACLs/xattrs/ownership; reflinks when available, never links
    # backup files to live inodes. A concurrent replacement is caught below.
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    os.close(descriptor)
    subprocess.run(["/usr/bin/cp", "--reflink=auto", "--preserve=all", "--no-dereference",
                    "--", str(source), str(destination)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=900)


def verify_metadata(source: Path, destination: Path) -> None:
    before, after = source.lstat(), destination.lstat()
    if ((stat.S_IMODE(before.st_mode), before.st_uid, before.st_gid)
            != (stat.S_IMODE(after.st_mode), after.st_uid, after.st_gid)):
        raise BackupError("No se conservaron los permisos o propietarios del snapshot.")
    if hasattr(os, "listxattr"):
        original = {key: os.getxattr(source, key, follow_symlinks=False)
                    for key in os.listxattr(source, follow_symlinks=False)}
        copied = {key: os.getxattr(destination, key, follow_symlinks=False)
                  for key in os.listxattr(destination, follow_symlinks=False)}
        if original != copied:
            raise BackupError("No se conservaron los atributos extendidos o ACL del snapshot.")


def copy_tree(source: Path, destination: Path, before: dict[str, Stamp]) -> None:
    for relative, value in before.items():
        if stat.S_ISDIR(value.mode):
            (destination / relative).mkdir(mode=0o700, parents=True, exist_ok=True)
    for relative, value in before.items():
        if stat.S_ISREG(value.mode):
            original, target = source / relative, destination / relative
            if stamp(original) != value:
                raise BackupError("Los datos cambiaron antes de copiarlos.")
            copy_file(original, target)
            if stamp(original) != value or not stat.S_ISREG(target.lstat().st_mode):
                raise BackupError("Los datos cambiaron durante su copia.")
            verify_metadata(original, target)
    # Restore directory metadata last, because copying children changes mtimes.
    for relative, value in reversed(list(before.items())):
        if stat.S_ISDIR(value.mode):
            original, target = source / relative, destination / relative
            if hasattr(os, "chown"):
                os.chown(target, value.uid, value.gid)
            shutil.copystat(original, target, follow_symlinks=False)
            verify_metadata(original, target)


def require_space(destination: Path, inventories: list[dict[str, Stamp]]) -> None:
    parent = destination
    while not parent.exists():
        parent = parent.parent
    required = sum(value.size for values in inventories for value in values.values()
                   if stat.S_ISREG(value.mode)) + SPACE_RESERVE
    if shutil.disk_usage(parent).free < required:
        raise BackupError("No hay espacio para el snapshot y la reserva privada de 2 GiB.")


def require_iss_data(root: Path) -> None:
    required = ("secrets/youtube-token.json", "nasa/videos/manifest.json",
                "nasa/videos/playlist.ffconcat", "nasa/videos/astrolearner-nasa-loop.mp4",
                "nasa/videos/astrolearner-nasa-loop.json")
    if any(not (root / name).is_file() for name in required) or not any((root / "music").glob("*.wav")):
        raise BackupError("Faltan datos recuperables del emisor ISS activo; no se detendran servicios.")


def snapshot(source: Path, destination: Path, *, iss: bool, attempts: int = 3,
             required_iss: bool = False) -> None:
    if destination.exists() or destination.is_symlink():
        raise BackupError("El destino del snapshot ya existe.")
    for attempt in range(attempts):
        try:
            if required_iss:
                require_iss_data(source)
            before = inventory(source, iss=iss)
            if not before:
                return
            require_space(destination, [before])
            copy_tree(source, destination, before)
            if inventory(source, iss=iss) != before:
                raise BackupError("Los datos cambiaron durante el snapshot.")
            if iss:
                if required_iss:
                    require_iss_data(destination)
                validate_iss(destination)
            # Validation may hash large assets: cover that interval too.
            if inventory(source, iss=iss) != before:
                raise BackupError("Los datos cambiaron al validar el snapshot.")
            return
        except (BackupError, OSError, subprocess.SubprocessError, ValueError):
            if destination.is_dir() and not destination.is_symlink():
                shutil.rmtree(destination)
            if attempt + 1 == attempts:
                raise BackupError("No se pudo obtener un snapshot estable; no se archivaron datos ISS en vivo.") from None
            time.sleep(1)


def snapshot_empty_cache(source: Path, destination: Path) -> None:
    """Keep a regenerable host cache writable after restore, without its data."""
    if not source.exists() and not source.is_symlink():
        return
    before = stamp(source)
    if not stat.S_ISDIR(before.mode):
        raise BackupError("La cache del estado del host no es un directorio normal.")
    if destination.exists() or destination.is_symlink():
        raise BackupError("El destino de la cache ya existe.")
    destination.mkdir(mode=0o700, parents=True)
    if hasattr(os, "chown"):
        os.chown(destination, before.uid, before.gid)
    shutil.copystat(source, destination, follow_symlinks=False)
    verify_metadata(source, destination)
    after = stamp(source)
    if ((before.device, before.inode, before.mode, before.uid, before.gid)
            != (after.device, after.inode, after.mode, after.uid, after.gid)):
        raise BackupError("La identidad de la cache del host cambio durante la copia.")


def container_plan(items: list[dict]) -> dict[str, list[str]]:
    plan: dict[str, list[str]] = {"bulk": [], "iss": [], "iss_main": [], "dns": []}
    seen: set[str] = set()
    services: set[str] = set()
    for item in items:
        identity = item.get("Id", "")
        if not isinstance(identity, str) or not ID.fullmatch(identity) or identity in seen:
            raise BackupError("El inventario Docker no es valido.")
        seen.add(identity)
        if item.get("State", {}).get("Running") is not True:
            raise BackupError("El inventario Docker cambio durante su consulta.")
        labels = item.get("Config", {}).get("Labels") or {}
        project, service = labels.get(PROJECT_LABEL), labels.get(SERVICE_LABEL)
        name = item.get("Name", "").lstrip("/")
        is_iss = project == PROJECT and service in {"iss-live", "camera-browser"}
        is_dns = project == "adguardhome" and service == "adguardhome" and name == "adguardhome"
        if name == "astrolearner-iss-live" and not (is_iss and service == "iss-live"):
            raise BackupError("La identidad del emisor ISS no coincide con el proyecto esperado.")
        if name == "adguardhome" and not is_dns:
            raise BackupError("La identidad de AdGuard no coincide con el proyecto esperado.")
        if is_iss:
            if service in services:
                raise BackupError("Hay servicios ISS duplicados; no se detendra ninguno.")
            services.add(service)
            if service == "iss-live" and name != "astrolearner-iss-live":
                raise BackupError("El emisor ISS no tiene la identidad esperada.")
            allowed = {
                "/data/music": str(ISS_ROOT / "music"),
                "/data/nasa": str(ISS_ROOT / "nasa"),
                "/data/secrets/youtube-token.json": str(ISS_ROOT / "secrets/youtube-token.json"),
                "/status": str(ISS_ROOT / "status"),
            } if service == "iss-live" else {}
            for mount in item.get("Mounts", []):
                if mount.get("Type") == "tmpfs":
                    continue
                if mount.get("Type") != "bind" or allowed.get(mount.get("Destination")) != mount.get("Source"):
                    raise BackupError("Los volumenes ISS requieren revisar la politica de backup.")
            if service == "iss-live" and {m.get("Destination") for m in item.get("Mounts", []) if m.get("Type") != "tmpfs"} != set(allowed):
                raise BackupError("Faltan los volumenes ISS esperados.")
            plan["iss"].append(identity)
            if service == "iss-live":
                plan["iss_main"].append(identity)
        elif is_dns:
            allowed_dns = {"/opt/adguardhome/work": str(DNS_ROOT / "work"),
                           "/opt/adguardhome/conf": str(DNS_ROOT / "conf")}
            mounts = item.get("Mounts", [])
            if len(mounts) != 2 or any(m.get("Type") != "bind" or allowed_dns.get(m.get("Destination")) != m.get("Source") for m in mounts):
                raise BackupError("Los volumenes AdGuard requieren revisar la politica de backup.")
            plan["dns"].append(identity)
        else:
            plan["bulk"].append(identity)
    if len(plan["dns"]) > 1:
        raise BackupError("Hay resolutores DNS duplicados.")
    return plan


def docker_inventory() -> list[dict]:
    result = subprocess.run(["/usr/bin/docker", "ps", "--no-trunc", "-q"], check=True,
                            capture_output=True, text=True, timeout=20)
    identities = result.stdout.split()
    if not identities:
        return []
    if any(not ID.fullmatch(value) for value in identities):
        raise BackupError("Docker devolvio identificadores no validos.")
    result = subprocess.run(["/usr/bin/docker", "inspect", *identities], check=True,
                            capture_output=True, text=True, timeout=30)
    value = json.loads(result.stdout)
    if not isinstance(value, list):
        raise BackupError("Docker no devolvio un inventario valido.")
    return value


def checked_work(path: Path) -> Path:
    # No arbitrary destination paths or symlink traversal from the root CLI.
    if path.parent != BACKUP_ROOT or not re.fullmatch(r"\.work-[A-Za-z0-9]+", path.name):
        raise BackupError("El directorio privado de trabajo no es valido.")
    for directory in (BACKUP_ROOT, path):
        value = directory.lstat()
        if (not stat.S_ISDIR(value.st_mode) or value.st_uid != 0
                or stat.S_IMODE(value.st_mode) != 0o700 or directory.resolve() != directory):
            raise BackupError("El directorio de trabajo debe pertenecer a root con modo 0700.")
    return path


def wait_dns(identities: list[str], *, timeout: float = 30) -> None:
    if not identities:
        return
    if any(not isinstance(identity, str) or not ID.fullmatch(identity) for identity in identities):
        raise BackupError("El plan DNS no es valido.")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(["/usr/bin/docker", "inspect", *identities], check=True,
                                capture_output=True, text=True, timeout=5)
        items = json.loads(result.stdout)
        if len(items) == len(identities) and all(
            item.get("State", {}).get("Running") is True
            and item.get("State", {}).get("Health", {}).get("Status", "none") in {"none", "healthy"}
            for item in items
        ):
            return
        time.sleep(1)
    raise BackupError("AdGuard no esta activo y sano tras el reinicio; no se detendran mas servicios.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "ids", "preflight-space", "snapshot-iss", "snapshot-dns", "snapshot-status", "wait-dns", "verify-quiesced", "verify-restarted"))
    parser.add_argument("work", type=Path)
    parser.add_argument("group", nargs="?", choices=("bulk", "dns"))
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise BackupError("El helper solo puede ejecutarlo root.")
    work = checked_work(args.work)
    if args.command == "plan":
        private_json(work / "plan.json", container_plan(docker_inventory()))
    elif args.command == "preflight-space":
        plan = load_json(work / "plan.json")
        if plan["iss_main"]:
            require_iss_data(ISS_ROOT)
        require_space(work, [inventory(ISS_ROOT, iss=True), inventory(DNS_ROOT, iss=False)])
    elif args.command == "wait-dns":
        plan = load_json(work / "plan.json")
        wait_dns(plan["dns"])
    elif args.command == "snapshot-status":
        snapshot_empty_cache(STATUS_ROOT, work / "snapshot" / STATUS_ROOT.relative_to("/"))
    elif args.command == "ids":
        plan = load_json(work / "plan.json")
        if not isinstance(plan, dict) or args.group is None:
            raise BackupError("Falta el grupo del plan de contenedores.")
        identities = plan.get(args.group)
        if not isinstance(identities, list) or any(not isinstance(value, str) or not ID.fullmatch(value) for value in identities):
            raise BackupError("El plan de contenedores no es valido.")
        for identity in identities:
            print(identity)
    elif args.command.startswith("snapshot-"):
        iss = args.command == "snapshot-iss"
        source = ISS_ROOT if iss else DNS_ROOT
        destination = work / "snapshot" / source.relative_to("/")
        plan = load_json(work / "plan.json")
        snapshot(source, destination, iss=iss, attempts=3 if iss else 1,
                 required_iss=iss and bool(plan["iss_main"]))
    else:
        plan = load_json(work / "plan.json")
        current = container_plan(docker_inventory())
        expected = set(plan["iss"] + plan["dns"])
        if args.command == "verify-restarted":
            expected.update(plan["bulk"])
        actual = set(current["iss"] + current["dns"] + current["bulk"])
        if actual != expected:
            raise BackupError("Los contenedores activos no coinciden con el plan; revisar servicios.")


if __name__ == "__main__":
    try:
        main()
    except BackupError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        print("ERROR: no se completo la comprobacion privada del backup; revisar la politica y los servicios.", file=sys.stderr)
        sys.exit(1)
