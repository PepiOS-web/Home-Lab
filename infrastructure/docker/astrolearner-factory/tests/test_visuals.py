from app.audio import ambient_seed
from app.visuals import resolve_visual_kind


def test_visual_kind_resolves_moon_scenes() -> None:
    assert (
        resolve_visual_kind(
            "La luz y la Luna",
            "El Sol ilumina la mitad de la Luna",
        )
        == "moon_light"
    )
    assert (
        resolve_visual_kind(
            "Las ocho fases",
            "Diagrama etiquetado de las fases",
        )
        == "moon_phases"
    )
    assert (
        resolve_visual_kind(
            "Un ciclo de 29,5 días",
            "Calendario orbital alrededor de la Tierra",
        )
        == "orbit"
    )
    assert (
        resolve_visual_kind(
            "Eclipse de Sol",
            "La Luna bloquea la luz del Sol",
        )
        == "eclipse"
    )


def test_explicit_visual_kind_is_preserved() -> None:
    assert resolve_visual_kind("Tema", "Dirección", "telescope") == "telescope"


def test_music_seed_is_deterministic() -> None:
    assert ambient_seed("master-1080p") == ambient_seed("master-1080p")
    assert ambient_seed("master-1080p") != ambient_seed("short-01")
