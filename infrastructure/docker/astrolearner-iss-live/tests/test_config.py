from dataclasses import replace

import pytest
from app.config import Settings


@pytest.fixture(autouse=True)
def camera_environment(monkeypatch):
    for suffix in (
        "ENABLED", "URL", "AUTHORIZED", "MODE", "TIMEOUT_SECONDS", "STABLE_SECONDS",
        "RETRY_SECONDS",
    ):
        monkeypatch.delenv(f"ISS_LIVE_CAMERA_{suffix}", raising=False)


def test_safe_defaults(monkeypatch):
    monkeypatch.delenv("ISS_LIVE_DRY_RUN", raising=False)
    settings = Settings()
    assert settings.dry_run is True
    assert settings.block_seconds < 43_200
    assert settings.max_blocks == 0
    assert settings.camera_enabled is False
    assert settings.camera_url == ""
    assert settings.camera_authorized is False
    assert settings.camera_mode == "auto"
    assert settings.camera_timeout_seconds == 8
    assert settings.camera_stable_seconds == 15
    assert settings.camera_retry_seconds == 30
    settings.validate()


def test_rejects_twelve_hour_block(monkeypatch):
    monkeypatch.setenv("ISS_LIVE_BLOCK_SECONDS", "43200")
    settings = Settings()
    with pytest.raises(ValueError):
        settings.validate()


def test_rejects_negative_max_blocks(monkeypatch):
    monkeypatch.setenv("ISS_LIVE_MAX_BLOCKS", "-1")
    settings = Settings()
    with pytest.raises(ValueError):
        settings.validate()


@pytest.mark.parametrize("mode", ["auto", "fallback", "map"])
def test_camera_without_source_is_ready_for_fallback(mode):
    replace(Settings(), camera_enabled=True, camera_mode=mode).validate()


@pytest.mark.parametrize("mode", ["fallback", "map"])
def test_manual_camera_fallback_does_not_require_source_permission(mode):
    replace(
        Settings(), camera_enabled=True, camera_mode=mode,
        camera_url="https://camera.example/live/index.m3u8",
    ).validate()


def test_disabled_camera_does_not_require_source_permission():
    replace(Settings(), camera_url="https://camera.example/live/index.m3u8").validate()


def test_camera_auto_requires_explicit_operator_permission():
    settings = replace(
        Settings(), camera_enabled=True,
        camera_url="https://camera.example/live/index.m3u8?token=do-not-print",
    )
    with pytest.raises(ValueError, match="ISS_LIVE_CAMERA_AUTHORIZED") as exc:
        settings.validate()
    assert "do-not-print" not in str(exc.value)
    replace(settings, camera_authorized=True).validate()


def test_reads_camera_environment(monkeypatch):
    for name, value in {
        "ENABLED": "true", "URL": "https://camera.example/live/index.m3u8",
        "AUTHORIZED": "yes", "MODE": " AUTO ", "TIMEOUT_SECONDS": "10",
        "STABLE_SECONDS": "20", "RETRY_SECONDS": "40",
    }.items():
        monkeypatch.setenv(f"ISS_LIVE_CAMERA_{name}", value)
    settings = Settings()
    settings.validate()
    assert settings.camera_enabled is True
    assert settings.camera_authorized is True
    assert settings.camera_mode == "auto"
    assert settings.camera_timeout_seconds == 10
    assert settings.camera_stable_seconds == 20
    assert settings.camera_retry_seconds == 40


@pytest.mark.parametrize("url", [
    "https://camera.example/live/index.m3u8?token=private-test-token",
    "http://127.0.0.1:8891/synthetic.m3u8",
    "http://localhost:8891/live",
    "http://[::1]:8891/live",
    "HTTPS://camera.example/live/index.m3u8",
])
def test_accepts_authorized_direct_camera_urls(url):
    replace(
        Settings(), camera_enabled=True, camera_authorized=True, camera_url=url,
    ).validate()


@pytest.mark.parametrize("url", [
    "file:///private/camera", "ftp://camera.example/live", "rtsp://camera.example/live",
    "https:///no-host", "https://", "camera.example/live.m3u8",
    "https://user:private-test-token@camera.example/live.m3u8",
    "https://user@camera.example/live.m3u8",
    "https://camera.example/live.m3u8#fragment", "https://camera.example/live.m3u8#",
    "https://camera.example:invalid/live.m3u8", "https://camera.example:65536/live.m3u8",
    "https://camera.example:-1/live.m3u8", "https://[invalid]/live.m3u8",
    "https://camera.example/live\n.m3u8", "\rhttps://camera.example/live.m3u8",
    "https://camera.example/live.m3u8\t", "https://camera.example/live\x00.m3u8",
    "https://camera.example/live\x7f.m3u8", "https://camera.example/live .m3u8",
    "https://camera%2eexample/live.m3u8", "https://camera.example\\evil/live.m3u8",
])
def test_rejects_malformed_camera_urls_without_exposing_them(url):
    with pytest.raises(ValueError, match="ISS_LIVE_CAMERA_URL") as exc:
        replace(Settings(), camera_url=url).validate()
    assert url not in str(exc.value)
    assert "private-test-token" not in str(exc.value)


@pytest.mark.parametrize("host", [
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtube.com.",
    "youtu.be", "www.youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com",
    "googlevideo.com", "rr1.googlevideo.com", "RR1.GOOGLEVIDEO.COM",
])
def test_rejects_youtube_pages_and_extracted_delivery_urls(host):
    with pytest.raises(ValueError, match="authorized direct camera source") as exc:
        replace(
            Settings(), camera_url=f"https://{host}/live?token=private-test-token",
        ).validate()
    assert "private-test-token" not in str(exc.value)


@pytest.mark.parametrize("mode", ["", "youtube", "camera", "AUTO", "invalid"])
def test_rejects_invalid_camera_modes(mode):
    with pytest.raises(ValueError, match="ISS_LIVE_CAMERA_MODE"):
        replace(Settings(), camera_mode=mode).validate()


@pytest.mark.parametrize("field, value", [
    ("camera_timeout_seconds", 1.9), ("camera_timeout_seconds", 60.1),
    ("camera_stable_seconds", 4.9), ("camera_stable_seconds", 120.1),
    ("camera_retry_seconds", 4.9), ("camera_retry_seconds", 300.1),
])
def test_rejects_out_of_range_camera_timing(field, value):
    with pytest.raises(ValueError, match="ISS_LIVE_CAMERA_"):
        replace(Settings(), **{field: value}).validate()


@pytest.mark.parametrize("field", [
    "camera_timeout_seconds", "camera_stable_seconds", "camera_retry_seconds",
])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_rejects_nonfinite_camera_timing(field, value):
    with pytest.raises(ValueError, match="must be finite"):
        replace(Settings(), **{field: value}).validate()


@pytest.mark.parametrize("field", ["camera_stable_seconds", "camera_retry_seconds"])
def test_camera_stability_and_retry_cannot_be_shorter_than_timeout(field):
    with pytest.raises(ValueError, match="must not be shorter"):
        replace(Settings(), camera_timeout_seconds=10, **{field: 5}).validate()


def test_accepts_camera_timing_boundaries():
    replace(
        Settings(), camera_timeout_seconds=2, camera_stable_seconds=5,
        camera_retry_seconds=5,
    ).validate()
    replace(
        Settings(), camera_timeout_seconds=60, camera_stable_seconds=120,
        camera_retry_seconds=300,
    ).validate()
