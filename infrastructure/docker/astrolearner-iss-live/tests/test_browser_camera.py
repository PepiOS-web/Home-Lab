import io
import json
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from urllib.request import urlopen
from unittest.mock import Mock

from PIL import Image
import pytest
import yaml

from app.browser_camera import CaptureSettings, FrameHub, PlaybackGate, browser_error_details, browser_launch_options, make_server, player_page


def playing(position=10, decoded=10, **kwargs):
    return dict(state=1, time=position, decoded=decoded, paused=False, ready=4,
                error=0, advertisement=False, **kwargs)


def jpeg():
    output = io.BytesIO()
    Image.new("RGB", (160, 90), "black").save(output, "JPEG")
    return output.getvalue()


def test_no_capture_without_explicit_authorisation(monkeypatch):
    monkeypatch.delenv("ISS_BROWSER_CAPTURE_AUTHORIZED", raising=False)
    with pytest.raises(ValueError, match="permiso"):
        CaptureSettings.from_env()


@pytest.mark.parametrize("value", ["https://portal.home.arpa", "../secrets", "abc\n123", "bad\"<script>", "awQzjn72bI0?key=PRIVATE"])
def test_only_public_video_id_allowed(value):
    with pytest.raises(ValueError):
        CaptureSettings(authorised=True, video_id=value).validate()


@pytest.mark.parametrize("changes", [dict(width=1920), dict(height=1080), dict(fps=31), dict(width=1279), dict(fps=0)])
def test_capture_geometry_bounded(changes):
    with pytest.raises(ValueError):
        CaptureSettings(authorised=True, **changes).validate()


@pytest.mark.parametrize("fps", [20, 30])
def test_higher_fps_is_opt_in_and_does_not_change_the_default(monkeypatch, fps):
    monkeypatch.setenv("ISS_BROWSER_CAPTURE_AUTHORIZED", "true")
    monkeypatch.delenv("ISS_BROWSER_FPS", raising=False)
    assert CaptureSettings.from_env().fps == 12
    monkeypatch.setenv("ISS_BROWSER_FPS", str(fps))
    assert CaptureSettings.from_env().fps == fps


def test_dedicated_page_never_loads_portal_or_credentials():
    page = player_page(CaptureSettings(authorised=True)).decode()
    assert "awQzjn72bI0" in page
    assert "https://www.youtube.com/iframe_api" in page
    assert "portal.home.arpa" not in page
    assert "control.html" not in page
    assert "rtmp" not in page
    assert "strict-origin-when-cross-origin" in page
    assert "mute:1" in page


def test_esa_map_is_an_optional_credited_corner_not_a_fullscreen_replacement():
    plain = player_page(CaptureSettings(authorised=True)).decode()
    assert 'id="esa-map-wrap"' not in plain
    page = player_page(CaptureSettings(authorised=True, map_overlay="esa")).decode()
    assert 'id="esa-map-wrap"' in page and 'id="esa-map"' in page
    assert "top:18px;right:18px" in page and "width:28%" in page
    assert "© ESA" in page and "performance.now()-window.esaMapUpdated>10000" in page
    assert "opacity:0" in page
    assert "portal.home.arpa" not in page


def test_no_arbitrary_map_urls_allowed():
    with pytest.raises(ValueError, match="URLs"):
        CaptureSettings(authorised=True, map_overlay="https://private.invalid/map").validate()


def test_map_failure_does_not_invalidate_camera_frames():
    hub = FrameHub(12, "esa")
    hub.publish(jpeg(), time.monotonic())
    hub.set_map_ready(True)
    assert hub.status()["map_ready"]
    hub.set_map_ready(False)
    assert not hub.status()["map_ready"]
    assert hub.status()["ready"] and hub.frame() is not None
    hub.set_map_ready(True)
    hub.map_received = time.monotonic() - 11
    assert not hub.status()["map_ready"]


def test_gate_requires_time_and_decoded_frames_to_advance():
    gate = PlaybackGate()
    assert not gate.observe(playing(), 0)
    assert not gate.observe(playing(position=11), 1)
    assert gate.observe(playing(position=12, decoded=20), 2)
    assert not gate.observe(playing(position=16, decoded=20), 5)


