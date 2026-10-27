from pathlib import Path
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock
import io
import json
import pytest

from app.browser_camera_deployment import COMPOSE_FILES, deployment_ready, prepare_environment, refresh_selector, require_stopped, values, verify

CAPTURE = 'ISS_BROWSER_CAPTURE_AUTHORIZED=true\nISS_BROWSER_VIDEO_ID=awQzjn72bI0\n'


def ready_state():
    return dict(live_requested=False, ffmpeg_running=False, control_ready=True,
                camera_enabled=True, camera_configured=True, camera_available=True,
                video_mode='camera', last_error='')


def ready_capture(fps=12):
    return dict(ready=True, map_source='esa', map_ready=True, target_fps=fps,
                capture_fps=fps * 0.95, captured_frames=fps * 10)


def test_deployment_preserves_secrets_and_unrelated_lines_without_logging(capsys):
    original = '# keep\r\nISS_LIVE_CONTROL_TOKEN="SECRET=unchanged"\r\nOTHER="do not touch"\r\nISS_LIVE_AUTO_START=false\r\n'
    prepared = prepare_environment(original, CAPTURE)
    assert '# keep\r\nISS_LIVE_CONTROL_TOKEN="SECRET=unchanged"\r\nOTHER="do not touch"\r\n' in prepared
    result = values(prepared)
    assert result['COMPOSE_FILE'] == COMPOSE_FILES
    assert result['ISS_LIVE_AUTO_START'] == 'false'
    assert result['ISS_LIVE_DRY_RUN'] == 'false'
    assert result['ISS_LIVE_CAMERA_MODE'] == 'auto'
    assert result['ISS_LIVE_MAP_SECONDS'] == '0'
    assert result['ISS_BROWSER_MAP_OVERLAY'] == 'esa'
    assert result['ISS_LIVE_FPS'] == '12'
    assert result['ISS_LIVE_CAMERA_URL'] == 'http://camera-browser:8093/camera.mjpeg'
    assert capsys.readouterr() == ('', '')


def test_preparation_is_idempotent_and_deduplicates_only_managed_keys():
    first = prepare_environment('ISS_LIVE_AUTO_START=false\nISS_LIVE_AUTO_START=false', CAPTURE)
    assert first.count('ISS_LIVE_AUTO_START=') == 1
    assert prepare_environment(first, CAPTURE) == first


@pytest.mark.parametrize('fps', [20, 30])
def test_preparation_preserves_existing_higher_fps_when_no_target_is_supplied(fps):
    original = f'ISS_LIVE_AUTO_START=false\nISS_LIVE_FPS={fps}\n'
    prepared = prepare_environment(original, CAPTURE)
    assert values(prepared)['ISS_LIVE_FPS'] == str(fps)
    assert prepare_environment(prepared, CAPTURE) == prepared


@pytest.mark.parametrize('previous', [12, 20, 30])
@pytest.mark.parametrize('requested', [12, 20, 30])
def test_preparation_explicitly_selects_only_the_requested_fps(previous, requested):
    prepared = prepare_environment(f'ISS_LIVE_FPS={previous}\n', CAPTURE, fps=requested)
    assert values(prepared)['ISS_LIVE_FPS'] == str(requested)
    assert prepared.count('ISS_LIVE_FPS=') == 1


@pytest.mark.parametrize('fps', [0, 1, 15, 21, 31, True, False, 12.0, '20'])
def test_preparation_rejects_unsupported_or_wrong_type_explicit_targets(fps):
    with pytest.raises(ValueError):
        prepare_environment('', CAPTURE, fps=fps)


@pytest.mark.parametrize('configured', ['0', '15', '21', '31', 'not-a-number'])
def test_preparation_rejects_unsupported_existing_target_without_silently_changing_it(configured):
    with pytest.raises(ValueError):
        prepare_environment(f'ISS_LIVE_FPS={configured}\n', CAPTURE)


@pytest.mark.parametrize('original', ['COMPOSE_FILE=unrelated.yaml\n', 'COMPOSE_PROJECT_NAME=other\n',
    'ISS_LIVE_AUTO_START=true\n', 'COMPOSE_PATH_SEPARATOR=;\n'])
def test_unrelated_compose_selection_never_overwritten(original):
    with pytest.raises(ValueError):
        prepare_environment(original, CAPTURE)


