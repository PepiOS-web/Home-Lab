"""Operator upgrade refuses active broadcasts and unexpected source versions."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT.parents[1] / 'maintenance' / 'install-iss-stream-upgrade.py'
spec = importlib.util.spec_from_file_location('stream_upgrade_install', SCRIPT)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_pinned_upgrade_matches_exact_reviewed_sources():
    manifest = json.loads((SCRIPT.parent / 'iss-stream-upgrade-manifest.json').read_text())
    assert set(manifest['files']) == installer.EXPECTED_FILES
    for name, pin in manifest['files'].items():
        actual = hashlib.sha256((ROOT / name).read_text(encoding='utf-8').encode()).hexdigest()
        assert actual == pin['after']
        assert pin['before'] is None or len(pin['before']) == 64


@pytest.mark.parametrize('state', [
    {'live_requested': True, 'ffmpeg_running': True},
    {'live_requested': False, 'ffmpeg_running': True},
    {'live_requested': True, 'ffmpeg_running': False}, {},
])
def test_no_source_or_bundle_read_until_live_is_confirmed_stopped(monkeypatch, tmp_path, state):
    monkeypatch.setattr(installer, 'status', lambda: state)
    with pytest.raises(RuntimeError, match='directo está activo'):
        installer.install(tmp_path / 'does-not-exist')
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('name', ['.env', 'app/../.env', '/etc/passwd', 'app/a/b.py', 'app/main.sh'])
def test_unapproved_paths_are_rejected(monkeypatch, tmp_path, name):
    monkeypatch.setattr(installer, 'ROOT', tmp_path)
    with pytest.raises(RuntimeError):
        installer.safe_target(name)


def test_atomic_source_replacement_uses_exact_bytes_and_owner(monkeypatch, tmp_path):
    source = tmp_path / 'new.py'
    target = tmp_path / 'old.py'
    source.write_bytes(b'new reviewed code\n')
    target.write_bytes(b'old\n')
    owners = []
    monkeypatch.setattr(installer.os, 'chown', lambda p, u, g: owners.append((u, g)), raising=False)
    installer.replace_file(source, target, (1000, 1000))
    assert target.read_bytes() == source.read_bytes()
    assert owners == [(1000, 1000)]
    assert not list(tmp_path.glob('.stream-upgrade-*'))


def test_api_down_only_counts_as_stopped_when_docker_confirms(monkeypatch):
    def offline():
        raise OSError('offline')
    monkeypatch.setattr(installer, 'status', offline)
    replies = iter(['id', '{"Running":false,"Restarting":false}'])
    monkeypatch.setattr(installer, 'run', lambda *args, **kwargs: next(replies))
    installer.stopped()
    replies = iter(['id', '{"Running":true,"Restarting":false}'])
    monkeypatch.setattr(installer, 'run', lambda *args, **kwargs: next(replies))
    with pytest.raises(RuntimeError, match='parada segura'):
        installer.stopped()


def test_docker_compose_cannot_inherit_autostart(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setenv('ISS_LIVE_AUTO_START', 'true')
    monkeypatch.setenv('COMPOSE_FILE', 'unreviewed.yaml')
    monkeypatch.setattr(installer, 'ROOT', tmp_path)
    def completed(*args, **kwargs):
        seen.append(kwargs['env'])
        return type('Result', (), {'returncode': 0, 'stdout': 'ok'})()
    monkeypatch.setattr(installer.subprocess, 'run', completed)
    assert installer.run(['docker', 'compose', 'config', '--quiet']) == 'ok'
    assert seen[0]['ISS_LIVE_AUTO_START'] == 'false'
    assert 'COMPOSE_FILE' not in seen[0]


def test_install_does_not_call_live_start_or_stop_and_probe_is_isolated():
    source = SCRIPT.read_text()
    assert "'/start'" not in source and "'/stop'" not in source
    assert "'--network', 'none'" in source
    assert "'--read-only'" in source and "'--cap-drop', 'ALL'" in source
    assert 'app.stream_upgrade_preflight' in source
    assert 'private.env' in source and 'mode=0o700' in source
    assert 'ISS_BROWSER_MAP_OVERLAY=none' in source
    assert 'ISS_LIVE_CONTROL_TOKEN=' not in source
