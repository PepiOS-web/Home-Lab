"""Isolated, credential-free browser capture for an operator-authorised player.

This process never loads the portal, OAuth, RTMP keys or a user's browser profile.
Only moving playback is offered to VideoSwitcher; errors close its MJPEG input.
Playwright is a separate sidecar dependency, not a production-app dependency.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import deque
from dataclasses import dataclass
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
import re
import signal
import threading
import time
from urllib.request import urlopen

if __package__:
    from .browser_snapshot import MAX_JPEG_BYTES, capture_jpeg
    from .browser_esa_map import monitor_esa_map
    from .browser_local_map import MAP_URLS, PRODUCTION_MAP_URL, monitor_local_map
else:
    from browser_snapshot import MAX_JPEG_BYTES, capture_jpeg
    from browser_esa_map import monitor_esa_map
    from browser_local_map import MAP_URLS, PRODUCTION_MAP_URL, monitor_local_map

PROGRESS_GRACE = 2.0
DRIVER_START_TIMEOUT_SECONDS = 10.0
LAUNCH_TIMEOUT_SECONDS = 25.0
SETUP_TIMEOUT_SECONDS = 10.0
NAVIGATION_TIMEOUT_SECONDS = 25.0
PLAYER_STATE_TIMEOUT_SECONDS = 2.5
BROWSER_CLOSE_TIMEOUT_SECONDS = 5.0
DRIVER_STOP_TIMEOUT_SECONDS = 5.0
NO_USABLE_FRAME_TIMEOUT_SECONDS = 45.0
RETRY_SECONDS = 30.0
CAPTURE_STAGES = {"driver", "launch", "context", "page", "session", "navigation", "player_state", "native_video", "screenshot", "shutdown"}
ERROR_SIGNAL_MARKERS = {
    "no_usable_sandbox": ("no usable sandbox",),
    "namespace_transition_denied": ("failed to move to new namespace", "user namespace sandbox failed"),
    "operation_not_permitted": ("operation not permitted",),
    "permission_denied": ("permission denied",),
    "thread_creation_failed": ("pthread_create", "failed to launch thread"),
    "chroot_failed": ("chroot",),
    "clone3_mentioned": ("clone3",),
    "setuid_no_new_privileges": ("the setuid sandbox is not running as root", "no_new_privs", "no new privileges"),
    "read_only_filesystem": ("read-only file system",),
    "crashpad_missing_database": ("crashpad_handler: --database",),
    "apparmor_mentioned": ("apparmor",),
    "process_signal": ("sigtrap", "sigabrt"),
}


def browser_error_details(error: Exception, stage: str) -> dict[str, object]:
    """Classify private diagnostics without ever returning the original text."""
    message = str(error).lower()
    if "clone3" in message or "pthread_create" in message or "failed to launch thread" in message:
        code = "thread_or_syscall_denied"
    elif any(marker in message for marker in ("no usable sandbox", "failed to move to new namespace", "user namespace sandbox failed")):
        code = "sandbox_denied"
    elif "executable doesn't exist" in message or "executable not found" in message:
        code = "browser_missing"
    elif any(marker in message for marker in ("read-only file system", "permission denied", "crashpad_handler: --database")):
        code = "profile_write_error"
    elif "frame was detached" in message or "execution context was destroyed" in message:
        code = "frame_detached"
    elif isinstance(error, TimeoutError) or "timeout" in message:
        code = "operation_timeout"
    elif "closed" in message or "sigtrap" in message or "sigabrt" in message:
        code = "process_exited"
    else:
        code = "unknown"
    exception_type = type(error).__name__
    if exception_type not in {"Error", "TimeoutError", "TargetClosedError", "OSError", "PermissionError", "FileNotFoundError", "RuntimeError"}:
        exception_type = "Exception"
    return {"error_stage": stage if stage in CAPTURE_STAGES else "unknown",
            "error_code": code, "error_type": exception_type,
            "error_signals": [name for name, markers in ERROR_SIGNAL_MARKERS.items()
                              if any(marker in message for marker in markers)],
            "error_fingerprint": hashlib.sha256(str(error).encode(errors="replace")).hexdigest()[:12]}


def browser_launch_options() -> dict:
    return {"channel": "chrome", "headless": True, "chromium_sandbox": True,
            "timeout": 20000,
            "args": ["--autoplay-policy=no-user-gesture-required", "--disable-background-timer-throttling",
                     "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows"]}


@dataclass(frozen=True)
class CaptureSettings:
    authorised: bool = False
    video_id: str = "awQzjn72bI0"
    width: int = 1280
    height: int = 720
    fps: int = 12
    port: int = 8093
    map_overlay: str = "none"
    local_map_url: str = PRODUCTION_MAP_URL

    @classmethod
    def from_env(cls) -> "CaptureSettings":
        settings = cls(
            authorised=os.getenv("ISS_BROWSER_CAPTURE_AUTHORIZED", "false").lower() == "true",
            video_id=os.getenv("ISS_BROWSER_VIDEO_ID", "awQzjn72bI0"),
            width=int(os.getenv("ISS_BROWSER_WIDTH", "1280")),
            height=int(os.getenv("ISS_BROWSER_HEIGHT", "720")),
            fps=int(os.getenv("ISS_BROWSER_FPS", "12")),
            map_overlay=os.getenv("ISS_BROWSER_MAP_OVERLAY", "none").strip().lower(),
            local_map_url=os.getenv("ISS_BROWSER_LOCAL_MAP_URL", PRODUCTION_MAP_URL),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.authorised:
            raise ValueError("Falta confirmar el permiso de retransmisión del reproductor")
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", self.video_id):
            raise ValueError("Identificador de vídeo no válido; no se aceptan URLs")
        if not (160 <= self.width <= 1280 and 90 <= self.height <= 720):
            raise ValueError("La captura está limitada a 1280x720")
        if self.width % 2 or self.height % 2 or not 1 <= self.fps <= 30:
            raise ValueError("Resolución o FPS de captura no válidos")
        if self.map_overlay not in {"none", "esa", "astrolearner"}:
            raise ValueError("Superposicion de mapa no valida; no se admiten URLs")
        if self.local_map_url not in MAP_URLS:
            raise ValueError("Solo se admite el mapa orbital interno")


def player_page(settings: CaptureSettings) -> bytes:
    # Only a validated public video ID enters this document, never a portal URL.
    settings.validate()
    map_html = """<div id="esa-map-wrap" style="position:fixed;top:18px;right:18px;