@pytest.mark.parametrize("field,value", [("state", 2), ("state", 3), ("error", 153), ("paused", True), ("ready", 1), ("advertisement", True), ("time", float("nan"))])
def test_player_errors_pauses_ads_and_buffering_are_not_camera_frames(field, value):
    gate = PlaybackGate()
    gate.observe(playing(), 0)
    assert gate.observe(playing(11, 20), 1)
    bad = playing(12, 30)
    bad[field] = value
    assert not gate.observe(bad, 2)
    assert gate.last_progress is None


def test_playhead_reset_requires_new_progress():
    gate = PlaybackGate()
    gate.observe(playing(100, 100), 0)
    assert gate.observe(playing(101, 110), 1)
    assert not gate.observe(playing(0, 1), 2)
    assert gate.observe(playing(1, 10), 3)


def test_dark_frame_is_accepted_without_brightness_heuristic():
    hub = FrameHub(12)
    assert hub.publish(jpeg(), time.monotonic())
    assert hub.frame() is not None
    assert hub.status()["ready"] is True


def test_errors_and_old_frames_never_remain_available():
    hub = FrameHub(12)
    hub.publish(jpeg(), time.monotonic() - 3)
    assert hub.frame() is None
    assert not hub.status()["ready"]
    hub.publish(jpeg(), time.monotonic())
    hub.invalidate("player_error", 153)
    assert hub.frame() is None
    status = hub.status()
    assert status["player_error"] == 153
    assert status["publishing"] is False


@pytest.mark.parametrize("payload", [b"not-jpeg", b"\xff\xd8" + b"x" * (2 * 1024 * 1024) + b"\xff\xd9"], ids=["invalid", "oversized"])
def test_unbounded_or_invalid_image_rejected(payload):
    hub = FrameHub(12)
    assert not hub.publish(payload, time.monotonic())
    assert hub.frame() is None


def test_measured_fps_and_status_are_bounded_and_private():
    hub = FrameHub(12)
    for i in range(150):
        hub.publish(jpeg(), i / 12)
    assert len(hub.timestamps) == 120
    status = hub.status()
    assert status["capture_fps"] == 12
    assert set(status) == {"state", "ready", "captured_frames", "capture_fps", "target_fps", "last_frame_age_seconds", "player_error", "publishing"}


@pytest.fixture
def server():
    hub, stop = FrameHub(12), threading.Event()
    server = make_server(CaptureSettings(authorised=True, port=0), hub, stop)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", hub
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_liveness_not_falsely_claiming_readiness(server):
    url, hub = server
    with urlopen(url + "/health", timeout=2) as response:
        assert not json.load(response)["ready"]
    for path in ("/ready", "/camera.mjpeg"):
        with pytest.raises(HTTPError) as error:
            urlopen(url + path, timeout=2)
        assert error.value.code == 503
    hub.publish(jpeg(), time.monotonic())
    with urlopen(url + "/ready", timeout=2) as response:
        assert json.load(response)["ready"]


def test_http_jpeg_is_from_capture_and_stream_closes_on_error(server):
    url, hub = server
    payload = jpeg()
    hub.publish(payload, time.monotonic())
    with urlopen(url + "/camera.mjpeg", timeout=2) as response:
        assert response.headers["Cache-Control"] == "no-store"
        assert response.readline().strip() == b"--frame"
        assert response.readline().strip() == b"Content-Type: image/jpeg"
        assert response.readline().strip() == b"Content-Length: " + str(len(payload)).encode()
        assert response.readline() == b"\r\n"
        assert response.read(len(payload)) == payload
        hub.invalidate("player_error", 153)
        assert response.read() == b"\r\n"


