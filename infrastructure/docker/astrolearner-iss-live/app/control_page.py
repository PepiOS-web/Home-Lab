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
    h1 { margin: 0 0 .2rem; font-size: 1rem; }
    p { margin: .3rem 0 .8rem; color: #aab5c8; font-size: .8rem; }
    .status { margin-bottom: .8rem; font-weight: 650; }
    label { display: block; margin-bottom: .3rem; color: #aab5c8; font-size: .75rem; }
    input { box-sizing: border-box; width: 100%; padding: .55rem; border: 1px solid #4b5563;
      border-radius: .45rem; color: #fff; background: #202431; }
    .row { display: flex; gap: .5rem; margin-top: .55rem; }
    button { flex: 1; padding: .6rem .75rem; border: 0; border-radius: .45rem;
      color: white; font-weight: 700; cursor: pointer; }
    button:disabled { opacity: .45; cursor: not-allowed; }
    #save { background: #374151; }
    #start { background: #16834b; }
    #stop { background: #a52835; }
    #message { min-height: 1.1rem; color: #b8c4d8; }
    a { color: #53d3ef; }
  </style>
</head>
<body>
  <h1>Control del directo</h1>
  <p>Inicia una emisión pública o detenla. No se inicia automáticamente al reiniciar el servidor.</p>
  <div id="status" class="status">Consultando estado…</div>
  <label for="token">Token de control (solo se guarda en esta pestaña)</label>
  <input id="token" type="password" autocomplete="off" spellcheck="false">
  <div class="row">
    <button id="save" type="button">Desbloquear</button>
    <button id="start" type="button" disabled>Iniciar emisión pública</button>
    <button id="stop" type="button" disabled>Detener</button>
  </div>
  <p id="message" role="status" aria-live="polite"></p>
  <p id="watch"></p>
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
  const startButton = document.getElementById('start');
  const stopButton = document.getElementById('stop');
  const statusBox = document.getElementById('status');
  const message = document.getElementById('message');
  const watch = document.getElementById('watch');
  const storageKey = 'astrolearner-live-control-token';
  let state = null;
  let token = sessionStorage.getItem(storageKey) || '';

  function renderButtons() {
    const unlocked = token.length >= 32;
    const desired = Boolean(state && state.live_requested);
    const ready = Boolean(state && state.control_ready);
    startButton.disabled = !unlocked || !ready || desired;
    stopButton.disabled = !unlocked || !desired;
    tokenInput.placeholder = token
      ? 'Token cargado en esta pestaña'
      : 'Pega aquí el token del servidor';
  }

  async function refresh() {
    try {
      const response = await fetch('/iss-live/status.json', { cache: 'no-store' });
      if (!response.ok) throw new Error('No se pudo leer el estado');
      state = await response.json();
      statusBox.textContent = `${state.status} · ${state.mode === 'youtube' ? 'YouTube' : 'simulación'}`;
      if (!state.control_ready && !state.live_requested) {
        statusBox.textContent += ' · Controles desactivados';
      }
      watch.replaceChildren();
      if (state.youtube_watch_url) {
        const link = document.createElement('a');
        link.href = state.youtube_watch_url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = 'Abrir emisión en YouTube';
        watch.append(link);
      }
      renderButtons();
    } catch (error) {
      statusBox.textContent = error.message;
    }
  }

  saveButton.addEventListener('click', () => {
    const candidate = tokenInput.value.trim();
    if (candidate.length < 32) {
      message.textContent = 'El token debe tener al menos 32 caracteres.';
      return;
    }
    token = candidate;
    sessionStorage.setItem(storageKey, token);
    tokenInput.value = '';
    message.textContent = 'Controles desbloqueados en esta pestaña.';
    renderButtons();
  });

  async function control(action) {
    const prompt = action === 'start'
      ? 'Vas a iniciar una emisión PÚBLICA en YouTube. ¿Continuar?'
      : 'Se detendrá la emisión de YouTube. ¿Continuar?';
    if (!window.confirm(prompt)) return;
    message.textContent = action === 'start' ? 'Solicitando inicio…' : 'Deteniendo emisión…';
    startButton.disabled = true;
    stopButton.disabled = true;
    try {
      const response = await fetch(`/iss-live/control/${action}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        cache: 'no-store',
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'La operación fue rechazada');
      message.textContent = action === 'start'
        ? 'Inicio solicitado. La emisión aparecerá en unos segundos.'
        : 'Parada solicitada; YouTube cerrará el bloque actual.';
      await refresh();
    } catch (error) {
      if (error.message.includes('Token de control incorrecto')) {
        token = '';
        sessionStorage.removeItem(storageKey);
        tokenInput.value = '';
      }
      message.textContent = error.message;
      renderButtons();
    }
  }

  startButton.addEventListener('click', () => control('start'));
  stopButton.addEventListener('click', () => control('stop'));
  refresh();
  window.setInterval(refresh, 3000);
})();
""",
        encoding="utf-8",
    )
