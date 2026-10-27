from datetime import datetime, timedelta, timezone
import io
import struct
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import asyncio
from collections import deque
import ast
import hashlib
from pathlib import Path
import re

from PIL import Image
import pytest

from app.corner_map import SIZE, position_state, render_corner_map
from app import browser_local_map as bridge
from app.browser_camera import CaptureSettings, FrameHub, player_page
from app.browser_camera_deployment import prepare_environment, values, deployment_ready

NOW = datetime(2026, 10, 15, 22, 0, tzinfo=timezone.utc)


def state(**changes):
    return {"latitude": 25.1, "longitude": 132.1, "altitude_km": 423.1,
            "velocity_kmh": 27575., "position_updated_at": NOW.isoformat(), **changes}


def test_card_is_png_at_display_resolution_and_marks_fresh_data():
    data, quality = render_corner_map(state(), ((24, 130), (25, 132)), NOW)
    assert quality == "fresh" and data.startswith(b"\x89PNG") and len(data) < bridge.MAX_PNG_BYTES
    with Image.open(io.BytesIO(data)) as image:
        assert image.size == SIZE and image.format == "PNG"
    old = state(position_updated_at=(NOW - timedelta(seconds=46)).isoformat())
    assert render_corner_map(old, now=NOW)[1] == "stale"
    assert render_corner_map({}, now=NOW)[1] == "unavailable"
    assert render_corner_map(old, now=NOW)[0] != data


def test_png_endpoint_uses_public_state_and_does_not_write_files(monkeypatch):
    from app import main
    snapshot = state(position_updated_at=datetime.now(timezone.utc).isoformat())
    monkeypatch.setattr(main, "store", SimpleNamespace(snapshot=lambda: snapshot))
    monkeypatch.setattr(main, "controller", SimpleNamespace(position_track=deque([(24, 130), (25, 132)])))
    response = main.corner_map()
    assert response.media_type == "image/png"
    assert response.headers["x-iss-position-state"] == "fresh"
    assert response.headers["cache-control"] == "no-store"
    assert len(response.body) < bridge.MAX_PNG_BYTES


@pytest.mark.parametrize("changes", [
    {"latitude": True}, {"latitude": float("nan")}, {"longitude": 181},
    {"latitude": -91}, {"position_updated_at": "not a date"},
    {"position_updated_at": "2026-10-15T22:00:00"},
    {"position_updated_at": (NOW + timedelta(seconds=31)).isoformat()},
])
def test_no_invented_or_future_position(changes):
    assert position_state(state(**changes), NOW) == "unavailable"


def test_bad_track_points_and_dateline_crossings_do_not_break_map():
    points = ((0, 179), (0, -179), (1, -178), (float("inf"), 0), (True, 1), (None,), "x")
    assert render_corner_map(state(), points, NOW)[1] == "fresh"


def test_only_fixed_internal_urls_are_allowed_and_direct_requests_ignore_proxy(monkeypatch):
    with pytest.raises(ValueError):
        bridge.read_map("https://evil.invalid/private?token=SECRET")
    data, _ = render_corner_map(state(), now=NOW)
    headers = Mock()
    headers.get_content_type.return_value = "image/png"
    headers.get.return_value = "fresh"
    response = Mock(headers=headers)
    response.read.return_value = data
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(bridge, "build_opener", Mock(return_value=opener))
    assert bridge.read_map(bridge.PRODUCTION_MAP_URL) == (data, True)
    response.read.assert_called_once_with(bridge.MAX_PNG_BYTES + 1)
    opener.open.assert_called_once_with(bridge.PRODUCTION_MAP_URL, timeout=3)
    for bad in (b"not png", data + b"x", data[:16] + struct.pack(">II", 9000, 9000) + data[24:], b"x" * (bridge.MAX_PNG_BYTES+1)):
        response.read.return_value = bad
        with pytest.raises(ValueError):
            bridge.read_map(bridge.PRODUCTION_MAP_URL)
    with pytest.raises(ValueError):
        bridge._NoRedirect().redirect_request(None, None, None, None, None, "https://evil.invalid/")


def test_local_monitor_displays_png_then_cleans_up_without_external_browser(monkeypatch):
    stop = threading.Event()
    data, _ = render_corner_map(state(), now=NOW)
    monkeypatch.setattr(bridge, "read_map", Mock(return_value=(data, True)))
    async def show(script, *_):
        if script == bridge.SHOW_PNG:
            stop.set()
        return True
    output, statuses = SimpleNamespace(evaluate=AsyncMock(side_effect=show)), []
    asyncio.run(bridge.monitor_local_map(output, statuses.append, stop))
    assert statuses == [True, False]
    assert output.evaluate.await_args_list[-1].args == (bridge.HIDE_MAP,)