def test_thirty_fps_http_transport_compensates_for_socket_write_time(monkeypatch):
    from app import browser_camera as module
    clock = {"now": 10.0}
    writes, waits = [], []
    hub = Mock()
    hub.frame.return_value = b"\xff\xd8frame\xff\xd9"
    hub.clients.acquire.return_value = True

    class Stop:
        def is_set(self):
            return len(writes) == 4

        def wait(self, duration):
            waits.append(duration)
            clock["now"] += duration

    class Writer:
        def write(self, _payload):
            clock["now"] += 0.01
            writes.append(clock["now"])

        def flush(self):
            pass

    http_server = make_server(CaptureSettings(authorised=True, fps=30, port=0), hub, Stop())
    try:
        handler = object.__new__(http_server.RequestHandlerClass)
        handler.path = "/camera.mjpeg"
        handler.connection = Mock()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.wfile = Writer()
        monkeypatch.setattr(module.time, "monotonic", lambda: clock["now"])
        handler.do_GET()
    finally:
        http_server.server_close()

    assert writes == pytest.approx([10.01 + index / 30 for index in range(4)])
    assert waits == pytest.approx([1 / 30 - 0.01] * 4)
    hub.clients.release.assert_called_once()


def test_unknown_paths_do_not_serve_files(server):
    url, _ = server
    with pytest.raises(HTTPError) as error:
        urlopen(url + "/.env", timeout=2)
    assert error.value.code == 404


def test_browser_launch_has_sandbox_and_no_authentication_profile():
    source = (Path(__file__).parents[1] / "app" / "browser_camera.py").read_text(encoding="utf-8")
    options = browser_launch_options()
    assert options["chromium_sandbox"] is True
    assert options["channel"] == "chrome"
    assert options["timeout"] == 20000
    assert "--no-sandbox" not in source
    assert "ignore_https_errors" not in source
    assert "launch_persistent_context" not in source
    assert "storage_state=" not in source


@pytest.mark.parametrize("message,code", [
    ("No usable sandbox! https://private.invalid/key", "sandbox_denied"),
    ("Failed to move to new namespace: Operation not permitted", "sandbox_denied"),
    ("pthread_create: Operation not permitted", "thread_or_syscall_denied"),
    ("zygote_host_impl_linux.cc: pthread_create failed: Operation not permitted", "thread_or_syscall_denied"),
    ("zygote_host_impl_linux.cc: process launch failed", "unknown"),
    ("Executable doesn't exist at /private/binary", "browser_missing"),
    ("Permission denied writing /private/profile", "profile_write_error"),
    ("chrome_crashpad_handler: --database is required", "profile_write_error"),
    ("Frame was detached from https://private.invalid/?key=SECRET", "frame_detached"),
    ("Timeout navigating https://private.invalid", "operation_timeout"),
    ("Target page, context or browser has been closed", "process_exited"),
    ("PRIVATE SECRET unrecognised browser message", "unknown"),
])
def test_error_classification_never_exposes_private_message(message, code):
    details = browser_error_details(RuntimeError(message), "launch")
    assert details["error_code"] == code
    assert details["error_stage"] == "launch"
    assert len(details["error_fingerprint"]) == 12
    assert "private" not in json.dumps(details).lower()
    assert "SECRET" not in json.dumps(details)


def test_invalid_stage_and_exception_type_do_not_leak_text():
    class PrivateNameError(Exception):
        pass
    details = browser_error_details(PrivateNameError("secret"), "https://private.invalid")
    assert details["error_stage"] == "unknown"
    assert details["error_type"] == "Exception"


def test_bounded_cdp_timeout_is_classified_even_without_an_error_message():
    assert browser_error_details(TimeoutError(), "screenshot")["error_code"] == "operation_timeout"


def test_broker_drops_unknown_diagnostic_fields():
    hub = FrameHub(12)
    details = browser_error_details(RuntimeError("closed"), "page")
    hub.invalidate("browser_error", error_details={**details, "raw_exception": "SECRET",
                                                  "error_signals": ["SECRET", "operation_not_permitted"]})
    assert hub.status()["error_stage"] == "page"
    assert hub.status()["error_signals"] == ["operation_not_permitted"]
    assert "SECRET" not in json.dumps(hub.status())


