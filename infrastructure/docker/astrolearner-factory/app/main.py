from __future__ import annotations

import json
import logging
import math
import os
import secrets
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from starlette.datastructures import UploadFile
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import settings
from .db import Database
from .llm import _derive_short_from_long, ollama_health, validate_package_length
from .pipeline import save_content_package
from .schemas import ContentPackage
from .sources import validate_source_url
from .worker import SerialWorker

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
LOGGER = logging.getLogger(__name__)

settings.ensure_directories()
database = Database(settings.database_path)
worker = SerialWorker(database, settings)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
CSRF_TOKEN = secrets.token_urlsafe(32)
MAX_FORM_BYTES = 200_000
MAX_SCENE_CLIP_BYTES = 80 * 1024 * 1024
MAX_JOB_SCENE_CLIPS_BYTES = 256 * 1024 * 1024
MAX_SCENE_CLIP_DURATION = 20.0
MAX_SCENE_CLIP_DIMENSION = 3840


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    recovered = database.recover_interrupted_jobs()
    if recovered:
        LOGGER.warning("Se marcaron %s trabajos interrumpidos como fallidos", recovered)
    worker.start()
    yield
    worker.stop()


app = FastAPI(
    title="AstroLearner Factory",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["127.0.0.1", "localhost"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        content_length = request.headers.get("content-length")
        is_scene_clip_upload = (
            request.method == "POST"
            and request.url.path.startswith("/jobs/")
            and "/segments/" in request.url.path
            and request.url.path.endswith("/clip")
        )
        max_body_bytes = (
            MAX_SCENE_CLIP_BYTES + 1024 * 1024
            if is_scene_clip_upload
            else MAX_FORM_BYTES
        )
        if is_scene_clip_upload and not content_length:
            return JSONResponse(
                {"detail": "La subida debe incluir Content-Length"},
                status_code=411,
            )
        if content_length:
            try:
                if int(content_length) > max_body_bytes:
                    return JSONResponse(
                        {"detail": "El formulario supera el límite permitido"},
                        status_code=413,
                    )
            except ValueError:
                return JSONResponse(
                    {"detail": "Content-Length no válido"}, status_code=400
                )

        origin = request.headers.get("origin")
        # Sandboxed local webviews can emit the opaque Origin value "null".
        # The per-process CSRF secret remains mandatory and TrustedHost still
        # restricts the request target to loopback hostnames.
        if origin and origin != "null":
            parsed_origin = urlsplit(origin)
            if (
                parsed_origin.scheme != "http"
                or parsed_origin.hostname not in {"127.0.0.1", "localhost"}
                or parsed_origin.username is not None
                or parsed_origin.password is not None
            ):
                return JSONResponse(
                    {"detail": "Origen del formulario no permitido"},
                    status_code=403,
                )

    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; media-src 'self'; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    )
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


def _split_source_urls(raw: str) -> list[str]:
    urls: list[str] = []
    for line in raw.replace(",", "\n").splitlines():
        candidate = line.strip()
        if candidate and candidate not in urls:
            urls.append(candidate)
    return urls


def _required_form_text(form, name: str) -> str:
    value = form.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Falta el campo {name}")
    return value.strip()


def _form_lines(form, name: str) -> list[str]:
    return [
        line.strip()
        for line in _required_form_text(form, name).splitlines()
        if line.strip()
    ]


def _require_csrf(value: str | None) -> None:
    if not value or not secrets.compare_digest(value, CSRF_TOKEN):
        raise HTTPException(status_code=403, detail="Formulario caducado o no válido")


@app.get("/health")
def health() -> JSONResponse:
    disk = shutil.disk_usage(settings.data_dir)
    ollama = ollama_health(settings)
    ready = bool(ollama.get("available") and ollama.get("model_present"))
    return JSONResponse(
        {
            "status": "ok" if ready else "degraded",
            "database": str(settings.database_path),
            "disk_free_gib": round(disk.free / 1024**3, 2),
            "ollama": ollama,
            "publication_enabled": False,
        },
        status_code=200 if ready else 503,
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "jobs": database.list_jobs(),
            "model": settings.model,
            "allowed_hosts": settings.allowed_source_hosts,
            "csrf_token": CSRF_TOKEN,
        },
    )