def test_local_monitor_error_is_private_and_does_not_escape(monkeypatch, capsys):
    stop = threading.Event()
    monkeypatch.setattr(bridge, "read_map", Mock(side_effect=RuntimeError("SECRET private URL")))
    async def stop_wait(*_): stop.set()
    monkeypatch.setattr(bridge, "_wait_with_stop", stop_wait)
    statuses, output = [], SimpleNamespace(evaluate=AsyncMock())
    asyncio.run(bridge.monitor_local_map(output, statuses.append, stop))
    assert not any(statuses) and capsys.readouterr() == ("", "")


def test_own_overlay_uses_native_card_size_and_honest_source():
    settings = CaptureSettings(authorised=True, fps=30, map_overlay="astrolearner")
    settings.validate()
    page = player_page(settings).decode()
    assert "width:432px" in page and "Natural Earth" in page
    assert "ESA ISS Tracker · © ESA" not in page
    hub = FrameHub(30, "astrolearner")
    hub.set_map_ready(True)
    assert hub.status()["map_source"] == "astrolearner" and hub.status()["map_ready"]
    with pytest.raises(ValueError):
        CaptureSettings(authorised=True, local_map_url="http://localhost:8092/metadata").validate()


def test_deployment_selects_own_map_and_preserves_choice_on_later_fps_changes():
    capture = "ISS_BROWSER_CAPTURE_AUTHORIZED=true\n"
    original = "ISS_LIVE_FPS=30\nISS_BROWSER_MAP_OVERLAY=esa\nISS_LIVE_CONTROL_TOKEN=SECRET\n"
    changed = prepare_environment(original, capture, map_overlay="astrolearner")
    assert values(changed)["ISS_BROWSER_MAP_OVERLAY"] == "astrolearner"
    assert values(changed)["ISS_LIVE_FPS"] == "30" and "ISS_LIVE_CONTROL_TOKEN=SECRET" in changed
    assert values(prepare_environment(changed, capture, fps=20))["ISS_BROWSER_MAP_OVERLAY"] == "astrolearner"
    with pytest.raises(ValueError): prepare_environment(original, capture, map_overlay="http://evil.invalid/")
    state_ = dict(live_requested=False, ffmpeg_running=False, control_ready=True,
                  camera_enabled=True, camera_configured=True, camera_available=True, video_mode="camera")
    camera = dict(ready=True, map_source="astrolearner", map_ready=True, target_fps=30,
                  capture_fps=29., captured_frames=400)
    assert deployment_ready(state_, camera, 30, "astrolearner")
    assert not deployment_ready(state_, camera, 30, "esa")


def test_operator_bundle_pins_current_sources_and_never_starts_publication(assert_current_or_multistream_successor):
    root = Path(__file__).parents[1]
    installer = root.parents[1] / "maintenance" / "install-crisp-corner-map.sh"
    source = installer.read_text()
    block = re.search(r"<<'PY'\n(.*?)\nPY", source, re.S).group(1)
    tree = ast.parse(block)
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "files" for target in node.targets))
    expected = ast.literal_eval(assignment.value)
    assert len(expected) == 9
    for name, (_, digest) in expected.items():
        current = hashlib.sha256((root / name).read_text(encoding="utf-8").encode()).hexdigest()
        if name == "app/main.py" and current != digest:
            # The map bundle is deliberately frozen. The later auth bundle must
            # pin exactly this predecessor, not silently retarget the old bundle
            # to a main.py that also requires a new private session module.
            session_source = (root.parents[1] / "maintenance" / "install-live-control-sessions.sh").read_text()
            session_block = re.search(r"<<'PY'\n(.*?)\nPY", session_source, re.S).group(1)
            session_tree = ast.parse(session_block)
            session_assignment = next(n for n in session_tree.body if isinstance(n, ast.Assign)
                                      and any(isinstance(t, ast.Name) and t.id == "files" for t in n.targets))
            successor = ast.literal_eval(session_assignment.value)
            assert successor[name][0] == digest
            assert_current_or_multistream_successor(root, name, successor[name][1])
            assert "app/control_sessions.py" in successor
        else:
            assert_current_or_multistream_successor(root, name, digest)
    assert source.index("stopped ||") < source.index("install -o martin")
    assert "enable-browser-camera.sh 30 astrolearner" in source
    assert "flock -u 8" in source and "systemctl start homelab-backup.timer" in source
    assert "/start" not in source and "docker commit" not in source
