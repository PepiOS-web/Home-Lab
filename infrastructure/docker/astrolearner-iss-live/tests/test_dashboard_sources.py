import asyncio
from datetime import datetime, timezone
import io
import json
import threading

import httpx
from PIL import Image
import pytest

from app import dashboard_sources as sources


NOW = datetime(2026, 10, 23, 16, 40, tzinfo=timezone.utc)


def image_bytes():
    output = io.BytesIO()
    Image.new("RGB", (1024, 1024), "#1c5483").save(output, "JPEG")
    return output.getvalue()


def install_http(monkeypatch, handler):
    original = httpx.AsyncClient
    options = []

    def factory(**kwargs):
        options.append(kwargs.copy())
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(sources.httpx, "AsyncClient", factory)
    return options


def routes():
    moon, _ = sources.moon_url(NOW)
    earth = "https://epic.gsfc.nasa.gov/archive/natural/2026/10/22/jpg/epic_1b_20261022200000.jpg"
    aurora_path = "/images/animations/ovation/north/aurora_N_2026-10-23_1630.jpg"
    return {
        sources.SUN_URL: httpx.Response(200, headers={"content-type": "image/jpeg", "last-modified": "Fri, 23 Oct 2026 16:00:00 GMT"}, content=image_bytes()),
        sources.EARTH_METADATA_URL: httpx.Response(200, json=[
            {"date": "2026-10-22 18:00:00", "image": "epic_1b_20261022180000"},
            {"date": "2026-10-22 20:00:00", "image": "epic_1b_20261022200000"},
        ]),
        earth: httpx.Response(200, headers={"content-type": "image/jpeg"}, content=image_bytes()),
        moon: httpx.Response(200, headers={"content-type": "image/jpeg"}, content=image_bytes()),
        sources.AURORA_METADATA_URL: httpx.Response(200, json=[{"url": aurora_path, "time_tag": "2026-10-23T16:30:00Z"}]),
        "https://services.swpc.noaa.gov" + aurora_path: httpx.Response(200, headers={"content-type": "image/jpeg"}, content=image_bytes()),
    }


@pytest.fixture(autouse=True)
def fixed_date(monkeypatch):
    monkeypatch.setattr(sources, "_utcnow", lambda: NOW)


def test_official_images_have_real_dates_downsampled_and_no_environment_auth(monkeypatch, tmp_path):
    payloads, visited = routes(), []

    def handler(request):
        visited.append(str(request.url))
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        return payloads[str(request.url)]

    options = install_http(monkeypatch, handler)
    worker = sources.DashboardSources(tmp_path, threading.Event())
    asyncio.run(worker._refresh_due())
    cards = {card.key: card for card in worker.snapshot()}
    assert len(visited) == 6
    assert all(sources.allowed_url(url) for url in visited)
    assert options[0]["follow_redirects"] is False and options[0]["trust_env"] is False
    assert all(card.state == "available" and card.image for card in cards.values())
    assert cards["sun"].observed_at is None  # Last-Modified isn't an observation.
    assert cards["earth"].observed_at == "2026-10-22T20:00:00+00:00"
    assert cards["moon"].observed_at == "2026-10-23T16:00:00+00:00"
    assert "modelo" in cards["moon"].credit
    assert cards["aurora"].observed_at == "2026-10-23T16:30:00+00:00"
    for card in cards.values():
        with Image.open(io.BytesIO(card.image)) as image:
            assert image.size == (512, 512) and image.format == "JPEG"
    assert len(list(tmp_path.glob("*.jpg"))) == 4
    assert len(list(tmp_path.glob("*.json"))) == 4
    asyncio.run(worker._refresh_due())
    assert len(visited) == 6  # Never poll at render/frame rate.