def test_diagnostics_report_fixed_signals_not_paths_or_private_message():
    details = browser_error_details(RuntimeError(
        "zygote_host_impl_linux.cc: chroot /private/SECRET: Operation not permitted; "
        "clone3 failed; AppArmor; SIGTRAP https://private.invalid/?key=SECRET"), "launch")
    assert details["error_code"] == "thread_or_syscall_denied"
    assert details["error_signals"] == ["operation_not_permitted", "chroot_failed", "clone3_mentioned",
                                       "apparmor_mentioned", "process_signal"]
    assert "SECRET" not in json.dumps(details)
    assert "private" not in json.dumps(details)


def test_staging_and_production_sidecar_have_no_secrets_or_public_ports():
    root = Path(__file__).parents[1]
    common = yaml.safe_load((root / "compose.camera-browser.yaml").read_text(encoding="utf-8"))["services"]["camera-browser"]
    assert "volumes" not in common and "ports" not in common
    assert common["cap_drop"] == ["ALL"]
    assert "cap_add" not in common and not common.get("privileged", False)
    assert common.get("ipc") != "host"
    assert common["read_only"]
    assert common["mem_limit"] == "1536m"
    assert "no-new-privileges:true" in common["security_opt"]
    assert "seccomp:./camera-browser-seccomp.json" in common["security_opt"]
    assert not any("unconfined" in option for option in common["security_opt"])
    staging = yaml.safe_load((root / "compose.camera-browser-staging.yaml").read_text(encoding="utf-8"))["services"]
    assert staging["camera-browser"]["ports"] == ["127.0.0.1:8095:8093"]
    assert common["environment"]["ISS_BROWSER_MAP_OVERLAY"] == "${ISS_BROWSER_MAP_OVERLAY:-none}"
    assert staging["camera-browser"]["environment"]["ISS_BROWSER_MAP_OVERLAY"] == "esa"
    assert staging["camera-staging"]["environment"]["ISS_LIVE_MAP_SECONDS"] == "0"
    assert staging["camera-browser"]["environment"]["ISS_BROWSER_FPS"] == "${ISS_CAMERA_TEST_FPS:-12}"
    assert staging["camera-staging"]["environment"]["ISS_LIVE_FPS"] == "${ISS_CAMERA_TEST_FPS:-12}"
    live = yaml.safe_load((root / "compose.camera-browser-live.yaml").read_text())["services"]
    assert live["camera-browser"]["environment"]["ISS_BROWSER_FPS"] == "${ISS_LIVE_FPS:-12}"
    assert staging["camera-staging"]["cpus"] == 3.0
    assert staging["camera-staging"]["mem_limit"] == "1g"
    assert staging["camera-staging"]["pids_limit"] == 128
    profile = json.loads((root / "camera-browser-seccomp.json").read_text())
    assert profile["defaultAction"] == "SCMP_ACT_ERRNO"


def test_modern_glibc_can_fall_back_without_allowing_clone3():
    root = Path(__file__).parents[1]
    profile = json.loads((root / "camera-browser-seccomp.json").read_text())
    clone3_rules = [rule for rule in profile["syscalls"] if "clone3" in rule["names"]]
    assert len(clone3_rules) == 1
    rule = clone3_rules[0]
    assert rule["action"] == "SCMP_ACT_ERRNO" and rule["errnoRet"] == 38
    assert not rule.get("includes") and not rule.get("excludes") and not rule.get("args")


def test_sandbox_can_isolate_filesystem_without_container_capabilities():
    root = Path(__file__).parents[1]
    profile = json.loads((root / "camera-browser-seccomp.json").read_text())
    unconditional = [rule for rule in profile["syscalls"] if rule["action"] == "SCMP_ACT_ALLOW"
                     and not rule.get("includes") and not rule.get("excludes") and not rule.get("args")]
    assert any("chroot" in rule["names"] for rule in unconditional)
    assert any({"clone", "setns", "unshare"}.issubset(rule["names"]) for rule in unconditional)
    common = yaml.safe_load((root / "compose.camera-browser.yaml").read_text())["services"]["camera-browser"]
    assert common["cap_drop"] == ["ALL"] and "cap_add" not in common
    dockerfile = (root / "Dockerfile.camera-browser").read_text()
    assert "USER pwuser" in dockerfile