@app.post("/jobs")
def create_job(
    topic: str = Form(...),
    source_urls: str = Form(...),
    target_seconds: int = Form(90),
    csrf_token: str = Form(...),
) -> RedirectResponse:
    _require_csrf(csrf_token)
    normalized_topic = " ".join(topic.split())
    if not 8 <= len(normalized_topic) <= 240:
        raise HTTPException(
            status_code=400, detail="El tema debe tener entre 8 y 240 caracteres"
        )
    if len(source_urls) > 10_000:
        raise HTTPException(
            status_code=400, detail="La lista de fuentes es demasiado larga"
        )
    urls = _split_source_urls(source_urls)
    if not 1 <= len(urls) <= 5:
        raise HTTPException(status_code=400, detail="Añade entre 1 y 5 URLs de fuentes")
    if not 45 <= target_seconds <= 360:
        raise HTTPException(
            status_code=400, detail="La duración debe estar entre 45 y 360 segundos"
        )
    try:
        for url in urls:
            validate_source_url(url, settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job_id = database.create_job(normalized_topic, urls, target_seconds)
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(request: Request, job_id: str) -> HTMLResponse:
    job = database.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    scene_clips: list[bool] = []
    if job.package and job.output_dir:
        job_dir = Path(job.output_dir).resolve()
        if job_dir.is_relative_to(settings.jobs_dir.resolve()):
            assets_dir = job_dir / "assets"
            scene_clips = [
                (assets_dir / f"scene-{index:02d}.mp4").is_file()
                for index in range(1, len(job.package.segments) + 1)
            ]
    return templates.TemplateResponse(
        request=request,
        name="job.html",
        context={
            "job": job,
            "events": database.get_events(job_id),
            "csrf_token": CSRF_TOKEN,
            "scene_clips": scene_clips,
        },
    )


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> JSONResponse:
    job = database.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    return JSONResponse(job.model_dump(mode="json"))


@app.post("/jobs/{job_id}/approve-script")
def approve_script(job_id: str, csrf_token: str = Form(...)) -> RedirectResponse:
    _require_csrf(csrf_token)
    try:
        database.approve_script_and_queue_render(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@app.post("/jobs/{job_id}/reject-script")
def reject_script(job_id: str, csrf_token: str = Form(...)) -> RedirectResponse:
    _require_csrf(csrf_token)
    try:
        database.reject_script(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@app.post("/jobs/{job_id}/edit-script")
async def edit_script(request: Request, job_id: str) -> RedirectResponse:
    job = database.get_job(job_id)
    if (
        job is None
        or job.status != "script_ready"
        or job.package is None
        or job.output_dir is None
    ):
        raise HTTPException(
            status_code=409,
            detail="Solo se puede editar un guion pendiente de aprobación",
        )

    form = await request.form()
    try:
        _require_csrf(str(form.get("csrf_token", "")))
        segments = []
        for index, original in enumerate(job.package.segments):
            segments.append(
                {
                    "heading": _required_form_text(form, f"segment_heading_{index}"),
                    "narration": _required_form_text(
                        form, f"segment_narration_{index}"
                    ),
                    "visual_direction": _required_form_text(
                        form, f"segment_visual_{index}"
                    ),
                    "visual_kind": _required_form_text(
                        form, f"segment_visual_kind_{index}"
                    ),
                    "video_prompt_en": (
                        str(form.get(f"segment_video_prompt_{index}", "")).strip()
                        or None
                    ),
                    "source_ids": original.source_ids,
                }
            )

        shorts = []
        for index, original in enumerate(job.package.shorts):
            shorts.append(
                {
                    "title": _required_form_text(form, f"short_title_{index}"),
                    "hook": _required_form_text(form, f"short_hook_{index}"),
                    "body": _required_form_text(form, f"short_body_{index}"),
                    "call_to_action": _required_form_text(
                        form, f"short_call_to_action_{index}"
                    ),
                    "source_ids": original.source_ids,
                }
            )

        package = ContentPackage.model_validate(
            {
                "language": "es-ES",
                "title_options": _form_lines(form, "title_options"),
                "selected_title": _required_form_text(form, "selected_title"),
                "description": _required_form_text(form, "description"),
                "thumbnail_text": _required_form_text(form, "thumbnail_text"),
                "segments": segments,
                "shorts": shorts,
                "source_summary": _form_lines(form, "source_summary"),
                "warnings": [
                    line.strip()
                    for line in str(form.get("warnings", "")).splitlines()
                    if line.strip()
                ],
            }
        )
        validate_package_length(package, job.target_seconds)
        package = package.model_copy(
            update={
                "derived_short": _derive_short_from_long(
                    package, job.target_seconds
                )
            }
        )
    except (ValueError, ValidationError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Los cambios no son válidos: {exc}",
        ) from exc

    job_dir = Path(job.output_dir).resolve()
    if not job_dir.is_relative_to(settings.jobs_dir.resolve()):
        raise HTTPException(status_code=500, detail="Ruta de trabajo no válida")
    save_content_package(job_dir, package)
    database.update_package(job_id, package)
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@app.post("/jobs/{job_id}/segments/{segment_index}/clip")
async def upload_scene_clip(
    request: Request, job_id: str, segment_index: int
) -> RedirectResponse:
    """Attach one short, local MP4 insert to a long-video script segment."""
    job = database.get_job(job_id)
    if (
        job is None
        or job.status != "script_ready"
        or job.package is None
        or job.output_dir is None
    ):
        raise HTTPException(
            status_code=409,
            detail="Solo puedes añadir escenas antes de aprobar el guion",
        )
    if not 0 <= segment_index < len(job.package.segments):
        raise HTTPException(status_code=404, detail="Segmento no encontrado")

    form = await request.form(
        max_files=1,
        max_fields=2,
        max_part_size=MAX_SCENE_CLIP_BYTES,
    )
    try:
        _require_csrf(str(form.get("csrf_token", "")))
        upload = form.get("clip")
        if not isinstance(upload, UploadFile):
            raise HTTPException(status_code=400, detail="Selecciona un archivo MP4")
        if Path(upload.filename or "").suffix.lower() != ".mp4":
            raise HTTPException(status_code=400, detail="Solo se aceptan archivos .mp4")
        if upload.content_type not in {"video/mp4", "application/octet-stream"}:
            raise HTTPException(status_code=400, detail="El archivo debe ser un MP4")

        job_dir = Path(job.output_dir).resolve()
        if not job_dir.is_relative_to(settings.jobs_dir.resolve()):
            raise HTTPException(status_code=500, detail="Ruta de trabajo no válida")
        assets_dir = job_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        if not assets_dir.resolve().is_relative_to(job_dir):
            raise HTTPException(status_code=500, detail="Ruta de escenas no válida")

        clip_number = segment_index + 1
        target = assets_dir / f"scene-{clip_number:02d}.mp4"
        temporary = assets_dir / f".scene-{clip_number:02d}-{secrets.token_hex(8)}.part"
        received = 0
        try:
            with temporary.open("xb") as output:
                while chunk := await upload.read(1024 * 1024):
                    received += len(chunk)
                    if received > MAX_SCENE_CLIP_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail="El clip supera el máximo de 80 MiB",
                        )
                    output.write(chunk)
            if received < 1024:
                raise HTTPException(
                    status_code=400, detail="El clip está vacío o incompleto"
                )

            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_name,width,height,duration:format=duration",
                    "-of",
                    "json",
                    str(temporary),
                ],
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
            if probe.returncode != 0:
                raise HTTPException(status_code=400, detail="FFprobe no reconoce el clip")
            try:
                metadata = json.loads(probe.stdout)
                video_streams = metadata.get("streams", [])
                stream = video_streams[0] if video_streams else {}
                duration = float(
                    metadata.get("format", {}).get("duration")
                    or stream.get("duration")
                    or 0
                )
                width = int(stream.get("width", 0))
                height = int(stream.get("height", 0))
                codec = stream.get("codec_name")
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                raise HTTPException(
                    status_code=400, detail="Metadatos de vídeo no válidos"
                ) from exc

            if codec != "h264":
                raise HTTPException(
                    status_code=400,
                    detail="El clip debe usar vídeo H.264 dentro del contenedor MP4",
                )
            if not (256 <= width <= MAX_SCENE_CLIP_DIMENSION) or not (
                256 <= height <= MAX_SCENE_CLIP_DIMENSION
            ):
                raise HTTPException(
                    status_code=400,
                    detail="La resolución del clip debe estar entre 256 y 3840 píxeles",
                )
            if not math.isfinite(duration) or not 1 <= duration <= MAX_SCENE_CLIP_DURATION:
                raise HTTPException(
                    status_code=400,
                    detail="La duración del clip debe estar entre 1 y 20 segundos",
                )

            # Serialize the final status check, aggregate-size check and atomic
            # rename with other uploads and the approve-script DB transition.
            # This prevents a concurrent approval from rendering mid-upload and
            # stops parallel requests from exceeding the per-job storage cap.
            with database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                latest_job = connection.execute(
                    "SELECT status FROM jobs WHERE id = ?", (job_id,)
                ).fetchone()
                if latest_job is None or latest_job["status"] != "script_ready":
                    raise HTTPException(
                        status_code=409,
                        detail="El guion se aprobó mientras se subía el clip; no se guardó",
                    )
                existing_bytes = sum(
                    path.stat().st_size
                    for path in assets_dir.glob("scene-*.mp4")
                    if path.is_file() and path != target
                )
                if existing_bytes + received > MAX_JOB_SCENE_CLIPS_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Los clips de este trabajo superarían el límite de 256 MiB",
                    )
                os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    except HTTPException:
        raise
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOGGER.warning("No se pudo validar el clip de escena: %s", exc)
        raise HTTPException(
            status_code=400, detail="No se pudo guardar o validar el clip"
        ) from exc
    finally:
        await form.close()

    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@app.post("/jobs/{job_id}/approve-render")
