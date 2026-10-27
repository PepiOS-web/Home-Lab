from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import stat
import sys
from types import SimpleNamespace
import wave
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("live_backup", SOURCE / "homelab-backup-iss.py")
backup = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = backup
spec.loader.exec_module(backup)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def media(tmp_path, monkeypatch):
    source = tmp_path / "live"
    for folder in ("music", "nasa/videos", "nasa/epic", "secrets", "status"):
        (source / folder).mkdir(parents=True, exist_ok=True)
    write_json(source / "secrets/youtube-token.json", {
        "token": "PRIVATE-ACCESS-TOKEN", "refresh_token": "PRIVATE-REFRESH",
        "client_id": "private-id", "client_secret": "private-secret", "token_uri": "https://oauth2.googleapis.com/token",
    })
    (source / "status/status.json").write_text("volatile", encoding="utf-8")
    (source / "nasa/epic/current.jpg").write_bytes(b"cache")
    with wave.open(str(source / "music/astrolearner-lofi-hour-v1.wav"), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\0" * (8000 * 4))
    write_json(source / "music/astrolearner-lofi-hour-v1.json", {"duration_seconds": 1})
    (source / "nasa/videos/clip.mp4").write_bytes(b"test-mp4-content")
    asset = {"filename": "clip.mp4", "sha256": hashlib.sha256(b"test-mp4-content").hexdigest()}
    write_json(source / "nasa/videos/manifest.json", {"items": [asset], "playback_video": asset})
    (source / "nasa/videos/playlist.ffconcat").write_text("ffconcat version 1.0\nfile '/data/nasa/videos/clip.mp4'\ninpoint 0\noutpoint 900\n", encoding="utf-8")
    monkeypatch.setattr(backup, "copy_file", shutil.copy2)
    monkeypatch.setattr(backup.time, "sleep", lambda _: None)
    return source, tmp_path / "snapshot"


def test_complete_private_snapshot_and_empty_writable_cache_dirs(media):
    source, destination = media
    backup.snapshot(source, destination, iss=True)
    assert (destination / "secrets/youtube-token.json").read_bytes() == (source / "secrets/youtube-token.json").read_bytes()
    assert (destination / "music/astrolearner-lofi-hour-v1.wav").is_file()
    assert (destination / "nasa/videos/clip.mp4").is_file()
    assert list((destination / "status").iterdir()) == []
    assert list((destination / "nasa/epic").iterdir()) == []
    assert stat.S_IMODE((destination / "status").stat().st_mode) == stat.S_IMODE((source / "status").stat().st_mode)


@pytest.mark.parametrize("location", ["other", "nasa/other"])
def test_unmapped_persistent_data_aborts_before_any_snapshot(media, location):
    source, destination = media
    (source / location).mkdir()
    with pytest.raises(backup.BackupError, match="snapshot estable"):
        backup.snapshot(source, destination, iss=True)
    assert not destination.exists()


@pytest.mark.parametrize("location", ["music/output.tmp", "nasa/videos/build.tmp.mp4", "nasa/videos/clip.download", "music/.live-metadata-123.tmp", "music/lofi-render"])
def test_incomplete_generation_prevents_incoherent_cross_file_copy(media, location):
    source, destination = media
    (source / location).write_bytes(b"generation-in-progress")
    with pytest.raises(backup.BackupError):
        backup.snapshot(source, destination, iss=True)
    assert not destination.exists()


@pytest.mark.parametrize("content", [b"", b'{"token":"PRIVATE-ACCESS-TOKEN', b'[]', b'{"refresh_token":"refresh"}', b'{"value": NaN}'])
def test_truncated_or_invalid_credentials_never_enter_backup(media, content):
    source, destination = media
    (source / "secrets/youtube-token.json").write_bytes(content)
    with pytest.raises(backup.BackupError):
        backup.snapshot(source, destination, iss=True)
    assert not destination.exists()


def test_source_mutation_retries_entire_generation(media, monkeypatch):
    source, destination = media
    original = backup.copy_tree
    calls = []
    def mutate_once(src, dst, before):
        original(src, dst, before)
        calls.append(1)
        if len(calls) == 1:
            write_json(src / "music/live-metadata.json", {"title": "new", "description": "stable"})
    monkeypatch.setattr(backup, "copy_tree", mutate_once)
    backup.snapshot(source, destination, iss=True)
    assert len(calls) == 2
    assert json.loads((destination / "music/live-metadata.json").read_text())["title"] == "new"


def test_continuously_changing_source_aborts_and_removes_partial(media, monkeypatch):
    source, destination = media
    original = backup.copy_tree
    calls = []
    def mutate(src, dst, before):
        original(src, dst, before)
        calls.append(1)
        write_json(src / "music/live-metadata.json", {"title": str(len(calls))})
    monkeypatch.setattr(backup, "copy_tree", mutate)
    with pytest.raises(backup.BackupError):
        backup.snapshot(source, destination, iss=True)
    assert len(calls) == 3
    assert not destination.exists()


def test_status_changes_do_not_fail_hot_snapshot(media, monkeypatch):
    source, destination = media
    original = backup.copy_tree
    def update_cache(src, dst, before):
        original(src, dst, before)
        (src / "status/new-frame.jpg").write_bytes(b"new frame")
        (src / "nasa/epic/current.jpg").write_bytes(b"new cache")
    monkeypatch.setattr(backup, "copy_tree", update_cache)
    backup.snapshot(source, destination, iss=True)
    assert not (destination / "status/new-frame.jpg").exists()


@pytest.mark.parametrize("fault", ["missing_asset", "bad_hash", "broken_loop", "bad_playlist", "bad_wav", "truncated_wav", "wrong_duration"])
def test_media_integrity_and_cross_file_dependencies(media, fault):
    source, destination = media
    if fault == "missing_asset":
        (source / "nasa/videos/clip.mp4").unlink()
    elif fault == "bad_hash":
        (source / "nasa/videos/clip.mp4").write_bytes(b"changed-video")
    elif fault == "broken_loop":
        write_json(source / "nasa/videos/astrolearner-nasa-loop.json", {"filename": "missing.mp4", "sha256": "0" * 64})
    elif fault == "bad_playlist":
        (source / "nasa/videos/playlist.ffconcat").write_text("file 'https://private.example/video.mp4'", encoding="utf-8")
    elif fault == "bad_wav":
        (source / "music/astrolearner-lofi-hour-v1.wav").write_bytes(b"incomplete")
    elif fault == "truncated_wav":
        path = source / "music/astrolearner-lofi-hour-v1.wav"
        path.write_bytes(path.read_bytes()[:-1])
    else:
        write_json(source / "music/astrolearner-lofi-hour-v1.json", {"duration_seconds": 3600})
    with pytest.raises(backup.BackupError):
        backup.snapshot(source, destination, iss=True)
    assert not destination.exists()


def test_existing_destination_is_never_overwritten(media):
    source, destination = media
    destination.mkdir()
    (destination / "keep").write_text("keep")
    with pytest.raises(backup.BackupError, match="ya existe"):
        backup.snapshot(source, destination, iss=True)
    assert (destination / "keep").read_text() == "keep"


def test_private_json_exclusive_creation(tmp_path):
    destination = tmp_path / "plan.json"
    backup.private_json(destination, {"ids": []})
    with pytest.raises(FileExistsError):
        backup.private_json(destination, {"overwrite": True})
    assert json.loads(destination.read_text()) == {"ids": []}


def test_copy_reserves_exclusive_private_file_and_preserves_acl_metadata(tmp_path, monkeypatch):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.write_bytes(b"data")
    calls = []
    def copy(command, **options):
        calls.append((command, options))
        assert destination.is_file()
        assert destination.read_bytes() == b""
        assert "--preserve=all" in command
        assert "--reflink=auto" in command
        assert "--no-dereference" in command
        assert command[-2:] == [str(source), str(destination)]
        shutil.copy2(source, destination)
    monkeypatch.setattr(backup.subprocess, "run", copy)
    backup.copy_file(source, destination)
    assert destination.read_bytes() == b"data"
    with pytest.raises(FileExistsError):
        backup.copy_file(source, destination)
    assert len(calls) == 1


def test_symlink_never_follows_outside_snapshot(media):
    source, destination = media
    outside = source.parent / "outside-private"
    outside.write_bytes(b"private-outside")
    try:
        (source / "music/not-a-track").symlink_to(outside)
    except OSError:
        pytest.skip("This Windows session cannot create symlinks")
    with pytest.raises(backup.BackupError):
        backup.snapshot(source, destination, iss=True)
    assert not destination.exists()
    assert outside.read_bytes() == b"private-outside"


def container(identity, project, service, name=None, mounts=None):
    return {"Id": identity * 64, "Name": "/" + (name or service), "State": {"Running": True},
            "Config": {"Labels": {backup.PROJECT_LABEL: project, backup.SERVICE_LABEL: service}},
            "Mounts": mounts or []}


def live_container():
    return container("a", backup.PROJECT, "iss-live", "astrolearner-iss-live", [
        {"Type": "bind", "Source": str(backup.ISS_ROOT / src), "Destination": dest}
        for src, dest in (("music", "/data/music"), ("nasa", "/data/nasa"),
                          ("secrets/youtube-token.json", "/data/secrets/youtube-token.json"), ("status", "/status"))
    ])


def dns_container():
    return container("c", "adguardhome", "adguardhome", mounts=[
        {"Type": "bind", "Source": str(backup.DNS_ROOT / name), "Destination": "/opt/adguardhome/" + name}
        for name in ("work", "conf")
    ])


def test_exact_labels_protect_encoder_and_browser_not_similar_projects():
    plan = backup.container_plan([live_container(), container("b", backup.PROJECT, "camera-browser"), dns_container(),
                                  container("d", "astrolearner-iss-live-staging", "camera-browser"), container("e", "homepage", "homepage")])
    assert plan == {"iss": ["a" * 64, "b" * 64], "iss_main": ["a" * 64], "dns": ["c" * 64], "bulk": ["d" * 64, "e" * 64]}


@pytest.mark.parametrize("fault", ["wrong_project", "unexpected_mount", "missing_mount", "camera_mount", "duplicate", "bad_id", "stopped", "wrong_dns_project", "dns_mount"])
def test_unexpected_container_identity_or_mounts_fail_closed(fault):
    items = [live_container(), container("b", backup.PROJECT, "camera-browser"), dns_container()]
    if fault == "wrong_project":
        items[0]["Config"]["Labels"][backup.PROJECT_LABEL] = "other"
    elif fault == "unexpected_mount":
        items[0]["Mounts"].append({"Type": "bind", "Source": "/private", "Destination": "/more"})
    elif fault == "missing_mount":
        items[0]["Mounts"].pop()
    elif fault == "camera_mount":
        items[1]["Mounts"].append({"Type": "volume", "Destination": "/profile"})
    elif fault == "duplicate":
        items.append(container("d", backup.PROJECT, "camera-browser"))
    elif fault == "bad_id":
        items[0]["Id"] = "--malicious"
    elif fault == "stopped":
        items[0]["State"]["Running"] = False
    elif fault == "wrong_dns_project":
        items[2]["Config"]["Labels"][backup.PROJECT_LABEL] = "other"
    else:
        items[2]["Mounts"][0]["Source"] = "/unmanaged"
    with pytest.raises(backup.BackupError):
        backup.container_plan(items)


def test_dns_snapshot_copies_persistent_database_while_stopped(tmp_path, monkeypatch):
    source, destination = tmp_path / "dns", tmp_path / "dns-snapshot"
    (source / "work").mkdir(parents=True)
    (source / "conf").mkdir()
    (source / "work/queries.db").write_bytes(b"database")
    monkeypatch.setattr(backup, "copy_file", shutil.copy2)
    backup.snapshot(source, destination, iss=False, attempts=1)
    assert (destination / "work/queries.db").read_bytes() == b"database"


def test_host_status_cache_preserves_only_empty_directory_and_permissions(tmp_path):
    source, destination = tmp_path / "homelab-status", tmp_path / "snapshot/homelab-status"
    source.mkdir(mode=0o750)
    (source / "current.json").write_text('{"status":"volatile"}')
    (source / "status-123.tmp").write_bytes(b"partial cache")
    backup.snapshot_empty_cache(source, destination)
    assert destination.is_dir()
    assert list(destination.iterdir()) == []
    assert stat.S_IMODE(destination.stat().st_mode) == stat.S_IMODE(source.stat().st_mode)
    assert destination.stat().st_uid == source.stat().st_uid
    assert destination.stat().st_gid == source.stat().st_gid


def test_host_cache_changes_do_not_require_stopping_collector(tmp_path, monkeypatch):
    source, destination = tmp_path / "homelab-status", tmp_path / "snapshot/homelab-status"
    source.mkdir()
    copy_stat = backup.shutil.copystat
    def update_cache(original, target, **kwargs):
        (original / "new-status.json").write_text('{"new":"status"}')
        copy_stat(original, target, **kwargs)
    monkeypatch.setattr(backup.shutil, "copystat", update_cache)
    backup.snapshot_empty_cache(source, destination)
    assert list(destination.iterdir()) == []


def test_host_cache_path_cannot_be_a_regular_file(tmp_path):
    source, destination = tmp_path / "homelab-status", tmp_path / "snapshot/homelab-status"
    source.write_bytes(b"not a directory")
    with pytest.raises(backup.BackupError):
        backup.snapshot_empty_cache(source, destination)
    assert not destination.exists()


def test_insufficient_space_fails_without_starting_copy(media, monkeypatch):
    source, destination = media
    calls = []
    monkeypatch.setattr(backup.shutil, "disk_usage", lambda _: SimpleNamespace(free=backup.SPACE_RESERVE))
    monkeypatch.setattr(backup, "copy_tree", lambda *args: calls.append(args))
    with pytest.raises(backup.BackupError):
        backup.snapshot(source, destination, iss=True, attempts=1)
    assert calls == []
    assert not destination.exists()


@pytest.mark.parametrize("missing", ["root", "token", "wav", "manifest"])
def test_running_iss_requires_recoverable_persistent_sources(media, missing):
    source, destination = media
    # The running-production policy includes the validated normalized loop.
    loop = source / "nasa/videos/astrolearner-nasa-loop.mp4"
    loop.write_bytes(b"normalized-loop")
    write_json(loop.with_suffix(".json"), {"filename": loop.name, "sha256": hashlib.sha256(loop.read_bytes()).hexdigest()})
    if missing == "root":
        shutil.rmtree(source)
    elif missing == "token":
        (source / "secrets/youtube-token.json").unlink()
    elif missing == "wav":
        (source / "music/astrolearner-lofi-hour-v1.wav").unlink()
    else:
        (source / "nasa/videos/manifest.json").unlink()
    with pytest.raises(backup.BackupError):
        backup.snapshot(source, destination, iss=True, attempts=1, required_iss=True)
    assert not destination.exists()


def test_running_iss_complete_sources_can_be_copied(media):
    source, destination = media
    loop = source / "nasa/videos/astrolearner-nasa-loop.mp4"
    loop.write_bytes(b"normalized-loop")
    write_json(loop.with_suffix(".json"), {"filename": loop.name, "sha256": hashlib.sha256(loop.read_bytes()).hexdigest()})
    backup.snapshot(source, destination, iss=True, required_iss=True)
    assert (destination / "secrets/youtube-token.json").is_file()


def test_extended_attributes_and_acl_loss_are_fatal(tmp_path, monkeypatch):
    source, destination = tmp_path / "source", tmp_path / "copy"
    source.write_bytes(b"same")
    shutil.copy2(source, destination)
    monkeypatch.setattr(backup.os, "listxattr", lambda *a, **kw: ["system.posix_acl_access"], raising=False)
    monkeypatch.setattr(backup.os, "getxattr", lambda path, *a, **kw: b"original" if path == source else b"lost", raising=False)
    with pytest.raises(backup.BackupError, match="ACL"):
        backup.verify_metadata(source, destination)


@pytest.mark.parametrize("health", [None, "healthy"])
def test_dns_wait_confirms_running_and_health_if_defined(monkeypatch, health):
    state = {"Running": True}
    if health is not None:
        state["Health"] = {"Status": health}
    commands = []
    def inspect(command, **options):
        commands.append(command)
        assert options["timeout"] == 5
        return SimpleNamespace(stdout=json.dumps([{"State": state}]))
    monkeypatch.setattr(backup.subprocess, "run", inspect)
    backup.wait_dns(["c" * 64])
    assert commands == [["/usr/bin/docker", "inspect", "c" * 64]]


def test_dns_wait_is_bounded_and_does_not_accept_unhealthy(monkeypatch):
    moments = iter([0, 0, 1, 31])
    monkeypatch.setattr(backup.time, "monotonic", lambda: next(moments))
    monkeypatch.setattr(backup.time, "sleep", lambda _: None)
    monkeypatch.setattr(backup.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=json.dumps([
        {"State": {"Running": True, "Health": {"Status": "unhealthy"}}}
    ])))
    with pytest.raises(backup.BackupError, match="AdGuard"):
        backup.wait_dns(["c" * 64])