@pytest.mark.parametrize('capture', ['', 'ISS_BROWSER_CAPTURE_AUTHORIZED=false', CAPTURE.replace('awQzjn72bI0', 'https://private.invalid/SECRET')])
def test_only_validated_authorised_capture_settings_are_accepted(capture):
    with pytest.raises(ValueError) as error:
        prepare_environment('', capture)
    assert 'SECRET' not in str(error.value)


@pytest.mark.parametrize('state', [None, {}, {'live_requested': False},
    {'live_requested': True, 'ffmpeg_running': False},
    {'live_requested': False, 'ffmpeg_running': True},
    {'live_requested': False, 'ffmpeg_running': False, 'status': 'en directo'}])
def test_a_running_or_unknown_stream_blocks_deployment(state):
    with pytest.raises(ValueError):
        require_stopped(state)


def test_only_confirmed_stopped_stream_can_be_recreated():
    require_stopped({'live_requested': False, 'ffmpeg_running': False, 'status': 'simulación lista'})


def test_ready_requires_real_camera_esa_and_no_broadcast():
    state = ready_state()
    capture = {**ready_capture(), 'capture_fps': 11.45, 'captured_frames': 150}
    assert deployment_ready(state, capture)
    for key in ('control_ready', 'camera_enabled', 'camera_configured', 'camera_available'):
        assert not deployment_ready({**state, key: False}, capture)
    assert not deployment_ready(state, {**capture, 'map_ready': False})
    assert not deployment_ready({**state, 'video_mode': 'recorded'}, capture)
    with pytest.raises(ValueError):
        deployment_ready({**state, 'live_requested': True}, capture)
    for fps in (None, 1, 11.39, float('nan'), float('inf'), True):
        assert not deployment_ready(state, {**capture, 'capture_fps': fps})
    assert not deployment_ready(state, {**capture, 'captured_frames': 119})


@pytest.mark.parametrize('fps', [20, 30])
def test_higher_fps_readiness_requires_matching_capture_target_and_real_throughput(fps):
    state, capture = ready_state(), ready_capture(fps)
    assert deployment_ready(state, capture, target_fps=fps)
    assert not deployment_ready(state, capture)
    assert not deployment_ready(state, ready_capture(12), target_fps=fps)
    assert not deployment_ready(state, {**capture, 'target_fps': 12}, target_fps=fps)
    assert not deployment_ready(state, {**capture, 'target_fps': None}, target_fps=fps)
    assert not deployment_ready(state, {**capture, 'capture_fps': fps * 0.95 - 0.01}, target_fps=fps)
    assert not deployment_ready(state, {**capture, 'captured_frames': fps * 10 - 1}, target_fps=fps)


@pytest.mark.parametrize('target', [None, 0, 15, 21, 31, True, False, 12.0, '20'])
def test_readiness_rejects_unsupported_or_wrong_type_targets(target):
    assert not deployment_ready(ready_state(), ready_capture(20), target_fps=target)


@pytest.mark.parametrize('fps', [12, 20, 30])
def test_verify_checks_actual_fps_and_preserves_nonpublishing_guards(monkeypatch, capsys, tmp_path, fps):
    from app import browser_camera_deployment as module, config
    settings = SimpleNamespace(dry_run=False, auto_start=False, privacy='public',
                               camera_enabled=True, camera_authorized=True, camera_mode='auto',
                               camera_url='http://camera-browser:8093/camera.mjpeg',
                               width=1280, height=720, encoder='libx264', fps=fps,
                               map_seconds=0, data_dir=tmp_path, validate=Mock())
    monkeypatch.setattr(config, 'Settings', Mock(return_value=settings))
    opener = Mock(side_effect=[io.BytesIO(json.dumps(ready_state()).encode()),
                               io.BytesIO(json.dumps(ready_capture(fps)).encode())])
    monkeypatch.setattr(module, 'urlopen', opener)
    audio = Mock()
    audio.getnchannels.return_value = 2
    audio.getsampwidth.return_value = 2
    audio.getframerate.return_value = 48000
    audio.getnframes.return_value = 3600 * 48000
    monkeypatch.setattr(module.wave, 'open', Mock(return_value=nullcontext(audio)))

    verify()

    settings.validate.assert_called_once_with()
    assert opener.call_count == 2
    assert opener.call_args_list[0].args == ('http://127.0.0.1:8092/api/status',)
    assert opener.call_args_list[1].args == ('http://camera-browser:8093/ready',)
    output = json.loads(capsys.readouterr().out)
    assert output['target_fps'] == fps
    assert output['publishing'] is False and output['live_requested'] is False
    assert output['hourly_music_preserved'] is True


