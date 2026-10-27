from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    dry_run: bool = field(default_factory=lambda: _bool("ISS_LIVE_DRY_RUN", True))
    auto_start: bool = field(
        default_factory=lambda: _bool("ISS_LIVE_AUTO_START", False)
    )
    use_nasa_playlist: bool = field(
        default_factory=lambda: _bool("ISS_LIVE_USE_NASA_PLAYLIST", True)
    )
    privacy: str = field(
        default_factory=lambda: os.getenv("ISS_LIVE_PRIVACY", "unlisted")
    )
    control_token: str = field(
        default_factory=lambda: os.getenv("ISS_LIVE_CONTROL_TOKEN", "").strip()
    )
    block_seconds: int = field(
        default_factory=lambda: int(os.getenv("ISS_LIVE_BLOCK_SECONDS", "39000"))
    )
    gap_seconds: int = field(
        default_factory=lambda: int(os.getenv("ISS_LIVE_GAP_SECONDS", "90"))
    )
    max_blocks: int = field(
        default_factory=lambda: int(os.getenv("ISS_LIVE_MAX_BLOCKS", "0"))
    )
    map_seconds: int = field(
        default_factory=lambda: int(os.getenv("ISS_LIVE_MAP_SECONDS", "120"))
    )
    map_interval_seconds: int = field(
        default_factory=lambda: int(os.getenv("ISS_LIVE_MAP_INTERVAL_SECONDS", "600"))
    )
    source_url: str = field(
        default_factory=lambda: os.getenv("ISS_LIVE_SOURCE_URL", "").strip()
    )
    camera_enabled: bool = field(
        default_factory=lambda: _bool("ISS_LIVE_CAMERA_ENABLED", False)
    )
    camera_url: str = field(
        default_factory=lambda: os.getenv("ISS_LIVE_CAMERA_URL", "")
    )
    camera_authorized: bool = field(
        default_factory=lambda: _bool("ISS_LIVE_CAMERA_AUTHORIZED", False)
    )
    camera_mode: str = field(
        default_factory=lambda: os.getenv("ISS_LIVE_CAMERA_MODE", "auto").strip().lower()
    )
    camera_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("ISS_LIVE_CAMERA_TIMEOUT_SECONDS", "8"))
    )
    camera_stable_seconds: float = field(
        default_factory=lambda: float(os.getenv("ISS_LIVE_CAMERA_STABLE_SECONDS", "15"))
    )
    camera_retry_seconds: float = field(
        default_factory=lambda: float(os.getenv("ISS_LIVE_CAMERA_RETRY_SECONDS", "30"))
    )
    source_label: str = field(
        default_factory=lambda: os.getenv(
            "ISS_LIVE_SOURCE_LABEL", "NASA Space Station Views"
        )
    )
    position_url: str = field(
        default_factory=lambda: os.getenv(
            "ISS_LIVE_POSITION_URL", "https://api.wheretheiss.at/v1/satellites/25544"
        )
    )
    width: int = field(default_factory=lambda: int(os.getenv("ISS_LIVE_WIDTH", "1280")))
    height: int = field(
        default_factory=lambda: int(os.getenv("ISS_LIVE_HEIGHT", "720"))
    )
    fps: int = field(default_factory=lambda: int(os.getenv("ISS_LIVE_FPS", "12")))
    encoder: str = field(
        default_factory=lambda: os.getenv("ISS_LIVE_ENCODER", "libx264").strip()
    )
    video_bitrate: str = field(
        default_factory=lambda: os.getenv("ISS_LIVE_VIDEO_BITRATE", "4500k")
    )
    video_buffer_size: str = field(
        default_factory=lambda: os.getenv("ISS_LIVE_VIDEO_BUFSIZE", "9000k")
    )
    audio_bitrate: str = field(
        default_factory=lambda: os.getenv("ISS_LIVE_AUDIO_BITRATE", "128k")
    )
    music_volume: float = field(
        default_factory=lambda: float(os.getenv("ISS_LIVE_MUSIC_VOLUME", "4"))
    )
    youtube_client_secret: Path = field(
        default_factory=lambda: Path(
            os.getenv(
                "ISS_LIVE_YOUTUBE_CLIENT_SECRET",
                "/run/secrets/youtube-client-secret.json",
            )
        )
    )
    youtube_token: Path = field(
        default_factory=lambda: Path(
            os.getenv("ISS_LIVE_YOUTUBE_TOKEN", "/data/secrets/youtube-token.json")
        )
    )
    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("ISS_LIVE_DATA_DIR", "/data"))
    )
    status_dir: Path = field(
        default_factory=lambda: Path(os.getenv("ISS_LIVE_STATUS_DIR", "/status"))
    )
    nasa_playlist: Path = field(
        default_factory=lambda: Path(
            os.getenv(
                "ISS_LIVE_NASA_PLAYLIST",
                "/data/nasa/videos/playlist.ffconcat",
            )
        )
    )
    nasa_loop_video: Path = field(
        default_factory=lambda: Path(
            os.getenv(
                "ISS_LIVE_NASA_LOOP_VIDEO",
                "/data/nasa/videos/astrolearner-nasa-loop.mp4",
            )
        )
    )

    def validate(self) -> None:
        if self.privacy not in {"private", "unlisted", "public"}:
            raise ValueError("ISS_LIVE_PRIVACY must be private, unlisted or public")
        if self.control_token and len(self.control_token) < 32:
            raise ValueError("ISS_LIVE_CONTROL_TOKEN must contain at least 32 characters")
        if self.dry_run and self.auto_start:
            raise ValueError("ISS_LIVE_AUTO_START cannot be enabled during dry-run")
        if not 60 <= self.block_seconds < 43_200:
            raise ValueError("ISS_LIVE_BLOCK_SECONDS must be between 60 and 43199")
        if not 30 <= self.gap_seconds <= 900:
            raise ValueError("ISS_LIVE_GAP_SECONDS must be between 30 and 900")
        if self.max_blocks < 0:
            raise ValueError("ISS_LIVE_MAX_BLOCKS must be zero or greater")
        if self.map_seconds >= self.map_interval_seconds:
            raise ValueError("map duration must be shorter than map interval")
        if not 0 <= self.music_volume <= 4:
            raise ValueError("ISS_LIVE_MUSIC_VOLUME must be between 0 and 4")
        if self.width % 2 or self.height % 2:
            raise ValueError("video dimensions must be even")
        if self.encoder not in {"libx264", "h264_vaapi"}:
            raise ValueError("ISS_LIVE_ENCODER must be libx264 or h264_vaapi")
        if self.source_url:
            parsed = urlparse(self.source_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("ISS_LIVE_SOURCE_URL must be a direct HTTP(S) URL")
            if parsed.hostname in {"youtube.com", "www.youtube.com", "youtu.be"}:
                raise ValueError(
                    "ISS_LIVE_SOURCE_URL must not be a YouTube watch-page URL"
                )
        if self.camera_mode not in {"auto", "fallback", "map"}:
            raise ValueError("ISS_LIVE_CAMERA_MODE must be auto, fallback or map")
        if self.camera_enabled and not (
            160 <= self.width <= 1920 and 90 <= self.height <= 1080 and 1 <= self.fps <= 30
        ):
            raise ValueError("Camera selector dimensions/FPS exceed the supported limits")
        for name, value, minimum, maximum in (
            ("TIMEOUT_SECONDS", self.camera_timeout_seconds, 2, 60),
            ("STABLE_SECONDS", self.camera_stable_seconds, 5, 120),
            ("RETRY_SECONDS", self.camera_retry_seconds, 5, 300),
        ):
            if not math.isfinite(value) or not minimum <= value <= maximum:
                raise ValueError(
                    f"ISS_LIVE_CAMERA_{name} must be finite and between {minimum} and {maximum}"
                )
        if self.camera_stable_seconds < self.camera_timeout_seconds:
            raise ValueError(
                "ISS_LIVE_CAMERA_STABLE_SECONDS must not be shorter than the camera timeout"
            )
        if self.camera_retry_seconds < self.camera_timeout_seconds:
            raise ValueError(
                "ISS_LIVE_CAMERA_RETRY_SECONDS must not be shorter than the camera timeout"
            )
        if self.camera_url:
            self._validate_camera_url()
        if (
            self.camera_enabled
            and self.camera_mode == "auto"
            and self.camera_url
            and not self.camera_authorized
        ):
            raise ValueError(
                "Set ISS_LIVE_CAMERA_AUTHORIZED=true only after confirming permission to receive and retransmit the camera source"
            )

    def _validate_camera_url(self) -> None:
        # A signed input URL may contain a secret: never include it in diagnostics.
        message = "ISS_LIVE_CAMERA_URL must be a direct HTTP(S) URL without credentials, whitespace, control characters or fragments"
        if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in self.camera_url):
            raise ValueError(message)
        try:
            parsed = urlparse(self.camera_url)
            hostname = parsed.hostname
            # Accessing port also rejects malformed or out-of-range ports.
            parsed.port
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or not hostname
                or parsed.username is not None
                or parsed.password is not None
                or "#" in self.camera_url
                or "\\" in parsed.netloc
                or "%" in hostname
            ):
                raise ValueError(message)
        except ValueError:
            raise ValueError(message) from None
        hostname = hostname.lower().rstrip(".")
        for blocked_host in (
            "youtube.com", "youtu.be", "youtube-nocookie.com", "googlevideo.com"
        ):
            if hostname == blocked_host or hostname.endswith("." + blocked_host):
                raise ValueError(
                    "ISS_LIVE_CAMERA_URL must not be a YouTube page or an extracted YouTube delivery URL; use an authorized direct camera source"
                )
