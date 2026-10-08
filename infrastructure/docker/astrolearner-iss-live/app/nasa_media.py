from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx

from .config import Settings

MAX_VIDEO_BYTES = 20 * 1024 * 1024 * 1024
ASSET_HOST = "images-assets.nasa.gov"
CURATED_VIDEOS = (
    {
        "nasa_id": "jsc2022m000172_Earth_in_4K_Expedition_65_Edition",
        "center": "JSC",
        "filename": "01-earth-expedition-65-original.mp4",
    },
    {
        "nasa_id": (
            "jsc2021m000138_4K_Earth_Views_Extended_Cut_for_Earth_Day_ "
            "2021_210422-4KMP4"
        ),
        "center": "JSC",
        "filename": "02-earth-day-2021-original.mp4",
    },
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_video(path: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_name,codec_type,width,height",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    details = json.loads(result.stdout)
    streams = details.get("streams", [])
    if not any(stream.get("codec_type") == "video" for stream in streams):
        raise ValueError(f"El recurso no contiene vídeo: {path.name}")
    duration = float(details.get("format", {}).get("duration", 0))
    if duration < 900:
        raise ValueError(f"El vídeo dura menos de 15 minutos: {path.name}")
    return {"duration_seconds": round(duration, 2), "streams": streams}


def _build_normalized_loop(
    destination: Path, videos: list[dict[str, object]]
) -> dict[str, object]:
    """Create one stable H.264 stream so live FFmpeg never switches source files."""
    if not videos:
        raise ValueError("No hay vídeos NASA para crear el bucle de reproducción")
    output = destination / "astrolearner-nasa-loop.mp4"
    temporary = destination / "astrolearner-nasa-loop.tmp.mp4"
    metadata_path = destination / "astrolearner-nasa-loop.json"
    profile = {"width": 1280, "height": 720, "fps": 12, "crf": 18, "version": 1}
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "profile": profile,
                "videos": [
                    {"filename": video["filename"], "sha256": video["sha256"]}
                    for video in videos
                ],
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    if output.is_file() and metadata_path.is_file():
        try:
            cached = json.loads(metadata_path.read_text(encoding="utf-8"))
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            cached_duration = float(probe.stdout.strip())
            if (
                cached.get("fingerprint") == fingerprint
                and output.stat().st_size > 100_000
                and cached_duration >= len(videos) * 900 - 2
            ):
                return {
                    **cached,
                    "duration_seconds": round(cached_duration, 2),
                    "bytes": output.stat().st_size,
                }
        except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError):
            pass
    filters: list[str] = []
    command = ["ffmpeg", "-hide_banner", "-loglevel", "info", "-stats_period", "60", "-y"]
    for index, video in enumerate(videos):
        source = destination / str(video["filename"])
        command.extend(["-i", str(source)])
        filters.append(
            f"[{index}:v:0]trim=duration=900,setpts=PTS-STARTPTS,fps=12,"
            "scale=1280:720:force_original_aspect_ratio=decrease:flags=lanczos,"
            "pad=1280:720:(ow-iw)/2:(oh-ih)/2:black,setsar=1,"
            f"format=yuv420p[v{index}]"
        )
    inputs = "".join(f"[v{index}]" for index in range(len(videos)))
    filters.append(f"{inputs}concat=n={len(videos)}:v=1:a=0,format=yuv420p[outv]")
    command.extend(
        [
            "-filter_complex", ";".join(filters),
            "-map", "[outv]", "-an",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-r", "12", "-g", "24", "-keyint_min", "24", "-sc_threshold", "0",
            "-pix_fmt", "yuv420p", "-video_track_timescale", "90000",
            "-movflags", "+faststart", str(temporary),
        ]
    )
    temporary.unlink(missing_ok=True)
    try:
        subprocess.run(command, check=True, timeout=4 * 60 * 60)
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(temporary),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        duration = float(probe.stdout.strip())
        expected_duration = len(videos) * 900
        if duration < expected_duration - 2:
            raise ValueError(
                f"El bucle NASA dura {duration:.1f}s; se esperaban ~{expected_duration}s"
            )
        os.chmod(temporary, 0o644)
        temporary.replace(output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    result = {
        "filename": output.name,
        "duration_seconds": round(duration, 2),
        "bytes": output.stat().st_size,
        "sha256": _sha256(output),
        "video_codec": "h264",
        "width": 1280,
        "height": 720,
        "fps": 12,
        "fingerprint": fingerprint,
    }
    metadata_temporary = metadata_path.with_suffix(".tmp")
    metadata_temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.chmod(metadata_temporary, 0o644)
    metadata_temporary.replace(metadata_path)
    return result


def _metadata(client: httpx.Client, nasa_id: str, center: str) -> dict[str, str]:
    response = client.get(
        "https://images-api.nasa.gov/search",
        params={"nasa_id": nasa_id},
    )
    response.raise_for_status()
    items = response.json().get("collection", {}).get("items", [])
    if not items:
        raise ValueError(f"NASA no devolvió metadatos para {nasa_id}")
    data = items[0]["data"][0]
    if data.get("nasa_id") != nasa_id or data.get("center") != center:
        raise ValueError(f"La procedencia NASA no coincide para {nasa_id}")
    if data.get("media_type") != "video":
        raise ValueError(f"El recurso NASA no es un vídeo: {nasa_id}")
    return {
        "nasa_id": nasa_id,
        "title": str(data.get("title", nasa_id)),
        "center": center,
        "date_created": str(data.get("date_created", "")),
        "description": str(data.get("description", "")),
    }


def _asset_url(client: httpx.Client, nasa_id: str) -> str:
    response = client.get(
        f"https://images-api.nasa.gov/asset/{quote(nasa_id, safe='')}"
    )
    response.raise_for_status()
    items = response.json().get("collection", {}).get("items", [])
    # Prefer NASA's large web rendition. The original masters are 4K and
    # needlessly expensive to decode for a 720p live stream on this host.
    candidates = [
        str(item.get("href", "")).replace("http://", "https://", 1)
        for item in items
        if str(item.get("href", "")).lower().endswith(
            ("~orig.mp4", "~large.mp4", "~medium.mp4", "~mobile.mp4")
        )
    ]
    priorities = ("~large.mp4", "~medium.mp4", "~orig.mp4", "~mobile.mp4")
    url = next(
        (candidate for suffix in priorities for candidate in candidates
         if candidate.lower().endswith(suffix)),
        "",
    )
    if not url:
        raise ValueError(f"NASA no ofrece una variante MP4 compatible para {nasa_id}")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != ASSET_HOST:
        raise ValueError(f"Host de descarga NASA no permitido: {url}")
    return url


def _download(client: httpx.Client, url: str, destination: Path) -> None:
    temporary = destination.with_suffix(".download")
    total = 0
    try:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if not content_type.startswith(("video/", "application/octet-stream")):
                raise ValueError(f"Tipo de contenido no permitido: {content_type}")
            declared = int(response.headers.get("content-length", "0") or 0)
            if declared > MAX_VIDEO_BYTES:
                raise ValueError("El vídeo NASA supera el límite configurado")
            with temporary.open("wb") as output:
                for chunk in response.iter_bytes(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_VIDEO_BYTES:
                        raise ValueError("El vídeo NASA supera el límite configurado")
                    output.write(chunk)
        if total < 1024 * 1024:
            raise ValueError("La descarga NASA es anormalmente pequeña")
        os.chmod(temporary, 0o644)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> None:
    settings = Settings()
    destination = settings.data_dir / "nasa" / "videos"
    destination.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []

    with httpx.Client(timeout=120, follow_redirects=True) as client:
        for item in CURATED_VIDEOS:
            nasa_id = str(item["nasa_id"])
            filename = str(item["filename"])
            if not re.fullmatch(r"[a-z0-9-]+\.mp4", filename):
                raise ValueError("Nombre local de vídeo no permitido")
            metadata = _metadata(client, nasa_id, str(item["center"]))
            url = _asset_url(client, nasa_id)
            rendition = url.rsplit("~", 1)[-1].split(".", 1)[0]
            stem = filename.removesuffix("-original.mp4")
            rendition_filename = f"{stem}-{rendition}.mp4"
            video_path = destination / rendition_filename
            if not video_path.exists():
                print(f"Descargando {metadata['title']} ({rendition})...")
                _download(client, url, video_path)
            probe = _validate_video(video_path)
            manifest.append(
                {
                    **metadata,
                    **probe,
                    "filename": rendition_filename,
                    "bytes": video_path.stat().st_size,
                    "sha256": _sha256(video_path),
                    "asset_url": url,
                    "attribution": "NASA Johnson Space Center",
                }
            )

    playlist = destination / "playlist.ffconcat"
    temporary_playlist = playlist.with_suffix(".tmp")
    temporary_playlist.write_text(
        "ffconcat version 1.0\n"
        + "".join(
            (
                f"file '/data/nasa/videos/{item['filename']}'\n"
                "inpoint 0\n"
                "outpoint 900\n"
            )
            for item in manifest
        ),
        encoding="utf-8",
    )
    os.chmod(temporary_playlist, 0o644)
    temporary_playlist.replace(playlist)
    print(
        "Normalizando los clips a un único MP4 720p12 para evitar cortes "
        "en los cambios de vídeo...",
        flush=True,
    )
    playback_video = _build_normalized_loop(destination, manifest)
    manifest_path = destination / "manifest.json"
    temporary_manifest = manifest_path.with_suffix(".tmp")
    temporary_manifest.write_text(
        json.dumps(
            {
                "source": "NASA Image and Video Library",
                "usage_guidelines": (
                    "https://www.nasa.gov/nasa-brand-center/images-and-media/"
                ),
                "items": manifest,
                "playback_video": playback_video,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary_manifest, 0o644)
    temporary_manifest.replace(manifest_path)
    print(f"Biblioteca NASA validada: {len(manifest)} vídeos")
    print(f"Lista FFmpeg: {playlist}")


if __name__ == "__main__":
    main()
