import wave
from pathlib import Path

import pytest

import json

from app.browser_camera_preflight import (
    PipelineDiagnostics, make_audio, measured_output_rate, resource_snapshot,
    select_audio, source_sequence_ok,
)


@pytest.mark.parametrize("events", [
    ["camera", "recorded", "camera"],
    ["map", "recorded", "camera", "recorded", "map", "camera"],
])
def test_recovery_requires_a_camera_before_and_after_fallback(events):
    assert source_sequence_ok(events)


@pytest.mark.parametrize("events", [[], ["recorded"], ["camera"], ["recorded", "camera"], ["camera", "recorded"]])
def test_no_false_success_without_real_source_loss_and_recovery(events):
    assert not source_sequence_ok(events)


def test_probe_audio_is_small_and_non_silent(tmp_path):
    destination = tmp_path / "tone.wav"
    make_audio(destination)
    with wave.open(str(destination), "rb") as audio:
        assert audio.getframerate() == 48000
        assert audio.getnframes() == 48000
        assert audio.getsampwidth() == 2
        assert any(audio.readframes(48000))


def test_pipeline_errors_are_classified_without_retaining_urls_or_keys():
    diagnostics = PipelineDiagnostics()
    diagnostics.observe("[libx264] pthread_create failed: Resource temporarily unavailable https://private.invalid/?key=SECRET")
    diagnostics.observe("Error while opening encoder: Generic error in an external library")
    # The cause must survive subsequent progress and finalization messages.
    for _ in range(50):
        diagnostics.observe("progress=end")
    report = diagnostics.report()
    assert report["error_signals"] == ["thread_creation_failed", "resource_unavailable",
                                       "encoder_initialization", "external_library"]
    assert len(report["error_fingerprint"]) == 12
    assert "SECRET" not in json.dumps(report) and "private" not in json.dumps(report)
    assert not any(isinstance(value, str) and "SECRET" in value for value in vars(diagnostics).values())


def test_cgroup_diagnostics_only_expose_selected_counters(tmp_path):
    (tmp_path / "pids.current").write_text("40\n")
    (tmp_path / "pids.max").write_text("64\n")
    (tmp_path / "pids.events").write_text("max 3\n")
    (tmp_path / "memory.events").write_text("low 0\noom_kill 1\n")
    assert resource_snapshot(tmp_path) == {"pids_current": 40, "pids_limit": 64,
                                          "pids_limit_hits": 3, "oom_kills": 1}


def test_cgroup_diagnostics_do_not_guess_when_unavailable(tmp_path):
    assert all(value is None for value in resource_snapshot(tmp_path).values())
    (tmp_path / "pids.max").write_text("max\n")
    (tmp_path / "memory.events").write_text("PRIVATE SECRET malformed input\n")
    assert all(value is None for value in resource_snapshot(tmp_path).values())


def test_fps_trial_is_opt_in_nonpublishing_and_restores_its_paused_browser():
    script = (Path(__file__).parents[1] / "scripts/test-browser-camera.sh").read_text()
    assert "ISS_CAMERA_TEST_FPS=${1:-12}" in script
    assert "export ISS_CAMERA_TEST_FPS" in script
    assert "12|20|30)" in script
    assert "flock -n 9" in script
    assert script.index("stopped ||") < script.index("compose build")
    assert script.index("compose build") < script.index("Se ha iniciado un directo")
    assert 'if [ "$ISS_CAMERA_TEST_FPS" -ge 20 ]' in script
    assert "production_compose stop camera-browser" in script
    assert "production_compose start camera-browser" in script
    assert "trap cleanup EXIT" in script
    assert "/start" not in script and "/stop" not in script
    assert "exec --interactive=false -T" in script and "</dev/null" in script


@pytest.mark.parametrize("fps", [12, 20, 30])
def test_probe_measures_real_output_rate_instead_of_nominal_fps(fps):
    ratio, span = measured_output_rate([(0., 0), (5., 10), (95., 10 + fps * 90)], fps)
    assert ratio == 1 and span == 90
    slow, _ = measured_output_rate([(5., 0), (95., int(fps * 90 * .976))], fps)
    assert slow < .985


@pytest.mark.parametrize("samples,fps", [
    ([], 30), ([(5., 0)], 30), ([(5., 0), (15., 300)], 30),
    ([(5., 100), (95., 99)], 30), ([(5., 0), (float("nan"), 2700)], 30),
    ([(5., 0), (95., 2700)], 0), ([(5., 0), (95., True)], 30),
])
def test_invalid_or_short_output_measurement_cannot_pass(samples, fps):
    assert measured_output_rate(samples, fps)[0] == 0


def test_tone_remains_available_for_non_music_probes(tmp_path):
    audio, label = select_audio(tmp_path / "tone.wav", "tone")
    assert audio.is_file() and label == "test_tone"


def test_real_hourly_music_is_read_only_and_never_regenerated(monkeypatch, tmp_path):
    from unittest.mock import MagicMock
    from app import browser_camera_preflight as probe
    handle = MagicMock()
    handle.getnframes.return_value = 3600 * 24000
    handle.getframerate.return_value = 24000
    handle.getnchannels.return_value = 2
    handle.getsampwidth.return_value = 2
    handle.getcomptype.return_value = "NONE"
    handle.readframes.return_value = b"\0" * 4
    opener = MagicMock()
    opener.return_value.__enter__.return_value = handle
    monkeypatch.setattr(probe.wave, "open", opener)
    audio, label = select_audio(tmp_path / "unused.wav", "hourly")
    assert audio == probe.HOURLY_MUSIC and label == "hourly_lofi_read_only"
    opener.assert_called_once_with(str(probe.HOURLY_MUSIC), "rb")
    handle.setpos.assert_called_once_with(3600 * 24000 - 1)
    assert not (tmp_path / "unused.wav").exists()
    handle.readframes.return_value = b""
    with pytest.raises(ValueError, match="incompleta"):
        select_audio(tmp_path / "unused.wav", "hourly")
    handle.getnframes.return_value = 10
    with pytest.raises(ValueError, match="no es valida"):
        select_audio(tmp_path / "unused.wav", "hourly")


def test_no_arbitrary_probe_music_path(tmp_path):
    with pytest.raises(ValueError, match="no permitido"):
        select_audio(tmp_path / "tone.wav", "/private/token.json")


def test_trial_uses_distinct_image_and_only_read_only_music_mount():
    import yaml
    compose = yaml.safe_load((Path(__file__).parents[1] / "compose.camera-browser-staging.yaml").read_text())
    assert compose["services"]["camera-browser"]["image"].endswith(":fps-trial")
    staging = compose["services"]["camera-staging"]
    assert staging["environment"]["ISS_CAMERA_PROBE_MUSIC"] == "hourly"
    assert staging["volumes"] == ["/srv/data/appdata/astrolearner-iss-live/music:/production-music:ro"]
