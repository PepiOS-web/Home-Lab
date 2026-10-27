"""Non-publishing deployment helpers; never print dotenv or browser errors."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
from urllib.request import urlopen
import wave

COMPOSE_FILES = "compose.yaml:compose.camera-browser-live.yaml"
SUPPORTED_FPS = (12, 20, 30)
ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def values(text: str) -> dict[str, str]:
    result = {}
    for line in text.splitlines():
        match = ASSIGNMENT.match(line)
        if match:
            value = match[2].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            result[match[1]] = value
    return result


def prepare_environment(original: str, capture: str, fps: int | None = None, map_overlay: str | None = None) -> str:
    production, source = values(original), values(capture)
    if fps is None:
        fps = int(production.get("ISS_LIVE_FPS", "12"))
    if type(fps) is not int or fps not in SUPPORTED_FPS:
        raise ValueError("Solo se admiten 12, 20 o 30 FPS; probar la frecuencia antes de desplegar")
    if map_overlay is None:
        map_overlay = production.get("ISS_BROWSER_MAP_OVERLAY", "esa")
    if map_overlay not in {"esa", "astrolearner"}:
        raise ValueError("El mapa debe ser ESA o AstroLearner")
    if production.get("ISS_LIVE_AUTO_START", "false").lower() not in {"false", "0", "no", "off"}:
        raise ValueError("Desactivar el arranque automatico antes de preparar una recuperacion segura")
    if production.get("COMPOSE_FILE", "") not in {"", COMPOSE_FILES}:
        raise ValueError("Hay una seleccion Compose distinta; no se modificara automaticamente")
    if production.get("COMPOSE_PROJECT_NAME", "") not in {"", "astrolearner-iss-live"}:
        raise ValueError("Hay un proyecto Compose distinto; no se modificara automaticamente")
    if production.get("COMPOSE_PATH_SEPARATOR", "") not in {"", ":"}:
        raise ValueError("Hay un separador Compose distinto; no se modificara automaticamente")
    if source.get("ISS_BROWSER_CAPTURE_AUTHORIZED", "").lower() != "true":
        raise ValueError("Falta la autorizacion de la fuente que se probo en staging")
    video_id = source.get("ISS_BROWSER_VIDEO_ID", "awQzjn72bI0")
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Identificador de fuente no valido")
    changes = {
        "COMPOSE_FILE": COMPOSE_FILES,
        "COMPOSE_PATH_SEPARATOR": ":",
        "ISS_LIVE_DRY_RUN": "false", "ISS_LIVE_AUTO_START": "false",
        "ISS_LIVE_PRIVACY": "public", "ISS_LIVE_ENCODER": "libx264",
        "ISS_LIVE_WIDTH": "1280", "ISS_LIVE_HEIGHT": "720", "ISS_LIVE_FPS": str(fps),
        "ISS_LIVE_CAMERA_ENABLED": "true", "ISS_LIVE_CAMERA_MODE": "auto",
        "ISS_LIVE_CAMERA_URL": "http://camera-browser:8093/camera.mjpeg",
        "ISS_LIVE_CAMERA_AUTHORIZED": "true", "ISS_LIVE_MAP_SECONDS": "0",
        "ISS_BROWSER_CAPTURE_AUTHORIZED": "true", "ISS_BROWSER_VIDEO_ID": video_id,
        "ISS_BROWSER_MAP_OVERLAY": map_overlay,
    }
    output, written = [], set()
    for line in original.splitlines(keepends=True):
        match = ASSIGNMENT.match(line.rstrip("\r\n"))
        key = match[1] if match else None
        if key in changes:
            if key not in written:
                output.append(f"{key}={changes[key]}\n")
                written.add(key)
        else:
            output.append(line)
    if output and not output[-1].endswith("\n"):
        output.append("\n")
    output.extend(f"{key}={value}\n" for key, value in changes.items() if key not in written)
    return "".join(output)


def require_stopped(state: object) -> None:
    if (not isinstance(state, dict) or state.get("live_requested") is not False
            or state.get("ffmpeg_running") is not False or state.get("status") == "en directo"):
        raise ValueError("Primero pulsa Detener en el portal y espera; no se cortara un directo automaticamente")


def deployment_ready(state: dict, capture: dict, target_fps: int = 12, map_source: str = "esa") -> bool:
    require_stopped(state)
    if type(target_fps) is not int or target_fps not in SUPPORTED_FPS or map_source not in {"esa", "astrolearner"}:
        return False
    fps, frames = capture.get("capture_fps"), capture.get("captured_frames")
    return (state.get("control_ready") is True and state.get("camera_enabled") is True
            and state.get("camera_configured") is True and state.get("camera_available") is True
            and state.get("video_mode") == "camera" and not state.get("last_error")
            and capture.get("ready") is True and capture.get("map_source") == map_source
            and capture.get("map_ready") is True
            and capture.get("target_fps") == target_fps
            and isinstance(fps, (int, float)) and not isinstance(fps, bool)
            and math.isfinite(fps) and fps >= target_fps * 0.95
            and isinstance(frames, int) and not isinstance(frames, bool) and frames >= target_fps * 10)


def refresh_selector() -> None:
    """Exercise the local gateway without starting an encoder or publishing.

    Source freshness and selection are evaluated when a frame is consumed. A
    stopped outbound encoder must not make deployment readiness wait forever.
    """
    with urlopen("http://127.0.0.1:8092/api/status", timeout=3) as response:
        require_stopped(json.load(response))
    with urlopen("http://127.0.0.1:8092/video.mjpeg", timeout=2) as response:
        if not response.read(512):
            raise ValueError("El selector local no ha entregado imagen")


def verify() -> None:
    from app.config import Settings

    settings = Settings()
    settings.validate()
    if (settings.dry_run or settings.auto_start or settings.privacy != "public"
            or not settings.camera_enabled or not settings.camera_authorized
            or settings.camera_mode != "auto"
            or settings.camera_url != "http://camera-browser:8093/camera.mjpeg"
            or (settings.width, settings.height, settings.encoder) != (1280, 720, "libx264")
            or settings.fps not in SUPPORTED_FPS or settings.map_seconds != 0):
        raise ValueError("La configuracion efectiva no coincide con el despliegue validado")
    with urlopen("http://127.0.0.1:8092/api/status", timeout=4) as response:
        state = json.load(response)
    with urlopen("http://camera-browser:8093/ready", timeout=4) as response:
        capture = json.load(response)
    map_source = os.getenv("ISS_BROWSER_MAP_OVERLAY", "esa")
    if not deployment_ready(state, capture, settings.fps, map_source):
        raise ValueError("La camara y el mapa aun no estan listos")
    with wave.open(str(settings.data_dir / "music" / "astrolearner-lofi-hour-v1.wav"), "rb") as audio:
        if (audio.getnchannels() != 2 or audio.getsampwidth() != 2
                or abs(audio.getnframes() / audio.getframerate() - 3600) >= 0.01):
            raise ValueError("No se ha validado la musica de una hora")
    print(json.dumps({"deployment": "ready", "publishing": False, "live_requested": False,
                      "camera_available": True, "esa_map_ready": map_source == "esa",
                      "map_source": map_source, "map_ready": True,
                      "target_fps": settings.fps,
                      "capture_fps": capture["capture_fps"],
                      "hourly_music_preserved": True, "start_from_portal": True}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "stopped", "verify", "refresh"))
    parser.add_argument("--production", type=Path)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fps", type=int, choices=SUPPORTED_FPS)
    parser.add_argument("--map-overlay", choices=("esa", "astrolearner"))
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            if None in (args.production, args.capture, args.output):
                raise ValueError("Faltan los archivos del despliegue")
            # Output is a pre-created private mktemp file; .env is not modified here.
            with args.production.open(newline="") as stream:
                original = stream.read()
            args.output.write_text(prepare_environment(original, args.capture.read_text(), args.fps, args.map_overlay), encoding="utf-8")
        elif args.action == "stopped":
            require_stopped(json.loads(sys.stdin.read(65537)))
        elif args.action == "refresh":
            refresh_selector()
        else:
            verify()
    except Exception:
        # No traceback: dotenv, token paths and HTTP exceptions may contain secrets.
        print("Comprobacion no superada; no iniciar ni recrear la emision.", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
