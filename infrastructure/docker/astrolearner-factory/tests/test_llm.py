import pytest

from app.llm import (
    _derive_short_from_long,
    _length_revision_prompt,
    _needs_narration_revision,
    _narration_bounds,
    _narration_word_count,
    _source_bundle,
    _validate_model_json,
    validate_package_length,
)
from app.schemas import AuditedContent, CapturedSource, ContentPackage


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


def test_six_minute_narration_bounds_match_duration_target() -> None:
    package = package_with_lengths(segment_count=6)

    assert _narration_bounds(360) == (774, 542, 1045)
    assert _narration_word_count(package) == 210
    assert _needs_narration_revision(package, 360)
    assert not _needs_narration_revision(package_with_lengths(), 60)


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


def test_audit_source_bundle_caps_each_excerpt_without_losing_source_identity() -> None:
    source = CapturedSource(
        id="S1",
        url="https://science.nasa.gov/moon/",
        title="La Luna",
        excerpt="dato " * 500,
        retrieved_at="2026-10-09T00:00:00+00:00",
        sha256="0" * 64,
    )

    bundle = _source_bundle([source], max_excerpt_chars=100)

    assert '<FUENTE id="S1">' in bundle
    assert str(source.url) in bundle
    assert "[extracto reducido para auditoría]" in bundle
    assert len(bundle) < 400


def test_length_revision_prompt_requests_target_duration_without_padding() -> None:
    source = CapturedSource(
        id="S1",
        url="https://science.nasa.gov/moon/",
        title="La Luna",
        excerpt="La Luna refleja la luz del Sol. " * 60,
        retrieved_at="2026-10-09T00:00:00+00:00",
        sha256="0" * 64,
    )

    prompt = _length_revision_prompt(
        "Fases lunares", 360, [source], package_with_lengths(segment_count=6)
    )
    prompt = " ".join(prompt.split())

    assert "entre 542 y 1045 palabras" in prompt
    assert "unas 774 palabras" in prompt
    assert "no repitas contenido, no rellenes" in prompt


def test_derived_short_is_a_literal_sentence_bounded_excerpt() -> None:
    package = package_with_lengths()
    sentence = (
        "La Luna cambia de aspecto según la parte iluminada que vemos desde la Tierra."
    )
    first = package.segments[0].model_copy(
        update={"narration": " ".join([sentence] * 4)}
    )
    package = package.model_copy(update={"segments": [first, *package.segments[1:]]})

    derived = _derive_short_from_long(package, 360)

    assert derived is not None
    assert derived.excerpt in first.narration
    assert 45 <= len(derived.excerpt.split()) <= 95
    assert derived.segment_index == 0


def test_derived_short_is_skipped_for_short_pilot() -> None:
    assert _derive_short_from_long(package_with_lengths(), 90) is None
