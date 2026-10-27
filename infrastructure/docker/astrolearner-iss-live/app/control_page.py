from __future__ import annotations

from pathlib import Path


def create_control_page(status_dir: Path) -> None:
    status_dir.mkdir(parents=True, exist_ok=True)
    (status_dir / "control.html").write_text(
        """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>Control AstroLearner ISS Live</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; }
    body { box-sizing: border-box; margin: 0; padding: 1rem; color: #e8edf7;
      background: #171923; }
    h1, h2 { margin: 0 0 .2rem; font-size: 1rem; }
    p { margin: .3rem 0 .8rem; color: #aab5c8; font-size: .8rem; }
    .status { margin-bottom: .8rem; font-weight: 650; }
    label { display: block; margin-bottom: .3rem; color: #aab5c8; font-size: .75rem; }
    input, textarea, select { box-sizing: border-box; width: 100%; padding: .55rem; border: 1px solid #4b5563;
      border-radius: .45rem; color: #fff; background: #202431; }
    input[type="checkbox"] { width: auto; }
    textarea { min-height: 7rem; resize: vertical; font: inherit; font-size: .85rem; }
    section { margin-top: 1rem; padding-top: 1rem; border-top: 1px solid #374151; }
    .health-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .6rem; }
    .health-card { border: 1px solid #374151; border-radius: .45rem; padding: .7rem; }
    .visual-card { grid-column: 1 / -1; }
    .health-card h3 { margin: 0 0 .4rem; font-size: .75rem; color: #aab5c8; }
    .health-value { font-size: .85rem; font-weight: 650; }
    .health-value[data-tone="good"] { color: #9be3b1; }
    .health-value[data-tone="warning"] { color: #ffd08a; }
    .health-value[data-tone="bad"] { color: #ffb1b8; }
    .health-value[data-tone="unknown"], .health-value[data-tone="idle"] { color: #b8c4d8; }
    .health-detail { margin: .35rem 0 0; font-size: .75rem; overflow-wrap: anywhere; }
    .health-issues { margin: .6rem 0 0; padding-left: 1.2rem; color: #ffd08a; font-size: .75rem; }
    .health-issues:empty { display: none; }
    .music-title { font-size: .95rem; font-weight: 650; overflow-wrap: anywhere; }
    .music-session { margin-bottom: .4rem; font-size: .75rem; }
    .music-progress { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: .35rem .6rem; }
    .music-progress label { margin: 0; }
    progress { width: 100%; height: .55rem; accent-color: #53d3ef; }
    .music-time { font-size: .75rem; color: #b8c4d8; }
    [hidden] { display: none !important; }
    .metadata label { margin-top: .6rem; }
    .hint { margin-top: .3rem; font-size: .75rem; }
    .over-limit { color: #ffb1b8; }
    .row { display: flex; gap: .5rem; margin-top: .55rem; }
    button { flex: 1; padding: .6rem .75rem; border: 0; border-radius: .45rem;
      color: white; font-weight: 700; cursor: pointer; }
    button:disabled { opacity: .45; cursor: not-allowed; }
    #save { background: #374151; }
    #logout { background: #374151; flex: none; }
    #start { background: #16834b; }
    #stop { background: #a52835; }
    #save-metadata { background: #374151; }
    #update-metadata { background: #166582; }
    #message { min-height: 1.1rem; color: #b8c4d8; }
    a { color: #53d3ef; }
    @media (max-width: 560px) {
      .row { flex-wrap: wrap; } button { flex-basis: 100%; }
      .health-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <h1>Control del directo</h1>
  <p>Inicia una emisión pública o detenla. No se inicia automáticamente al reiniciar el servidor.</p>
  <div id="status" class="status">Consultando estado…</div>
  <div id="auth-panel" hidden>
    <label for="token">Token de control · solo para autorizar este navegador</label>
    <input id="token" type="password" autocomplete="off" spellcheck="false">
    <p class="hint">En tu equipo de confianza: la sesión dura hasta 30 días. El token no se guarda en el navegador.</p>
    <div class="row"><button id="save" type="button">Autorizar este navegador</button></div>
  </div>
  <p id="session-status" role="status" aria-live="polite">Comprobando acceso…</p>
  <div class="row">
    <button id="start" type="button" disabled>Iniciar emisión pública</button>
    <button id="stop" type="button" disabled>Detener</button>
    <button id="logout" type="button" hidden>Cerrar sesión</button>
  </div>
  <p id="message" role="status" aria-live="polite"></p>
  <p id="watch"></p>
  <section aria-labelledby="starvios-heading">
    <h2 id="starvios-heading">Multistream · Starvios</h2>
    <p>Comparte cámara, mapa y música con YouTube, sin una segunda codificación. Configura los destinos con la emisión detenida.</p>
    <p id="starvios-output" role="status">Sin envío a Starvios</p>
    <label><input id="starvios-enabled" type="checkbox" disabled> Enviar también a Starvios al iniciar</label>
    <label for="starvios-key">Nueva clave de Starvios · regenera la que mostraste en la captura</label>
    <input id="starvios-key" type="password" autocomplete="new-password" spellcheck="false" maxlength="512" disabled>
    <label><input id="starvios-rotated" type="checkbox" disabled> He regenerado la clave y esta es la nueva</label>
    <p class="hint">Servidor fijo: rtmps://live.cloudflare.com:443/live/ · Deja la clave vacía para conservar la guardada. No se devuelve al navegador.</p>
    <div class="row"><button id="save-starvios" type="button" disabled>Guardar Starvios sin iniciar</button></div>
    <p id="starvios-message" role="status">Autoriza este navegador para configurar.</p>
    <p class="hint">Comprueba la recepción en <a href="https://starvios.com/astrolearnerspace" target="_blank" rel="noopener noreferrer">tu canal de Starvios</a>. No disponemos de confirmación remota por API. Título y descripción de Starvios se editan allí. El inicio y la parada de ambos destinos son conjuntos.</p>
  </section>
  <section aria-labelledby="health-heading">
    <h2 id="health-heading">Salud de la emisión</h2>
    <p>Señal enviada, recepción en YouTube y datos orbitales: cada indicador se comprueba por separado.</p>
    <div class="health-grid">
      <div class="health-card">
        <h3>Fotogramas del servidor</h3>
        <div id="frame-health" class="health-value" data-tone="unknown">Sin confirmación</div>
        <p id="frame-detail" class="health-detail">Esperando estado…</p>
      </div>
      <div class="health-card">
        <h3>Entrada en YouTube</h3>
        <div id="youtube-health" class="health-value" data-tone="unknown">Sin confirmación</div>
        <p id="youtube-detail" class="health-detail">Esperando consulta…</p>
      </div>
      <div class="health-card">
        <h3>Posición ISS</h3>
        <div id="position-health" class="health-value" data-tone="unknown">Sin confirmación</div>
        <p id="position-detail" class="health-detail">Esperando posición válida…</p>
      </div>
      <div class="health-card visual-card">
        <h3>Fuente visual base</h3>
        <div id="visual-health" class="health-value" data-tone="unknown">Sin confirmación</div>
        <p id="visual-detail" class="health-detail">Esperando estado de la cámara y del respaldo…</p>
      </div>
    </div>
    <ul id="youtube-issues" class="health-issues" aria-label="Avisos de YouTube"></ul>
  </section>
  <section aria-labelledby="music-heading">
    <h2 id="music-heading">Ahora suena</h2>
    <p id="music-session" class="music-session"></p>
    <div id="music-title" class="music-title">Sin reproducción</div>
    <p id="music-position" class="hint">La música se iniciará con el directo.</p>
    <div id="music-progress" class="music-progress" hidden>
      <label for="track-progress">Tema actual</label>
      <span id="track-time" class="music-time"></span>
      <progress id="track-progress" max="1" value="0"></progress>
      <span></span>
      <label for="session-progress">Sesión en bucle</label>
      <span id="session-time" class="music-time"></span>
      <progress id="session-progress" max="1" value="0"></progress>
      <span></span>
    </div>
    <p class="hint">Progreso aproximado de la música enviada; YouTube puede reproducirla con retraso.</p>
  </section>
  <section class="metadata" aria-labelledby="presentation-heading">
    <h2 id="presentation-heading">Presentación y música</h2>
    <p>El respaldo cambia sin cortar. Panel y música se aplican en el próximo bloque, nunca reiniciando el actual.</p>
    <label><input id="dashboard-enabled" type="checkbox" disabled> Panel orbital con Sol, Tierra, Luna y pronóstico de auroras</label>
    <label><input id="recorded-fallback" type="checkbox" disabled> Usar vídeos grabados cuando falla la cámara (desmarca para mostrar el mapa)</label>
    <label for="music-style">Música para el próximo bloque</label>
    <select id="music-style" disabled><option value="classic">Lo-Fi anterior</option><option value="melodic">Piano orbital melódico</option></select>
    <div class="row"><button id="save-presentation" type="button" disabled>Guardar presentación sin reiniciar</button></div>
    <p id="presentation-message" role="status" aria-live="polite">Autoriza este navegador para configurar.</p>
  </section>
  <section class="metadata" aria-labelledby="metadata-heading">
    <h2 id="metadata-heading">Título y descripción</h2>
    <p>Guarda los cambios antes de iniciar. Se usarán en los próximos directos; actualizar el actual también los guarda para futuras emisiones.</p>
    <label for="live-title">Título del directo</label>
    <input id="live-title" type="text" maxlength="100" autocomplete="off" disabled>
    <p class="hint">Máximo 100 caracteres.</p>
    <label for="live-description">Descripción</label>
    <textarea id="live-description" rows="6" aria-describedby="description-count" disabled></textarea>
    <p id="description-count" class="hint">0 / 5000 bytes UTF-8</p>
    <div class="row">
      <button id="save-metadata" type="button" disabled>Guardar para próximos directos</button>
      <button id="update-metadata" type="button" disabled>Actualizar directo actual</button>
    </div>
    <p id="metadata-message" role="status" aria-live="polite">Desbloquea los controles para editar.</p>
  </section>
  <script src="control.js" defer></script>
</body>
</html>
""",
        encoding="utf-8",
    )
    (status_dir / "control.js").write_text(
        """(() => {
  const tokenInput = document.getElementById('token');
  const saveButton = document.getElementById('save');
  const authPanel = document.getElementById('auth-panel');
  const sessionStatus = document.getElementById('session-status');
  const logoutButton = document.getElementById('logout');
  const startButton = document.getElementById('start');
  const stopButton = document.getElementById('stop');
  const statusBox = document.getElementById('status');
  const message = document.getElementById('message');
  const watch = document.getElementById('watch');
  const titleInput = document.getElementById('live-title');
  const descriptionInput = document.getElementById('live-description');
  const descriptionCount = document.getElementById('description-count');
  const saveMetadataButton = document.getElementById('save-metadata');
  const updateMetadataButton = document.getElementById('update-metadata');
  const metadataMessage = document.getElementById('metadata-message');
  const starviosEnabled = document.getElementById('starvios-enabled');
  const starviosKey = document.getElementById('starvios-key');
  const starviosRotated = document.getElementById('starvios-rotated');
  const saveStarviosButton = document.getElementById('save-starvios');
  const starviosMessage = document.getElementById('starvios-message');
  const starviosOutput = document.getElementById('starvios-output');
  let starviosLoaded = false;
  let presentationLoaded = false;
  const dashboardEnabled = document.getElementById('dashboard-enabled');
  const recordedFallback = document.getElementById('recorded-fallback');
  const musicStyle = document.getElementById('music-style');
  const savePresentation = document.getElementById('save-presentation');
  const presentationMessage = document.getElementById('presentation-message');
  const frameHealth = document.getElementById('frame-health');
  const frameDetail = document.getElementById('frame-detail');
  const youtubeHealth = document.getElementById('youtube-health');
  const youtubeDetail = document.getElementById('youtube-detail');
  const youtubeIssues = document.getElementById('youtube-issues');
  const positionHealth = document.getElementById('position-health');
  const positionDetail = document.getElementById('position-detail');
  const visualHealth = document.getElementById('visual-health');
  const visualDetail = document.getElementById('visual-detail');
  const musicSession = document.getElementById('music-session');
  const musicTitle = document.getElementById('music-title');
  const musicPosition = document.getElementById('music-position');
  const musicProgress = document.getElementById('music-progress');
  const trackProgress = document.getElementById('track-progress');
  const trackTime = document.getElementById('track-time');
  const sessionProgress = document.getElementById('session-progress');
  const sessionTime = document.getElementById('session-time');
  let state = null;
  let authenticated = false;
  let sessionChecked = false;
  let busy = false;
  let metadataLoaded = false;
  let refreshing = false;

  function ageSeconds(timestamp, now = Date.now()) {
    if (typeof timestamp !== 'string' || !timestamp) return null;
    const milliseconds = Date.parse(timestamp);
    if (!Number.isFinite(milliseconds) || milliseconds > now + 5000) return null;
    return Math.max(0, (now - milliseconds) / 1000);
  }

  function ageLabel(age) {
    if (age === null) return 'sin fecha válida';
    if (age < 60) return `hace ${Math.floor(age)} s`;
    if (age < 3600) return `hace ${Math.floor(age / 60)} min`;
    return `hace ${Math.floor(age / 3600)} h`;
  }

  function currentState() {
    const age = state && ageSeconds(state.updated_at);
    return Boolean(state && age !== null && age <= 15);
  }

  function emissionRequested() {
    return Boolean(state && state.mode === 'youtube' && state.live_requested === true);
  }

  function setHealth(node, text, tone) {
    node.textContent = text;
    node.dataset.tone = tone;
  }

  function safeText(value, maxLength = 120) {
    return typeof value === 'string' ? value.slice(0, maxLength) : '';
  }

  function numberOrNull(value) {
    return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
  }

  function clockLabel(seconds) {
    const total = Math.floor(seconds);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const remainder = String(total % 60).padStart(2, '0');
    return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${remainder}` : `${minutes}:${remainder}`;
  }

  function renderVisualSource() {
    if (!state || !currentState()) {
      setHealth(visualHealth, 'Fuente visual sin confirmar', 'unknown');
      visualDetail.textContent = 'No se dispone de un estado reciente del servidor.';
      return;
    }
    const enabled = state.camera_enabled === true;
    const configured = state.camera_configured === true;
    const outputAge = ageSeconds(state.last_frame_at);
    const outputConfirmed = state.ffmpeg_running === true && outputAge !== null && outputAge <= 15;
    if (!emissionRequested()) {
      setHealth(visualHealth, 'Sin emisión', 'idle');
      visualDetail.textContent = enabled && !configured
        ? 'Cámara sin configurar; el respaldo se utilizará al iniciar.'
        : 'La fuente seleccionada se enviará al iniciar el directo.';
      return;
    }
    if (!outputConfirmed) {
      setHealth(visualHealth, 'Fuente visual sin confirmar', 'unknown');
      visualDetail.textContent = 'Esperando fotogramas recientes de la salida de vídeo.';
      return;
    }
    const mode = state.video_mode;
    if (!enabled) {
      // Old deployments may have a direct source instead of the new selector.
      // Only display a bounded attribution, never a URL or an arbitrary error.
      const attribution = safeText(state.visual_source, 160);
      const legacySource = !['recorded', 'map', 'camera'].includes(mode)
        && attribution && !/https?:|rtmp:|[?=&]|@/i.test(attribution);
      setHealth(visualHealth, mode === 'map' ? 'Mapa orbital' : legacySource ? 'Fuente visual configurada' : 'Vídeos grabados', 'good');
      visualDetail.textContent = legacySource
        ? `${attribution} · selector de cámara desactivado.`
        : 'Cámara externa desactivada; imágenes grabadas y mapa, no una cámara ISS en directo.';
      return;
    }
    if (!configured) {
      setHealth(visualHealth, 'Cámara sin configurar', 'warning');
      visualDetail.textContent = mode === 'map'
        ? 'Se está enviando el mapa orbital como respaldo.'
        : 'Se están enviando imágenes grabadas y el mapa como respaldo.';
      return;
    }
    const cameraAge = ageSeconds(state.camera_last_frame_at);
    const timeout = numberOrNull(state.camera_timeout_seconds);
    const cameraFresh = cameraAge !== null && cameraAge <= (timeout && timeout <= 120 ? timeout : 8);
    if (mode === 'camera' && state.camera_available === true && state.camera_state === 'live' && cameraFresh) {
      setHealth(visualHealth, 'Señal externa ISS', 'good');
      visualDetail.textContent = `Último fotograma de la fuente: ${ageLabel(cameraAge)}. La continuidad depende del proveedor; puede incluir material grabado.`;
      return;
    }
    const reasons = {
      camera_unconfigured: 'Cámara sin configurar.',
      camera_disabled: 'Cámara desactivada.',
      camera_connecting: 'Conectando con la cámara.',
      camera_unstable: 'Esperando una señal de cámara estable antes de volver.',
      camera_stale: 'No llegan fotogramas recientes de la cámara.',
      camera_timeout: 'No llegan fotogramas recientes de la cámara.',
      camera_error: 'La cámara no está disponible.',
      camera_recovering: 'Esperando una señal de cámara estable antes de volver.',
      camera_unavailable: 'La cámara no está disponible.',
      camera_stabilizing: 'Esperando una señal de cámara estable antes de volver.',
      recorded_unavailable: 'Los vídeos de respaldo no están disponibles.',
      recorded_requested: 'Respaldo de vídeos seleccionado manualmente.',
      map_requested: 'Mapa orbital seleccionado manualmente.',
      map_unavailable: 'No se puede confirmar el mapa de respaldo.',
      camera_not_ready: 'Esperando una señal de cámara estable antes de volver.',
    };
    const cameraStates = {
      connecting: 'Conectando con la cámara.',
      stale: 'No llegan fotogramas recientes de la cámara.',
      error: 'La cámara no está disponible.',
      recovering: 'Esperando una señal de cámara estable antes de volver.',
    };
    const reason = reasons[state.video_fallback_reason] || cameraStates[state.camera_state]
      || 'La señal externa de cámara no está confirmada.';
    if (mode === 'recorded' || mode === 'map') {
      setHealth(visualHealth, mode === 'map' ? 'Respaldo: mapa orbital' : 'Respaldo: vídeos grabados', 'warning');
      visualDetail.textContent = `${reason} La música y la misma emisión continúan.`;
    } else {
      setHealth(visualHealth, 'Fuente visual sin confirmar', 'unknown');
      visualDetail.textContent = `${reason} Último fotograma de la cámara: ${ageLabel(cameraAge)}.`;
    }
    const switches = numberOrNull(state.video_switch_count);
    const switchedAge = ageSeconds(state.video_switch_at);
    if (switches !== null && switches > 0) {
      visualDetail.textContent += ` Cambios de fuente: ${Math.floor(switches)}; último ${ageLabel(switchedAge)}.`;
    }
  }

  function renderHealth() {
    renderVisualSource();
    youtubeIssues.replaceChildren();
    if (!state) {
      setHealth(frameHealth, 'Estado no disponible', 'unknown');
      setHealth(youtubeHealth, 'Estado no disponible', 'unknown');
      setHealth(positionHealth, 'Estado no disponible', 'unknown');
      frameDetail.textContent = 'No se pudo leer el estado del servidor.';
      youtubeDetail.textContent = 'No se puede confirmar la recepción de la señal.';
      positionDetail.textContent = 'No se puede confirmar la antigüedad de la posición.';
      return;
    }
    const now = Date.now();
    const frameAge = ageSeconds(state.last_frame_at, now);
    const progressAge = ageSeconds(state.last_progress_at, now);
    const positionAge = ageSeconds(state.position_updated_at, now);
    const checkAge = ageSeconds(state.youtube_checked_at, now);
    const healthAge = ageSeconds(state.youtube_health_updated_at, now);
    const requested = emissionRequested();
    const frameCount = numberOrNull(state.ffmpeg_frame_count);

    if (!requested) {
      setHealth(frameHealth, 'Sin emisión', 'idle');
      frameDetail.textContent = 'No se están enviando fotogramas a YouTube.';
      setHealth(youtubeHealth, 'Sin emisión', 'idle');
      youtubeDetail.textContent = 'La simulación no transmite a YouTube.';
    } else {
      frameDetail.textContent = `Último fotograma: ${ageLabel(frameAge)} · progreso: ${ageLabel(progressAge)}`;
      if (frameCount !== null) frameDetail.textContent += ` · ${Math.floor(frameCount)} fotogramas`;
      if (state.ffmpeg_running !== true) {
        setHealth(frameHealth, frameCount ? 'Sin señal del servidor' : 'Esperando señal', frameCount ? 'bad' : 'unknown');
      } else if (frameAge === null) {
        setHealth(frameHealth, 'Esperando primer fotograma', 'unknown');
      } else if (frameAge > 15) {
        setHealth(frameHealth, 'Posible señal bloqueada', 'warning');
      } else {
        setHealth(frameHealth, 'Fotogramas recientes', 'good');
      }

      const lifecycle = safeText(state.youtube_lifecycle_status, 30);
      const privacyLabels = { public: 'pública', private: 'privada', unlisted: 'no listada' };
      const privacy = privacyLabels[state.youtube_privacy_status];
      youtubeDetail.textContent = `Última consulta: ${ageLabel(checkAge)} · salud: ${ageLabel(healthAge)}`;
      if (privacy) youtubeDetail.textContent += ` · ${privacy}`;
      if (state.youtube_check_error) {
        setHealth(youtubeHealth, 'Consulta no disponible', 'unknown');
      } else if (checkAge === null || healthAge === null || checkAge > 150 || healthAge > 150) {
        setHealth(youtubeHealth, 'Verificación pendiente o antigua', 'unknown');
      } else if (lifecycle === 'complete' || lifecycle === 'revoked') {
        setHealth(youtubeHealth, 'Emisión cerrada en YouTube', 'bad');
      } else if (state.youtube_stream_status === 'error' || state.youtube_health_status === 'bad') {
        setHealth(youtubeHealth, 'YouTube detecta problemas', 'bad');
      } else if (state.youtube_stream_status === 'inactive') {
        setHealth(youtubeHealth, 'YouTube no recibe datos', 'warning');
      } else if (state.youtube_health_status === 'noData') {
        setHealth(youtubeHealth, 'Salud todavía no disponible', 'unknown');
      } else if (state.youtube_stream_status === 'active' && lifecycle === 'live'
        && ['good', 'ok'].includes(state.youtube_health_status)) {
        const issues = Array.isArray(state.youtube_health_issues) ? state.youtube_health_issues : [];
        setHealth(youtubeHealth, issues.length ? 'Señal recibida con avisos' : 'Señal recibida', issues.length ? 'warning' : 'good');
      } else {
        setHealth(youtubeHealth, 'Esperando confirmación de YouTube', 'unknown');
      }
      if (checkAge !== null && healthAge !== null && checkAge <= 150 && healthAge <= 150
        && !state.youtube_check_error && Array.isArray(state.youtube_health_issues)) {
        for (const issue of state.youtube_health_issues.slice(0, 8)) {
          if (!issue || typeof issue !== 'object') continue;
          const type = safeText(issue.type, 80);
          const severity = safeText(issue.severity, 24);
          if (!type) continue;
          const item = document.createElement('li');
          item.textContent = `YouTube: ${type}${severity ? ` (${severity})` : ''}`;
          youtubeIssues.append(item);
        }
      }
    }

    positionDetail.textContent = `Última posición válida: ${ageLabel(positionAge)}`;
    if (positionAge === null) {
      setHealth(positionHealth, 'Posición sin confirmar', 'unknown');
    } else if (positionAge > 60) {
      setHealth(positionHealth, 'Datos orbitales antiguos', 'warning');
    } else {
      setHealth(positionHealth, 'Posición actualizada', 'good');
    }
  }

  function renderMusic() {
    musicProgress.hidden = true;
    trackProgress.max = sessionProgress.max = 1;
    trackProgress.value = sessionProgress.value = 0;
    trackTime.textContent = sessionTime.textContent = '';
    musicSession.textContent = state ? safeText(state.music_session, 180) : '';
    const frameAge = state && ageSeconds(state.last_frame_at);
    if (!state) {
      musicTitle.textContent = 'Reproducción sin confirmar';
      musicPosition.textContent = 'No se pudo leer el estado del servidor.';
      return;
    }
    if (!emissionRequested()) {
      musicTitle.textContent = 'Sin reproducción';
      musicPosition.textContent = 'La música se iniciará con el próximo directo.';
      return;
    }
    if (state.music_playback_active !== true || state.ffmpeg_running !== true
      || frameAge === null || frameAge > 15) {
      musicTitle.textContent = 'Reproducción sin confirmar';
      musicPosition.textContent = 'Esperando una señal reciente; el progreso no avanza sin confirmación.';
      return;
    }
    musicTitle.textContent = safeText(state.music_track) || 'Música de la emisión';
    const index = numberOrNull(state.music_track_index);
    const count = numberOrNull(state.music_track_count);
    musicPosition.textContent = index && count && index <= count ? `Tema ${Math.floor(index)} de ${Math.floor(count)}` : 'Pista en bucle';
    const elapsed = numberOrNull(state.music_track_elapsed_seconds);
    const duration = numberOrNull(state.music_track_duration_seconds);
    const sessionElapsed = numberOrNull(state.music_session_elapsed_seconds);
    const sessionDuration = numberOrNull(state.music_session_duration_seconds);
    if (elapsed !== null && duration !== null && duration > 0
      && sessionElapsed !== null && sessionDuration !== null && sessionDuration > 0) {
      musicProgress.hidden = false;
      trackProgress.max = duration;
      trackProgress.value = Math.min(elapsed, duration);
      trackTime.textContent = `${clockLabel(elapsed)} / ${clockLabel(duration)}`;
      sessionProgress.max = sessionDuration;
      sessionProgress.value = Math.min(sessionElapsed, sessionDuration);
      sessionTime.textContent = `${clockLabel(sessionElapsed)} / ${clockLabel(sessionDuration)}`;
    }
  }

  function descriptionBytes() {
    return new TextEncoder().encode(descriptionInput.value).length;
  }

  function renderMetadataCount() {
    const bytes = descriptionBytes();
    descriptionCount.textContent = `${bytes} / 5000 bytes UTF-8`;
    descriptionCount.classList.toggle('over-limit', bytes > 5000);
  }

  function renderButtons() {
    const unlocked = authenticated;
    const desired = Boolean(state && state.live_requested === true);
    const fresh = currentState();
    const ready = Boolean(fresh && state.control_ready === true);
    const validMetadata = Boolean(titleInput.value.trim()) && descriptionBytes() <= 5000;
    startButton.disabled = busy || !unlocked || !ready || desired;
    stopButton.disabled = busy || !unlocked || (fresh && !desired);
    saveButton.disabled = busy || !sessionChecked;
    logoutButton.disabled = busy;
    logoutButton.hidden = !unlocked;
    authPanel.hidden = !sessionChecked || unlocked;
    titleInput.disabled = busy || !unlocked || !metadataLoaded;
    descriptionInput.disabled = busy || !unlocked || !metadataLoaded;
    saveMetadataButton.disabled = busy || !unlocked || !metadataLoaded || !validMetadata;
    updateMetadataButton.disabled = busy || !unlocked || !metadataLoaded || !validMetadata
      || !fresh || !desired || !state.youtube_watch_url;
    tokenInput.placeholder = 'Solo necesario al autorizar este navegador';
    for (const input of [dashboardEnabled, recordedFallback, musicStyle, savePresentation]) input.disabled = busy || !unlocked || !presentationLoaded;
    const destinationsLocked = busy || !unlocked || !starviosLoaded || !fresh || desired || state.ffmpeg_running === true;
    for (const input of [starviosEnabled, starviosKey, starviosRotated, saveStarviosButton]) input.disabled = destinationsLocked;
    starviosOutput.textContent = fresh && state.starvios_output_active === true
      ? 'Salida local preparada con reconexión · recepción en Starvios SIN verificar'
      : 'Sin envío local activo a Starvios';
  }

  function rejectToken(error) {
    if (error.status === 401) {
      authenticated = false;
      tokenInput.value = '';
      metadataLoaded = false;
      starviosLoaded = false;
      starviosKey.value = '';
      sessionStatus.textContent = 'Sesión caducada o revocada. Autoriza de nuevo este navegador.';
    }
  }

  async function readResult(response) {
    const result = await response.json();
    if (!response.ok) {
      const detail = result.detail;
      const error = new Error(typeof detail === 'string' ? detail : 'La operación fue rechazada');
      error.status = response.status;
      throw error;
    }
    return result;
  }

  async function loadMetadata() {
    if (busy || !authenticated) return;
    busy = true;
    metadataLoaded = false;
    metadataMessage.textContent = 'Cargando título y descripción…';
    renderButtons();
    try {
      const response = await fetch('/iss-live/control/metadata', {
        credentials: 'same-origin',
        cache: 'no-store',
      });
      const result = await readResult(response);
      titleInput.value = result.title;
      descriptionInput.value = result.description;
      metadataLoaded = true;
      metadataMessage.textContent = 'Puedes editar los datos y guardarlos antes de iniciar.';
      renderMetadataCount();
      await loadStarvios();
      await loadPresentation();
    } catch (error) {
      rejectToken(error);
      metadataMessage.textContent = error.message;
    } finally {
      busy = false;
      renderButtons();
    }
  }

  async function loadStarvios() {
    starviosLoaded = false;
    try {
      const response = await fetch('/iss-live/control/starvios', { credentials: 'same-origin', cache: 'no-store' });
      const result = await readResult(response);
      if (typeof result.enabled !== 'boolean' || typeof result.configured !== 'boolean') throw new Error('No se pudo leer la configuración de Starvios');
      starviosEnabled.checked = result.enabled;
      starviosKey.value = '';
      starviosRotated.checked = false;
      starviosLoaded = true;
      starviosMessage.textContent = result.configured ? 'Hay una clave privada guardada. Guardar no inicia ni verifica la emisión.' : 'Sin clave guardada. Introduce únicamente la clave regenerada.';
    } catch (error) {
      rejectToken(error);
      starviosMessage.textContent = error.message;
    }
  }

  async function loadPresentation() {
    presentationLoaded = false;
    try {
      const response = await fetch('/iss-live/control/presentation', {credentials: 'same-origin', cache: 'no-store'});
      const result = await readResult(response);
      dashboardEnabled.checked = result.dashboard_enabled === true;
      recordedFallback.checked = result.recorded_fallback_enabled === true;
      musicStyle.value = result.music_style === 'melodic' ? 'melodic' : 'classic';
      presentationLoaded = true;
      presentationMessage.textContent = result.dashboard_active ? 'Panel activo. Música y cambios de diseño: próximo bloque.' : 'Panel y música se aplicarán en el próximo bloque. El mapa de respaldo no detiene los reintentos de cámara.';
    } catch (error) {
      rejectToken(error);
      presentationMessage.textContent = error.message;
    }
  }

  savePresentation.addEventListener('click', async () => {
    if (busy || !authenticated || !presentationLoaded) return;
    busy = true;
    renderButtons();
    try {
      const response = await fetch('/iss-live/control/presentation', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({dashboard_enabled: dashboardEnabled.checked,
          recorded_fallback_enabled: recordedFallback.checked, music_style: musicStyle.value}),
      });
      await readResult(response);
      presentationMessage.textContent = 'Guardado sin cortar: respaldo aplicado ahora; panel y música en el próximo bloque.';
    } catch (error) {
      rejectToken(error);
      presentationMessage.textContent = error.message;
    } finally { busy = false; renderButtons(); }
  });

  saveStarviosButton.addEventListener('click', async () => {
    if (busy || !authenticated || !starviosLoaded || !currentState() || emissionRequested() || state.ffmpeg_running) return;
    busy = true;
    renderButtons();
    try {
      const response = await fetch('/iss-live/control/starvios', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: starviosEnabled.checked, key: starviosKey.value || null, rotated_key_confirmed: starviosRotated.checked }),
      });
      starviosKey.value = '';
      await readResult(response);
      await loadStarvios();
      starviosMessage.textContent = 'Guardado sin publicar. Al iniciar se enviará a YouTube' + (starviosEnabled.checked ? ' y Starvios.' : ' solamente.');
    } catch (error) {
      rejectToken(error);
      starviosMessage.textContent = error.message;
    } finally {
      starviosKey.value = '';
      starviosRotated.checked = false;
      busy = false;
      renderButtons();
    }
  });

  async function refresh() {
    if (refreshing) return;
    refreshing = true;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch('/iss-live/status.json', { cache: 'no-store', signal: controller.signal });
      if (!response.ok) throw new Error('No se pudo leer el estado');
      const result = await response.json();
      if (!result || typeof result !== 'object' || Array.isArray(result)
        || typeof result.status !== 'string' || typeof result.mode !== 'string'
        || typeof result.live_requested !== 'boolean' || typeof result.control_ready !== 'boolean') {
        throw new Error('Estado no válido');
      }
      state = result;
      statusBox.textContent = `${state.status} · ${state.mode === 'youtube' ? 'YouTube' : 'simulación'}`;
      if (!state.control_ready && !state.live_requested) {
        statusBox.textContent += ' · Controles desactivados';
      }
      if (!currentState()) statusBox.textContent += ' · Estado sin actualizar';
      watch.replaceChildren();
      const watchUrl = publicWatchUrl(state.youtube_watch_url);
      if (emissionRequested() && watchUrl) {
        const link = document.createElement('a');
        link.href = watchUrl;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = 'Abrir emisión en YouTube';
        watch.append(link);
      }
    } catch (_) {
      state = null;
      watch.replaceChildren();
      statusBox.textContent = 'No se pudo leer el estado. Inicio y actualización del directo desactivados.';
    } finally {
      window.clearTimeout(timeout);
      refreshing = false;
      renderHealth();
      renderMusic();
      renderButtons();
    }
  }

  function publicWatchUrl(value) {
    if (typeof value !== 'string') return '';
    try {
      const url = new URL(value);
      const id = url.searchParams.get('v');
      if (url.protocol !== 'https:' || !['www.youtube.com', 'youtube.com'].includes(url.hostname)
        || url.pathname !== '/watch' || url.port || url.username || url.password
        || !id || !/^[A-Za-z0-9_-]{11}$/.test(id)) return '';
      return `https://www.youtube.com/watch?v=${id}`;
    } catch (_) {
      return '';
    }
  }

  async function authorizeBrowser(candidate) {
    if (candidate.length < 32) {
      message.textContent = 'El token debe tener al menos 32 caracteres.';
      return;
    }
    busy = true;
    tokenInput.value = '';
    renderButtons();
    try {
      const response = await fetch('/iss-live/control/session', {
        method: 'POST', headers: { Authorization: `Bearer ${candidate}` },
        credentials: 'same-origin', cache: 'no-store',
      });
      await readResult(response);
      candidate = '';
      // Check that the browser really accepted the Secure cookie before unlocking.
      const check = await fetch('/iss-live/control/session', {
        credentials: 'same-origin', cache: 'no-store',
      });
      const result = await readResult(check);
      authenticated = result.authenticated === true;
      if (!authenticated) throw new Error('No se pudo recordar el acceso. Abre el portal por HTTPS y permite sus cookies.');
      sessionStatus.textContent = 'Navegador autorizado · sesión de hasta 30 días.';
      message.textContent = 'Acceso recordado. No necesitas volver a pegar el token en cada pestaña.';
    } catch (error) {
      rejectToken(error);
      message.textContent = error.message;
    } finally {
      candidate = '';
      busy = false;
      renderButtons();
    }
    if (authenticated) await loadMetadata();
  }

  async function restoreSession() {
    // One-time migration: immediately remove the old tab-stored credential.
    let legacy = '';
    try {
      legacy = sessionStorage.getItem('astrolearner-live-control-token') || '';
      sessionStorage.removeItem('astrolearner-live-control-token');
    } catch (_) { /* Storage restrictions must not prevent cookie sessions. */ }
    try {
      const response = await fetch('/iss-live/control/session', {
        credentials: 'same-origin', cache: 'no-store',
      });
      const result = await readResult(response);
      authenticated = result.authenticated === true;
      sessionStatus.textContent = authenticated
        ? 'Navegador autorizado · no necesitas introducir el token.'
        : 'Autoriza este navegador una vez para usar los controles.';
    } catch (_) {
      sessionStatus.textContent = 'No se pudo comprobar el acceso. Los controles siguen bloqueados.';
    } finally {
      sessionChecked = true;
      renderButtons();
    }
    if (!authenticated && legacy.length >= 32) await authorizeBrowser(legacy);
    else if (authenticated) await loadMetadata();
    legacy = '';
  }

  saveButton.addEventListener('click', async () => {
    if (busy || !sessionChecked) return;
    await authorizeBrowser(tokenInput.value.trim());
  });

  logoutButton.addEventListener('click', async () => {
    if (busy || !authenticated) return;
    busy = true;
    renderButtons();
    try {
      const response = await fetch('/iss-live/control/session/logout', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
      });
      await readResult(response);
      authenticated = false;
      metadataLoaded = false;
      tokenInput.value = '';
      starviosLoaded = false;
      starviosKey.value = '';
      sessionStatus.textContent = 'Sesión cerrada. Los controles están bloqueados.';
      message.textContent = 'Cerrar sesión no detiene la emisión.';
    } catch (error) {
      rejectToken(error);
      message.textContent = error.message;
    } finally {
      busy = false;
      renderButtons();
    }
  });

  async function saveMetadata(applyToCurrent) {
    if (busy || !metadataLoaded || !authenticated) return;
    const title = titleInput.value.trim();
    if (!title || title.length > 100 || descriptionBytes() > 5000) {
      metadataMessage.textContent = 'Introduce un título de hasta 100 caracteres y una descripción de hasta 5000 bytes UTF-8.';
      return;
    }
    if (applyToCurrent && (!currentState() || !emissionRequested() || !state.youtube_watch_url)) return;
    if (applyToCurrent && !window.confirm('Se cambiarán el título y la descripción de la emisión actual en YouTube y se guardarán para los próximos directos. ¿Continuar?')) return;
    busy = true;
    metadataMessage.textContent = applyToCurrent ? 'Actualizando emisión…' : 'Guardando datos…';
    renderButtons();
    try {
      const response = await fetch('/iss-live/control/metadata', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ title, description: descriptionInput.value, apply_to_current: applyToCurrent }),
        cache: 'no-store',
      });
      const result = await readResult(response);
      titleInput.value = result.title;
      descriptionInput.value = result.description;
      renderMetadataCount();
      metadataMessage.textContent = result.applied_to_current
        ? 'Título y descripción actualizados en YouTube y guardados para próximos directos.'
        : 'Datos guardados. Se usarán al iniciar el próximo directo.';
    } catch (error) {
      rejectToken(error);
      metadataMessage.textContent = error.message;
    } finally {
      busy = false;
      renderButtons();
    }
  }

  async function control(action) {
    if (busy || !authenticated) return;
    if (action === 'start' && (!currentState() || !state.control_ready || state.live_requested)) return;
    const prompt = action === 'start'
      ? 'Vas a iniciar una emisión PÚBLICA en YouTube y, si está habilitado, también en Starvios. ¿Continuar?'
      : 'Se detendrá el envío a YouTube y a Starvios, si está habilitado. ¿Continuar?';
    if (!window.confirm(prompt)) return;
    busy = true;
    message.textContent = action === 'start' ? 'Solicitando inicio…' : 'Deteniendo emisión…';
    renderButtons();
    try {
      const response = await fetch(`/iss-live/control/${action}`, {
        method: 'POST',
        credentials: 'same-origin',
        cache: 'no-store',
      });
      await readResult(response);
      message.textContent = action === 'start'
        ? 'Inicio solicitado. La emisión aparecerá en unos segundos.'
        : 'Parada solicitada; YouTube cerrará el bloque actual.';
      await refresh();
    } catch (error) {
      rejectToken(error);
      message.textContent = error.message;
    } finally {
      busy = false;
      renderButtons();
    }
  }

  startButton.addEventListener('click', () => control('start'));
  stopButton.addEventListener('click', () => control('stop'));
  saveMetadataButton.addEventListener('click', () => saveMetadata(false));
  updateMetadataButton.addEventListener('click', () => saveMetadata(true));
  titleInput.addEventListener('input', renderButtons);
  descriptionInput.addEventListener('input', () => {
    renderMetadataCount();
    renderButtons();
  });
  renderButtons();
  renderHealth();
  renderMusic();
  refresh();
  restoreSession();
  window.setInterval(refresh, 3000);
})();
""",
        encoding="utf-8",
    )
