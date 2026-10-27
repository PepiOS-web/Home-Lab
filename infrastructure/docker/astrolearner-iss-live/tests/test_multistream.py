import ast
import hashlib
import importlib
import json
import os
import re
from pathlib import Path
import shutil
import sys
import subprocess
from unittest.mock import Mock
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.controller import Controller, connection_failure_reason
from app.multistream import Destination, FIFO_OPTIONS, SERVER, StarviosStore, redact_output, tee_output
from app.state import StateStore

KEY = "test_new_private_key_" + "x" * 44
HEADERS = {"Authorization": "Bearer " + "a" * 64, "Origin": "https://portal.home.arpa"}


def test_numeric_windows_reset_is_retryable_but_not_a_filter_failure():
    assert connection_failure_reason(4294957242, "Error number -10054 occurred") == "connection_reset"
    assert connection_failure_reason(-10054, "Error number -10054 occurred") == "connection_reset"
    assert connection_failure_reason(-10054, "Error reinitializing filters") is None


@pytest.mark.parametrize("deadline_expired", [False, True])
def test_stuck_fifo_does_not_extend_stop_or_original_block_limit(tmp_path, monkeypatch, deadline_expired):
    settings = replace(Settings(), data_dir=tmp_path, status_dir=tmp_path)
    controller = Controller(settings, StateStore(tmp_path / "status.json", "test"))
    controller._starvios_destination = Destination(True, KEY)
    controller._ffmpeg_command = Mock(return_value=["synthetic-test"])
    if deadline_expired:
        controller.live_requested.set()
    process = Mock()
    process.stderr = iter([])
    process.wait.side_effect = [subprocess.TimeoutExpired("synthetic-test", 3), 0]
    process.poll.return_value = 0
    monkeypatch.setattr("app.controller.subprocess.Popen", Mock(return_value=process))
    controller._run_ffmpeg("rtmp://example.invalid/local", "watch", Mock(), "id", "stream",
                           block_deadline=0 if deadline_expired else float("inf"))
    assert [call.kwargs["timeout"] for call in process.wait.call_args_list] == [3, 5]
    process.kill.assert_called_once()
    assert controller.store.snapshot()["starvios_output_active"] is False


def test_private_atomic_configuration_and_write_only_snapshot(tmp_path):
    store = StarviosStore(tmp_path / ".starvios.json")
    assert store.load() == Destination()
    with pytest.raises(ValueError):
        store.save(enabled=True, key=KEY)
    assert not store.path.exists()
    result = store.save(enabled=True, key=KEY, rotated_key_confirmed=True)
    assert result.url == SERVER + KEY
    assert KEY not in repr(result) and KEY not in json.dumps(result.public())
    assert result.public()["remote_verified"] is False
    assert store.load() == result
    assert store.save(enabled=False).key == KEY
    assert not list(tmp_path.glob(".starvios-*"))
    if os.name != "nt":
        assert store.path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("key", ["", "short", "x" * 513, KEY + "\n", KEY + "|", KEY + ":", KEY + "'", KEY + "[", "https://example.com/" + KEY])
def test_key_validation_does_not_reflect_private_input(tmp_path, key):
    store = StarviosStore(tmp_path / "private.json")
    with pytest.raises(ValueError) as error:
        store.save(enabled=True, key=key, rotated_key_confirmed=True)
    assert key not in str(error.value) if key else True
    assert not store.path.exists()


@pytest.mark.parametrize("data", ["invalid SECRET", '{"enabled":true,"key":"SECRET"}', '[]', '{"enabled":"false","key":""}'])
def test_corrupted_file_fail_closed(tmp_path, data):
    path = tmp_path / "private.json"
    path.write_text(data)
    os.chmod(path, 0o600)
    with pytest.raises(ValueError) as error:
        StarviosStore(path).load()
    assert "SECRET" not in str(error.value)


def test_symlink_is_refused(tmp_path):
    target = tmp_path / "target.json"
    target.write_text('{"enabled":false,"key":""}')
    path = tmp_path / "link.json"
    try:
        path.symlink_to(target)
    except OSError:
        pytest.skip("Symlinks need privileges on this Windows host")
    with pytest.raises(ValueError):
        StarviosStore(path).load()


def test_tee_uses_one_encoder_independent_nonblocking_recovery_and_safe_escaping():
    result = tee_output("rtmp://a.example/live/test'with|separators", SERVER + KEY)
    assert result.count("tee") == 1 and "-c:v" not in result
    assert result[-2] == FIFO_OPTIONS
    assert "attempt_recovery=1" in FIFO_OPTIONS and "drop_pkts_on_overflow=1" in FIFO_OPTIONS
    assert "restart_with_keyframe=1" in FIFO_OPTIONS and "max_recovery_attempts=0" in FIFO_OPTIONS
    assert result[-1].count("onfail=ignore") == 2
    assert "test\\'with\\|separators" in result[-1]
    for value in ("file:/tmp/output", "rtmp://host/key\nother"):
        with pytest.raises(ValueError):
            tee_output(value, SERVER + KEY)


def test_redaction_including_bare_keys():
    line = f"Unable to send {SERVER}{KEY}: key={KEY}; rtmp://a.example/live/YOUTUBEKEY"
    result = redact_output(line, SERVER + KEY, "rtmp://a.example/live/YOUTUBEKEY")
    assert KEY not in result and "YOUTUBEKEY" not in result and "rtmp://" not in result.lower()


