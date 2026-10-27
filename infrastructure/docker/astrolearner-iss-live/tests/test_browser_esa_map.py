import asyncio
import base64
from datetime import datetime, timezone
import inspect
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import browser_esa_map
from app.browser_esa_map import (
    ESA_MAP_URL, HIDE_MAP, SHOW_MAP, MapReadinessGate, is_esa_origin,
    monitor_esa_map, parse_esa_gmt, valid_map_dom,
)

UTC_NOW = datetime(2026, 10, 14, 17, 57, 15, tzinfo=timezone.utc).timestamp()


def state(gmt="14 Oct 2026, 17:57:15", **changes):
    return dict(url=ESA_MAP_URL, title="ESA ISS Tracker", canvas_width=625,
                canvas_height=313, canvas_visible=True, logo_loaded=True,
                cover_visible=False, error_visible=False,
                telemetry=["38,0 N", "82,0 W", "426 km", "27572 km/h"],
                gmt=gmt, **changes)


def test_gmt_parse_is_explicit_utc_and_independent_of_locale():
    assert parse_esa_gmt("14 Oct 2026, 17:57:15") == UTC_NOW
    assert parse_esa_gmt(" 14 Oct 2026,17:57:15 ") == UTC_NOW
    assert parse_esa_gmt("14\u00a0Oct\u00a02026,\u00a017:57:15") == UTC_NOW
    assert parse_esa_gmt("1 Jan 2026, 00:00:00") == datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()


@pytest.mark.parametrize("value", [None, 1, "", "-", "14 oct 2026, 17:57:15", "31 Feb 2026, 17:57:15",
                                  "14 Oct 2026, 25:57:15", "14 Oct 2026, 17:57:15 UTC", "x" * 65])
def test_invalid_clock_labels_are_rejected(value):
    assert parse_esa_gmt(value) is None


@pytest.mark.parametrize("url", [ESA_MAP_URL, ESA_MAP_URL + "?v=1", "https://isstracker.spaceflight.esa.int:443/"])
def test_only_official_https_origin_is_allowed(url):
    assert is_esa_origin(url)


@pytest.mark.parametrize("url", [None, "", "http://isstracker.spaceflight.esa.int/", "https://evil.invalid/",
    "https://isstracker.spaceflight.esa.int.evil.invalid/", "https://isstracker.spaceflight.esa.int@evil.invalid/",
    "https://user@isstracker.spaceflight.esa.int/", "https://isstracker.spaceflight.esa.int:8090/",
    "https://isstracker.spaceflight.esa.int:bad/", " https://isstracker.spaceflight.esa.int/",
    "https://isstracker.spaceflight.esa.int/\n", "https://isstracker.spaceflight.esa.int\\@evil.invalid/"])
def test_wrong_origin_redirects_and_ambiguous_urls_fail_closed(url):
    assert not is_esa_origin(url)


@pytest.mark.parametrize("change", [
    {"url": "https://evil.invalid/"}, {"title": "Error"}, {"canvas_width": 0},
    {"canvas_height": 0}, {"canvas_visible": False}, {"logo_loaded": False},
    {"cover_visible": True}, {"error_visible": True}, {"telemetry": []},
    {"telemetry": ["-", "82 W", "426 km", "27000 km/h"]},
    {"telemetry": ["38 N", "", "426 km", "27000 km/h"]},
    {"telemetry": ["38 N", "82 W", None, "27000 km/h"]},
    {"telemetry": ["38 N", "82 W", "NaN km", "27000 km/h"]},
])
def test_loading_covers_http_200_error_screens_and_missing_telemetry_are_not_ready(change):
    sample = state()
    sample.update(change)
    assert not valid_map_dom(sample)


def test_gate_needs_observed_clock_progress_and_expires_frozen_clock():
    gate = MapReadinessGate()
    assert not gate.observe(state(), 0, UTC_NOW)
    assert not gate.observe(state(), 4, UTC_NOW + 4)
    assert gate.observe(state("14 Oct 2026, 17:57:20"), 5, UTC_NOW + 5)
    assert gate.observe(state("14 Oct 2026, 17:57:20"), 20, UTC_NOW + 20)
    assert not gate.observe(state("14 Oct 2026, 17:57:20"), 20.1, UTC_NOW + 20.1)


def test_clock_reversal_resets_progress_before_recovery():
    gate = MapReadinessGate()
    assert not gate.observe(state(), 0, UTC_NOW)
    assert gate.observe(state("14 Oct 2026, 17:57:20"), 5, UTC_NOW + 5)
    assert not gate.observe(state(), 6, UTC_NOW + 6)
    assert not gate.observe(state(), 7, UTC_NOW + 7)
    assert gate.observe(state("14 Oct 2026, 17:57:20"), 10, UTC_NOW + 10)