def approve_render(job_id: str, csrf_token: str = Form(...)) -> RedirectResponse:
    _require_csrf(csrf_token)
    try:
        database.approve_render(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@app.post("/jobs/{job_id}/retry")
def retry(job_id: str, csrf_token: str = Form(...)) -> RedirectResponse:
    _require_csrf(csrf_token)
    job = database.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    if job.status != "failed":
        raise HTTPException(
            status_code=409, detail="Solo se pueden reintentar trabajos fallidos"
        )
    if job.package and job.approved_script_at:
        database.queue_action(job_id, "render", "Reintento del render solicitado")
    else:
        database.queue_action(job_id, "generate", "Reintento de generación solicitado")
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@app.post("/jobs/{job_id}/rerender")
def rerender(job_id: str, csrf_token: str = Form(...)) -> RedirectResponse:
    _require_csrf(csrf_token)
    try:
        database.queue_rerender(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@app.get("/artifacts/{job_id}/{artifact_path:path}")
def artifact(job_id: str, artifact_path: str) -> FileResponse:
    job = database.get_job(job_id)
    if job is None or not job.output_dir:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    base = Path(job.output_dir).resolve()
    requested = (base / artifact_path).resolve()
    if not requested.is_relative_to(base) or not requested.is_file():
        raise HTTPException(status_code=404, detail="Artefacto no encontrado")
    return FileResponse(requested)
