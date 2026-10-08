from app.schemas import ContentPackage


def valid_payload() -> dict:
    return {
        "language": "es-ES",
        "title_options": ["Título uno", "Título dos", "Título tres"],
        "selected_title": "Título uno",
        "description": "Descripción suficientemente extensa para explicar el contenido científico del vídeo sin exageraciones.",
        "thumbnail_text": "UN MUNDO EXTRAÑO",
        "segments": [
            {
                "heading": f"Sección {index}",
                "narration": "Esta narración contiene suficiente contenido para superar la validación mínima.",
                "visual_direction": "Diagrama original y claramente etiquetado.",
                "source_ids": ["S1"],
            }
            for index in range(1, 4)
        ],
        "shorts": [
            {
                "title": "Un dato sorprendente",
                "hook": "Hay un detalle que cambia por completo esta historia.",
                "body": "La explicación se apoya en la misma fuente científica y evita exageraciones.",
                "call_to_action": "Descubre la historia completa en AstroLearner.",
                "source_ids": ["S1"],
            }
        ],
        "source_summary": ["Resumen basado en S1"],
        "warnings": [],
    }


def test_selected_title_must_be_in_options() -> None:
    payload = valid_payload()
    payload["selected_title"] = "Título inexistente"
    try:
        ContentPackage.model_validate(payload)
    except ValueError:
        return
    raise AssertionError("La validación aceptó un título no propuesto")


def test_valid_package() -> None:
    package = ContentPackage.model_validate(valid_payload())
    assert package.language == "es-ES"
    assert len(package.segments) == 3
