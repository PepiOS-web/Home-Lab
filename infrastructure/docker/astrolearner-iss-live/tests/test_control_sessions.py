import importlib
import ast
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.control_auth import ControlAuthError
from app.control_sessions import COOKIE_NAME, COOKIE_PATH, SESSION_SECONDS, ControlSessions

SECRET = "a" * 64
ORIGIN = {"Origin": "https://portal.home.arpa"}
LOGIN = {**ORIGIN, "Authorization": "Bearer " + SECRET}
PREFIX = COOKIE_PATH.rstrip("/")


def test_private_hash_only_sessions_survive_restart_expire_and_revoke(tmp_path, monkeypatch):
    monkeypatch.setattr("app.control_sessions.time.time", lambda: 1000)
    path = tmp_path / "music" / ".control-sessions.json"
    sessions = ControlSessions(path)
    value = sessions.create(SECRET)
    assert sessions.valid(value, SECRET)
    assert ControlSessions(path).valid(value, SECRET)
    assert not sessions.valid(value, "b" * 64)
    assert not sessions.valid(value, "")
    assert not sessions.valid("wrong", SECRET)
    assert value not in path.read_text() and SECRET not in path.read_text()
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    replacement = sessions.create(SECRET, previous=value)
    assert not sessions.valid(value, SECRET)
    assert sessions.valid(replacement, SECRET)
    sessions.revoke(replacement, SECRET)
    assert not ControlSessions(path).valid(replacement, SECRET)
    expiring = sessions.create(SECRET)
    monkeypatch.setattr("app.control_sessions.time.time", lambda: 1000 + SESSION_SECONDS)
    assert not sessions.valid(expiring, SECRET)


def test_session_store_failure_is_closed_and_sanitized(tmp_path):
    path = tmp_path / "sessions.json"
    path.write_text('{"PRIVATE SECRET":', encoding="utf-8")
    sessions = ControlSessions(path)
    with pytest.raises(ControlAuthError) as exc:
        sessions.valid("a" * 43, SECRET)
    assert exc.value.status_code == 503
    assert "PRIVATE" not in str(exc.value) and str(path) not in str(exc.value)


def test_session_count_bounded_and_random_values_differ(tmp_path):
    sessions = ControlSessions(tmp_path / "sessions.json")
    values = {sessions.create(SECRET) for _ in range(130)}
    assert len(values) == 130
    assert len(json.loads(sessions.path.read_text())) == 128


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("ISS_LIVE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ISS_LIVE_STATUS_DIR", str(tmp_path / "status"))
    monkeypatch.setenv("ISS_LIVE_CONTROL_TOKEN", SECRET)
    monkeypatch.setenv("ISS_LIVE_AUTO_START", "false")
    monkeypatch.setenv("ISS_LIVE_DRY_RUN", "true")
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    proxy = FastAPI()
    proxy.mount(PREFIX, main.app)
    yield TestClient(proxy, base_url="https://portal.home.arpa"), main
    sys.modules.pop("app.main", None)


def test_cookie_login_restoration_and_logout_revoke_server_side(api):
    client, main = api
    assert client.get(PREFIX + "/session").json() == {"authenticated": False}
    response = client.post(PREFIX + "/session", headers=LOGIN)
    assert response.status_code == 200 and response.json() == {"authenticated": True}
    assert response.headers["cache-control"] == "no-store"
    cookie = response.headers["set-cookie"]
    for flag in ("Secure", "HttpOnly", "SameSite=strict", "Path=" + COOKIE_PATH,
                 "Max-Age=" + str(SESSION_SECONDS)):
        assert flag in cookie
    assert "Domain=" not in cookie and SECRET not in cookie
    stolen_copy = client.cookies.get(COOKIE_NAME)
    assert client.get(PREFIX + "/session").json() == {"authenticated": True}
    assert client.get(PREFIX + "/metadata").status_code == 200
    result = client.post(PREFIX + "/metadata", headers=ORIGIN,
                         json={"title": "Prueba", "description": "Datos"})
    assert result.status_code == 200
    assert not main.controller.live_requested.is_set()
    assert not main.controller.stop_event.is_set()
    assert client.post(PREFIX + "/session/logout", headers=ORIGIN).status_code == 200
    assert client.get(PREFIX + "/session").json() == {"authenticated": False}
    assert not main.control_sessions.valid(stolen_copy, SECRET)


@pytest.mark.parametrize("headers,status", [
    ({}, 403), ({"Origin": "https://evil.example"}, 403), (ORIGIN, 401),
    ({**LOGIN, "Authorization": "Bearer wrong"}, 401),
])
def test_session_creation_requires_real_token_and_origin(api, headers, status):
    client, main = api
    assert client.post(PREFIX + "/session", headers=headers).status_code == status
    assert not main.control_sessions.path.exists()


@pytest.mark.parametrize("route", ["/start", "/stop", "/metadata", "/starvios", "/session/logout"])
def test_cookie_does_not_bypass_csrf_origin_or_explicit_bad_bearer(api, route):
    client, _ = api
    client.post(PREFIX + "/session", headers=LOGIN)
    for headers, status in (({}, 403), ({"Origin": "null"}, 403),
                            ({"Origin": "https://evil.example"}, 403),
                            ({**ORIGIN, "Authorization": "Bearer wrong"}, 401)):
        assert client.post(PREFIX + route, headers=headers, json={}).status_code == status


def test_control_token_rotation_and_dry_run_are_not_bypassed(api, monkeypatch):
    client, main = api
    client.post(PREFIX + "/session", headers=LOGIN)
    assert client.post(PREFIX + "/start", headers=ORIGIN).status_code == 409
    monkeypatch.setattr(main, "settings", type("Settings", (), {"control_token": "b" * 64})())
    assert client.get(PREFIX + "/session").json() == {"authenticated": False}
    assert client.post(PREFIX + "/stop", headers=ORIGIN).status_code == 401


def test_operator_bundle_pins_only_reviewed_auth_sources_and_never_cuts_live(assert_current_or_multistream_successor):
    root = Path(__file__).parents[1]
    source = (root.parents[1] / "maintenance" / "install-live-control-sessions.sh").read_text(encoding="utf-8")
    block = re.search(r"<<'PY'\n(.*?)\nPY", source, re.S).group(1)
    tree = ast.parse(block)
    assignment = next(n for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "files" for t in n.targets))
    files = ast.literal_eval(assignment.value)
    assert set(files) == {"app/main.py", "app/control_auth.py", "app/control_page.py", "app/control_sessions.py"}
    for name, (_, digest) in files.items():
        assert_current_or_multistream_successor(root, name, digest)
    assert source.index("stopped ||") < source.index("install -o martin")
    assert "up -d --no-deps --force-recreate" in source
    assert "/start" not in source and "/stop" not in source
    assert "docker commit" not in source and "systemctl start homelab-backup.timer" in source