def test_network_failure_keeps_original_image_and_date_and_cache(monkeypatch, tmp_path):
    payloads, fail = routes(), {"value": False}
    install_http(monkeypatch, lambda request: httpx.Response(503) if fail["value"] else payloads[str(request.url)])
    worker = sources.DashboardSources(tmp_path, threading.Event())
    asyncio.run(worker._refresh_due())
    original = worker.snapshot()
    metadata_before = {path.name: path.read_bytes() for path in tmp_path.glob("*.json")}
    fail["value"] = True
    worker._attempted = {key: -float("inf") for key in sources.KEYS}
    asyncio.run(worker._refresh_due())
    for old, new in zip(original, worker.snapshot()):
        assert new.state == "stale"
        assert old.image == new.image and old.observed_at == new.observed_at
    assert metadata_before == {path.name: path.read_bytes() for path in tmp_path.glob("*.json")}
    restarted = sources.DashboardSources(tmp_path, threading.Event())
    for old, loaded in zip(original, restarted.snapshot()):
        assert loaded.state == "stale" and loaded.observed_at == old.observed_at
        assert loaded.image


@pytest.mark.parametrize("url", [
    "http://sdo.gsfc.nasa.gov/assets/img/latest/latest_1024_0304.jpg",
    sources.SUN_URL + "?api_key=SECRET", sources.SUN_URL + "#fragment",
    sources.SUN_URL.replace("https://", "https://user:SECRET@"),
    sources.SUN_URL.replace("nasa.gov/", "nasa.gov:443/"),
    sources.SUN_URL.replace("sdo.gsfc.nasa.gov", "sdo.gsfc.nasa.gov.evil.invalid"),
    "https://127.0.0.1/secret", "https://services.swpc.noaa.gov/images/../../secret.png",
    "https://services.swpc.noaa.gov/images/animations/ovation/north/../../secret.jpg",
    sources.MOON_PREFIX + "moon.0000.jpg", sources.MOON_PREFIX + "moon.8761.jpg",
    sources.MOON_PREFIX + "moon.1234.jpg?x=1", sources.MOON_PREFIX + "../moon.1234.jpg",
])
def test_url_allowlist_rejects_other_paths_auth_queries_and_redirect_targets(url):
    assert not sources.allowed_url(url)


def test_untrusted_metadata_can_never_supply_remote_or_private_urls(monkeypatch, tmp_path):
    payloads, visited = routes(), []
    payloads[sources.EARTH_METADATA_URL] = httpx.Response(200, json=[{"date": "2026-10-23 12:00:00", "image": "../../SECRET"}])
    payloads[sources.AURORA_METADATA_URL] = httpx.Response(200, json=[
        {"time_tag": "2026-10-23T16:30:00Z", "url": "https://evil.invalid/image.jpg"},
        {"time_tag": "2026-10-23T16:30:00Z", "url": "/images/animations/ovation/north/../../secret.jpg"},
    ])

    def handler(request):
        visited.append(str(request.url))
        return payloads[str(request.url)]

    install_http(monkeypatch, handler)
    worker = sources.DashboardSources(tmp_path, threading.Event())
    asyncio.run(worker._refresh_due())
    cards = {card.key: card for card in worker.snapshot()}
    assert len(visited) == 4 and all("SECRET" not in url and "evil" not in url for url in visited)
    assert cards["earth"].state == "unavailable" and cards["aurora"].state == "unavailable"


@pytest.mark.parametrize("response", [
    httpx.Response(302, headers={"location": "http://127.0.0.1/private"}),
    httpx.Response(200, headers={"content-type": "text/html"}, content=b"SECRET"),
    httpx.Response(200, headers={"content-type": "image/jpeg", "content-length": str(sources.MAX_IMAGE_BYTES + 1)}, content=b"x"),
    httpx.Response(200, headers={"content-type": "image/jpeg"}, content=b"x" * (sources.MAX_IMAGE_BYTES + 1)),
])
def test_bad_image_responses_fail_closed_without_following(monkeypatch, tmp_path, response):
    visited = []

    def handler(request):
        visited.append(str(request.url))
        return response

    install_http(monkeypatch, handler)
    worker = sources.DashboardSources(tmp_path, threading.Event())
    asyncio.run(worker._refresh_due())
    assert all(card.state == "unavailable" and card.image is None for card in worker.snapshot())
    assert len(visited) == 4  # No extra image/redirect requests after bad metadata.


