from pathlib import Path
from subprocess import CompletedProcess

from app.nasa_media import _build_normalized_loop


def test_nasa_media_builds_one_normalized_loop_file(monkeypatch, tmp_path: Path):
    source_one = tmp_path / "one.mp4"
    source_two = tmp_path / "two.mp4"
    source_one.touch()
    source_two.touch()
    videos = [
        {"filename": source_one.name, "sha256": "a" * 64},
        {"filename": source_two.name, "sha256": "b" * 64},
    ]
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[0] == "ffmpeg":
            Path(command[-1]).write_bytes(b"normalized-loop")
            return CompletedProcess(command, 0)
        return CompletedProcess(command, 0, stdout="1800.0\n")

    monkeypatch.setattr("app.nasa_media.subprocess.run", fake_run)

    result = _build_normalized_loop(tmp_path, videos)

    assert result["filename"] == "astrolearner-nasa-loop.mp4"
    assert result["duration_seconds"] == 1800.0
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["fps"] == 12
    command = calls[0]
    graph = command[command.index("-filter_complex") + 1]
    assert "concat=n=2:v=1:a=0" in graph
    assert "trim=duration=900" in graph
    assert command[-1].endswith("astrolearner-nasa-loop.tmp.mp4")