@pytest.mark.parametrize("offset", [-121, 121, float("nan"), float("inf")])
def test_advancing_but_incorrect_real_world_clock_is_rejected(offset):
    gate = MapReadinessGate()
    gate.observe(state(), 0, UTC_NOW)
    assert not gate.observe(state("14 Oct 2026, 17:57:20"), 5, UTC_NOW + 5 + offset)


def test_invalid_dom_clears_previous_progress():
    gate = MapReadinessGate()
    gate.observe(state(), 0, UTC_NOW)
    assert gate.observe(state("14 Oct 2026, 17:57:20"), 5, UTC_NOW + 5)
    invalid = state("14 Oct 2026, 17:57:25")
    invalid["error_visible"] = True
    assert not gate.observe(invalid, 10, UTC_NOW + 10)
    assert not gate.observe(state("14 Oct 2026, 17:57:25"), 11, UTC_NOW + 11)
    assert gate.observe(state("14 Oct 2026, 17:57:30"), 15, UTC_NOW + 15)


def test_reversed_monotonic_clock_requires_new_baseline():
    gate = MapReadinessGate()
    gate.observe(state(), 10, UTC_NOW)
    assert gate.observe(state("14 Oct 2026, 17:57:20"), 15, UTC_NOW + 5)
    assert not gate.observe(state("14 Oct 2026, 17:57:25"), 14, UTC_NOW + 10)


def environment():
    jpeg = b"\xff\xd8map\xff\xd9"
    session = SimpleNamespace(send=AsyncMock(return_value={"data": base64.b64encode(jpeg).decode()}),
                              detach=AsyncMock())
    page = SimpleNamespace(url=ESA_MAP_URL, set_viewport_size=AsyncMock(), goto=AsyncMock(),
                           evaluate=AsyncMock(return_value=state()), close=AsyncMock())
    context = SimpleNamespace(new_page=AsyncMock(return_value=page), new_cdp_session=AsyncMock(return_value=session))
    output = SimpleNamespace(evaluate=AsyncMock(return_value=True))
    return context, page, session, output, jpeg


def test_monitor_reuses_browser_context_and_only_transfers_bounded_jpeg(monkeypatch):
    context, page, session, output, jpeg = environment()
    stop, statuses = threading.Event(), []
    monkeypatch.setattr(browser_esa_map.MapReadinessGate, "observe", lambda *_args: True)

    async def output_evaluate(script, argument=None):
        if script == SHOW_MAP:
            assert base64.b64decode(argument) == jpeg
            stop.set()
        return True

    output.evaluate.side_effect = output_evaluate
    asyncio.run(monitor_esa_map(context, output, statuses.append, stop))
    context.new_page.assert_awaited_once()
    page.set_viewport_size.assert_awaited_once_with({"width": 625, "height": 365})
    page.goto.assert_awaited_once_with(ESA_MAP_URL, wait_until="domcontentloaded", timeout=20000)
    context.new_cdp_session.assert_awaited_once_with(page)
    assert True in statuses and statuses[-1] is False
    assert output.evaluate.await_args_list[-1].args == (HIDE_MAP,)
    session.detach.assert_awaited_once()
    page.close.assert_awaited_once()


@pytest.mark.parametrize("failure", ["redirect", "navigation", "dom", "snapshot", "output"])
def test_monitor_failure_is_private_hides_overlay_and_never_escapes(monkeypatch, capsys, failure):
    context, page, session, output, _jpeg = environment()
    stop, statuses = threading.Event(), []
    error = RuntimeError("SECRET https://private.invalid/")
    if failure == "redirect":
        page.url = "https://evil.invalid/"
    elif failure == "navigation":
        page.goto.side_effect = error
    elif failure == "dom":
        page.evaluate.side_effect = error
    elif failure == "snapshot":
        session.send.side_effect = error
    else:
        async def output_evaluate(script, *_args):
            if script == SHOW_MAP:
                raise error
            return True
        output.evaluate.side_effect = output_evaluate
    monkeypatch.setattr(browser_esa_map.MapReadinessGate, "observe", lambda *_args: True)

    async def retry_stop(_stop, seconds):
        assert seconds == 30
        stop.set()

    monkeypatch.setattr(browser_esa_map, "_wait_with_stop", retry_stop)
    asyncio.run(monitor_esa_map(context, output, statuses.append, stop))
    assert statuses and not any(statuses)
    assert output.evaluate.await_args_list[-1].args == (HIDE_MAP,)
    page.close.assert_awaited_once()
    if failure == "redirect":
        context.new_cdp_session.assert_not_awaited()
    assert capsys.readouterr() == ("", "")