def test_invalid_image_and_oversized_geometry_are_rejected():
    with pytest.raises(sources.SourceError, match="image_invalid"):
        sources._thumbnail(b"not an image")
    output = io.BytesIO()
    Image.new("1", (5000, 4000)).save(output, "PNG")
    with pytest.raises(sources.SourceError, match="image_format"):
        sources._thumbnail(output.getvalue())


def test_moon_is_current_hour_numbered_from_one_and_not_reused_next_year(monkeypatch, tmp_path):
    first = datetime(2026, 1, 1, tzinfo=timezone.utc)
    last = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)
    assert sources.moon_url(first)[0].endswith("moon.0001.jpg")
    assert sources.moon_url(last)[0].endswith("moon.8760.jpg")
    with pytest.raises(sources.SourceError, match="moon_year_unavailable"):
        sources.moon_url(datetime(2027, 1, 1, tzinfo=timezone.utc))
    worker = sources.DashboardSources(tmp_path, threading.Event())
    worker._cards["moon"] = sources.SpaceCard("moon", image_bytes(), NOW.isoformat())
    monkeypatch.setattr(sources, "_utcnow", lambda: datetime(2027, 1, 1, tzinfo=timezone.utc))
    card = worker.snapshot()[2]
    assert card.state == "unavailable" and card.image is None


def test_old_product_dates_are_labelled_stale_even_after_successful_download(monkeypatch, tmp_path):
    payloads = routes()
    payloads[sources.SUN_URL].headers["last-modified"] = "Thu, 22 Oct 2026 00:00:00 GMT"
    install_http(monkeypatch, lambda request: payloads[str(request.url)])
    worker = sources.DashboardSources(tmp_path, threading.Event())
    asyncio.run(worker._refresh_due())
    assert worker.snapshot()[0].state == "stale" and worker.snapshot()[0].observed_at is None


def test_stopped_worker_does_not_fetch(monkeypatch, tmp_path):
    handler = lambda request: pytest.fail("No network after stop")
    install_http(monkeypatch, handler)
    stop = threading.Event()
    stop.set()
    worker = sources.DashboardSources(tmp_path, stop)
    asyncio.run(worker._refresh_due())
    worker.run()
    assert all(card.image is None for card in worker.snapshot())


def test_request_deadline_cancels_slow_http_response(monkeypatch, tmp_path):
    cancelled = []

    async def handler(request):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    install_http(monkeypatch, handler)
    monkeypatch.setattr(sources, "REQUEST_TIMEOUT_SECONDS", 0.01)
    worker = sources.DashboardSources(tmp_path, threading.Event())
    asyncio.run(worker._refresh_due())
    assert len(cancelled) == 4
    assert all(card.state == "unavailable" for card in worker.snapshot())


def test_cache_integrity_and_bounded_metadata_fail_closed(tmp_path):
    (tmp_path / "earth.jpg").write_bytes(image_bytes())
    (tmp_path / "earth.json").write_text(json.dumps({"version": 1, "key": "earth", "sha256": "invalid"}))
    worker = sources.DashboardSources(tmp_path, threading.Event())
    assert worker.snapshot()[1].image is None


def test_poll_intervals_do_not_reload_images_faster_than_five_minutes():
    assert sources.POLL_SECONDS >= 300
    assert min(sources.INTERVALS.values()) >= 300
    assert sources.INTERVALS["sun"] >= 900
    assert sources.INTERVALS["moon"] >= 3600
    assert sources.REFRESH_TIMEOUT_SECONDS <= 50
