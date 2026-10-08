import struct
import wave

from app.audio import generate_ambient_track


def test_ambient_track_crossfades_section_boundaries(tmp_path) -> None:
    output = tmp_path / "ambient.wav"
    generate_ambient_track(output, 12.01, "continuity-check")

    with wave.open(str(output), "rb") as recording:
        recording.setpos(12 * recording.getframerate() - 1)
        before, after = struct.unpack("<2h", recording.readframes(2))

    assert abs(after - before) < 1000
