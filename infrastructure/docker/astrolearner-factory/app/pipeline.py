from __future__ import annotations

import json

from .config import Settings
from .db import Database
from .llm import generate_content_package
from .media import render_package
from .schemas import JobView
from .sources import capture_sources


def save_content_package(job_dir, package) -> None:
    (job_dir / "content-package.json").write_text(
        package.model_dump_json(indent=2), encoding="utf-8"
    )
    (job_dir / "script.txt").write_text(
        "\n\n".join(
            f"{segment.heading}\n{segment.narration}" for segment in package.segments
        )
        + "\n",
        encoding="utf-8",
    )


def generate_job(job: JobView, database: Database, settings: Settings) -> None:
    job_dir = settings.jobs_dir / job.id
    job_dir.mkdir(parents=True, exist_ok=True)

    database.set_progress(job.id, "Descargando y extrayendo las fuentes permitidas")
    sources = capture_sources(job.source_urls, settings)
    (job_dir / "sources.json").write_text(
        json.dumps(
            [source.model_dump(mode="json") for source in sources],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    database.set_progress(job.id, f"Generando el guion local con {settings.model}")
    package, metrics, draft = generate_content_package(
        job.topic,
        job.target_seconds,
        sources,
        settings,
        progress_callback=lambda message: database.set_progress(job.id, message),
    )
    (job_dir / "draft-content-package.json").write_text(
        draft.model_dump_json(indent=2), encoding="utf-8"
    )
    save_content_package(job_dir, package)
    (job_dir / "generation-metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    database.complete_generation(job.id, package, str(job_dir))


def render_job(job: JobView, database: Database, settings: Settings) -> None:
    if not job.package:
        raise ValueError("No hay paquete de contenido para renderizar")
    if not job.approved_script_at:
        raise ValueError("El guion no cuenta con aprobación humana")
    job_dir = settings.jobs_dir / job.id
    database.set_progress(
        job.id, "Generando narración y vídeo; puede tardar varios minutos"
    )
    render_hash = render_package(job.id, job.package, job_dir, settings)
    database.complete_render(job.id, render_hash)
