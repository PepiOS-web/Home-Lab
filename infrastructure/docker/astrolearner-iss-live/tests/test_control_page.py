import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

import pytest

from app.control_page import create_control_page


NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def timestamp(age=0):
    return (NOW - timedelta(seconds=age)).isoformat().replace("+00:00", "Z")


def live_state(**overrides):
    return {
        "status": "en directo",
        "mode": "youtube",
        "live_requested": True,
        "control_ready": True,
        "updated_at": timestamp(),
        "ffmpeg_running": True,
        "ffmpeg_frame_count": 480,
        "last_frame_at": timestamp(1),
        "last_progress_at": timestamp(1),
        "ffmpeg_out_time_seconds": 723,
        "position_updated_at": timestamp(10),
        "youtube_lifecycle_status": "live",
        "youtube_privacy_status": "public",
        "youtube_stream_status": "active",
        "youtube_health_status": "good",
        "youtube_checked_at": timestamp(20),
        "youtube_health_updated_at": timestamp(25),
        "youtube_health_issues": [],
        "youtube_check_error": "",
        "youtube_watch_url": "https://www.youtube.com/watch?v=abcdefghijk",
        "music_session": "AstroLearner Lo-Fi · sesión de 1 h",
        "music_playback_active": True,
        "music_track": "Aurora",
        "music_track_index": 3,
        "music_track_count": 12,
        "music_track_elapsed_seconds": 123,
        "music_track_duration_seconds": 300,
        "music_session_elapsed_seconds": 723,
        "music_session_duration_seconds": 3600,
        **overrides,
    }


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key == "id":
                self.ids.append(value)


def test_control_page_has_accessible_health_music_and_existing_controls(tmp_path):
    create_control_page(tmp_path)
    html = (tmp_path / "control.html").read_text(encoding="utf-8")
    script = (tmp_path / "control.js").read_text(encoding="utf-8")
    parser = PageParser()
    parser.feed(html)

    assert len(parser.ids) == len(set(parser.ids))
    assert {
        "health-heading", "frame-health", "youtube-health", "position-health",
        "visual-health", "visual-detail",
        "music-heading", "track-progress", "session-progress", "token", "start",
        "stop", "live-title", "live-description", "update-metadata",
    }.issubset(parser.ids)
    assert 'aria-labelledby="health-heading"' in html
    assert '<label for="track-progress">' in html
    assert '<label for="session-progress">' in html
    assert 'type="password" autocomplete="off"' in html
    assert "innerHTML" not in script
    assert "youtube.googleapis.com" not in script
    assert "sessionStorage.removeItem" in script
    assert "sessionStorage.setItem" not in script and "localStorage" not in script
    assert "auth-panel" in parser.ids and "logout" in parser.ids
    assert "credentials: 'same-origin'" in script
    assert "window.setInterval(refresh, 3000)" in script
    assert "AbortController" in script
    assert "apply_to_current: applyToCurrent" in script


def test_remembered_cookie_hides_token_and_keeps_authenticated_controls(run_page):
    result = run_page([live_state(mode="simulacion", live_requested=False)])
    view = result["snapshots"][0]
    assert view["auth-panel"]["hidden"] is True
    assert view["logout"]["hidden"] is False
    assert view["start"]["disabled"] is False
    assert all(r["method"] == "GET" for r in result["requests"])


def test_new_browser_cannot_start_without_successful_login(run_page):
    result = run_page([live_state(mode="simulacion", live_requested=False)], [
        {"type": "click", "id": "start"},
        {"type": "edit", "id": "token", "value": "a" * 64},
        {"type": "click", "id": "save"},
    ], authenticated=False)
    first, last = result["snapshots"][0], result["snapshots"][-1]
    assert first["auth-panel"]["hidden"] is False and first["start"]["disabled"] is True
    assert last["auth-panel"]["hidden"] is True and last["start"]["disabled"] is False
    assert last["token"]["value"] == "" and result["stored"] == []
    assert not any(r["url"].endswith("/start") for r in result["requests"])


def test_cookie_refusal_never_unlocks_the_browser(run_page):
    result = run_page([live_state(mode="simulacion", live_requested=False)], [
        {"type": "edit", "id": "token", "value": "a" * 64},
        {"type": "click", "id": "save"},
    ], authenticated=False, accept_cookie=False)
    view = result["snapshots"][-1]
    assert view["start"]["disabled"] is True and view["auth-panel"]["hidden"] is False
    assert "HTTPS" in view["message"]["text"]


