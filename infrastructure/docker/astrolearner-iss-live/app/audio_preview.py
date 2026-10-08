from __future__ import annotations

import logging
import subprocess
from pathlib import Path

LOG = logging.getLogger(__name__)


def create_music_preview(music_path: Path, status_dir: Path) -> None:
    """Publish a short, compressed local preview through Homepage's read-only mount."""
    if not music_path.is_file():
        LOG.warning("No se genera la preescucha: falta la pista %s", music_path.name)
        return

    status_dir.mkdir(parents=True, exist_ok=True)
    audio_path = status_dir / "lofi-preview.mp3"
    page_path = status_dir / "lofi-preview.html"
    temp_path = status_dir / "lofi-preview.tmp.mp3"

    try:
        if (
            not audio_path.is_file()
            or audio_path.stat().st_mtime < music_path.stat().st_mtime
        ):
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(music_path),
                    "-t",
                    "90",
                    "-vn",
                    "-codec:a",
                    "libmp3lame",
                    "-b:a",
                    "128k",
                    "-ar",
                    "44100",
                    "-ac",
                    "2",
                    str(temp_path),
                ],
                check=True,
                capture_output=True,
                timeout=45,
            )
            temp_path.replace(audio_path)

        page = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>Preescucha AstroLearner Lo-Fi</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; }
    body { box-sizing: border-box; margin: 0; padding: 1rem; color: #e8edf7;
      background: #171923; }
    h1 { margin: 0 0 .35rem; font-size: 1rem; }
    p { margin: 0 0 .8rem; color: #aab5c8; font-size: .82rem; }
    audio { width: 100%; height: 42px; }
  </style>
</head>
<body>
  <h1>AstroLearner Lo-Fi</h1>
  <p>Muestra de 90 segundos · Rhodes suave · sin ruido blanco</p>
  <audio controls preload="none">
    <source src="lofi-preview.mp3" type="audio/mpeg">
    Tu navegador no admite audio HTML5.
  </audio>
</body>
</html>
"""
        page_path.write_text(page, encoding="utf-8")
    except (OSError, subprocess.SubprocessError) as exc:
        temp_path.unlink(missing_ok=True)
        LOG.warning("No se pudo crear la preescucha Lo-Fi: %s", exc)
