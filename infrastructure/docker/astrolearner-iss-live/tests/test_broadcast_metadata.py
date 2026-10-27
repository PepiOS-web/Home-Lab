import json
from dataclasses import replace

import pytest

from app.broadcast_metadata import BroadcastMetadataStore, default_metadata, validate_metadata
from app.config import Settings
from app.controller import Controller
from app.state import StateStore


def test_private_metadata_persists_and_snapshot_is_a_copy(tmp_path):
    path = tmp_path / "music" / "live-metadata.json"
    store = BroadcastMetadataStore(path, "NASA Image and Video Library")
    assert "No es una cámara en directo" in store.snapshot()["description"]
    store.save("  Nuestra Tierra 🌍  ", "Lo-Fi\nVídeos NASA grabados")
    store.snapshot()["title"] = "not saved"
    assert BroadcastMetadataStore(path).snapshot() == {
        "title": "Nuestra Tierra 🌍", "description": "Lo-Fi\nVídeos NASA grabados"
    }
    assert json.loads(path.read_text(encoding="utf-8"))["title"] == "Nuestra Tierra 🌍"
    assert not list(path.parent.glob("*.tmp"))


@pytest.mark.parametrize("contents", ["{", "[]", '{"title": 1, "description": "x"}', "x" * 32769],
                         ids=["broken-json", "array", "wrong-type", "too-large"])
def test_invalid_saved_file_falls_back_without_breaking_live(tmp_path, contents):
    path = tmp_path / "live-metadata.json"
    path.write_text(contents, encoding="utf-8")
    assert BroadcastMetadataStore(path).snapshot() == default_metadata()


@pytest.mark.parametrize("title,description", [
    ("", ""), (" " * 10, ""), ("a" * 101, ""), ("title", "🌙" * 1251),
    ("<title>", ""), ("title", "<script>"), ("title\nsecond", ""), ("title", "\x00"),
    (1, "description"), ("title", None), ("title", "\ud800"),
])
def test_invalid_values_rejected(title, description):
    with pytest.raises(ValueError):
        validate_metadata(title, description)


def test_utf8_limit_and_empty_description():
    assert validate_metadata("🌙" * 100, "🌙" * 1250)["description"] == "🌙" * 1250
    assert validate_metadata("title", "")["description"] == ""


def make_controller(tmp_path):
    settings = replace(Settings(), data_dir=tmp_path / "data", status_dir=tmp_path)
    store = StateStore(tmp_path / "status.json", settings.source_label)
    return Controller(settings, store)


def test_future_metadata_save_does_not_start_or_contact_youtube(monkeypatch, tmp_path):
    def no_youtube(*args, **kwargs):
        pytest.fail("Saving defaults should not contact YouTube")
    monkeypatch.setattr("app.controller.YouTubeLive", no_youtube)
    controller = make_controller(tmp_path)
    result = controller.save_metadata("Title", "Description")
    assert result["applied_to_current"] is False
    assert not controller.live_requested.is_set()
    assert controller.metadata_snapshot() == {"title": "Title", "description": "Description", "active": False}


def test_stale_watch_url_never_authorizes_edit(tmp_path):
    controller = make_controller(tmp_path)
    controller.live_requested.set()
    controller.store.update(youtube_watch_url="https://youtube.com/watch?v=old")
    with pytest.raises(RuntimeError, match="No hay un directo"):
        controller.save_metadata("Title", "Description", True)
    assert not controller.metadata.path.exists()


def test_active_edit_and_stop_clear_id(monkeypatch, tmp_path):
    calls = []
    class FakeYouTube:
        def __init__(self, *args):
            pass
        def update_metadata(self, broadcast_id, **value):
            calls.append((broadcast_id, value))
    monkeypatch.setattr("app.controller.YouTubeLive", FakeYouTube)
    controller = make_controller(tmp_path)
    controller.live_requested.set()
    controller._active_broadcast_id = "current"
    assert controller.save_metadata("New title", "New description", True)["applied_to_current"]
    assert calls == [("current", {"title": "New title", "description": "New description"})]
    assert controller.live_requested.is_set()
    controller.request_live_stop()
    assert controller._active_broadcast_id is None
    with pytest.raises(RuntimeError, match="No hay un directo"):
        controller.save_metadata("Other title", "Description", True)
    assert len(calls) == 1


def test_youtube_edit_failure_saves_future_without_stopping_stream(monkeypatch, tmp_path):
    class FakeYouTube:
        def __init__(self, *args):
            pass
        def update_metadata(self, *args, **kwargs):
            raise RuntimeError("remote failure")
    monkeypatch.setattr("app.controller.YouTubeLive", FakeYouTube)
    controller = make_controller(tmp_path)
    controller.live_requested.set()
    controller._active_broadcast_id = "current"
    with pytest.raises(RuntimeError, match="se guardaron.*No se ha interrumpido"):
        controller.save_metadata("New title", "New description", True)
    assert controller.live_requested.is_set()
    assert controller.metadata.snapshot()["title"] == "New title"
    assert controller.store.snapshot()["last_error"] == ""


def test_disk_failure_does_not_contact_youtube_or_change_memory(monkeypatch, tmp_path):
    controller = make_controller(tmp_path)
    old = controller.metadata.snapshot()
    def fail_replace(*args):
        raise OSError("disk failure")
    monkeypatch.setattr("app.broadcast_metadata.os.replace", fail_replace)
    with pytest.raises(RuntimeError, match="No se pudieron guardar"):
        controller.save_metadata("New title", "New description")
    assert controller.metadata.snapshot() == old
    assert not list(controller.metadata.path.parent.glob("*.tmp"))


def test_next_broadcast_uses_saved_values_and_clears_active_id(monkeypatch, tmp_path):
    from app.youtube import Broadcast

    controller = make_controller(tmp_path)
    controller.settings = replace(controller.settings, source_url="https://example.invalid/stream")
    controller.save_metadata("Saved title", "Saved description")
    controller.live_requested.set()
    monkeypatch.setattr(controller.stop_event, "wait", lambda timeout: False)
    calls = []
    class FakeYouTube:
        def __init__(self, *args):
            pass
        def create(self, seconds, **value):
            calls.append(value)
            return Broadcast("new-id", "stream-id", "rtmp://invalid/key", "https://youtube.com/watch?v=new-id")
        def complete(self, broadcast_id):
            assert controller._active_broadcast_id is None

    def run_ffmpeg(*args, **kwargs):
        assert controller._active_broadcast_id == "new-id"
        controller.live_requested.clear()
        controller.stop_event.set()
    monkeypatch.setattr("app.controller.YouTubeLive", FakeYouTube)
    monkeypatch.setattr(controller, "_run_ffmpeg", run_ffmpeg)
    controller.run()
    assert calls == [{"title": "Saved title", "description": "Saved description"}]
    assert controller._active_broadcast_id is None
