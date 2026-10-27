from datetime import datetime, timedelta, timezone
import io
from unittest.mock import Mock

from PIL import Image
import pytest

from app.stream_dashboard import (
    DEFAULT_SIZE, MAX_CARD_BYTES, SpaceCard, StreamDashboard, render_dashboard,
)

NOW = datetime(2026, 10, 23, 16, 24, 24, tzinfo=timezone.utc)


def state(**changes):
    result = dict(latitude=-38.8, longitude=66.7, altitude_km=427.6,
                velocity_kmh=27566.7, position_updated_at=NOW.isoformat(),
                video_mode="camera", music_playback_active=True,
                music_track="Amanecer orbital", last_progress_at=NOW.isoformat(),
                music_track_elapsed_seconds=91, music_track_duration_seconds=300)
    result.update(changes)
    return result


def image_bytes():
    buffer = io.BytesIO()
    with Image.new("RGB", (200, 200), "red") as image:
        image.save(buffer, "PNG")
    return buffer.getvalue()


def test_panel_is_small_bounded_and_never_claims_verified_live():
    frame = render_dashboard(state(), now=NOW)
    assert frame.source_label == "SEÑAL EXTERNA"
    assert frame.position_state == "fresh"
    assert frame.position_age_seconds == 0
    assert any("archivo" in line for line in frame.text_lines)
    assert "LIVE NOW" not in " ".join(frame.text_lines)
    assert "EN DIRECTO" not in " ".join(frame.text_lines)
    for payload, format_ in ((frame.png, "PNG"), (frame.jpeg, "JPEG")):
        with Image.open(io.BytesIO(payload)) as image:
            assert image.size == DEFAULT_SIZE and image.format == format_
        assert len(payload) < 300_000


def test_cache_ignores_private_and_high_frequency_fields_but_switches_immediately():
    dashboard = StreamDashboard()
    first = dashboard.render(state(), now=NOW)
    current = state()
    current.update(last_error="SECRET_TOKEN", youtube_watch_url="https://example/?key=SECRET",
                   ffmpeg_frame_count=10001, youtube_token="PRIVATE")
    second = dashboard.render(current, now=NOW + timedelta(milliseconds=100))
    assert second is first and dashboard.render_count == 1
    current["video_mode"] = "map"
    fallback = dashboard.render(current, now=NOW + timedelta(milliseconds=300))
    assert fallback is not first and fallback.source_label == "MAPA DE RESPALDO"
    assert "SECRET" not in " ".join(fallback.text_lines)
    assert dashboard.render_count == 2
    dashboard.render(current, now=NOW + timedelta(seconds=1))
    assert dashboard.render_count == 3


def test_position_staleness_and_unknown_position_are_honest():
    older = state()
    older["position_updated_at"] = (NOW - timedelta(seconds=90)).isoformat()
    frame = render_dashboard(older, now=NOW)
    assert frame.position_state == "stale" and frame.position_age_seconds == 90
    assert "ANTERIOR" in frame.text_lines
    assert "Posición hace 1 min" in frame.text_lines
    for key, bad in (("latitude", float("nan")), ("longitude", 181),
                     ("position_updated_at", (NOW + timedelta(seconds=31)).isoformat()),
                     ("position_updated_at", "2026-10-23T16:24:24")):
        current = state()
        current[key] = bad
        unavailable = render_dashboard(current, now=NOW)
        assert unavailable.position_state == "unavailable"
        assert "Posición no disponible" in unavailable.text_lines


def test_music_requires_recent_confirmed_progress():
    current = state()
    current["last_progress_at"] = (NOW - timedelta(seconds=13)).isoformat()
    frame = render_dashboard(current, now=NOW)
    assert "Reproducción sin confirmar" in frame.text_lines
    assert "Amanecer orbital" not in frame.text_lines
    current["last_progress_at"] = NOW.isoformat()
    assert "Amanecer orbital" in render_dashboard(current, now=NOW).text_lines