width:28%;max-width:390px;min-width:160px;opacity:0;z-index:10;pointer-events:none;
background:#071b29;border:1px solid #779bad;box-shadow:0 3px 12px #0008">
<img id="esa-map" alt="ESA ISS Tracker" style="display:block;width:100%;height:auto">
<div style="font:12px sans-serif;color:white;padding:4px 6px">ESA ISS Tracker · © ESA</div></div>
<script>window.esaMapUpdated=0;setInterval(()=>{if(performance.now()-window.esaMapUpdated>10000){
document.getElementById('esa-map-wrap').style.opacity='0'}},250);</script>""" if settings.map_overlay == "esa" else ""
    if settings.map_overlay == "astrolearner":
        map_html = """<div id="esa-map-wrap" style="position:fixed;top:18px;right:18px;
width:432px;max-width:calc(100% - 36px);opacity:0;z-index:10;pointer-events:none;
background:#071321;border:1px solid #507c91;box-shadow:0 3px 12px #0008">
<img id="esa-map" alt="AstroLearner ISS · Natural Earth" style="display:block;width:100%;height:auto">
</div><script>window.esaMapUpdated=0;setInterval(()=>{
if(performance.now()-window.esaMapUpdated>10000){document.getElementById('esa-map-wrap').style.opacity='0'}
},250);</script>"""
    return ("""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="referrer" content="strict-origin-when-cross-origin">
