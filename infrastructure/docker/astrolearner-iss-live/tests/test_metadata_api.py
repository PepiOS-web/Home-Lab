import importlib
import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("ISS_LIVE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ISS_LIVE_STATUS_DIR", str(tmp_path / "status"))
    monkeypatch.setenv("ISS_LIVE_CONTROL_TOKEN", "a" * 64)
    monkeypatch.setenv("ISS_LIVE_AUTO_START", "false")
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    # Do not enter the client's lifespan: no threads, synthesis or external API.
    yield TestClient(main.app), main
    sys.modules.pop("app.main", None)


HEADERS = {"Authorization": "Bearer " + "a" * 64, "Origin": "https://portal.home.arpa"}
VALUE = {"title": "Tierra y Lo-Fi", "description": "Vídeos grabados de NASA", "apply_to_current": False}


def test_authenticated_same_origin_get_without_origin(api):
    client, _ = api
    result = client.get("/metadata", headers={"Authorization": HEADERS["Authorization"]})
    assert result.status_code == 200
    assert result.json()["active"] is False
    assert result.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("method,headers,status", [
    ("get", {}, 401), ("get", {**HEADERS, "Origin": "https://evil.example"}, 403),
    ("post", {"Authorization": HEADERS["Authorization"]}, 403),
    ("post", {**HEADERS, "Authorization": "Bearer wrong"}, 401),
    ("post", {**HEADERS, "Origin": "https://evil.example"}, 403),
])
def test_unauthorized_metadata_never_written(api, method, headers, status):
    client, main = api
    response = client.request(method.upper(), "/metadata", headers=headers, json=VALUE)
    assert response.status_code == status
    assert not main.controller.metadata.path.exists()


def test_save_defaults_without_starting_live(api):
    client, main = api
    result = client.post("/metadata", headers=HEADERS, json=VALUE)
    assert result.status_code == 200
    assert result.json()["applied_to_current"] is False
    assert not main.controller.live_requested.is_set()
    assert client.get("/metadata", headers=HEADERS).json()["title"] == VALUE["title"]


@pytest.mark.parametrize("value", [
    {**VALUE, "title": 1}, {**VALUE, "title": ""}, {**VALUE, "description": "x" * 5001},
    {**VALUE, "apply_to_current": "false"}, {**VALUE, "broadcast_id": "not allowed"},
])
def test_server_validation_rejects_bad_forms(api, value):
    client, main = api
    assert client.post("/metadata", headers=HEADERS, json=value).status_code == 422
    assert not main.controller.metadata.path.exists()


def test_oversized_body_rejected(api):
    client, main = api
    assert client.post("/metadata", headers=HEADERS, content="x" * 32769).status_code == 413
    assert not main.controller.metadata.path.exists()


def test_update_without_current_broadcast_is_conflict(api):
    client, _ = api
    assert client.post("/metadata", headers=HEADERS, json={**VALUE, "apply_to_current": True}).status_code == 409
