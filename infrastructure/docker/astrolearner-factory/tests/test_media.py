import json
from types import SimpleNamespace

from app import media
from app.schemas import ContentPackage


def _package() -> ContentPackage:
    return ContentPackage.model_validate(
        {
            "language": "es-ES",
            "title_options": ["Un título científico", "Otro título", "Tercer título"],
            "selected_title": "Un título científico",
            "description": (
                "Una descripción suficientemente detallada del tema científico "
                "para explicar el valor educativo de este vídeo."
            ),
            "thumbnail_text": "EL ESPACIO",
            "segments": [
                {
                    "heading": f"Sección {index}",
                    "narration": "La narración explica este hecho científico con detalle suficiente.",
                    "visual_direction": "Diagrama esquemático de astronomía.",
                    "visual_kind": "orbit",
                    "source_ids": ["S1"],
                }
                for index in range(1, 4)
            ],
            "shorts": [
                {
                    "title": f"Short de ciencia número {index}",
                    "hook": "Una pregunta científica sorprendente para empezar.",
                    "body": "La explicación resume el hecho con claridad y sin exagerarlo.",
                    "call_to_action": "Descubre más ciencia en AstroLearner.",
                    "source_ids": ["S1"],
                }
                for index in range(1, 4)
            ],
            "source_summary": ["Resumen basado en S1"],
            "warnings": [],
        }
    )


def test_render_package_outputs_all_shorts_and_captions(tmp_path, monkeypatch) -> None:
    rendered: list[str] = []

    def fake_thumbnail(path, package):
        path.write_bytes(b"thumbnail")

    def fake_sequence(sequence, output, captions, settings, **kwargs):
        rendered.append(kwargs["prefix"])
        output.write_bytes(kwargs["prefix"].encode())
        captions.write_text("captions", encoding="utf-8")
        return {"visual_kinds": ["orbit"], "music": {"seed": kwargs["prefix"]}}

    monkeypatch.setattr(media, "make_thumbnail", fake_thumbnail)
    monkeypatch.setattr(media, "_render_sequence", fake_sequence)

    digest = media.render_package(
        "job-1",
        _package(),
        tmp_path,
        SimpleNamespace(tts_voice="es_ES-davefx-medium"),
    )

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert rendered == ["long", "short-01", "short-02", "short-03"]
    assert manifest["artifacts"]["short_03"] == "render/short-03.mp4"
    assert manifest["artifacts"]["short_03_captions"] == "render/short-03-es.srt"
    assert len(digest) == 64


def test_derived_short_is_additive_and_keeps_existing_shorts(tmp_path, monkeypatch) -> None:
    package = _package()
    excerpt = " ".join(["fragmento"] * 45) + "."
    package = ContentPackage.model_validate(
        {
            **package.model_dump(),
            "derived_short": {
                "title": "Fragmento del vídeo largo",
                "excerpt": excerpt,
                "segment_index": 1,
                "source_ids": ["S1"],
            },
        }
    )
    rendered: list[tuple[str, dict[str, object]]] = []

    def fake_thumbnail(path, package):
        path.write_bytes(b"thumbnail")

    def fake_sequence(sequence, output, captions, settings, **kwargs):
        rendered.append((kwargs["prefix"], kwargs))
        output.write_bytes(kwargs["prefix"].encode())
        captions.write_text("captions", encoding="utf-8")
        return {"visual_kinds": ["orbit"], "music": {"seed": kwargs["prefix"]}}

    monkeypatch.setattr(media, "make_thumbnail", fake_thumbnail)
    monkeypatch.setattr(media, "_render_sequence", fake_sequence)

    media.render_package(
        "job-2",
        package,
        tmp_path,
        SimpleNamespace(tts_voice="es_ES-davefx-medium"),
    )

    prefixes = [prefix for prefix, _ in rendered]
    assert prefixes == ["long", "short-01", "short-02", "short-03", "short-from-long"]
    derived_kwargs = rendered[-1][1]
    assert derived_kwargs["scene_offset"] == 1
    assert derived_kwargs["scene_clips_dir"] == tmp_path / "assets"
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"]["short_01"] == "render/short-01.mp4"
    assert manifest["artifacts"]["short_from_long"] == "render/short-from-long.mp4"
    assert manifest["derived_short"]["selection"] == "literal_contiguous_script_excerpt"


def test_ai_clip_render_uses_local_video_and_the_voice_track_only(tmp_path, monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)

    monkeypatch.setattr(media, "_run", fake_run)
    media._render_segment_with_clip(
        tmp_path / "art.png",
        tmp_path / "voice.wav",
        tmp_path / "scene-01.mp4",
        tmp_path / "output.mp4",
        35.0,
        1080,
        1920,
        SimpleNamespace(ffmpeg_threads=2),
    )

    command = commands[0]
    clip_index = command.index(str(tmp_path / "scene-01.mp4"))
    assert command[clip_index - 1] == "-i"
    assert "-protocol_whitelist" in command
    assert command[command.index("-protocol_whitelist") + 1] == "file"
    assert command[command.index("-map") + 1] == "[v]"
    audio_map_index = command.index("-map", command.index("-map") + 1)
    assert command[audio_map_index + 1] == "1:a:0"
