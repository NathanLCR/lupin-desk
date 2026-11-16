/* Módulo Cowork, Nathan-OS, Jarvis (First Wake, Visão/Clipboard, VAD) e ponte Electron. */
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
    pendingCaptureId: null,
    pendingActionId: null,
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
      window.EmoFace && typeof window.EmoFace.getHitboxRect === 'function'
        ? window.EmoFace.getHitboxRect()
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
        if (target === 'actions') loadActions();
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

  async function loadFirstWake() {
    if (isMiniPet) return;
    try {
      const resp = await fetch('/api/jarvis/first-wake');
      if (!resp.ok) return;
      const data = await resp.json();
      if (!data.should_brief || !data.today || !data.today.summary) return;

      const card = el('first-wake-card');
      const headline = el('first-wake-headline');
      const list = el('first-wake-list');
      if (!card || !headline || !list) return;

      headline.textContent = data.today.summary.headline || 'Bom dia! Resumo do Cowork pronto.';
      list.innerHTML = '';
      (data.today.summary.top || []).forEach((item) => {
        const li = document.createElement('li');
        li.textContent = `${item.id}: ${item.why}`;
        list.appendChild(li);
      });
      card.classList.remove('hidden');

      if (window.EmoAudio && typeof window.EmoAudio.chirp === 'function') {
        window.EmoAudio.chirp('curious');
      }
    } catch (_) {
      // Silencioso em caso de offline
    }
  }

  async function loadToday() {
    try {
      const resp = await fetch('/api/cowork/today');
      if (!resp.ok) return;
      const data = await resp.json();
      const summary = data.summary || {};
      const led = syncDotEmoji(data.sync_status);

      const displayHeadline = el('display-today-headline');
      const displayLed = el('display-sync-led');
      const displayTop = el('display-today-top');
      if (displayHeadline) displayHeadline.textContent = summary.headline || '—';
      if (displayLed) displayLed.textContent = `${led} ${data.sync_status || 'yellow'}`;
      if (displayTop) {
        displayTop.innerHTML = '';
        (summary.top || []).forEach((item) => {
          const li = document.createElement('li');
          li.textContent = `${item.id} — ${item.why}`;
          displayTop.appendChild(li);
        });
      }

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

  async function loadActions() {
    const container = el('nathan-actions-list');
    if (!container) return;
    try {
      const resp = await fetch('/api/cowork/actions');
      if (!resp.ok) return;
      const data = await resp.json();
      const actions = data.actions || [];
      container.innerHTML = '';
      if (!actions.length) {
        container.innerHTML = '<p class="muted-note">Nenhuma ação encontrada em Cowork/app/actions.yaml.</p>';
        return;
      }
      actions.forEach((act) => {
        const row = document.createElement('div');
        row.className = 'nathan-action-row';
        const info = document.createElement('div');
        info.innerHTML = `<strong>${escapeHtml(act.title)}</strong> <span class="panel-pill">${escapeHtml(act.risk)}</span>`;
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = act.risk === 'read' ? 'btn-secondary btn-sm' : 'btn-primary btn-sm';
        btn.textContent = act.risk === 'read' ? '▶ Executar' : '🛡️ Revisar & Executar';
        btn.addEventListener('click', () => runCoworkAction(act.id));
        row.appendChild(info);
        row.appendChild(btn);
        container.appendChild(row);
      });
    } catch (_) {
      // Ignora
    }
  }

  async function runCoworkAction(actionId) {
    const logEl = el('nathan-actions-log');
    try {
      const resp = await fetch('/api/cowork/actions/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action_id: actionId, params: {} }),
      });
      const data = await resp.json();
      if (data.requires_approval) {
        let confirmed = false;
        if (window.electronAPI && typeof window.electronAPI.confirmWrite === 'function') {
          confirmed = await window.electronAPI.confirmWrite({
            title: data.title,
            message: `Executar ação (${data.risk})?`,
            diff: data.diff || '',
          });
        } else {
          confirmed = window.confirm(`Executar ${data.title}?\n\n${data.diff || ''}`);
        }
        if (!confirmed) {
          if (logEl) logEl.textContent = 'Execução cancelada pelo usuário.';
          return;
        }
        const applyResp = await fetch('/api/cowork/actions/apply', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ approval_id: data.approval_id }),
        });
        const applied = await applyResp.json();
        if (logEl) {
          logEl.textContent = `[exit ${applied.exit_code}]\n${applied.stdout || ''}\n${applied.stderr || ''}`.trim();
        }
        return;
      }
      if (logEl) {
        logEl.textContent = `[exit ${data.exit_code}]\n${data.stdout || ''}\n${data.stderr || ''}`.trim();
      }
    } catch (err) {
      if (logEl) logEl.textContent = `Erro: ${err.message || err}`;
    }
  }

  async function previewAndApplyCapture(title, domain, due, previewTargetEl) {
    if (!title.trim()) return;
    const resp = await fetch('/api/cowork/capture/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        kind: 'add_task',
        payload: { title: title.trim(), domain: domain || 'personal', due: due || '' },
      }),
    });
    const preview = await resp.json();
    if (!resp.ok) {
      if (previewTargetEl) previewTargetEl.textContent = preview.detail || 'Erro no preview.';
      return;
    }
    state.pendingCaptureId = preview.approval_id;
    if (previewTargetEl) {
      previewTargetEl.textContent = preview.diff || preview.summary;
    }

    let approved = false;
    if (window.electronAPI && typeof window.electronAPI.confirmWrite === 'function') {
      approved = await window.electronAPI.confirmWrite({
        title: preview.summary,
        message: `Confirmar gravação em ${preview.target_file}?`,
        diff: preview.diff,
      });
    } else {
      const btnApply = el('btn-capture-apply');
      if (btnApply) {
        btnApply.classList.remove('hidden');
        return;
      }
      approved = window.confirm(`${preview.summary}\n\n${preview.diff}`);
    }
    if (approved) {
      await applyPendingCapture(previewTargetEl);
    }
  }

  async function applyPendingCapture(previewTargetEl) {
    if (!state.pendingCaptureId) return;
    const resp = await fetch('/api/cowork/capture/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approval_id: state.pendingCaptureId }),
    });
    const res = await resp.json();
    state.pendingCaptureId = null;
    const btnApply = el('btn-capture-apply');
    if (btnApply) btnApply.classList.add('hidden');
    if (previewTargetEl) {
      previewTargetEl.textContent = res.ok
        ? `✅ Salvo em ${res.target_file} (backup: ${res.backup_path || 'ok'})`
        : res.detail || 'Falha ao salvar.';
    }
    loadToday();
    loadSync();
  }

  function isLocalProviderUrl(rawUrl) {
    try {
      const url = new URL(rawUrl);
      if (!['http:', 'https:'].includes(url.protocol) || !url.hostname) return false;
      const host = url.hostname.toLowerCase();
      return host === '127.0.0.1' || host === 'localhost' || host === '::1' || host === '[::1]';
    } catch (_) {
      return false;
    }
  }

  async function confirmExternalJarvisIfNeeded(endpoint) {
    try {
      const resp = await fetch('/api/llm/providers');
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      const active = data && data.active;
      const knownProviders = Array.isArray(data && data.presets)
        ? data.presets.map((preset) => preset && preset.id)
        : [];
      if (
        !active ||
        typeof active.provider_id !== 'string' ||
        !knownProviders.includes(active.provider_id) ||
        typeof active.base_url !== 'string' ||
        !active.base_url.trim()
      ) {
        throw new Error('Dados do provedor ausentes ou desconhecidos.');
      }
      const providerUrl = new URL(active.base_url);
      if (!['http:', 'https:'].includes(providerUrl.protocol) || !providerUrl.hostname) {
        throw new Error('URL do provedor inválida.');
      }
      if (isLocalProviderUrl(active.base_url)) return true;

      const targetLabel = endpoint.includes('clipboard') ? 'conteúdo do seu clipboard' : 'captura da sua tela';
      const msg = `O provedor ativo (${active.provider_id} — ${providerUrl.host}) é externo.`;
      const detail = `Deseja enviar ${targetLabel} para este provedor remoto?`;
      if (window.electronAPI && typeof window.electronAPI.confirmWrite === 'function') {
        return await window.electronAPI.confirmWrite({
          title: 'Aviso de Privacidade — Jarvis',
          message: msg,
          diff: detail,
        });
      }
      return window.confirm(`${msg}\n\n${detail}`);
    } catch (err) {
      return { blocked: true, reason: err.message || 'resposta inválida' };
    }
  }

  async function triggerJarvisEndpoint(endpoint, promptText) {
    const out = el('nathan-jarvis-output');
    const allowed = await confirmExternalJarvisIfNeeded(endpoint);
    if (allowed && allowed.blocked) {
      if (out) {
        out.textContent = `Não foi possível confirmar o provedor ativo (${allowed.reason}). Nenhuma captura foi enviada. Atualize os provedores em Diagnóstico e tente novamente.`;
      }
      return;
    }
    if (!allowed) {
      if (out) out.textContent = 'Envio cancelado pelo usuário.';
      return;
    }
    if (out) out.textContent = 'Processando...';
    try {
      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: promptText || '' }),
      });
      const data = await resp.json();
      if (out) out.textContent = data.text || data.detail || 'Concluído.';
      if (window.EmoFace && data.emotion) {
        window.EmoFace.setEmotion(data.emotion);
      }
    } catch (err) {
      if (out) out.textContent = `Erro: ${err.message || err}`;
    }
  }

  async function toggleVad() {
    const btn = el('btn-vad-toggle');
    const output = el('nathan-jarvis-output');
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
    const btnDismissWake = el('btn-first-wake-close');
    if (btnDismissWake) {
      btnDismissWake.addEventListener('click', () => {
        const card = el('first-wake-card');
        if (card) card.classList.add('hidden');
      });
    }

    const btnSpeakWake = el('btn-first-wake-speak');
    if (btnSpeakWake) {
      btnSpeakWake.addEventListener('click', () => {
        const headline = el('first-wake-headline')?.textContent || '';
        if (headline && window.speechSynthesis) {
          const u = new SpeechSynthesisUtterance(headline);
          u.lang = 'pt-BR';
          window.speechSynthesis.speak(u);
        }
      });
    }

    const btnVad = el('btn-vad-toggle');
    if (btnVad) btnVad.addEventListener('click', toggleVad);

    const btnCapturePreview = el('btn-capture-preview');
    if (btnCapturePreview) {
      btnCapturePreview.addEventListener('click', () => {
        const title = el('capture-task-title')?.value || '';
        const domain = el('capture-task-domain')?.value || 'personal';
        const due = el('capture-task-due')?.value || '';
        previewAndApplyCapture(title, domain, due, el('capture-diff-preview'));
      });
    }

    const btnCaptureApply = el('btn-capture-apply');
    if (btnCaptureApply) {
      btnCaptureApply.addEventListener('click', () => applyPendingCapture(el('capture-diff-preview')));
    }

    const btnDockQuick = el('btn-dock-cowork-add');
    if (btnDockQuick) {
      btnDockQuick.addEventListener('click', () => {
        const title = el('dock-cowork-input')?.value || '';
        previewAndApplyCapture(title, 'personal', '', el('dock-cowork-status'));
      });
    }

    const btnVision = el('btn-jarvis-vision');
    if (btnVision) {
      btnVision.addEventListener('click', () => triggerJarvisEndpoint('/api/jarvis/vision', ''));
    }

    const btnClip = el('btn-jarvis-clipboard');
    if (btnClip) {
      btnClip.addEventListener('click', () => triggerJarvisEndpoint('/api/jarvis/clipboard', ''));
    }

    if (window.electronAPI && typeof window.electronAPI.onShortcutTrigger === 'function') {
      window.electronAPI.onShortcutTrigger((kind) => {
        if (kind === 'vision') triggerJarvisEndpoint('/api/jarvis/vision', '');
      });
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (isMiniPet) {
      initMiniPetMode();
      return;
    }
    initElectronTabs();
    bindUiEvents();
    loadFirstWake();
    loadSync();
    loadToday();
    window.setInterval(loadSync, 30000);
  });
})();
