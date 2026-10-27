"""Renderer hangs must not leave a healthy-but-stale camera sidecar forever."""
import asyncio
import io
import json
import sys
import threading
import time
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.error import HTTPError
from urllib.request import urlopen

from PIL import Image
import pytest

from app import browser_camera as camera


def black_jpeg():
    output = io.BytesIO()
    Image.new("RGB", (160, 90), "black").save(output, "JPEG")
    return output.getvalue()


@pytest.fixture
def live_hub():
    hub, stop = camera.FrameHub(30), threading.Event()
    server = camera.make_server(camera.CaptureSettings(authorised=True, fps=30, port=0), hub, stop)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield hub, stop, f"http://127.0.0.1:{server.server_port}"
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def install_playwright(monkeypatch, driver):
    package, api = ModuleType("playwright"), ModuleType("playwright.async_api")
    api.async_playwright = Mock(return_value=SimpleNamespace(start=AsyncMock(return_value=driver)))
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.async_api", api)


def quick_deadlines(monkeypatch):
    for name in ("DRIVER_START_TIMEOUT_SECONDS", "LAUNCH_TIMEOUT_SECONDS", "SETUP_TIMEOUT_SECONDS",
                 "NAVIGATION_TIMEOUT_SECONDS", "PLAYER_STATE_TIMEOUT_SECONDS",
                 "BROWSER_CLOSE_TIMEOUT_SECONDS", "DRIVER_STOP_TIMEOUT_SECONDS"):
        monkeypatch.setattr(camera, name, 0.02)
    monkeypatch.setattr(camera, "RETRY_SECONDS", 0)


def fake_browser(*, stalled_stage=None, on_close=None, on_state=None):
    cancelled = []

    async def stuck(*_args, **_kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(stalled_stage)

    positions = {"count": 0}

    async def state(*_args, **_kwargs):
        positions["count"] += 1
        if on_state:
            on_state()
        return {"state": 1, "time": positions["count"], "error": 0}

    async def native(*_args, **_kwargs):
        return {"ready": 4, "paused": False, "decoded": positions["count"], "advertisement": False}

    frame = SimpleNamespace(url="https://www.youtube.com/embed/awQzjn72bI0",
                            evaluate=AsyncMock(side_effect=stuck if stalled_stage == "native_video" else native))
    page = SimpleNamespace(
        set_default_timeout=Mock(), frames=[frame],
        goto=AsyncMock(side_effect=stuck if stalled_stage == "navigation" else None),
        evaluate=AsyncMock(side_effect=stuck if stalled_stage == "player_state" else state),
    )
    context = SimpleNamespace(
        new_page=AsyncMock(side_effect=stuck if stalled_stage == "page" else None, return_value=page),
        new_cdp_session=AsyncMock(side_effect=stuck if stalled_stage == "session" else None,
                                  return_value=SimpleNamespace()),
    )
    browser = SimpleNamespace(
        new_context=AsyncMock(side_effect=stuck if stalled_stage == "context" else None, return_value=context),
        close=AsyncMock(side_effect=on_close),
    )
    return browser, stuck, cancelled


@pytest.mark.parametrize("stage", ["launch", "context", "page", "session", "navigation", "player_state", "native_video"])
def test_hung_operation_invalidates_camera_then_recovers_black_frames(monkeypatch, live_hub, stage, capsys):
    hub, stop, url = live_hub
    quick_deadlines(monkeypatch)
    # There was a usable image before the renderer/driver stopped responding.
    assert hub.publish(black_jpeg(), time.monotonic())
    broken, stuck, cancelled = fake_browser(stalled_stage=stage)
    recovered, _, _ = fake_browser()
    launches = []

    async def launch(**_kwargs):
        launches.append(True)
        if len(launches) == 1:
            return await stuck() if stage == "launch" else broken
        # The HTTP service remains alive, but never claims stale pixels ready.
        with urlopen(url + "/health", timeout=2) as response:
            status = json.load(response)
        assert status["ready"] is False
        assert status["error_stage"] == stage
        assert status["error_code"] == "operation_timeout"
        with pytest.raises(HTTPError) as error:
            urlopen(url + "/ready", timeout=2)
        assert error.value.code == 503
        return recovered

    driver = SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(side_effect=launch)), stop=AsyncMock())
    install_playwright(monkeypatch, driver)
    monkeypatch.setattr(camera, "capture_jpeg", AsyncMock(return_value=black_jpeg()))
    real_publish, ready_after_recovery = hub.publish, []

    def publish(payload, now):
        result = real_publish(payload, now)
        ready_after_recovery.append(hub.status()["ready"])
        stop.set()
        return result

    monkeypatch.setattr(hub, "publish", publish)
    asyncio.run(camera.capture(camera.CaptureSettings(authorised=True, fps=30), hub, stop))
    assert len(launches) == 2
    assert cancelled == [stage]
    assert ready_after_recovery == [True]  # Night-side black is not an outage.
    assert broken.close.await_count == (0 if stage == "launch" else 1)
    recovered.close.assert_awaited_once()
    driver.stop.assert_awaited_once()
    assert "operation_timeout" in capsys.readouterr().out


def test_hung_browser_cleanup_exits_instead_of_accumulating_browsers(monkeypatch, live_hub):
    hub, stop, _ = live_hub
    quick_deadlines(monkeypatch)
    cancelled_close = []

    async def stuck_close():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled_close.append(True)

    broken, _, _ = fake_browser(stalled_stage="player_state", on_close=stuck_close)
    driver = SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=broken)), stop=AsyncMock())
    install_playwright(monkeypatch, driver)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        asyncio.run(camera.capture(camera.CaptureSettings(authorised=True), hub, stop))
    driver.chromium.launch.assert_awaited_once()
    driver.stop.assert_awaited_once()
    assert cancelled_close == [True]
    assert hub.status()["ready"] is False
    assert hub.status()["error_stage"] == "shutdown"


def test_hung_driver_cleanup_is_bounded_and_fails_closed(monkeypatch, live_hub):
    hub, stop, _ = live_hub
    quick_deadlines(monkeypatch)
    healthy, _, _ = fake_browser(on_state=stop.set)
    cancelled_stop = []

    async def stuck_stop():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled_stop.append(True)

    driver = SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=healthy)),
                             stop=AsyncMock(side_effect=stuck_stop))
    install_playwright(monkeypatch, driver)
    with pytest.raises(RuntimeError, match="driver cleanup failed"):
        asyncio.run(camera.capture(camera.CaptureSettings(authorised=True), hub, stop))
    assert cancelled_stop == [True]
    healthy.close.assert_awaited_once()
    assert hub.status()["ready"] is False
    assert hub.status()["error_code"] == "operation_timeout"


def test_startup_timeout_is_sanitised_and_invalidates_source(monkeypatch, live_hub, capsys):
    hub, stop, _ = live_hub
    quick_deadlines(monkeypatch)
    package, api = ModuleType("playwright"), ModuleType("playwright.async_api")

    async def failed_start():
        raise TimeoutError("PRIVATE https://private.invalid/?key=SECRET")

    api.async_playwright = Mock(return_value=SimpleNamespace(start=failed_start))
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.async_api", api)
    with pytest.raises(RuntimeError, match="driver could not start") as error:
        asyncio.run(camera.capture(camera.CaptureSettings(authorised=True), hub, stop))
    assert hub.status()["error_stage"] == "driver"
    assert hub.status()["error_code"] == "operation_timeout"
    assert not hub.status()["ready"]
    assert "PRIVATE" not in str(error.value) + capsys.readouterr().out
