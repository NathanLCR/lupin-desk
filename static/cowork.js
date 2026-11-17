/* Módulo Cowork somente leitura (Today, Sync, First Wake), VAD e mini-pet Electron. */
(function () {
  'use strict';

  const params = new URLSearchParams(window.location.search);
  const isMiniPet = params.get('widget') === 'minipet';
  const isElectronShell = params.get('shell') === 'electron' || Boolean(window.electronAPI);

  const state = {
    vadEnabled: false,
    vadStream: null,
    vadCtx: null,
    vadTimer: null,
    vadRecorder: null,
    vadSttControllers: new Set(),
    vadStarting: false,
    vadSessionId: 0,
    vadSpeaking: false,
    vadSilenceMs: 0,
    syncStatus: 'yellow',
  };

  function el(id) {
    return document.getElementById(id);
  }

  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function syncDotEmoji(status) {
    if (status === 'green') return '🟢';
    if (status === 'red') return '🔴';
    return '🟡';
  }

  function initMiniPetMode() {
    if (!isMiniPet) return;
    document.body.classList.add('is-minipet');
    const stage = el('stage') || el('face-stage');
    const controls = el('mini-pet-controls');
    const dragButton = el('mini-pet-drag');
    const openButton = el('mini-pet-open');
    const hideButton = el('mini-pet-hide');
    const api = window.electronAPI;
    let pointer = null;
    let dragging = false;
    let hitTestTimer = null;
    let lastIgnore = null;

    const setMouseIgnore = (ignore) => {
      if (ignore === lastIgnore) return;
      lastIgnore = ignore;
      if (api && typeof api.setPetIgnoreMouse === 'function') api.setPetIgnoreMouse(ignore);
    };
    const containsPoint = (rect, point, pad = 0) => Boolean(
      rect && rect.width > 0 && rect.height > 0 &&
      point.x >= rect.left - pad && point.x <= rect.right + pad &&
      point.y >= rect.top - pad && point.y <= rect.bottom + pad
    );
    const faceRect = () => (
      window.LupinFace && typeof window.LupinFace.getHitboxRect === 'function'
        ? window.LupinFace.getHitboxRect()
        : null
    );
    const hasControlFocus = () => Boolean(
      controls && document.activeElement && controls.contains(document.activeElement)
    );
    const setInteracting = (active) => {
      if (controls) controls.classList.toggle('is-visible', active);
      document.body.classList.toggle('minipet-interacting', active);
    };
    const refreshHitTest = () => {
      if (document.hidden) {
        setInteracting(false);
        setMouseIgnore(true);
        return;
      }
      const overPet = pointer && containsPoint(faceRect(), pointer, 16);
      const overControls = pointer && controls && containsPoint(controls.getBoundingClientRect(), pointer);
      const focused = hasControlFocus();
      const active = Boolean(overPet || overControls || focused || dragging);
      setInteracting(active);
      setMouseIgnore(!active);
    };
    const rememberPointer = (event) => {
      pointer = { x: event.clientX, y: event.clientY };
      refreshHitTest();
    };
    const clearPointer = () => {
      pointer = null;
      refreshHitTest();
    };
    const stopHitTest = () => {
      if (hitTestTimer !== null) {
        window.clearInterval(hitTestTimer);
        hitTestTimer = null;
      }
      pointer = null;
    };
    const startHitTest = () => {
      if (document.hidden || hitTestTimer !== null) return;
      hitTestTimer = window.setInterval(refreshHitTest, 100);
      refreshHitTest();
    };
    const endDrag = () => {
      if (!dragging) return;
      dragging = false;
      if (api && typeof api.endPetDrag === 'function') api.endPetDrag();
      refreshHitTest();
    };
    const hideMiniPet = () => {
      endDrag();
      stopHitTest();
      setInteracting(false);
      setMouseIgnore(true);
      if (api && typeof api.hideMiniPet === 'function') api.hideMiniPet();
    };

    if (stage) {
      stage.title = 'Duplo clique para abrir o painel do Lupin';
      stage.addEventListener('dblclick', () => {
        if (api && typeof api.openDashboard === 'function') api.openDashboard();
      });
    }
    if (openButton) {
      openButton.addEventListener('click', (event) => {
        event.stopPropagation();
        if (api && typeof api.openDashboard === 'function') api.openDashboard();
      });
    }
    if (hideButton) hideButton.addEventListener('click', hideMiniPet);
    if (dragButton) {
      dragButton.addEventListener('pointerdown', (event) => {
        if (event.button !== undefined && event.button !== 0) return;
        if (event.isPrimary === false) return;
        event.preventDefault();
        event.stopPropagation();
        dragging = true;
        if (typeof dragButton.setPointerCapture === 'function' && event.pointerId !== undefined) {
          dragButton.setPointerCapture(event.pointerId);
        }
        if (api && typeof api.beginPetDrag === 'function') api.beginPetDrag();
        refreshHitTest();
      });
      ['pointerup', 'pointercancel', 'lostpointercapture'].forEach((type) => {
        dragButton.addEventListener(type, (event) => {
          event.stopPropagation();
          endDrag();
        });
      });
    }
    if (controls) {
      ['pointerdown', 'pointerup', 'pointercancel', 'pointermove', 'click', 'dblclick'].forEach((type) => {
        controls.addEventListener(type, (event) => event.stopPropagation());
      });
      controls.addEventListener('pointerover', rememberPointer);
      controls.addEventListener('focusin', refreshHitTest);
      controls.addEventListener('focusout', refreshHitTest);
    }

    window.addEventListener('pointermove', rememberPointer, true);
    window.addEventListener('pointerover', rememberPointer, true);
    window.addEventListener('pointerleave', clearPointer);
    window.addEventListener('blur', () => {
      endDrag();
      clearPointer();
    });
    document.addEventListener('mouseleave', clearPointer);
    document.addEventListener('focusin', refreshHitTest);
    document.addEventListener('focusout', refreshHitTest);
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        endDrag();
        stopHitTest();
        setInteracting(false);
        setMouseIgnore(true);
      } else {
        startHitTest();
      }
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        hideMiniPet();
        return;
      }
      const directions = {
        ArrowLeft: { x: -1, y: 0 },
        ArrowRight: { x: 1, y: 0 },
        ArrowUp: { x: 0, y: -1 },
        ArrowDown: { x: 0, y: 1 },
      };
      const direction = directions[event.key];
      const target = event.target || document.activeElement;
      if (!direction || event.altKey || event.ctrlKey || event.metaKey ||
          (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName || '')))) return;
      const step = event.shiftKey ? 30 : 10;
      event.preventDefault();
      if (api && typeof api.nudgePet === 'function') {
        api.nudgePet({ x: direction.x * step, y: direction.y * step });
      }
    });

    setMouseIgnore(true);
    startHitTest();
  }

  function initElectronTabs() {
    const modeBtn = el('btn-mode-nathan');
    if (modeBtn && isElectronShell) {
      modeBtn.classList.remove('hidden');
    }
    const subTabs = document.querySelectorAll('.nathan-subtab');
    subTabs.forEach((btn) => {
      btn.addEventListener('click', () => {
        const target = btn.dataset.subtab;
        subTabs.forEach((b) => b.classList.toggle('is-active', b === btn));
        document.querySelectorAll('.nathan-subpanel').forEach((panel) => {
          panel.classList.toggle('hidden', panel.id !== `nathan-tab-${target}`);
        });
        if (target === 'today') loadToday();
        if (target === 'sync') loadSync();
      });
    });

    window.addEventListener('desk:modechange', (event) => {
      if (event && event.detail && event.detail.mode === 'nathan') {
        loadToday();
        loadSync();
      }
    });
  }

  async function loadToday() {
    try {
      const resp = await fetch('/api/cowork/today');
      if (!resp.ok) return;
      const data = await resp.json();
      const summary = data.summary || {};

      const nathanHeadline = el('nathan-today-headline');
      const nathanTop = el('nathan-today-top');
      const nathanWarn = el('nathan-today-warnings');
      if (nathanHeadline) nathanHeadline.textContent = summary.headline || '—';
      if (nathanTop) {
        nathanTop.innerHTML = '';
        (summary.top || []).forEach((item) => {
          const li = document.createElement('li');
          li.textContent = `${item.id}: ${item.why}`;
          nathanTop.appendChild(li);
        });
      }
      if (nathanWarn) {
        nathanWarn.innerHTML = '';
        (summary.warnings || []).forEach((w) => {
          const li = document.createElement('li');
          li.textContent = `⚠️ ${w}`;
          nathanWarn.appendChild(li);
        });
      }
    } catch (_) {
      // Ignora erro de rede temporário
    }
  }

  async function loadSync() {
    try {
      const resp = await fetch('/api/cowork/sync');
      if (!resp.ok) return;
      const data = await resp.json();
      state.coworkAvailable = data.cowork_available !== false;
      const modeBtn = el('btn-mode-nathan');
      if (modeBtn && !state.coworkAvailable) {
        modeBtn.classList.add('hidden');
      }
      state.syncStatus = data.sync_status || 'yellow';

      if (window.electronAPI && typeof window.electronAPI.updateTrayStatus === 'function') {
        window.electronAPI.updateTrayStatus({ syncStatus: state.syncStatus });
      }

      const badge = el('nathan-sync-badge');
      const detail = el('nathan-sync-detail');
      if (badge) badge.textContent = `${syncDotEmoji(state.syncStatus)} ${state.syncStatus.toUpperCase()}`;
      if (detail && data.git) {
        detail.textContent = `${data.state_message || ''} | Git: ${data.git.summary || '—'}`;
      }
    } catch (_) {
      // Ignora
    }
  }

  async function toggleVad() {
    const btn = el('btn-vad-toggle');
    const output = el('vad-status');
    if (state.vadEnabled || state.vadStarting) {
      state.vadEnabled = false;
      state.vadStarting = false;
      state.vadSessionId += 1;
      if (state.vadTimer) window.clearInterval(state.vadTimer);
      state.vadTimer = null;
      state.vadSttControllers.forEach((controller) => controller.abort());
      state.vadSttControllers.clear();
      if (state.vadRecorder && state.vadRecorder.state === 'recording') state.vadRecorder.stop();
      state.vadRecorder = null;
      if (state.vadStream) state.vadStream.getTracks().forEach((t) => t.stop());
      if (state.vadCtx) state.vadCtx.close().catch(() => {});
      state.vadStream = null;
      state.vadCtx = null;
      state.vadSpeaking = false;
      state.vadSilenceMs = 0;
      if (btn) {
        btn.classList.remove('is-active');
        btn.setAttribute('aria-pressed', 'false');
        btn.textContent = '🎙️ VAD';
      }
      return;
    }

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      if (output) output.textContent = 'Microfone indisponível. Use HTTPS ou localhost e confira a permissão do navegador antes de tentar novamente.';
      return;
    }

    const sessionId = ++state.vadSessionId;
    state.vadStarting = true;
    if (btn) btn.textContent = '⏳ Abrindo microfone…';
    let stream;
    let ctx;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (sessionId !== state.vadSessionId || !state.vadStarting) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      src.connect(analyser);

      state.vadStarting = false;
      state.vadEnabled = true;
      state.vadStream = stream;
      state.vadCtx = ctx;
      if (btn) {
        btn.classList.add('is-active');
        btn.setAttribute('aria-pressed', 'true');
        btn.textContent = '🟢 VAD';
      }

      const buf = new Uint8Array(analyser.fftSize);
      state.vadTimer = window.setInterval(() => {
        if (!state.vadEnabled || sessionId !== state.vadSessionId) return;
        if (window.speechSynthesis && window.speechSynthesis.speaking) return;
        analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i += 1) {
          const v = (buf[i] - 128) / 128;
          sum += v * v;
        }
        const rms = Math.sqrt(sum / buf.length);
        if (rms > 0.045) {
          state.vadSilenceMs = 0;
          if (!state.vadSpeaking && typeof MediaRecorder !== 'undefined') {
            state.vadSpeaking = true;
            const chunks = [];
            const rec = new MediaRecorder(stream);
            state.vadRecorder = rec;
            rec.ondataavailable = (ev) => {
              if (sessionId === state.vadSessionId && state.vadEnabled && ev.data && ev.data.size > 0) chunks.push(ev.data);
            };
            rec.onstop = async () => {
              if (sessionId !== state.vadSessionId || !state.vadEnabled) return;
              if (state.vadRecorder === rec) state.vadRecorder = null;
              const blob = new Blob(chunks, { type: rec.mimeType || 'audio/webm' });
              if (blob.size < 800) return;
              const fd = new FormData();
              fd.append('file', blob, 'vad.webm');
              const controller = new AbortController();
              state.vadSttControllers.add(controller);
              try {
                const sttResp = await fetch('/api/stt', { method: 'POST', body: fd, signal: controller.signal });
                if (!sttResp.ok) throw new Error(`HTTP ${sttResp.status}`);
                const stt = await sttResp.json();
                if (sessionId !== state.vadSessionId || !state.vadEnabled) return;
                const text = (stt.text || '').trim();
                const input = el('chat-input');
                const form = el('chat-form');
                if (text && input && form) {
                  input.value = text;
                  form.dispatchEvent(new Event('submit', { cancelable: true }));
                }
              } catch (err) {
                if (sessionId === state.vadSessionId && state.vadEnabled && output) {
                  output.textContent = `Falha na transcrição VAD: ${err.message || err}. Verifique o STT e tente novamente.`;
                }
              } finally {
                state.vadSttControllers.delete(controller);
              }
            };
            rec.start();
          }
        } else if (state.vadSpeaking) {
          state.vadSilenceMs += 150;
          if (state.vadSilenceMs >= 900) {
            state.vadSpeaking = false;
            if (state.vadRecorder && state.vadRecorder.state === 'recording') state.vadRecorder.stop();
          }
        }
      }, 150);
    } catch (err) {
      if (stream) stream.getTracks().forEach((t) => t.stop());
      if (ctx) ctx.close().catch(() => {});
      if (sessionId === state.vadSessionId) {
        state.vadStarting = false;
        state.vadEnabled = false;
        if (btn) {
          btn.classList.remove('is-active');
          btn.setAttribute('aria-pressed', 'false');
          btn.textContent = '🎙️ VAD';
        }
        if (output) output.textContent = `Falha ao abrir o microfone: ${err.message || err}. Verifique a permissão e tente novamente.`;
      }
    }
  }

  function bindUiEvents() {
    const btnVad = el('btn-vad-toggle');
    if (btnVad) btnVad.addEventListener('click', toggleVad);
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (isMiniPet) {
      initMiniPetMode();
      return;
    }
    initElectronTabs();
    bindUiEvents();
    loadSync();
    loadToday();
    window.setInterval(loadSync, 30000);
  });
})();