def test_cancellation_propagates_after_bounded_cleanup(monkeypatch):
    context, page, session, output, _jpeg = environment()
    page.evaluate.side_effect = asyncio.CancelledError()
    statuses = []
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(monitor_esa_map(context, output, statuses.append, threading.Event()))
    assert statuses[-1] is False
    session.detach.assert_awaited_once()
    page.close.assert_awaited_once()


def test_redirect_during_snapshot_never_reaches_the_output_page(monkeypatch):
    context, page, session, output, _jpeg = environment()
    stop, statuses = threading.Event(), []
    monkeypatch.setattr(browser_esa_map.MapReadinessGate, "observe", lambda *_args: True)

    async def redirected_snapshot(_session):
        page.url = "https://evil.invalid/"
        return b"\xff\xd8map\xff\xd9"

    async def retry_stop(_stop, _seconds):
        stop.set()

    monkeypatch.setattr(browser_esa_map, "capture_jpeg", redirected_snapshot)
    monkeypatch.setattr(browser_esa_map, "_wait_with_stop", retry_stop)
    asyncio.run(monitor_esa_map(context, output, statuses.append, stop))
    assert all(call.args == (HIDE_MAP,) for call in output.evaluate.await_args_list)
    assert not any(statuses)


@pytest.mark.parametrize("jpeg", [b"not-jpeg", b"\xff\xd8" + b"x" * (2 * 1024 * 1024) + b"\xff\xd9"],
                         ids=["invalid", "oversized"])
def test_even_snapshot_helper_output_is_validated_before_transfer(monkeypatch, jpeg):
    context, _page, _session, output, _jpeg = environment()
    stop = threading.Event()
    monkeypatch.setattr(browser_esa_map.MapReadinessGate, "observe", lambda *_args: True)
    monkeypatch.setattr(browser_esa_map, "capture_jpeg", AsyncMock(return_value=jpeg))

    async def retry_stop(_stop, _seconds):
        stop.set()

    monkeypatch.setattr(browser_esa_map, "_wait_with_stop", retry_stop)
    asyncio.run(monitor_esa_map(context, output, lambda _ready: None, stop))
    assert all(call.args == (HIDE_MAP,) for call in output.evaluate.await_args_list)


def test_no_valid_map_for_60_seconds_reloads_after_30_second_retry(monkeypatch):
    context, _page, _session, output, _jpeg = environment()
    stop, waited = threading.Event(), []
    clock = [0.0]
    monkeypatch.setattr(browser_esa_map.MapReadinessGate, "observe", lambda *_args: False)
    monkeypatch.setattr(browser_esa_map.time, "monotonic", lambda: clock[0])

    async def fast_wait(_stop, seconds):
        waited.append(seconds)
        if seconds == 30:
            stop.set()
        else:
            clock[0] += 60.0

    monkeypatch.setattr(browser_esa_map, "_wait_with_stop", fast_wait)
    asyncio.run(monitor_esa_map(context, output, lambda _ready: None, stop))
    assert waited == [1.0, 30.0]
    assert context.new_page.await_count == 1
    assert all(call.args == (HIDE_MAP,) for call in output.evaluate.await_args_list)


def test_already_stopped_monitor_never_opens_provider():
    context, _page, _session, _output, _jpeg = environment()
    stop = threading.Event()
    stop.set()
    asyncio.run(monitor_esa_map(context, _output, lambda _ready: None, stop))
    context.new_page.assert_not_awaited()


def test_module_has_no_second_browser_launch_provider_rewrite_or_raw_logs():
    source = inspect.getsource(browser_esa_map)
    for forbidden in (".launch(", ".new_context(", "persistent_context", "storage_state", "print(",
                      "logging", "add_style_tag", "add_script_tag", "innerHTML =", "context.route("):
        assert forbidden not in source
    assert "#isst_map" in browser_esa_map.READ_MAP_STATE
    assert "#isst_tim" in browser_esa_map.READ_MAP_STATE
    assert "performance.now()" in SHOW_MAP
    assert SHOW_MAP.index("await image.decode()") < SHOW_MAP.index("wrapper.style.opacity = '1'")
    assert SHOW_MAP.index("window.esaMapSequence !== sequence") < SHOW_MAP.index("wrapper.style.opacity = '1'")
    assert "esaMapSequence" in HIDE_MAP
    assert "625x365" in browser_esa_map.__doc__