def test_legacy_tab_token_is_removed_and_exchanged_only_once(run_page):
    result = run_page([live_state()], authenticated=False, legacy="a" * 64)
    assert result["stored"] == []
    assert result["snapshots"][0]["auth-panel"]["hidden"] is True
    assert sum(r["method"] == "POST" for r in result["requests"]) == 1


def test_logout_never_stops_or_starts_the_live_and_expired_session_locks(run_page):
    result = run_page([live_state()], [{"type": "click", "id": "logout"}])
    view = result["snapshots"][-1]
    assert view["auth-panel"]["hidden"] is False and view["stop"]["disabled"] is True
    assert not any(r["url"].endswith(("/stop", "/start")) for r in result["requests"])
    result = run_page([live_state()], [{"type": "expire"}, {"type": "click", "id": "stop"}])
    view = result["snapshots"][-1]
    assert view["auth-panel"]["hidden"] is False and view["stop"]["disabled"] is True


# Execute the generated browser script without a browser/server/OAuth account.
# The DOM double records text assignments and the progress values actually shown.
NODE_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const scenario = JSON.parse(fs.readFileSync(0, 'utf8'));
let now = Date.parse('2026-10-12T12:00:00Z');
class FrozenDate extends Date { static now() { return now; } }
class Element {
  constructor(id) {
    this.id = id;
    this._text = '';
    this.value = '';
    this.disabled = false;
    this.hidden = false;
    this.dataset = {};
    this.children = [];
    this.listeners = {};
    this.classList = { toggle() {} };
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text; }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  replaceChildren(...children) { this.children = children; this._text = ''; }
  append(child) { this.children.push(child); }
}
const nodes = {};
const document = {
  getElementById(id) { return nodes[id] || (nodes[id] = new Element(id)); },
  createElement(tag) { return new Element(tag); },
};
const stored = new Map(scenario.legacy ? [['astrolearner-live-control-token', scenario.legacy]] : []);
let authenticated = scenario.authenticated !== false;
const sessionStorage = {
  getItem(key) { return stored.get(key); },
  setItem(key, value) { stored.set(key, value); },
  removeItem(key) { stored.delete(key); },
};
let interval;
let timerId = 0;
const window = {
  confirm() { return true; },
  setInterval(fn) { interval = fn; },
  setTimeout() { return ++timerId; },
  clearTimeout() {},
};
const requests = [];
const responses = [...scenario.responses];
let lastResponse;
async function fetch(url, options = {}) {
  requests.push({ url, method: options.method || 'GET', authorized: Boolean(
    (options.headers && options.headers.Authorization)
      || (options.credentials === 'same-origin' && authenticated)) });
  if (url === '/iss-live/status.json') {
    if (responses.length) lastResponse = responses.shift();
    if (lastResponse && lastResponse.fail) throw new Error('secret API key must not reach the page');
    return { ok: true, async json() { return lastResponse; } };
  }
  if (url === '/iss-live/control/session') {
    if (options.method === 'POST') {
      if (!options.headers || options.headers.Authorization !== 'Bearer ' + 'a'.repeat(64)) {
        return { ok: false, status: 401, async json() { return { detail: 'Token de control incorrecto' }; } };
      }
      authenticated = scenario.accept_cookie !== false;
    }
    return { ok: true, async json() { return { authenticated }; } };
  }
  if (!authenticated) {
    return { ok: false, status: 401, async json() { return { detail: 'Token de control incorrecto' }; } };
  }
  if (url === '/iss-live/control/session/logout') {
    authenticated = false;
    return { ok: true, async json() { return { authenticated: false }; } };
  }
  if (url === '/iss-live/control/metadata') {
    const body = options.body ? JSON.parse(options.body) : {};
    return { ok: true, async json() {
      return { title: body.title || 'Título editable', description: body.description || 'Descripción editable', applied_to_current: Boolean(body.apply_to_current) };
    } };
  }
  if (url === '/iss-live/control/starvios') {
    return { ok: true, async json() { return { enabled: false, configured: false, remote_verified: false }; } };
  }
  if (url === '/iss-live/control/presentation') {
    return { ok: true, async json() { return { dashboard_enabled: false, recorded_fallback_enabled: true, music_style: 'classic' }; } };
  }
  return { ok: true, async json() { return {}; } };
}
const context = vm.createContext({ document, sessionStorage, window, fetch, Date: FrozenDate, TextEncoder, URL, AbortController });
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
async function settle() { for (let i = 0; i < 4; i++) await new Promise(resolve => setImmediate(resolve)); }
function snapshot() {
  const result = {};
  for (const [id, node] of Object.entries(nodes)) {
    result[id] = { text: node.textContent, value: node.value, max: node.max, checked: node.checked,
      disabled: node.disabled, hidden: node.hidden, tone: node.dataset.tone,
      children: node.children.map(child => ({ text: child.textContent, href: child.href })) };
  }
  return result;
}
(async () => {
  await settle();
  const snapshots = [snapshot()];
  for (const action of scenario.actions || []) {
    if (action.type === 'expire') authenticated = false;
    if (action.advance_seconds) now += action.advance_seconds * 1000;
    if (action.type === 'refresh') await interval();
    if (action.type === 'edit') {
      nodes[action.id].value = action.value;
      if ('checked' in action) nodes[action.id].checked = action.checked;
      if (nodes[action.id].listeners.input) nodes[action.id].listeners.input();
    }
    if (action.type === 'click') await nodes[action.id].listeners.click();
    await settle();
    snapshots.push(snapshot());
  }
  process.stdout.write(JSON.stringify({ snapshots, requests, stored: [...stored] }));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


@pytest.fixture
def run_page(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is needed for generated portal behavior checks")
    create_control_page(tmp_path)

    def run(responses, actions=None, **options):
        result = subprocess.run(
            [node, "-e", NODE_HARNESS, str(tmp_path / "control.js")],
            input=json.dumps({"responses": responses, "actions": actions or [], **options}),
            text=True,
            capture_output=True,
            encoding="utf-8",
            timeout=15,
            check=True,
        )
        return json.loads(result.stdout)

    return run


def test_simulation_never_claims_live_signal_or_music(run_page):
    result = run_page([live_state(mode="simulacion", live_requested=False)])
    view = result["snapshots"][0]
    assert view["frame-health"]["text"] == "Sin emisión"
    assert view["youtube-health"]["text"] == "Sin emisión"
    assert view["frame-health"]["tone"] == "idle"
    assert view["music-title"]["text"] == "Sin reproducción"
    assert view["music-progress"]["hidden"] is True
    assert view["watch"]["children"] == []
    assert view["start"]["disabled"] is False


def test_multistream_configuration_requires_auth_stopped_fresh_state(run_page):
    ready = run_page([live_state(mode="simulacion", live_requested=False, ffmpeg_running=False)])["snapshots"][0]
    assert ready["save-starvios"]["disabled"] is False
    assert ready["starvios-key"]["value"] == ""
    for state, options in [
        (live_state(), {}),
        (live_state(mode="simulacion", live_requested=False), {"authenticated": False}),
        (live_state(mode="simulacion", live_requested=False, updated_at=timestamp(16)), {}),
    ]:
        view = run_page([state], **options)["snapshots"][0]
        assert view["save-starvios"]["disabled"] is True


def test_starvios_local_output_never_claims_remote_health(run_page):
    view = run_page([live_state(starvios_output_active=True)])["snapshots"][0]
    assert "SIN verificar" in view["starvios-output"]["text"]
    view = run_page([live_state(starvios_output_active=True, updated_at=timestamp(16))])["snapshots"][0]
    assert view["starvios-output"]["text"] == "Sin envío local activo a Starvios"


def test_recent_live_signal_and_music_use_encoded_timeline(run_page):
    result = run_page([live_state()], [{"type": "refresh", "advance_seconds": 3}])
    for view in result["snapshots"]:
        assert view["frame-health"]["tone"] == "good"
        assert view["youtube-health"]["text"] == "Señal recibida"
        assert view["position-health"]["tone"] == "good"
        assert view["music-title"]["text"] == "Aurora"
        assert view["music-position"]["text"] == "Tema 3 de 12"
        assert view["music-progress"]["hidden"] is False
        assert view["track-progress"]["value"] == 123
        assert view["track-progress"]["max"] == 300
        assert view["track-time"]["text"] == "2:03 / 5:00"
        assert view["session-time"]["text"] == "12:03 / 1:00:00"
        assert view["watch"]["children"][0]["href"] == "https://www.youtube.com/watch?v=abcdefghijk"
    # A dashboard poll only reads cached server state, never YouTube itself.
    assert [r["url"] for r in result["requests"]] == [
        "/iss-live/status.json", "/iss-live/control/session",
        "/iss-live/control/metadata", "/iss-live/control/starvios", "/iss-live/control/presentation", "/iss-live/status.json",
    ]


def test_stale_frames_and_position_are_not_masked_by_fresh_general_status(run_page):
    view = run_page([live_state(last_frame_at=timestamp(16), position_updated_at=timestamp(61))])["snapshots"][0]
    assert view["frame-health"]["text"] == "Posible señal bloqueada"
    assert view["frame-health"]["tone"] == "warning"
    assert view["position-health"]["text"] == "Datos orbitales antiguos"
    assert view["position-health"]["tone"] == "warning"
    assert view["music-title"]["text"] == "Reproducción sin confirmar"
    assert view["music-progress"]["hidden"] is True


@pytest.mark.parametrize("changes", [
    {"youtube_checked_at": timestamp(151)},
    {"youtube_health_updated_at": timestamp(151)},
    {"youtube_checked_at": None},
    {"youtube_health_updated_at": None},
    {"youtube_checked_at": "not a timestamp"},
    {"youtube_checked_at": timestamp(-3600)},
    {"youtube_check_error": "private transport error must not be shown"},
])
def test_cached_good_health_needs_recent_query_and_health_timestamps(run_page, changes):
    view = run_page([live_state(**changes)])["snapshots"][0]
    assert view["youtube-health"]["tone"] == "unknown"
    assert view["youtube-health"]["text"] != "Señal recibida"
    assert "private transport error" not in json.dumps(view)


@pytest.mark.parametrize("changes,text,tone", [
    ({"youtube_health_status": "noData"}, "Salud todavía no disponible", "unknown"),
    ({"youtube_stream_status": "inactive"}, "YouTube no recibe datos", "warning"),
    ({"youtube_health_status": "bad"}, "YouTube detecta problemas", "bad"),
    ({"youtube_stream_status": "error"}, "YouTube detecta problemas", "bad"),
    ({"youtube_lifecycle_status": "complete"}, "Emisión cerrada en YouTube", "bad"),
    ({"youtube_lifecycle_status": "revoked"}, "Emisión cerrada en YouTube", "bad"),
    ({"youtube_lifecycle_status": "testing"}, "Esperando confirmación de YouTube", "unknown"),
])
def test_youtube_health_distinguishes_missing_bad_closed_and_pending(run_page, changes, text, tone):
    view = run_page([live_state(**changes)])["snapshots"][0]
    assert view["youtube-health"]["text"] == text
    assert view["youtube-health"]["tone"] == tone


def test_youtube_issues_are_bounded_safe_text_and_clear_when_idle(run_page):
    issues = [{"type": '<img src=x onerror="alert(1)">', "severity": "warning"}] * 12
    result = run_page([
        live_state(youtube_health_issues=issues),
        live_state(mode="simulacion", live_requested=False),
    ], [{"type": "refresh"}])
    live, idle = result["snapshots"]
    assert live["youtube-health"]["tone"] == "warning"
    assert len(live["youtube-issues"]["children"]) == 8
    assert live["youtube-issues"]["children"][0]["text"] == 'YouTube: <img src=x onerror="alert(1)"> (warning)'
    assert idle["youtube-issues"]["children"] == []
    assert idle["track-progress"]["value"] == 0


@pytest.mark.parametrize("initial", [live_state(), live_state(mode="simulacion", live_requested=False)])
def test_fetch_failure_clears_cached_health_disables_writes_and_preserves_edits(run_page, initial):
    result = run_page([initial, {"fail": True}], [
        {"type": "edit", "id": "live-title", "value": "Mi título sin guardar"},
        {"type": "refresh"},
        {"type": "click", "id": "start"},
        {"type": "click", "id": "update-metadata"},
    ])
    view = result["snapshots"][2]
    assert view["frame-health"]["tone"] == "unknown"
    assert view["youtube-health"]["tone"] == "unknown"
    assert view["position-health"]["tone"] == "unknown"
    assert view["music-progress"]["hidden"] is True
    assert view["start"]["disabled"] is True
    assert view["update-metadata"]["disabled"] is True
    assert view["stop"]["disabled"] is False
    assert view["live-title"]["value"] == "Mi título sin guardar"
    assert view["watch"]["children"] == []
    assert "secret API key" not in json.dumps(view)
    assert all(request["method"] == "GET" for request in result["requests"])


@pytest.mark.parametrize("response", [[], None, {"status": "ready", "control_ready": "false"}])
def test_malformed_status_fails_closed(run_page, response):
    view = run_page([response])["snapshots"][0]
    assert view["start"]["disabled"] is True
    assert view["frame-health"]["tone"] == "unknown"


def test_stale_status_disables_start_even_when_fetch_succeeds(run_page):
    view = run_page([live_state(mode="simulacion", live_requested=False, updated_at=timestamp(16))])["snapshots"][0]
    assert view["start"]["disabled"] is True
    assert "Estado sin actualizar" in view["status"]["text"]


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "https://evil.example/watch?v=abcdefghijk",
    "https://www.youtube.com.evil.example/watch?v=abcdefghijk",
    "https://www.youtube.com@evil.example/watch?v=abcdefghijk",
    "https://www.youtube.com/watch?v=invalid",
])
def test_watch_link_is_not_created_from_unsafe_url(run_page, url):
    view = run_page([live_state(youtube_watch_url=url)])["snapshots"][0]
    assert view["watch"]["children"] == []


def test_status_poll_does_not_overwrite_metadata_edits(run_page):
    result = run_page([live_state()], [
        {"type": "edit", "id": "live-title", "value": "Título nuevo"},
        {"type": "edit", "id": "live-description", "value": "Descripción nueva"},
        {"type": "refresh"},
    ])
    view = result["snapshots"][-1]
    assert view["live-title"]["value"] == "Título nuevo"
    assert view["live-description"]["value"] == "Descripción nueva"
    assert sum(r["url"] == "/iss-live/control/metadata" for r in result["requests"]) == 1


def test_future_metadata_save_still_uses_authenticated_endpoint(run_page):
    result = run_page([live_state(mode="simulacion", live_requested=False)], [
        {"type": "edit", "id": "live-title", "value": "Título futuro"},
        {"type": "click", "id": "save-metadata"},
    ])
    request = result["requests"][-1]
    assert request == {"url": "/iss-live/control/metadata", "method": "POST", "authorized": True}
    assert result["snapshots"][-1]["metadata-message"]["text"] == "Datos guardados. Se usarán al iniciar el próximo directo."


def test_visual_selector_disabled_labels_recorded_material_honestly(run_page):
    view = run_page([live_state(camera_enabled=False, video_mode="recorded")])["snapshots"][0]
    assert view["visual-health"]["text"] == "Vídeos grabados"
    assert view["visual-health"]["tone"] == "good"
    assert "no una cámara ISS en directo" in view["visual-detail"]["text"]


def test_camera_enabled_without_authorized_url_shows_fallback_not_live_camera(run_page):
    view = run_page([live_state(
        camera_enabled=True, camera_configured=False, video_mode="recorded",
    )])["snapshots"][0]
    assert view["visual-health"]["text"] == "Cámara sin configurar"
    assert "imágenes grabadas y el mapa como respaldo" in view["visual-detail"]["text"]


def test_simulation_does_not_claim_camera_is_being_sent(run_page):
    view = run_page([live_state(
        mode="simulacion", live_requested=False, camera_enabled=True,
        camera_configured=True, video_mode="camera", camera_available=True,
        camera_state="live", camera_last_frame_at=timestamp(1),
    )])["snapshots"][0]
    assert view["visual-health"]["text"] == "Sin emisión"
    assert view["visual-health"]["tone"] == "idle"


def test_recent_camera_requires_both_camera_and_output_progress(run_page):
    view = run_page([live_state(
        camera_enabled=True, camera_configured=True, video_mode="camera",
        camera_available=True, camera_state="live", camera_last_frame_at=timestamp(2),
        camera_timeout_seconds=8,
    )])["snapshots"][0]
    assert view["visual-health"]["text"] == "Señal externa ISS"
    assert view["visual-health"]["tone"] == "good"
    assert "puede incluir material grabado" in view["visual-detail"]["text"]


@pytest.mark.parametrize("changes", [
    {"camera_last_frame_at": timestamp(9)},
    {"camera_last_frame_at": None},
    {"camera_last_frame_at": "invalid"},
    {"camera_last_frame_at": timestamp(-3600)},
    {"camera_available": False},
    {"camera_state": "recovering"},
    {"ffmpeg_running": False},
    {"last_frame_at": timestamp(16)},
    {"updated_at": timestamp(16)},
])
def test_unconfirmed_camera_never_claims_recent_live_feed(run_page, changes):
    view = run_page([live_state(**{
        "camera_enabled": True, "camera_configured": True, "video_mode": "camera",
        "camera_available": True, "camera_state": "live", "camera_last_frame_at": timestamp(1),
        **changes,
    })])["snapshots"][0]
    assert view["visual-health"]["text"] == "Fuente visual sin confirmar"
    assert view["visual-health"]["tone"] == "unknown"


@pytest.mark.parametrize("mode,label", [
    ("recorded", "Respaldo: vídeos grabados"),
    ("map", "Respaldo: mapa orbital"),
])
def test_camera_failure_and_recovery_show_actual_backing_visual(run_page, mode, label):
    view = run_page([live_state(
        camera_enabled=True, camera_configured=True, video_mode=mode,
        camera_available=False, camera_state="recovering", camera_last_frame_at=timestamp(2),
        video_fallback_reason="camera_recovering", video_switch_count=2,
        video_switch_at=timestamp(10),
    )])["snapshots"][0]
    assert view["visual-health"]["text"] == label
    assert view["visual-health"]["tone"] == "warning"
    assert "Esperando una señal de cámara estable" in view["visual-detail"]["text"]
    assert "Cambios de fuente: 2; último hace 10 s" in view["visual-detail"]["text"]


def test_camera_error_url_and_unknown_reason_never_reach_portal(run_page):
    private = "https://provider.example/private.m3u8?token=secret"
    view = run_page([live_state(
        camera_enabled=True, camera_configured=True, video_mode="recorded",
        camera_state=private, video_fallback_reason=private,
        camera_url=private,
    )])["snapshots"][0]
    assert view["visual-health"]["text"] == "Respaldo: vídeos grabados"
    assert private not in json.dumps(view)
    assert "token=secret" not in json.dumps(view)


def test_legacy_source_attribution_never_displays_a_url(run_page):
    view = run_page([live_state(
        camera_enabled=False,
        visual_source="https://provider.example/private.m3u8?token=secret",
    )])["snapshots"][0]
    assert view["visual-health"]["text"] == "Vídeos grabados"
    assert "token=secret" not in json.dumps(view)


def test_camera_status_read_failure_clears_cached_actual_source(run_page):
    result = run_page([live_state(
        camera_enabled=True, camera_configured=True, video_mode="camera",
        camera_available=True, camera_state="live", camera_last_frame_at=timestamp(1),
    ), {"fail": True}], [{"type": "refresh"}])
    view = result["snapshots"][-1]
    assert view["visual-health"]["text"] == "Fuente visual sin confirmar"
    assert view["visual-health"]["tone"] == "unknown"


@pytest.mark.parametrize("reason,explanation", [
    ("camera_unstable", "Esperando una señal de cámara estable antes de volver."),
    ("recorded_requested", "Respaldo de vídeos seleccionado manualmente."),
    ("recorded_unavailable", "Los vídeos de respaldo no están disponibles."),
    ("map_requested", "Mapa orbital seleccionado manualmente."),
    ("map_unavailable", "No se puede confirmar el mapa de respaldo."),
])
def test_visual_fallback_reasons_use_human_labels_not_raw_codes(run_page, reason, explanation):
    view = run_page([live_state(
        camera_enabled=True, camera_configured=True, video_mode="map",
        camera_state="recovering", video_fallback_reason=reason,
    )])["snapshots"][0]
    assert explanation in view["visual-detail"]["text"]
    assert reason not in view["visual-detail"]["text"]
