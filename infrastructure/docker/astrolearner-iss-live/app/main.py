from __future__ import annotations

import asyncio
import io
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse, Response
from PIL import Image
from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr

from .config import Settings
from .control_auth import ControlAuthError, authorize_control
from .control_sessions import COOKIE_NAME, COOKIE_PATH, SESSION_SECONDS, ControlSessions
from .controller import Controller
from .corner_map import render_corner_map
from .media import render_earth_frame, render_map
from .state import StateStore

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
settings = Settings()
settings.validate()
settings.status_dir.mkdir(parents=True, exist_ok=True)
store = StateStore(settings.status_dir / "status.json", settings.source_label)
controller = Controller(settings, store)
control_sessions = ControlSessions(settings.data_dir / "music" / ".control-sessions.json")


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.update(mode="simulacion" if settings.dry_run else "youtube")
    controller.start()
    try:
        yield
    finally:
        controller.shutdown()


app = FastAPI(
    title="AstroLearner ISS Live", docs_url=None, redoc_url=None, lifespan=lifespan
)


@app.get("/health")
def health() -> JSONResponse:
    state = store.snapshot()
    healthy = state["status"] != "error"
    return JSONResponse(
        {"status": "ok" if healthy else "error", "mode": state["mode"]},
        status_code=200 if healthy else 503,
    )


@app.get("/api/status")
def status() -> dict:
    return store.snapshot()


def _authorize_control(request: Request, *, read_only: bool = False) -> None:
    try:
        # Never fall back from an explicitly invalid Bearer token to a cookie.
        authorization = request.headers.get("authorization", "")
        session_authorized = not authorization and control_sessions.valid(
            request.cookies.get(COOKIE_NAME, ""), settings.control_token
        )
        authorize_control(
            request.headers.get("origin"),
            authorization,
            settings.control_token,
            allow_missing_origin=read_only,
            session_authorized=session_authorized,
        )
    except ControlAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.get("/session")
def get_control_session(request: Request) -> JSONResponse:
    try:
        _authorize_control(request, read_only=True)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        return JSONResponse({"authenticated": False}, headers={"Cache-Control": "no-store"})
    return JSONResponse({"authenticated": True}, headers={"Cache-Control": "no-store"})


@app.post("/session")
def create_control_session(request: Request) -> JSONResponse:
    try:
        # Only the actual control token can create/renew a remembered session.
        authorize_control(request.headers.get("origin"), request.headers.get("authorization", ""),
                          settings.control_token)
        value = control_sessions.create(settings.control_token, request.cookies.get(COOKIE_NAME, ""))
    except ControlAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    response = JSONResponse({"authenticated": True}, headers={"Cache-Control": "no-store"})
    response.set_cookie(COOKIE_NAME, value, max_age=SESSION_SECONDS, path=COOKIE_PATH,
                        secure=True, httponly=True, samesite="strict")
    return response


@app.post("/session/logout")
def delete_control_session(request: Request) -> JSONResponse:
    _authorize_control(request)
    try:
        control_sessions.revoke(request.cookies.get(COOKIE_NAME, ""), settings.control_token)
    except ControlAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    response = JSONResponse({"authenticated": False}, headers={"Cache-Control": "no-store"})
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH, secure=True, httponly=True, samesite="strict")
    return response


@app.post("/start")
def start_live(request: Request) -> JSONResponse:
    _authorize_control(request)
    try:
        controller.request_live_start()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(
        {"status": "inicio solicitado", "live_requested": True}, status_code=202
    )


@app.post("/stop")
def stop_live(request: Request) -> JSONResponse:
    _authorize_control(request)
    controller.request_live_stop()
    return JSONResponse({"status": "parada solicitada", "live_requested": False})


class MetadataInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: StrictStr
    description: StrictStr
    apply_to_current: StrictBool = False


class StarviosInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool
    key: StrictStr | None = None
    rotated_key_confirmed: StrictBool = False

class PresentationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dashboard_enabled: StrictBool
    recorded_fallback_enabled: StrictBool
    music_style: StrictStr


@app.get("/presentation")
def get_presentation(request: Request) -> JSONResponse:
    _authorize_control(request, read_only=True)
    return JSONResponse(controller.presentation_snapshot(), headers={"Cache-Control": "no-store"})


@app.post("/presentation")
async def set_presentation(request: Request) -> JSONResponse:
    _authorize_control(request)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 4096:
            raise HTTPException(status_code=413, detail="Formulario demasiado grande")
    try:
        value = PresentationInput.model_validate_json(body)
        result = await asyncio.to_thread(controller.save_presentation, **value.model_dump())
    except ValueError:
        raise HTTPException(status_code=422, detail="Preferencias de presentación no válidas") from None
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.get("/starvios")
def get_starvios(request: Request) -> JSONResponse:
    _authorize_control(request, read_only=True)
    try:
        result = controller.starvios_snapshot()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.post("/starvios")