def test_root_script_never_stops_iss_and_restarts_dns_before_bulk_tar():
    text = (SOURCE / "homelab-backup").read_text(encoding="utf-8")
    assert "docker stop \"${running_containers[@]}\"" not in text
    assert "|| true" not in text
    assert text.index('snapshot-iss "$work"') < text.index('docker stop "${dns_containers[@]}"')
    assert text.index('snapshot-dns "$work"') < text.index('docker stop "${bulk_containers[@]}"')
    assert text.index('snapshot-dns "$work"\nrestart_containers') < text.index('docker stop "${bulk_containers[@]}"')
    assert text.index('wait-dns "$work"') < text.index('docker stop "${bulk_containers[@]}"')
    assert text.index('preflight-space "$work"') < text.index('docker stop "${dns_containers[@]}"')
    assert '! -name astrolearner-iss-live ! -name adguardhome ! -name homelab-status -print0' in text
    assert 'python3 "$helper" snapshot-status "$work"' in text
    assert "srv/data/appdata/homelab-status; do" in text
    assert "systemctl stop" not in text
    assert "systemctl disable" not in text
    assert '-C "$work/snapshot" "${snapshot_paths[@]}"' in text
    assert 'flock -n 9' in text
    assert 'trap \'exit 143\' TERM' in text
    assert 'rm -rf --one-file-system -- "$work"' in text
    assert 'verify-restarted "$work"' in text
