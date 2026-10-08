import pytest

from app.llm import _validate_model_json, validate_package_length
from app.schemas import AuditedContent, ContentPackage


def package_with_lengths(*, segment_count: int = 3, short_words: int = 60):
    narration = " ".join(["dato"] * 35)
    short_text = " ".join(["dato"] * short_words)
    return ContentPackage.model_validate(
        {
            "language": "es-ES",
            "title_options": ["Título uno", "Título dos", "Título tres"],
            "selected_title": "Título uno",
            "description": (
                "Descripción suficientemente extensa para explicar el contenido "
                "científico del vídeo sin exageraciones."
            ),
            "thumbnail_text": "UN DATO CLARO",
            "segments": [
                {
                    "heading": f"Sección {index}",
                    "narration": narration,
                    "visual_direction": "Diagrama original claramente etiquetado.",
                    "source_ids": ["S1"],
                }
                for index in range(1, segment_count + 1)
            ],
            "shorts": [
                {
                    "title": "Un dato sorprendente",
                    "hook": "Una pregunta científica importante.",
                    "body": short_text,
                    "call_to_action": "Consulta el vídeo completo.",
                    "source_ids": ["S1"],
                }
            ],
            "source_summary": ["Resumen basado en S1"],
            "warnings": [],
        }
    )


def test_duration_validation_accepts_bounded_script() -> None:
    validate_package_length(package_with_lengths(), 60)


def test_duration_validation_rejects_wrong_segment_count() -> None:
    with pytest.raises(ValueError, match="se esperaban 3"):
        validate_package_length(package_with_lengths(segment_count=4), 60)


def test_duration_validation_rejects_oversized_short() -> None:
    with pytest.raises(ValueError, match="Short 1"):
        validate_package_length(package_with_lengths(short_words=120), 60)


def test_model_json_parser_accepts_markdown_fence() -> None:
    package = package_with_lengths().model_dump_json()

    parsed = _validate_model_json(f"```json\n{package}\n```", ContentPackage)

    assert parsed.selected_title == "Título uno"


def test_model_json_parser_accepts_preamble_and_braces_inside_strings() -> None:
    package = package_with_lengths().model_dump_json()

    parsed = _validate_model_json(
        f"Aquí está el resultado:\n{package}\nFin.", ContentPackage
    )

    assert len(parsed.segments) == 3


def test_model_json_parser_keeps_audit_schema_validation() -> None:
    package = package_with_lengths().model_dump_json()
    audited = '{"content": ' + package + ', "corrections": []}'

    parsed = _validate_model_json(f"```json\n{audited}\n```", AuditedContent)

    assert parsed.corrections == []
    assert parsed.content.selected_title == "Título uno"


def test_model_json_parser_rejects_invalid_schema() -> None:
    with pytest.raises(ValueError):
        _validate_model_json('```json\n{"content": {}}\n```', AuditedContent)