async def set_starvios(request: Request) -> JSONResponse:
    _authorize_control(request)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 2048:
            raise HTTPException(status_code=413, detail="Formulario demasiado grande")
    try:
        value = StarviosInput.model_validate_json(body)
    except ValueError:
        # Never reflect a Pydantic input_value containing the stream key.
        raise HTTPException(status_code=422, detail="Configuración de Starvios no válida") from None
    try:
        result = await asyncio.to_thread(controller.save_starvios, **value.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.get("/metadata")
def get_metadata(request: Request) -> JSONResponse:
    _authorize_control(request, read_only=True)
    return JSONResponse(controller.metadata_snapshot(), headers={"Cache-Control": "no-store"})


@app.post("/metadata")
async def set_metadata(request: Request) -> JSONResponse:
    _authorize_control(request)
    # Bound the JSON before parsing; neither oversized drafts nor arbitrary video
    # IDs can reach the YouTube client. Unicode/escaped JSON needs some overhead.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 32768:
            raise HTTPException(status_code=413, detail="Formulario demasiado grande")
    try:
        value = MetadataInput.model_validate_json(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Formulario de título y descripción no válido") from exc
    try:
        # Google requests and disk writes must not block the ASGI event loop.
        result = await asyncio.to_thread(controller.save_metadata, **value.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.get("/metrics", response_class=StreamingResponse)
def metrics() -> StreamingResponse:
    state = store.snapshot()
    live = 1 if state["status"] == "en directo" else 0
    error = 1 if state["status"] == "error" else 0
    body = (
        "# HELP astrolearner_iss_live Stream is actively sending video.\n"
        "# TYPE astrolearner_iss_live gauge\n"
        f"astrolearner_iss_live {live}\n"
        "# HELP astrolearner_iss_error Controller is in an error state.\n"
        "# TYPE astrolearner_iss_error gauge\n"
        f"astrolearner_iss_error {error}\n"
        "# TYPE astrolearner_iss_remaining_seconds gauge\n"
        f"astrolearner_iss_remaining_seconds {state['remaining_seconds']}\n"
        "# TYPE astrolearner_iss_restarts_total counter\n"
        f"astrolearner_iss_restarts_total {state['restart_count']}\n"
    )
    return StreamingResponse(iter([body]), media_type="text/plain; version=0.0.4")


@app.get("/map.mjpeg")
async def map_mjpeg() -> StreamingResponse:
    return _mjpeg(controller.map_path, "map")


@app.get("/corner-map.png")
def corner_map() -> Response:
    # Only public orbital data; never include local paths or provider responses.
    # Copy the deque once so concurrent telemetry appends cannot break iteration.
    image, quality = render_corner_map(store.snapshot(), tuple(controller.position_track.copy()))
    return Response(image, media_type="image/png", headers={
        "Cache-Control": "no-store", "X-ISS-Position-State": quality,
    })


@app.get("/earth.mjpeg")
async def earth_mjpeg() -> StreamingResponse:
    return _mjpeg(controller.earth_path, "earth")


@app.get("/video.mjpeg")
async def selected_video(request: Request) -> Response:
    # This high-rate transport is for the local encoder/staging tunnel, not
    # the portal's broad /control reverse proxy. Do not trust client IP alone:
    # the proxy itself also connects from loopback.
    if not _local_video_request(request):
        return JSONResponse({"detail": "Transporte de vídeo reservado a la conexión local"}, status_code=403)
    switcher = controller.video_switcher
    if switcher is None:
        return JSONResponse({"detail": "Selector de cámara desactivado"}, status_code=503)

    async def frames():
        period = 1 / settings.fps
        deadline = time.monotonic()
        while not controller.stop_event.is_set():
            frame = switcher.frame()
            if frame is not None:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                       + str(len(frame)).encode("ascii") + b"\r\n\r\n" + frame + b"\r\n")
            deadline += period
            now = time.monotonic()
            if deadline < now - period:
                deadline = now
            await asyncio.sleep(max(0, deadline - now))

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-store"})


def _local_video_request(request: Request) -> bool:
    return not (
        request.url.hostname not in {"127.0.0.1", "localhost", "::1"}
        or any(name in request.headers for name in ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto"))
        or request.headers.get("sec-fetch-site") == "cross-site"
    )


@app.get("/dashboard.mjpeg")
async def dashboard_video(request: Request) -> Response:
    if not _local_video_request(request):
        return JSONResponse({"detail": "Transporte de vídeo reservado a la conexión local"}, status_code=403)
    if not controller._dashboard_active:
        return JSONResponse({"detail": "Panel desactivado para este bloque"}, status_code=503)

    async def frames():
        period = 1 / settings.fps
        deadline = time.monotonic()
        while not controller.stop_event.is_set():
            frame = controller.dashboard_jpeg
            if frame is not None:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                       + str(len(frame)).encode("ascii") + b"\r\n\r\n" + frame + b"\r\n")
            deadline += period
            now = time.monotonic()
            if deadline < now - period:
                deadline = now
            await asyncio.sleep(max(0, deadline - now))

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-store"})


def _mjpeg(path, kind: str) -> StreamingResponse:
    async def frames():
        deadline = time.monotonic()
        while True:
            try:
                with Image.open(path) as source:
                    image = source.convert("RGB")
            except OSError:
                if kind == "map":
                    render_map(path, settings.width, settings.height, 0, 0, 420)
                else:
                    render_earth_frame(None, path, settings.width, settings.height)
                with Image.open(path) as source:
                    image = source.convert("RGB")
            buffer = io.BytesIO()
            try:
                image.save(buffer, format="JPEG", quality=88)
            finally:
                image.close()
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                + buffer.getvalue()
                + b"\r\n"
            )
            # Encoding and client backpressure count towards the one-second
            # period. Sleeping a full second afterwards made this <1 FPS and
            # slowed every output graph that used the map as a framesync input.
            deadline += 1
            now = time.monotonic()
            if deadline < now - 1:
                deadline = now
            await asyncio.sleep(max(0, deadline - now))

    return StreamingResponse(
        frames(), media_type="multipart/x-mixed-replace; boundary=frame"
    )
