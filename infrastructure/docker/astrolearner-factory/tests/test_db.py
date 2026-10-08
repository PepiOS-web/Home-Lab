from app.db import Database
from app.schemas import ContentPackage


def package() -> ContentPackage:
    return ContentPackage.model_validate(
        {
            "language": "es-ES",
            "title_options": ["Título uno", "Título dos", "Título tres"],
            "selected_title": "Título uno",
            "description": "Descripción suficientemente extensa para explicar el contenido científico del vídeo con claridad.",
            "thumbnail_text": "MISTERIO CÓSMICO",
            "segments": [
                {
                    "heading": f"Sección {index}",
                    "narration": "Narración basada exclusivamente en una fuente identificada y revisable.",
                    "visual_direction": "Diagrama original claramente identificado.",
                    "source_ids": ["S1"],
                }
                for index in range(1, 4)
            ],
            "shorts": [
                {
                    "title": "Un dato sorprendente",
                    "hook": "Hay un detalle que cambia por completo esta historia.",
                    "body": "La explicación se apoya en la fuente científica capturada.",
                    "call_to_action": "Descubre la historia completa en AstroLearner.",
                    "source_ids": ["S1"],
                }
            ],
            "source_summary": ["Resumen basado en S1"],
            "warnings": [],
        }
    )


def test_state_machine_requires_two_approvals(tmp_path) -> None:
    database = Database(tmp_path / "factory.sqlite3")
    database.initialize()
    job_id = database.create_job(
        "Un tema astronómico comprobable",
        ["https://science.nasa.gov/example"],
        90,
    )

    claimed = database.claim_next_job()
    assert claimed is not None
    job, action = claimed
    assert action == "generate"
    assert job.status == "processing"

    database.complete_generation(job_id, package(), str(tmp_path / job_id))
    assert database.get_job(job_id).status == "script_ready"

    edited = package().model_copy(
        update={
            "selected_title": "Título dos",
            "description": (
                "Descripción corregida manualmente y suficientemente extensa "
                "para mantener una revisión científica trazable."
            ),
        }
    )
    database.update_package(job_id, edited)
    updated = database.get_job(job_id)
    assert updated.status == "script_ready"
    assert updated.package.selected_title == "Título dos"
    assert "corregida manualmente" in updated.package.description

    database.approve_script_and_queue_render(job_id)
    claimed = database.claim_next_job()
    assert claimed is not None
    job, action = claimed
    assert action == "render"
    assert job.approved_script_at is not None

    database.complete_render(job_id, "a" * 64)
    assert database.get_job(job_id).status == "review_required"

    database.approve_render(job_id)
    final = database.get_job(job_id)
    assert final.status == "approved"
    assert final.approved_render_at is not None


def test_rejected_script_never_queues_render(tmp_path) -> None:
    database = Database(tmp_path / "factory.sqlite3")
    database.initialize()
    job_id = database.create_job(
        "Otro tema astronómico comprobable",
        ["https://science.nasa.gov/example"],
        60,
    )
    database.claim_next_job()
    database.complete_generation(job_id, package(), str(tmp_path / job_id))

    database.reject_script(job_id)

    rejected = database.get_job(job_id)
    assert rejected.status == "rejected"
    assert rejected.pending_action is None
    assert database.claim_next_job() is None


def test_completed_render_can_be_queued_again(tmp_path) -> None:
    database = Database(tmp_path / "factory.sqlite3")
    database.initialize()
    job_id = database.create_job(
        "Un tema que necesita nuevas ilustraciones",
        ["https://science.nasa.gov/example"],
        60,
    )
    database.claim_next_job()
    database.complete_generation(job_id, package(), str(tmp_path / job_id))
    database.approve_script_and_queue_render(job_id)
    database.claim_next_job()
    database.complete_render(job_id, "a" * 64)

    database.queue_rerender(job_id)

    queued = database.get_job(job_id)
    assert queued.status == "queued"
    assert queued.pending_action == "render"
    assert queued.approved_render_at is None


def test_interrupted_job_is_recovered_as_failed(tmp_path) -> None:
    database = Database(tmp_path / "factory.sqlite3")
    database.initialize()
    job_id = database.create_job(
        "Un trabajo interrumpido durante la generación",
        ["https://science.nasa.gov/example"],
        60,
    )
    database.claim_next_job()

    assert database.recover_interrupted_jobs() == 1

    recovered = database.get_job(job_id)
    assert recovered.status == "failed"
    assert recovered.pending_action is None
    assert "reinició" in recovered.error