def test_command_disabled_dry_run_and_local_preflight_do_not_publish_secondary(tmp_path):
    settings = replace(Settings(), data_dir=tmp_path, status_dir=tmp_path, dry_run=False)
    controller = Controller(settings, StateStore(tmp_path / "status.json", "test"))
    url = "rtmp://primary.example/live/primary-key"
    command = controller._ffmpeg_command(url)
    assert "tee" not in command and command[-1] == url
    controller._starvios_destination = Destination(True, KEY)
    command = controller._ffmpeg_command(url)
    assert "tee" in command and KEY in command[-1]
    assert command.count("-c:v") == 1 and command[command.index("-g") + 1] == str(settings.fps * 2)
    assert "nal-hrd=cbr:force-cfr=1" in command
    assert KEY not in " ".join(controller._ffmpeg_command("local-test.flv"))
    controller.settings = replace(settings, dry_run=True)
    assert KEY not in " ".join(controller._ffmpeg_command(url))


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("ISS_LIVE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ISS_LIVE_STATUS_DIR", str(tmp_path / "status"))
    monkeypatch.setenv("ISS_LIVE_CONTROL_TOKEN", "a" * 64)
    monkeypatch.setenv("ISS_LIVE_AUTO_START", "false")
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    yield TestClient(main.app), main
    sys.modules.pop("app.main", None)


def test_authenticated_save_never_starts_and_never_echoes_key(api):
    client, main = api
    response = client.post("/starvios", headers=HEADERS,
                           json={"enabled": True, "key": KEY, "rotated_key_confirmed": True})
    assert response.status_code == 200 and KEY not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert not main.controller.live_requested.is_set()
    assert not main.store.snapshot()["ffmpeg_running"]
    assert KEY not in client.get("/starvios", headers=HEADERS).text
    assert KEY not in client.get("/api/status").text
    assert KEY not in client.get("/metrics").text
    assert KEY not in client.get("/health").text
    response = client.post("/starvios", headers=HEADERS, json={"enabled": False})
    assert response.status_code == 200 and response.json()["configured"] is True


@pytest.mark.parametrize("method,headers,status", [
    ("get", {}, 401), ("post", {}, 403),
    ("post", {"Authorization": HEADERS["Authorization"]}, 403),
    ("post", {**HEADERS, "Authorization": "Bearer bad"}, 401),
    ("post", {**HEADERS, "Origin": "https://evil.example"}, 403),
])
def test_auth_and_origin_guard_private_destination(api, method, headers, status):
    client, main = api
    response = client.request(method.upper(), "/starvios", headers=headers,
                              json={"enabled": True, "key": KEY, "rotated_key_confirmed": True})
    assert response.status_code == status
    assert not main.controller.starvios.path.exists()


@pytest.mark.parametrize("value", [
    {"enabled": "true", "key": KEY}, {"enabled": True, "key": KEY},
    {"enabled": True, "key": [KEY]}, {"enabled": True, "key": KEY, "server": "rtmp://evil"},
    {"enabled": True, "key": KEY + "|", "rotated_key_confirmed": True},
])
def test_api_errors_do_not_echo_secret(api, value):
    client, main = api
    response = client.post("/starvios", headers=HEADERS, json=value)
    assert response.status_code == 422
    assert KEY not in response.text and not main.controller.starvios.path.exists()


def test_active_emission_cannot_be_reconfigured(api):
    client, main = api
    main.controller.live_requested.set()
    value = {"enabled": True, "key": KEY, "rotated_key_confirmed": True}
    assert client.post("/starvios", headers=HEADERS, json=value).status_code == 409
    main.controller.live_requested.clear()
    main.store.update(ffmpeg_running=True)
    assert client.post("/starvios", headers=HEADERS, json=value).status_code == 409
    assert not main.controller.starvios.path.exists()


def test_oversized_private_form_is_rejected(api):
    client, main = api
    response = client.post("/starvios", headers=HEADERS, content="x" * 2049)
    assert response.status_code == 413 and not main.controller.starvios.path.exists()


def test_installer_pins_sources_and_tests_without_credentials_before_recreate(assert_current_or_multistream_successor):
    root = Path(__file__).parents[1]
    source = (root.parents[1] / "maintenance" / "install-live-multistream.sh").read_text(encoding="utf-8")
    block = re.search(r"<<'PY'\n(.*?)\nPY", source, re.S).group(1)
    assignment = next(n for n in ast.parse(block).body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "files" for t in n.targets))
    files = ast.literal_eval(assignment.value)
    assert len(files) == 6
    for name, (_, digest) in files.items():
        assert_current_or_multistream_successor(root, name, digest)
    assert source.index("stopped ||") < source.index("install -o martin")
    assert source.index("--network none") < source.index("up -d --no-deps --force-recreate")
    assert "app.recovery_preflight" in source and "app.multistream_preflight" in source
    assert "--read-only" in source and "--cap-drop ALL" in source
    assert "-v " not in source and "--mount" not in source
    assert "original_runtime" in source and "cmp -s .env" in source
    assert "/start" not in source and "/stop" not in source


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="Isolated Docker operator probe requires FFmpeg")
def test_real_independent_cut_and_recovery():
    from app.multistream_preflight import run_probe
    report = run_probe()
    assert report["passed"] is True, report