def test_disabled_does_not_load_or_render_maps(monkeypatch):
    from app import stream_dashboard
    loader = Mock(side_effect=AssertionError("must not draw"))
    monkeypatch.setattr(stream_dashboard, "_world_background", loader)
    dashboard = StreamDashboard(enabled=False)
    assert dashboard.render(state(), now=NOW) is None
    assert dashboard.render_count == 0
    loader.assert_not_called()


def test_optional_science_tiles_remain_dated_and_aurora_is_always_forecast():
    data = image_bytes()
    cards = (SpaceCard("sun", data, (NOW - timedelta(hours=5)).isoformat(), "stale", "NASA SDO"),
             SpaceCard("aurora", data, NOW.isoformat(), credit="NOAA SWPC"),
             SpaceCard("moon", data, "invalid", credit="NASA SVS"))
    frame = render_dashboard(state(), now=NOW, cards=cards)
    assert "PRONÓSTICO" in frame.text_lines
    assert "SOL: ANTERIOR · hace 5 h" in frame.text_lines
    assert "LUNA: SIN FECHA" in frame.text_lines
    assert "NASA SDO" in frame.text_lines or "ANTERIOR" in frame.text_lines
    assert "SIN FECHA" in frame.text_lines


def test_invalid_images_and_oversized_images_fail_closed_without_network():
    for bad in (b"not a picture", b"x" * (MAX_CARD_BYTES + 1)):
        frame = render_dashboard(state(), now=NOW,
                                 cards=(SpaceCard("sun", bad, NOW.isoformat()),))
        assert "SOL: NO DISPONIBLE" in frame.text_lines
        assert frame.png.startswith(b"\x89PNG")


def test_future_aurora_valid_time_is_forecast_not_fake_observation_age():
    future = NOW + timedelta(hours=1)
    frame = render_dashboard(state(), now=NOW, cards=(SpaceCard("aurora", image_bytes(), future.isoformat(), credit="NOAA SWPC"),))
    assert "VÁLIDO 17:24 UTC" in frame.text_lines
    assert "AURORAS: PRONÓSTICO VÁLIDO 23/10 17:24 UTC" in frame.text_lines
    assert not any(line.startswith("AURORAS:") and "hace 0" in line for line in frame.text_lines)


def test_future_forecast_is_bounded_and_other_images_still_reject_future_dates():
    data = image_bytes()
    too_far = NOW + timedelta(hours=6, seconds=1)
    frame = render_dashboard(state(), now=NOW, cards=(SpaceCard("aurora", data, too_far.isoformat()),))
    assert "AURORAS: SIN FECHA" in frame.text_lines
    frame = render_dashboard(state(), now=NOW, cards=(SpaceCard("sun", data, (NOW + timedelta(hours=1)).isoformat()),))
    assert "SOL: SIN FECHA" in frame.text_lines


@pytest.mark.parametrize("cards", [
    (SpaceCard("invalid"),), (SpaceCard("sun"), SpaceCard("sun")),
    tuple(SpaceCard("sun") for _ in range(5)),
])
def test_unknown_or_duplicate_tile_is_rejected(cards):
    with pytest.raises(ValueError):
        render_dashboard(state(), now=NOW, cards=cards)


@pytest.mark.parametrize("size", [(True, 144), (640, 1), (4000, 144), (1280, 1000)])
def test_unbounded_dimensions_are_rejected(size):
    with pytest.raises(ValueError):
        StreamDashboard(*size)


def test_map_bad_track_and_dateline_are_bounded():
    frame = render_dashboard(state(), now=NOW,
                             track=((0, 179), (0, -179), (True, 1), (None,), "bad"))
    assert frame.position_state == "fresh"


def test_utc_is_explicit_regardless_of_host_or_input_timezone():
    local = NOW.astimezone(timezone(timedelta(hours=2)))
    frame = render_dashboard(state(), now=local)
    assert any("16:24:24 UTC" in line for line in frame.text_lines)
    with pytest.raises(ValueError):
        render_dashboard(state(), now=NOW.replace(tzinfo=None))