<title>Entrada de cámara autorizada</title><style>
html,body,#player{margin:0;width:100%;height:100%;overflow:hidden;background:#000}
</style></head><body><div id="player"></div><script>
window.capture = {state:-1,time:0,error:0};
let player;
function onYouTubeIframeAPIReady(){
 player=new YT.Player('player',{videoId:VIDEO_ID,
  playerVars:{autoplay:1,mute:1,playsinline:1,rel:0,origin:location.origin},
  events:{onReady:e=>{e.target.mute();e.target.playVideo()},
   onStateChange:e=>{window.capture.state=e.data},
   onError:e=>{window.capture.error=e.data}}});
 setInterval(()=>{try{window.capture.time=player.getCurrentTime();
 window.capture.state=player.getPlayerState()}catch(_){}},100);
}
</script><script src="https://www.youtube.com/iframe_api"></script>MAP_OVERLAY_HTML</body></html>
""".replace("VIDEO_ID", json.dumps(settings.video_id)).replace("MAP_OVERLAY_HTML", map_html)).encode()


class PlaybackGate:
    """A dark or identical image is valid; stopped player time is not."""
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.last_time: float | None = None
        self.last_progress: float | None = None
        self.last_decoded: int | None = None

    def observe(self, state: dict, now: float) -> bool:
        current = state.get("time")
        decoded = state.get("decoded")
        valid = (
            state.get("state") == 1 and not state.get("error")
            and not state.get("advertisement")
            and state.get("ready", 0) >= 2 and not state.get("paused", True)
            and isinstance(current, (int, float)) and math.isfinite(current)
            and isinstance(decoded, int) and decoded > 0
        )
        if not valid:
            self.reset()
            return False
        if self.last_time is not None and current < self.last_time - 1:
            self.reset()
        if (
            self.last_time is not None and self.last_decoded is not None
            and current > self.last_time and decoded > self.last_decoded
        ):
            self.last_progress = now
        self.last_time, self.last_decoded = current, decoded
        return self.last_progress is not None and now - self.last_progress <= PROGRESS_GRACE


class FrameHub:
    def __init__(self, fps: int, map_overlay: str = "none") -> None:
        self.fps = fps
        self.lock = threading.Lock()
        self.jpeg: bytes | None = None
        self.received: float | None = None
        self.count = 0
        self.timestamps: deque[float] = deque(maxlen=120)
        self.state = "starting"
        self.player_error = 0
        self.error_details: dict[str, object] = {}
        self.clients = threading.BoundedSemaphore(2)
        self.map_overlay = map_overlay
        self.map_received: float | None = None

    def set_map_ready(self, ready: bool) -> None:
        with self.lock:
            self.map_received = time.monotonic() if ready else None

    def invalidate(self, state: str, player_error: int = 0, error_details: dict | None = None) -> None:
        with self.lock:
            self.jpeg = None
            self.received = None
            self.timestamps.clear()
            self.state = state
            self.player_error = player_error if isinstance(player_error, int) else 0
            self.error_details = {key: value for key, value in (error_details or {}).items()
                                  if key in {"error_stage", "error_code", "error_type", "error_fingerprint"}}
            if error_details and isinstance(error_details.get("error_signals"), list):
                self.error_details["error_signals"] = [name for name in ERROR_SIGNAL_MARKERS
                                                       if name in error_details["error_signals"]]

    def publish(self, jpeg: bytes, now: float) -> bool:
        if not (4 <= len(jpeg) <= MAX_JPEG_BYTES and jpeg.startswith(b"\xff\xd8") and jpeg.endswith(b"\xff\xd9")):
            self.invalidate("invalid_frame")
            return False
        with self.lock:
            self.jpeg, self.received = jpeg, now
            self.count += 1
            self.timestamps.append(now)
            self.state, self.player_error = "playing", 0
            self.error_details = {}
        return True

    def frame(self) -> bytes | None:
        with self.lock:
            if self.received is None or time.monotonic() - self.received > PROGRESS_GRACE:
                return None
            return self.jpeg

    def status(self) -> dict:
        with self.lock:
            age = None if self.received is None else max(0, time.monotonic() - self.received)
            measured = 0.0
            if len(self.timestamps) > 1 and self.timestamps[-1] > self.timestamps[0]:
                measured = (len(self.timestamps) - 1) / (self.timestamps[-1] - self.timestamps[0])
            return {"state": self.state, "ready": self.jpeg is not None and age is not None and age <= PROGRESS_GRACE,
                    "captured_frames": self.count, "capture_fps": round(measured, 2),
                    "target_fps": self.fps, "last_frame_age_seconds": None if age is None else round(age, 2),
                    "player_error": self.player_error, "publishing": False, **self.error_details,
                    **({"map_source": self.map_overlay, "map_ready": self.map_received is not None
                         and time.monotonic() - self.map_received <= 10}
                       if self.map_overlay in {"esa", "astrolearner"} else {})}


def make_server(settings: CaptureSettings, hub: FrameHub, stop: threading.Event) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass  # No request URLs, cookies, headers or browser diagnostics in logs.

        def reply(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            self.connection.settimeout(3)
            if self.path == "/capture.html":
                self.reply(200, player_page(settings), "text/html; charset=utf-8")
            elif self.path in {"/health", "/ready"}:
                status = hub.status()
                code = 200 if self.path == "/health" or status["ready"] else 503
                self.reply(code, json.dumps(status).encode(), "application/json")
            elif self.path == "/preview":
                self.reply(200, b'<!doctype html><html lang="es"><meta charset="utf-8"><title>Captura NASA aislada</title><style>body{background:#10131c;color:#fff;font:16px sans-serif}img{width:100%;max-width:1280px}</style><h1>Captura NASA en el servidor</h1><p>Prueba aislada. No publica en YouTube. Si la captura falla, recarga cuando /ready indique disponibilidad.</p><img src="/camera.mjpeg" alt="Captura de prueba de la c\xc3\xa1mara NASA"></html>', "text/html; charset=utf-8")
            elif self.path == "/camera.mjpeg":
                if not hub.clients.acquire(blocking=False):
                    self.reply(503, b"", "text/plain")
                    return
                try:
                    if hub.frame() is None:
                        self.reply(503, b"", "text/plain")
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    period = 1 / settings.fps
                    deadline = time.monotonic()
                    while not stop.is_set():
                        frame = hub.frame()
                        if frame is None:
                            break  # Never repeat an error screen as a healthy camera.
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
                        self.wfile.flush()
                        # Socket writes consume part of the frame period; do
                        # not add their cost to every nominal 1/FPS interval.
                        deadline += period
                        now = time.monotonic()
                        if deadline < now - period:
                            deadline = now
                        stop.wait(max(0, deadline - now))
                except (OSError, TimeoutError):
                    pass
                finally:
                    hub.clients.release()
            else:
                self.reply(404, b"", "text/plain")

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 8

    return Server(("0.0.0.0", settings.port), Handler)


async def capture(settings: CaptureSettings, hub: FrameHub, stop: threading.Event) -> None:
    from playwright.async_api import async_playwright

    # Do not rely on Playwright's default action timeout: evaluate(), context
    # creation and CDP setup are not bounded by page.set_default_timeout(). A
    # stuck renderer must invalidate its frames and reach the reconnect loop.
    playwright = None
    try:
        try:
            playwright = await asyncio.wait_for(async_playwright().start(), timeout=DRIVER_START_TIMEOUT_SECONDS)
        except Exception as exc:
            details = browser_error_details(exc, "driver")
            hub.invalidate("browser_error", error_details=details)
            print(json.dumps({"state": "browser_error", **details}), flush=True)
            raise RuntimeError("Isolated browser driver could not start") from None
        while not stop.is_set():
            browser = None
            map_task = None
            stage = "launch"
            try:
                # Fail closed if the container/host cannot support Chromium's sandbox.
                browser = await asyncio.wait_for(
                    playwright.chromium.launch(**browser_launch_options()), timeout=LAUNCH_TIMEOUT_SECONDS)
                stage = "context"
                context = await asyncio.wait_for(browser.new_context(
                    viewport={"width": settings.width, "height": settings.height},
                    device_scale_factor=1, accept_downloads=False,
                    service_workers="block"), timeout=SETUP_TIMEOUT_SECONDS)
                stage = "page"
                page = await asyncio.wait_for(context.new_page(), timeout=SETUP_TIMEOUT_SECONDS)
                page.set_default_timeout(2500)
                stage = "session"
                session = await asyncio.wait_for(context.new_cdp_session(page), timeout=SETUP_TIMEOUT_SECONDS)
                stage = "navigation"
                await asyncio.wait_for(page.goto(
                    f"http://127.0.0.1:{settings.port}/capture.html", wait_until="domcontentloaded", timeout=20000),
                    timeout=NAVIGATION_TIMEOUT_SECONDS)
                if settings.map_overlay == "esa":
                    map_task = asyncio.create_task(monitor_esa_map(context, page, hub.set_map_ready, stop))
                elif settings.map_overlay == "astrolearner":
                    map_task = asyncio.create_task(monitor_local_map(page, hub.set_map_ready, stop, settings.local_map_url))
                gate = PlaybackGate()
                last_usable = time.monotonic()
                deadline = time.monotonic()
                while not stop.is_set():
                    stage = "player_state"
                    state = await asyncio.wait_for(page.evaluate(
                        "window.capture || {state:-1,time:0,error:0}"), timeout=PLAYER_STATE_TIMEOUT_SECONDS)
                    for frame in page.frames:
                        if frame.url.startswith("https://www.youtube.com/embed/"):
                            stage = "native_video"
                            try:
                                native = await asyncio.wait_for(frame.evaluate("""() => {const v=document.querySelector('video');
                            return {ready:v?.readyState||0,paused:v?.paused??true,
                            decoded:v?.getVideoPlaybackQuality?.().totalVideoFrames||0,
                            advertisement:!!document.querySelector('.ad-showing')};} """),
                                    timeout=PLAYER_STATE_TIMEOUT_SECONDS)
                            except Exception as exc:
                                details = browser_error_details(exc, stage)
                                if details["error_code"] != "frame_detached":
                                    raise
                                # Normal iframe reloads must not restart the whole browser.
                                # A timeout, unlike detachment, recycles the stuck renderer.
                                native = {"ready": 0, "paused": True, "decoded": 0}
                            state.update(native)
                            break
                    if gate.observe(state, time.monotonic()):
                        stage = "screenshot"
                        jpeg = await capture_jpeg(session)
                        # Progress may have expired during a slow screenshot.
                        now = time.monotonic()
                        if gate.last_progress is not None and now - gate.last_progress <= PROGRESS_GRACE:
                            if hub.publish(jpeg, now):
                                last_usable = now
                        else:
                            hub.invalidate("stalled")
                    else:
                        hub.invalidate("player_error" if state.get("error") else "waiting_for_playback", state.get("error", 0))
                    if time.monotonic() - last_usable > NO_USABLE_FRAME_TIMEOUT_SECONDS:
                        break
                    deadline += 1 / settings.fps
                    now = time.monotonic()
                    if deadline < now:
                        deadline = now
                    await asyncio.sleep(max(0, deadline - now))
            except Exception as exc:
                # Browser exceptions often contain signed media URLs: never print them.
                details = browser_error_details(exc, stage)
                hub.invalidate("browser_error", error_details=details)
                print(json.dumps({"state": "browser_error", **details}), flush=True)
            finally:
                if map_task is not None:
                    map_task.cancel()
                    try:
                        await asyncio.wait_for(map_task, timeout=3)
                    except (asyncio.CancelledError, Exception):
                        pass
                hub.set_map_ready(False)
                if hub.status()["state"] != "browser_error":
                    hub.invalidate("reconnecting")
                if browser is not None:
                    try:
                        await asyncio.wait_for(browser.close(), timeout=BROWSER_CLOSE_TIMEOUT_SECONDS)
                    except Exception as exc:
                        details = browser_error_details(exc, "shutdown")
                        hub.invalidate("browser_error", error_details=details)
                        print(json.dumps({"state": "browser_error", **details}), flush=True)
                        # Do not accumulate abandoned Chrome processes. In production
                        # the existing sidecar restart policy recycles the container,
                        # without restarting the main encoder or publishing a new live.
                        raise RuntimeError("Isolated browser cleanup failed; capture must be recycled") from None
            retry_deadline = time.monotonic() + RETRY_SECONDS
            while not stop.is_set() and time.monotonic() < retry_deadline:
                await asyncio.sleep(min(1.0, max(0, retry_deadline - time.monotonic())))
    finally:
        if playwright is not None:
            try:
                await asyncio.wait_for(playwright.stop(), timeout=DRIVER_STOP_TIMEOUT_SECONDS)
            except Exception as exc:
                details = browser_error_details(exc, "shutdown")
                hub.invalidate("browser_error", error_details=details)
                print(json.dumps({"state": "browser_error", **details}), flush=True)
                raise RuntimeError("Isolated browser driver cleanup failed; capture must be recycled") from None


async def diagnose() -> bool:
    """Launch about:blank only: no NASA, YouTube, portal or media requests."""
    from pathlib import Path
    from playwright.async_api import async_playwright

    report = {"test": "browser_startup_only", "publishing": False, "external_player_opened": False,
              "uid": os.getuid(), "home_writable": os.access(Path.home(), os.W_OK),
              "sandbox_enabled": True}
    browser, playwright, stage = None, None, "driver"
    try:
        try:
            playwright = await asyncio.wait_for(async_playwright().start(), timeout=DRIVER_START_TIMEOUT_SECONDS)
            stage = "launch"
            browser = await asyncio.wait_for(
                playwright.chromium.launch(**browser_launch_options()), timeout=LAUNCH_TIMEOUT_SECONDS)
            stage = "context"
            context = await asyncio.wait_for(browser.new_context(viewport={"width": 640, "height": 360}),
                                             timeout=SETUP_TIMEOUT_SECONDS)
            stage = "page"
            page = await asyncio.wait_for(context.new_page(), timeout=SETUP_TIMEOUT_SECONDS)
            stage = "session"
            session = await asyncio.wait_for(context.new_cdp_session(page), timeout=SETUP_TIMEOUT_SECONDS)
            stage = "navigation"
            await asyncio.wait_for(page.goto("about:blank", timeout=5000), timeout=SETUP_TIMEOUT_SECONDS)
            stage = "screenshot"
            image = await capture_jpeg(session)
            report.update(status="ok", screenshot_bytes=len(image))
        except Exception as exc:
            report.update(status="failed", **browser_error_details(exc, stage))
        finally:
            if browser is not None:
                try:
                    await asyncio.wait_for(browser.close(), timeout=BROWSER_CLOSE_TIMEOUT_SECONDS)
                except Exception as exc:
                    report.update(status="failed", **browser_error_details(exc, "shutdown"))
            if playwright is not None:
                try:
                    await asyncio.wait_for(playwright.stop(), timeout=DRIVER_STOP_TIMEOUT_SECONDS)
                except Exception as exc:
                    report.update(status="failed", **browser_error_details(exc, "shutdown"))
    finally:
        print(json.dumps(report), flush=True)
    return report.get("status") == "ok"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Comprueba que llegan fotogramas de captura")
    parser.add_argument("--diagnose", action="store_true", help="Prueba el arranque aislado sin abrir YouTube")
    args = parser.parse_args()
    if args.check:
        with urlopen("http://127.0.0.1:8093/ready", timeout=4) as response:
            print(response.read().decode())
        return
    if args.diagnose:
        raise SystemExit(0 if asyncio.run(diagnose()) else 1)
    settings = CaptureSettings.from_env()
    hub, stop = FrameHub(settings.fps, settings.map_overlay), threading.Event()
    for name in ("SIGINT", "SIGTERM"):
        signal.signal(getattr(signal, name), lambda *_: stop.set())
    server = make_server(settings, hub, stop)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print("Captura aislada iniciada; sin credenciales ni publicación", flush=True)
    try:
        asyncio.run(capture(settings, hub, stop))
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


if __name__ == "__main__":
    main()
