from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} debe ser un entero") from exc
    if value <= 0:
        raise RuntimeError(f"{name} debe ser mayor que cero")
    return value


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} debe ser un número") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} debe estar entre {minimum} y {maximum}")
    return value


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name, "true" if default else "false").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} debe ser true o false")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    model_dir: Path
    ollama_url: str
    model: str
    context_length: int
    max_source_chars: int
    allowed_source_hosts: tuple[str, ...]
    tts_voice: str
    ffmpeg_threads: int
    music_enabled: bool
    music_volume: float
    log_level: str

    @classmethod
    def from_env(cls) -> Settings:
        hosts = tuple(
            host.strip().lower().rstrip(".")
            for host in os.getenv(
                "ASTRO_ALLOWED_SOURCE_HOSTS",
                "nasa.gov,esa.int,eso.org,jpl.nasa.gov,science.nasa.gov,arxiv.org",
            ).split(",")
            if host.strip()
        )
        if not hosts:
            raise RuntimeError("ASTRO_ALLOWED_SOURCE_HOSTS no puede estar vacío")

        return cls(
            data_dir=Path(os.getenv("ASTRO_DATA_DIR", "/data")).resolve(),
            model_dir=Path(os.getenv("ASTRO_MODEL_DIR", "/models")).resolve(),
            ollama_url=os.getenv("ASTRO_OLLAMA_URL", "http://ollama:11434").rstrip("/"),
            model=os.getenv("ASTRO_MODEL", "qwen3.5:4b-q4_K_M"),
            context_length=_positive_int("ASTRO_CONTEXT_LENGTH", 6144),
            max_source_chars=_positive_int("ASTRO_MAX_SOURCE_CHARS", 9000),
            allowed_source_hosts=hosts,
            tts_voice=os.getenv("ASTRO_TTS_VOICE", "es_ES-davefx-medium"),
            ffmpeg_threads=_positive_int("ASTRO_FFMPEG_THREADS", 4),
            music_enabled=_boolean("ASTRO_MUSIC_ENABLED", True),
            music_volume=_bounded_float("ASTRO_MUSIC_VOLUME", 0.14, 0.0, 0.3),
            log_level=os.getenv("ASTRO_LOG_LEVEL", "INFO").upper(),
        )

    @property
    def database_path(self) -> Path:
        return self.data_dir / "factory.sqlite3"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)


settings = Settings.from_env()
