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