def test_scripts_are_scoped_and_never_call_publish_or_global_teardown():
    root = Path(__file__).parents[1]
    enable = (root / 'scripts/enable-browser-camera.sh').read_text()
    rollback = (root / 'scripts/rollback-browser-camera.sh').read_text()
    for text in (enable, rollback):
        assert '/start' not in text and 'down' not in text and '--remove-orphans' not in text
        assert 'docker compose config --quiet' in text or 'compose_new config --quiet' in text
    assert enable.index('stopped ||') < enable.index('compose_new build')
    assert enable.count('stopped ||') == 2
    assert 'chmod 700 "$backup_dir"' in enable
    assert 'chmod 600 "$backup_dir/.env"' in enable
    assert 'docker compose stop camera-browser' in rollback
    assert "{{.State.Running}}" in rollback and '"$running" == false' in rollback
    assert 'browser-image-id' in enable and 'browser-image-id' in rollback
    assert 'homepage' not in enable.lower() or 'no se toca Homepage' in enable


def test_thirty_fps_scripts_stay_opt_in_and_guard_a_live_started_during_trial():
    root = Path(__file__).parents[1]
    trial = (root / 'scripts/test-browser-camera.sh').read_text()
    enable = (root / 'scripts/enable-browser-camera.sh').read_text()
    assert 'ISS_CAMERA_TEST_FPS=${1:-12}' in trial
    assert '12|20|30)' in trial and '12|20|30)' in enable
    assert '[ "$ISS_CAMERA_TEST_FPS" -ge 20 ]' in trial
    pause = trial.index('production_compose stop camera-browser')
    assert trial.rfind('require_stopped', 0, pause) > trial.index('if [ -n "$production_browser" ]')
    assert 'production_compose start camera-browser' in trial
    assert 'trap cleanup EXIT' in trial
    assert 'if ! compose stop >/dev/null 2>&1; then' in trial
    assert 'compose stop >/dev/null 2>&1 || true' not in trial
    cleanup = trial[trial.index('cleanup() {'):trial.index('trap cleanup EXIT')]
    assert cleanup.index('result=1') < cleanup.index('production_compose start camera-browser')
    assert 'while kill -0 "$probe_pid" 2>/dev/null; do\n    wait_stopped 1' in trial
    assert trial.count('wait_stopped 2') == 2
    assert 'wait_stopped 3' in trial and 'wait_stopped 6' in trial
    assert '/start' not in trial and '/stop' not in trial
    assert 'production_compose stop iss-live' not in trial


def test_readiness_exec_never_reads_the_terminal_and_has_a_hard_kill_deadline():
    root = Path(__file__).parents[1]
    check = (root / 'scripts/check-browser-camera.sh').read_text()
    assert 'exec --interactive=false -T' in check and '</dev/null' in check
    assert 'timeout --kill-after=3s 12s' in check
    assert '--foreground' not in check
    assert 'deployment.py refresh' in check
    for forbidden in ('docker compose up', 'docker compose stop', '/start', 'docker compose build'):
        assert forbidden not in check


def test_refresh_only_reads_a_bounded_local_frame_while_stopped(monkeypatch):
    from app import browser_camera_deployment as module
    state = io.BytesIO(b'{"live_requested":false,"ffmpeg_running":false}')
    frame = io.BytesIO(b'JPEG')
    opener = Mock(side_effect=[state, frame])
    monkeypatch.setattr(module, 'urlopen', opener)
    refresh_selector()
    assert opener.call_args_list[0].args == ('http://127.0.0.1:8092/api/status',)
    assert opener.call_args_list[1].args == ('http://127.0.0.1:8092/video.mjpeg',)


def test_refresh_never_reads_the_gateway_if_a_broadcast_is_active(monkeypatch):
    from app import browser_camera_deployment as module
    opener = Mock(return_value=io.BytesIO(b'{"live_requested":true,"ffmpeg_running":true}'))
    monkeypatch.setattr(module, 'urlopen', opener)
    with pytest.raises(ValueError):
        refresh_selector()
    assert opener.call_count == 1
