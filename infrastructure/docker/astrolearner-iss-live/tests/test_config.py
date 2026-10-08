import pytest
from app.config import Settings


def test_safe_defaults(monkeypatch):
    monkeypatch.delenv("ISS_LIVE_DRY_RUN", raising=False)
    settings = Settings()
    assert settings.dry_run is True
    assert settings.block_seconds < 43_200
    assert settings.max_blocks == 0


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
