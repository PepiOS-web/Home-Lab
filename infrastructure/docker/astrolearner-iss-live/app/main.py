from __future__ import annotations

import asyncio
import io
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from PIL import Image

from .config import Settings
from .control_auth import ControlAuthError, authorize_control
from .controller import Controller
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


def _authorize_control(request: Request) -> None:
    try:
        authorize_control(
            request.headers.get("origin"),
            request.headers.get("authorization", ""),
            settings.control_token,
        )
    except ControlAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


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


@app.get("/earth.mjpeg")
async def earth_mjpeg() -> StreamingResponse:
    return _mjpeg(controller.earth_path, "earth")


def _mjpeg(path, kind: str) -> StreamingResponse:
    async def frames():
        while True:
            try:
                image = Image.open(path).convert("RGB")
            except OSError:
                if kind == "map":
                    render_map(path, settings.width, settings.height, 0, 0, 420)
                else:
                    render_earth_frame(None, path, settings.width, settings.height)
                image = Image.open(path).convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=88)
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                + buffer.getvalue()
                + b"\r\n"
            )
            await asyncio.sleep(1)

    return StreamingResponse(
        frames(), media_type="multipart/x-mixed-replace; boundary=frame"
    )
