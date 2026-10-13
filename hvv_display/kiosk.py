# ruff: noqa: E501
"""Reading-only display styling and progressive browser controls."""

DISPLAY_CSS = """
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap;border:0}
:focus-visible{outline:3px solid #ffdca6;outline-offset:5px}
.departure-list{list-style:none;margin:0;padding:0}
.departure-list .line{overflow-wrap:anywhere;max-width:100%;box-sizing:border-box}
.departure-list .delay{display:block;color:#ffb78d;font-size:1rem}
.departure-list .cancelled{color:#ff9aa5;text-decoration:none}
.departure-list .station{font-size:1rem;overflow-wrap:anywhere}
.departure-list .line-badge-u4,.departure-list .line-badge-s7,.departure-list .line-badge-akn{color:#05080e}
.display-page .display-controls{display:flex;flex-wrap:wrap;gap:16px;align-items:center}
.display-page button{background:#174667;border-color:#8bd3ff;min-height:44px}
.display-page .row>div{min-width:0}
.display-page .line{clip-path:none;border-radius:6px}
.display-page .time{overflow-wrap:anywhere}
.display-page .display-status{font-size:1rem;line-height:1.6;margin:16px 0}
.display-page h2{font-size:1.25rem;margin:16px 0 12px}
.display-page .station{font-size:1rem}
.display-page .display-refresh{text-align:left;font-size:1rem}
@media(max-width:600px){.departure-list .row{grid-template-columns:minmax(0,1fr);gap:12px;padding:16px 12px}.departure-list .row>div:first-child{display:flex;flex-wrap:wrap;align-items:center;gap:12px}.departure-list .time{grid-column:1;text-align:left}.display-page .station{font-size:1rem}.display-page .line{font-size:1.2rem}.display-page .time{font-size:1.5rem}.display-page .destination{font-size:1.15rem}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
"""

DISPLAY_SCRIPT = r"""
(() => {
  const root = document.querySelector('[data-display-mode]');
  if (!root) return;
  const board = root.querySelector('#display-board');
  const state = root.querySelector('#display-state');
  const age = root.querySelector('#display-age');
  const updated = root.querySelector('#display-updated');
  const retry = root.querySelector('#display-retry');
  const announcement = root.querySelector('#display-announcement');
  const fullscreen = root.querySelector('#display-fullscreen');
  const pause = root.querySelector('#display-pause');
  let timer, controller, failures = 0, stopped = false, paused = false;
  let delay = Number(root.dataset.retry) || 15;
  let due = performance.now() + delay * 1000;
  let ageSeconds = root.dataset.age === '' ? null : Number(root.dataset.age);
  let ageAt = performance.now();
  let maxAge = Number(root.dataset.maxAge) || 300;
  let signal = root.dataset.signal;
  let operational = state.textContent;
  let expired = root.dataset.expired === 'true';
  let disconnected = false;
  function announce(message) {
    if (announcement.textContent !== message) announcement.textContent = message;
  }
  function tick() {
    if (ageSeconds !== null) {
      const seconds = Math.max(0, ageSeconds + Math.floor((performance.now() - ageAt) / 1000));
      age.textContent = seconds < 60 ? `${seconds} Sekunden` : `${Math.floor(seconds / 60)} Minuten ${seconds % 60} Sekunden`;
      if (seconds >= maxAge && !expired) {
        expired = true;
        board.innerHTML = '<p class="empty">Letzter Stand zu alt; Abfahrten ausgeblendet.</p>';
        state.textContent = 'Veraltete Daten – keine verlässliche Abfahrtsanzeige.';
        announce(state.textContent);
      }
    }
    retry.textContent = stopped ? 'Automatische Aktualisierung angehalten.' : paused ? 'Aktualisierung pausiert.' : `Nächster Versuch in ${Math.max(0, Math.ceil((due - performance.now()) / 1000))} Sekunden.`;
  }
  function schedule(seconds) {
    clearTimeout(timer);
    delay = seconds;
    due = performance.now() + seconds * 1000;
    if (!paused && !stopped) timer = setTimeout(refresh, seconds * 1000);
    tick();
  }
  async function refresh() {
    if (stopped || paused || controller) return;
    controller = new AbortController();
    const timeout = setTimeout(() => controller?.abort(), 20000);
    try {
      const response = await fetch('/api/display', {cache:'no-store', credentials:'same-origin', signal:controller.signal});
      if (paused || stopped) return;
      if (response.status === 401 || response.status === 403) {
        stopped = true;
        state.textContent = 'Anmeldung erforderlich. Standardansicht öffnen und erneut anmelden.';
        announce(state.textContent);
        return;
      }
      if (!response.ok) throw new Error('unavailable');
      const data = await response.json();
      if (typeof data.board_html !== 'string' || typeof data.state !== 'string' ||
          !Number.isFinite(data.retry_in_seconds) || data.retry_in_seconds < 1 ||
          data.retry_in_seconds > 3600 || !Number.isFinite(data.max_age_seconds) ||
          !(data.data_age_seconds === null || Number.isFinite(data.data_age_seconds))) throw new Error('invalid');
      failures = 0;
      board.innerHTML = data.board_html; // Authenticated, escaped server-rendered fragment.
      state.textContent = data.state;
      ageSeconds = data.data_age_seconds;
      ageAt = performance.now();
      maxAge = data.max_age_seconds;
      expired = data.expired;
      updated.textContent = data.last_updated_label;
      if (disconnected || operational !== data.state) announce(data.state);
      else if (signal !== data.signal) announce(data.change_summary);
      disconnected = false;
      operational = data.state;
      signal = data.signal;
      schedule(data.retry_in_seconds);
    } catch {
      if (paused || stopped) return;
      failures = Math.min(failures + 1, 5);
      disconnected = true;
      state.textContent = 'Verbindung unterbrochen – letzter Stand bleibt bis zur Altersgrenze sichtbar.';
      announce(state.textContent);
      schedule(Math.min(300, 15 * 2 ** failures));
    } finally {
      clearTimeout(timeout);
      controller = null;
    }
  }
  pause.hidden = false;
  pause.addEventListener('click', () => {
    paused = !paused;
    pause.setAttribute('aria-pressed', String(paused));
    pause.textContent = paused ? 'Aktualisierung fortsetzen' : 'Aktualisierung pausieren';
    if (paused) { clearTimeout(timer); controller?.abort(); }
    else schedule(Math.max(1, Math.ceil((due - performance.now()) / 1000)));
    tick();
  });
  if (document.fullscreenEnabled && root.requestFullscreen) {
    fullscreen.hidden = false;
    fullscreen.addEventListener('click', async () => {
      try {
        if (document.fullscreenElement) await document.exitFullscreen();
        else await document.documentElement.requestFullscreen();
      } catch { announce('Vollbild nicht verfügbar. Browser-Vollbild kann über F11 aktiviert werden.'); }
    });
    document.addEventListener('fullscreenchange', () => {
      fullscreen.textContent = document.fullscreenElement ? 'Vollbild verlassen' : 'Vollbild';
      fullscreen.setAttribute('aria-pressed', String(Boolean(document.fullscreenElement)));
    });
  }
  const ticker = setInterval(tick, 1000);
  window.addEventListener('pagehide', () => {
    stopped = true; clearTimeout(timer); clearInterval(ticker); controller?.abort();
  }, {once:true});
  window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
  schedule(delay);
})();
"""
