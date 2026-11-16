/**
 * Estúdio de Diagnóstico (/static/diagnostics.js -> window.DeskDiagnostics)
 * Verifica contexto seguro, lista microfones, mede nível em tempo real,
 * executa loopback de 3s, inspeciona vozes TTS (Browser vs Servidor Mac),
 * exibe Gamepad RG406H ao vivo e sensores de movimento (com iOS permission).
 */
(function (global) {
  'use strict';

  const LOOPBACK_DURATION_MS = 3000;

  let containerEl = null;
  let options = {};
  let active = false;

  // Estado de microfone / WebAudio
  let micStream = null;
  let audioCtx = null;
  let analyserNode = null;
  let levelRafId = null;
  let loopbackRecording = false;
  let loopbackTimer = null;
  let loopbackUrl = null;
  let loopbackRecorder = null;
  let micRequestId = 0;
  let micStarting = false;

  // Estado de inspetor de Gamepad e sensores
  let gamepadIntervalId = null;
  let motionBound = false;
  let lastMotion = { ax: 0, ay: 0, az: 0, alpha: 0, beta: 0, gamma: 0, supported: false };

  // Estado do seletor de provedor e modelo LLM
  let llmPresets = [];
  let llmActive = null;

  function qs(id) {
    return containerEl ? containerEl.querySelector(`#${id}`) : document.getElementById(id);
  }

  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function renderScaffold() {
    if (!containerEl) return;
    const isSecure = Boolean(global.isSecureContext);
    const originText = global.location ? global.location.origin : '';

    containerEl.innerHTML = `
      <div class="diag-grid">
        <!-- Card 1: Ambiente Seguro & Backend -->
        <section class="diag-card">
          <div class="diag-card-head">
            <h3>🔒 Contexto Seguro & Servidor</h3>
            <span class="diag-pill ${isSecure ? 'is-ok' : 'is-err'}">
              ${isSecure ? 'isSecureContext: OK' : 'Sem HTTPS/Localhost'}
            </span>
          </div>
          <p class="diag-hint">
            Origem atual: <code>${escapeHtml(originText)}</code>.
            ${
              isSecure
                ? 'Microfone, WakeLock e Gamepad liberados.'
                : 'Microfone exige HTTPS (porta 8443) ou túnel ADB (http://localhost:8000).'
            }
          </p>
          <div id="diag-server-info" class="diag-kv-list">
            <div class="diag-kv"><span>Status API:</span><strong>Carregando...</strong></div>
          </div>
          <button id="diag-btn-refresh-server" type="button" class="btn-secondary diag-btn-sm">
            ↻ Atualizar Diagnóstico do Servidor
          </button>
        </section>

        <!-- Card 1b: Provedor & Modelo LLM -->
        <section class="diag-card">
          <div class="diag-card-head">
            <h3>🧠 Provedor & Modelo LLM</h3>
            <span id="diag-llm-key-badge" class="diag-pill">Carregando...</span>
          </div>
          <label class="diag-field-label" for="diag-llm-provider">Provedor (OpenAI-compat)</label>
          <select id="diag-llm-provider" class="diag-select" aria-label="Selecionar provedor LLM">
            <option value="local_proxy">Proxy Local</option>
          </select>
          <label class="diag-field-label" for="diag-llm-base-url">URL Base</label>
          <input
            id="diag-llm-base-url"
            type="url"
            class="diag-input"
            placeholder="http://127.0.0.1:31415/v1"
            aria-label="URL base do provedor LLM"
          />
          <label class="diag-field-label" for="diag-llm-model-select">Modelo</label>
          <div class="diag-row">
            <select id="diag-llm-model-select" class="diag-select" aria-label="Selecionar modelo LLM">
              <option value="">Carregando modelos...</option>
            </select>
            <button id="diag-btn-fetch-models" type="button" class="btn-secondary diag-btn-sm" aria-label="Atualizar lista de modelos LLM">
              ↻ Listar
            </button>
          </div>
          <input
            id="diag-llm-model-custom"
            type="text"
            class="diag-input"
            placeholder="Ou digite um ID de modelo manualmente"
            aria-label="ID do modelo LLM"
          />
          <div class="diag-btn-group">
            <button id="diag-btn-save-llm" type="button" class="btn-primary">
              💾 Salvar & Aplicar
            </button>
          </div>
          <p id="diag-llm-status" class="diag-hint">
            Chaves de API são lidas apenas do <code>.env</code> do servidor.
          </p>
        </section>

        <!-- Card 2: Microfone & Loopback 3s -->
        <section class="diag-card">
          <div class="diag-card-head">
            <h3>🎙️ Microfone & Loopback</h3>
            <span id="diag-mic-badge" class="diag-pill">Parado</span>
          </div>
          <div class="diag-row">
            <select id="diag-mic-select" class="diag-select" aria-label="Selecionar microfone">
              <option value="">Microfone padrão do sistema</option>
            </select>
            <button id="diag-btn-list-mics" type="button" class="btn-secondary diag-btn-sm" aria-label="Atualizar lista de microfones">
              ↻ Listar
            </button>
          </div>
          <div class="diag-meter-wrap" aria-label="Nível de entrada do microfone">
            <div id="diag-mic-meter-fill" class="diag-meter-fill"></div>
          </div>
          <div class="diag-btn-group">
            <button id="diag-btn-mic-toggle" type="button" class="btn-secondary">
              🎧 Monitorar Nível
            </button>
            <button id="diag-btn-loopback" type="button" class="btn-primary">
              ⏺️ Gravar 3s e reproduzir
            </button>
          </div>
          <p id="diag-loopback-status" class="diag-hint">
            Use o loopback para confirmar microfone interno, USB-C ou Bluetooth no RG406H/Mac/iPhone.
          </p>
          <audio id="diag-loopback-audio" class="diag-audio-player hidden" controls playsinline></audio>
        </section>

        <!-- Card 3: Inspetor de Vozes TTS -->
        <section class="diag-card">
          <div class="diag-card-head">
            <h3>🗣️ Vozes TTS (Híbrido)</h3>
            <span id="diag-tts-mode-badge" class="diag-pill is-ok">Browser</span>
          </div>
          <div class="diag-btn-group">
            <button id="diag-btn-test-browser-tts" type="button" class="btn-secondary">
              🔊 Testar Browser
            </button>
            <button id="diag-btn-test-server-tts" type="button" class="btn-primary">
              🖥️ Testar Servidor Mac
            </button>
          </div>
          <div class="diag-voices-columns">
            <div>
              <div class="diag-sublabel">Navegador (speechSynthesis)</div>
              <ul id="diag-browser-voices" class="diag-mini-list"></ul>
            </div>
            <div>
              <div class="diag-sublabel">Servidor Mac (/api/tts/voices)</div>
              <ul id="diag-server-voices" class="diag-mini-list"></ul>
            </div>
          </div>
        </section>

        <!-- Card 4: Inspetor ao Vivo Gamepad RG406H -->
        <section class="diag-card">
          <div class="diag-card-head">
            <h3>🎮 Gamepad RG406H ao Vivo</h3>
            <span id="diag-pad-status" class="diag-pill">Aguardando</span>
          </div>
          <p id="diag-pad-id" class="diag-hint">Pressione qualquer botão ou mova o analógico no controle.</p>
          <div id="diag-pad-axes" class="diag-axes-grid"></div>
          <div id="diag-pad-buttons" class="diag-pad-buttons"></div>
          <div id="diag-pad-last" class="diag-hint">Última ação: —</div>
        </section>

        <!-- Card 5: Giroscópio & Acelerômetro -->
        <section class="diag-card diag-card-wide">
          <div class="diag-card-head">
            <h3>🧭 Giroscópio & Acelerômetro</h3>
            <button id="diag-btn-motion-perm" type="button" class="btn-secondary diag-btn-sm">
              📱 Ativar Sensores (iOS / Movimento)
            </button>
          </div>
          <div id="diag-motion-readout" class="diag-motion-grid">
            <div class="diag-kv"><span>Orientação (α / β / γ):</span><strong id="diag-orient-val">0° / 0° / 0°</strong></div>
            <div class="diag-kv"><span>Aceleração (X / Y / Z):</span><strong id="diag-accel-val">0.0 / 0.0 / 0.0</strong></div>
          </div>
        </section>
      </div>
    `;

    bindInternalEvents();
  }

  function bindInternalEvents() {
    const btnRefresh = qs('diag-btn-refresh-server');
    const btnListMics = qs('diag-btn-list-mics');
    const btnMicToggle = qs('diag-btn-mic-toggle');
    const btnLoopback = qs('diag-btn-loopback');
    const btnTestBrowser = qs('diag-btn-test-browser-tts');
    const btnTestServer = qs('diag-btn-test-server-tts');
    const btnMotion = qs('diag-btn-motion-perm');

    if (btnRefresh) btnRefresh.addEventListener('click', fetchServerDiagnostics);
    if (btnListMics) btnListMics.addEventListener('click', () => listMicrophones(true));
    if (btnMicToggle) btnMicToggle.addEventListener('click', toggleMicMonitor);
    if (btnLoopback) btnLoopback.addEventListener('click', runLoopbackTest);

    const micSelect = qs('diag-mic-select');
    if (micSelect) {
      micSelect.addEventListener('change', () => {
        if (!micStream && !micStarting) return;
        stopMicMonitor();
        if (active) startMicMonitor();
      });
    }

    if (btnTestBrowser) {
      btnTestBrowser.addEventListener('click', () => {
        if (typeof options.onTestBrowserTts === 'function') {
          options.onTestBrowserTts('Olá! Teste de voz do navegador funcionando.');
        }
      });
    }

    if (btnTestServer) {
      btnTestServer.addEventListener('click', () => {
        if (typeof options.onTestServerTts === 'function') {
          options.onTestServerTts('Olá! Teste de voz offline do servidor Mac.');
        }
      });
    }

    if (btnMotion) {
      btnMotion.addEventListener('click', requestMotionAccess);
    }

    const providerSelect = qs('diag-llm-provider');
    const modelSelect = qs('diag-llm-model-select');
    const modelCustom = qs('diag-llm-model-custom');
    const btnFetchModels = qs('diag-btn-fetch-models');
    const btnSaveLlm = qs('diag-btn-save-llm');

    if (providerSelect) {
      providerSelect.addEventListener('change', onProviderChange);
    }
    if (modelSelect) {
      modelSelect.addEventListener('change', () => {
        if (modelCustom && modelSelect.value) {
          modelCustom.value = modelSelect.value;
        }
      });
    }
    if (btnFetchModels) {
      btnFetchModels.addEventListener('click', () => fetchLlmModels(true));
    }
    if (btnSaveLlm) {
      btnSaveLlm.addEventListener('click', saveLlmProvider);
    }
  }

  async function fetchServerDiagnostics() {
    const target = qs('diag-server-info');
    if (!target) return;
    try {
      const res = await fetch('/api/diagnostics');
      if (!res.ok) {
        target.innerHTML = `<div class="diag-kv"><span>Erro HTTP:</span><strong>${res.status}</strong></div>`;
        return;
      }
      const data = await res.json();
      const sttInfo = data.stt || {};
      const ttsInfo = data.tts || {};
      const sttOk = Boolean(sttInfo.available ?? data.stt_available);
      const ttsOk = Boolean(ttsInfo.available ?? data.tts_available);
      const engineName = sttInfo.engine || data.stt_engine || (sttOk ? 'ativo' : 'indisponível');

      target.innerHTML = `
        <div class="diag-kv"><span>STT Local:</span><strong>${sttOk ? `Disponível (${escapeHtml(engineName)})` : 'Indisponível'}</strong></div>
        <div class="diag-kv"><span>TTS Servidor Mac:</span><strong>${ttsOk ? 'Disponível (say + afconvert)' : 'Indisponível'}</strong></div>
        <div class="diag-kv"><span>Modelo LLM:</span><strong>${escapeHtml(data.llm_model || data.model || '—')}</strong></div>
        <div class="diag-kv"><span>Porta HTTPS:</span><strong>${escapeHtml(data.https_port || 8443)}</strong></div>
      `;
    } catch {
      target.innerHTML = '<div class="diag-kv"><span>Servidor:</span><strong>Offline / Reconectando</strong></div>';
    }
  }

  function findPresetById(providerId) {
    return llmPresets.find((item) => item.id === providerId) || null;
  }

  function updateLlmKeyBadge(preset, activeInfo) {
    const badge = qs('diag-llm-key-badge');
    if (!badge) return;
    const hasKey = Boolean((preset && preset.has_api_key) || (activeInfo && activeInfo.has_api_key));
    const envName = (preset && preset.api_key_env) || (activeInfo && activeInfo.api_key_env) || 'LLM_API_KEY';
    const requiresKey = Boolean(preset && preset.requires_api_key);

    badge.classList.remove('is-ok', 'is-err', 'is-warn');
    if (hasKey) {
      badge.classList.add('is-ok');
      badge.textContent = `🔑 ${envName} OK`;
    } else if (requiresKey) {
      badge.classList.add('is-err');
      badge.textContent = `⚠️ Falta ${envName}`;
    } else {
      badge.classList.add('is-warn');
      badge.textContent = `Sem chave (${envName})`;
    }
  }

  function populateModelOptions(models, selectedModel) {
    const select = qs('diag-llm-model-select');
    const customInput = qs('diag-llm-model-custom');
    if (!select) return;

    const list = Array.isArray(models) ? [...models] : [];
    if (selectedModel && !list.includes(selectedModel)) {
      list.unshift(selectedModel);
    }

    select.innerHTML = '';
    if (list.length === 0) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = 'Nenhum modelo listado — digite abaixo';
      select.appendChild(opt);
    } else {
      list.forEach((modelId) => {
        const opt = document.createElement('option');
        opt.value = modelId;
        opt.textContent = modelId;
        select.appendChild(opt);
      });
    }

    if (selectedModel) {
      select.value = selectedModel;
      if (customInput) customInput.value = selectedModel;
    } else if (list.length > 0 && customInput) {
      customInput.value = list[0];
    }
  }

  async function loadLlmProviders() {
    const providerSelect = qs('diag-llm-provider');
    const baseUrlInput = qs('diag-llm-base-url');
    const statusEl = qs('diag-llm-status');
    if (!providerSelect) return;

    try {
      const res = await fetch('/api/llm/providers');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      llmPresets = Array.isArray(data.presets) ? data.presets : [];
      llmActive = data.active || null;

      providerSelect.innerHTML = '';
      llmPresets.forEach((preset) => {
        const opt = document.createElement('option');
        opt.value = preset.id;
        opt.textContent = preset.name;
        providerSelect.appendChild(opt);
      });

      const activeId = (llmActive && llmActive.provider_id) || 'local_proxy';
      providerSelect.value = activeId;
      const preset = findPresetById(activeId);
      if (baseUrlInput) {
        baseUrlInput.value = (llmActive && llmActive.base_url) || (preset ? preset.default_base_url : '');
      }
      updateLlmKeyBadge(preset, llmActive);
      populateModelOptions(preset ? preset.suggested_models : [], llmActive ? llmActive.model : '');
      await fetchLlmModels(false);
    } catch {
      if (statusEl) {
        statusEl.textContent = 'Não foi possível carregar os provedores LLM do servidor.';
      }
    }
  }

  async function onProviderChange() {
    const providerSelect = qs('diag-llm-provider');
    const baseUrlInput = qs('diag-llm-base-url');
    const customInput = qs('diag-llm-model-custom');
    if (!providerSelect) return;

    const preset = findPresetById(providerSelect.value);
    if (baseUrlInput && preset) {
      baseUrlInput.value = preset.default_base_url || '';
    }
    updateLlmKeyBadge(preset, null);
    const defaultModel = preset ? preset.default_model : '';
    if (customInput) customInput.value = defaultModel;
    populateModelOptions(preset ? preset.suggested_models : [], defaultModel);
    await fetchLlmModels(false);
  }

  async function fetchLlmModels(showFeedback) {
    const providerSelect = qs('diag-llm-provider');
    const baseUrlInput = qs('diag-llm-base-url');
    const customInput = qs('diag-llm-model-custom');
    const statusEl = qs('diag-llm-status');
    const btn = qs('diag-btn-fetch-models');
    if (!providerSelect) return;

    const providerId = providerSelect.value;
    const baseUrl = baseUrlInput ? baseUrlInput.value.trim() : '';
    const currentModel = customInput ? customInput.value.trim() : '';
    if (btn) btn.disabled = true;

    try {
      const params = new URLSearchParams();
      if (providerId) params.set('provider_id', providerId);
      if (baseUrl) params.set('base_url', baseUrl);
      const res = await fetch(`/api/llm/models?${params.toString()}`);
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || `HTTP ${res.status}`);
      }
      populateModelOptions(data.models || [], currentModel);
      if (showFeedback && statusEl) {
        statusEl.textContent =
          data.source === 'remote'
            ? `✓ ${data.models.length} modelos carregados de /models.`
            : `Usando lista sugerida (${data.error || 'endpoint /models indisponível'}).`;
      }
    } catch (err) {
      if (showFeedback && statusEl) {
        statusEl.textContent = `Erro ao listar modelos: ${err.message || err}`;
      }
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function saveLlmProvider() {
    const providerSelect = qs('diag-llm-provider');
    const baseUrlInput = qs('diag-llm-base-url');
    const modelSelect = qs('diag-llm-model-select');
    const customInput = qs('diag-llm-model-custom');
    const statusEl = qs('diag-llm-status');
    const btn = qs('diag-btn-save-llm');
    if (!providerSelect) return;

    const modelId =
      (customInput && customInput.value.trim()) ||
      (modelSelect && modelSelect.value.trim()) ||
      '';
    const baseUrl = baseUrlInput ? baseUrlInput.value.trim() : '';

    if (btn) btn.disabled = true;
    try {
      const res = await fetch('/api/llm/provider', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider_id: providerSelect.value,
          base_url: baseUrl || null,
          model: modelId,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || `HTTP ${res.status}`);
      }
      llmActive = data.active || null;
      updateLlmKeyBadge(findPresetById(providerSelect.value), llmActive);
      if (statusEl && llmActive) {
        statusEl.textContent = `✓ Aplicado e salvo: ${llmActive.model} (${llmActive.base_url}).`;
      }
      await fetchServerDiagnostics();
    } catch (err) {
      if (statusEl) {
        statusEl.textContent = `Erro ao salvar provedor: ${err.message || err}`;
      }
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function listMicrophones(requestPermIfNeeded) {
    const select = qs('diag-mic-select');
    if (!select || !navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
      return;
    }

    const requestId = micRequestId;
    try {
      if (requestPermIfNeeded && navigator.mediaDevices.getUserMedia) {
        const tempStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (!active || requestId !== micRequestId) {
          tempStream.getTracks().forEach((t) => t.stop());
          return;
        }
        tempStream.getTracks().forEach((t) => t.stop());
      }
      const devices = await navigator.mediaDevices.enumerateDevices();
      if (!active || requestId !== micRequestId) return;
      const inputs = devices.filter((d) => d.kind === 'audioinput');
      const currentVal = select.value;

      select.innerHTML = '';
      if (inputs.length === 0) {
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = 'Nenhum microfone detectado';
        select.appendChild(opt);
        return;
      }

      inputs.forEach((dev, idx) => {
        const opt = document.createElement('option');
        opt.value = dev.deviceId || '';
        opt.textContent = dev.label || `Microfone ${idx + 1}`;
        select.appendChild(opt);
      });

      if (currentVal && inputs.some((d) => d.deviceId === currentVal)) {
        select.value = currentVal;
      }
    } catch (err) {
      const status = qs('diag-loopback-status');
      if (active && requestId === micRequestId && status) {
        status.textContent = `Permissão de microfone recusada ou bloqueada: ${err.message || err}. Verifique a permissão e tente novamente.`;
      }
    }
  }

  async function startMicMonitor() {
    if (micStream) return true;
    if (micStarting) return false;
    const requestId = ++micRequestId;
    micStarting = true;
    const badge = qs('diag-mic-badge');
    const toggleBtn = qs('diag-btn-mic-toggle');
    const select = qs('diag-mic-select');
    const status = qs('diag-loopback-status');

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      if (status) status.textContent = 'API de microfone indisponível neste navegador/origem.';
      micStarting = false;
      return false;
    }
    if (toggleBtn) toggleBtn.disabled = true;

    try {
      const deviceId = select ? select.value : '';
      const constraints = {
        audio: deviceId
          ? { deviceId: { exact: deviceId }, echoCancellation: true, noiseSuppression: true }
          : { echoCancellation: true, noiseSuppression: true },
      };
      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      if (!active || requestId !== micRequestId) {
        stream.getTracks().forEach((t) => t.stop());
        return false;
      }
      micStream = stream;
      await listMicrophones(false);
      if (!active || requestId !== micRequestId || micStream !== stream) return false;

      const AudioCtx = global.AudioContext || global.webkitAudioContext;
      if (AudioCtx) {
        audioCtx = new AudioCtx();
        if (audioCtx.state === 'suspended') {
          await audioCtx.resume();
        }
        if (!active || requestId !== micRequestId || micStream !== stream) return false;
        const source = audioCtx.createMediaStreamSource(stream);
        analyserNode = audioCtx.createAnalyser();
        analyserNode.fftSize = 256;
        source.connect(analyserNode);
        pumpMicLevel();
      }

      if (badge) {
        badge.textContent = 'Ouvindo';
        badge.classList.add('is-ok');
      }
      if (toggleBtn) toggleBtn.textContent = '⏹️ Parar Monitor';
      return true;
    } catch (err) {
      if (requestId === micRequestId && status) {
        status.textContent = `Falha ao abrir microfone: ${err.message || err}. Verifique a permissão e tente novamente.`;
      }
      if (requestId === micRequestId) stopMicMonitor();
      return false;
    } finally {
      if (requestId === micRequestId) {
        micStarting = false;
        if (toggleBtn) toggleBtn.disabled = false;
      }
    }
  }

  function pumpMicLevel() {
    if (!analyserNode || !micStream) return;
    const data = new Uint8Array(analyserNode.frequencyBinCount);
    analyserNode.getByteTimeDomainData(data);
    let peak = 0;
    for (let i = 0; i < data.length; i += 1) {
      const v = Math.abs(data[i] - 128) / 128;
      if (v > peak) peak = v;
    }
    const pct = Math.min(100, Math.round(peak * 180));
    const fill = qs('diag-mic-meter-fill');
    if (fill) {
      fill.style.width = `${pct}%`;
    }
    levelRafId = global.requestAnimationFrame(pumpMicLevel);
  }

  function stopMicMonitor() {
    micRequestId += 1;
    micStarting = false;
    if (levelRafId !== null) {
      global.cancelAnimationFrame(levelRafId);
      levelRafId = null;
    }
    if (micStream) {
      micStream.getTracks().forEach((t) => t.stop());
      micStream = null;
    }
    if (audioCtx) {
      audioCtx.close().catch(() => {});
      audioCtx = null;
      analyserNode = null;
    }
    if (loopbackTimer) {
      global.clearTimeout(loopbackTimer);
      loopbackTimer = null;
    }
    if (loopbackRecorder && loopbackRecorder.state === 'recording') {
      loopbackRecorder.stop();
    }
    const fill = qs('diag-mic-meter-fill');
    if (fill) fill.style.width = '0%';
    const badge = qs('diag-mic-badge');
    if (badge) {
      badge.textContent = 'Parado';
      badge.classList.remove('is-ok');
    }
    const toggleBtn = qs('diag-btn-mic-toggle');
    if (toggleBtn) {
      toggleBtn.disabled = false;
      toggleBtn.textContent = '🎧 Monitorar Nível';
    }
    const loopbackBtn = qs('diag-btn-loopback');
    if (loopbackBtn) loopbackBtn.disabled = false;
  }

  async function toggleMicMonitor() {
    if (micStream) {
      stopMicMonitor();
    } else {
      await startMicMonitor();
    }
  }

  async function runLoopbackTest() {
    if (loopbackRecording) return;
    const status = qs('diag-loopback-status');
    const audioEl = qs('diag-loopback-audio');
    const btn = qs('diag-btn-loopback');

    const ok = await startMicMonitor();
    if (!ok || !micStream) return;
    if (typeof global.MediaRecorder === 'undefined') {
      if (status) status.textContent = 'MediaRecorder não suportado neste navegador.';
      return;
    }

    loopbackRecording = true;
    if (btn) btn.disabled = true;
    if (status) status.textContent = 'Gravando 3 segundos... fale próximo ao microfone!';

    const chunks = [];
    const preferredTypes = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];
    const mimeType = preferredTypes.find((t) => global.MediaRecorder.isTypeSupported(t)) || '';
    const recorder = mimeType ? new global.MediaRecorder(micStream, { mimeType }) : new global.MediaRecorder(micStream);
    loopbackRecorder = recorder;

    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunks.push(e.data);
    };

    recorder.onstop = () => {
      loopbackRecording = false;
      loopbackRecorder = null;
      if (btn) btn.disabled = false;
      if (!active) return;
      if (loopbackUrl) {
        URL.revokeObjectURL(loopbackUrl);
        loopbackUrl = null;
      }
      const blob = new Blob(chunks, { type: mimeType || 'audio/webm' });
      loopbackUrl = URL.createObjectURL(blob);
      if (audioEl) {
        audioEl.src = loopbackUrl;
        audioEl.classList.remove('hidden');
        audioEl.play().catch(() => {});
      }
      if (status) status.textContent = `Loopback pronto (${Math.round(blob.size / 1024)} KB). Reproduzindo...`;
    };

    recorder.start();
    loopbackTimer = global.setTimeout(() => {
      if (recorder.state === 'recording') {
        recorder.stop();
      }
    }, LOOPBACK_DURATION_MS);
  }

  async function refreshTtsVoices() {
    const browserList = qs('diag-browser-voices');
    const serverList = qs('diag-server-voices');
    const modeBadge = qs('diag-tts-mode-badge');

    if (modeBadge && typeof options.getTtsMode === 'function') {
      const m = options.getTtsMode();
      modeBadge.textContent = m === 'server' ? 'Servidor Mac' : 'Browser';
    }

    if (browserList) {
      browserList.innerHTML = '';
      if ('speechSynthesis' in global) {
        const voices = global.speechSynthesis.getVoices() || [];
        const ptVoices = voices.filter((v) => /^pt/i.test(v.lang));
        const shown = (ptVoices.length > 0 ? ptVoices : voices).slice(0, 8);
        if (shown.length === 0) {
          browserList.innerHTML = '<li>Nenhuma voz listada ainda</li>';
        } else {
          shown.forEach((v) => {
            const li = document.createElement('li');
            li.textContent = `${v.name} (${v.lang})`;
            browserList.appendChild(li);
          });
        }
      } else {
        browserList.innerHTML = '<li>speechSynthesis indisponível</li>';
      }
    }

    if (serverList) {
      try {
        const res = await fetch('/api/tts/voices');
        if (!res.ok) {
          serverList.innerHTML = '<li>Erro ao consultar /api/tts/voices</li>';
          return;
        }
        const data = await res.json();
        const voices = Array.isArray(data) ? data : data.voices || [];
        serverList.innerHTML = '';
        if (voices.length === 0) {
          serverList.innerHTML = '<li>Nenhuma voz do Mac encontrada</li>';
          return;
        }
        voices.slice(0, 8).forEach((v) => {
          const li = document.createElement('li');
          const name = typeof v === 'string' ? v : v.name || v.voice || 'Voz';
          const lang = typeof v === 'object' && v.lang ? ` (${v.lang})` : '';
          li.textContent = `${name}${lang}`;
          serverList.appendChild(li);
        });
      } catch {
        serverList.innerHTML = '<li>Servidor indisponível</li>';
      }
    }
  }

  function updateGamepadInspector() {
    if (!active || !global.DeskGamepad) return;
    const snap = global.DeskGamepad.getSnapshot();
    const statusEl = qs('diag-pad-status');
    const idEl = qs('diag-pad-id');
    const axesEl = qs('diag-pad-axes');
    const btnsEl = qs('diag-pad-buttons');
    const lastEl = qs('diag-pad-last');

    if (statusEl) {
      statusEl.textContent = snap.connected ? 'Conectado' : 'Desconectado';
      statusEl.classList.toggle('is-ok', snap.connected);
    }
    if (idEl) {
      idEl.textContent = snap.connected
        ? `${snap.id} (mapping: ${snap.mapping})`
        : 'Pressione qualquer botão no controle RG406H para acordar a Gamepad API.';
    }
    if (lastEl) {
      lastEl.textContent = `Última ação: ${snap.lastAction || '—'}`;
    }

    if (axesEl) {
      const axisLabels = ['LX', 'LY', 'RX', 'RY'];
      axesEl.innerHTML = (snap.axes || []).slice(0, 4).map((val, idx) => {
        const pct = Math.round(((val + 1) / 2) * 100);
        return `
          <div class="diag-axis-item">
            <span>${axisLabels[idx] || `E${idx}`}: ${val.toFixed(2)}</span>
            <div class="diag-axis-bar"><div class="diag-axis-dot" style="left:${pct}%"></div></div>
          </div>
        `;
      }).join('');
    }

    if (btnsEl) {
      btnsEl.innerHTML = (snap.buttons || []).map((b) => {
        const activeCls = b.pressed || b.value > 0.25 ? 'is-pressed' : '';
        return `<span class="diag-pad-btn ${activeCls}">${escapeHtml(b.name)}</span>`;
      }).join('');
    }
  }

  function handleDeviceOrientation(event) {
    lastMotion.alpha = Number((event.alpha || 0).toFixed(1));
    lastMotion.beta = Number((event.beta || 0).toFixed(1));
    lastMotion.gamma = Number((event.gamma || 0).toFixed(1));
    lastMotion.supported = true;
    renderMotionValues();
  }

  function handleDeviceMotion(event) {
    const acc = event.accelerationIncludingGravity || event.acceleration || {};
    lastMotion.ax = Number((acc.x || 0).toFixed(2));
    lastMotion.ay = Number((acc.y || 0).toFixed(2));
    lastMotion.az = Number((acc.z || 0).toFixed(2));
    lastMotion.supported = true;
    renderMotionValues();
  }

  function renderMotionValues() {
    const orientEl = qs('diag-orient-val');
    const accelEl = qs('diag-accel-val');
    if (orientEl) {
      orientEl.textContent = `${lastMotion.alpha}° / ${lastMotion.beta}° / ${lastMotion.gamma}°`;
    }
    if (accelEl) {
      accelEl.textContent = `${lastMotion.ax} / ${lastMotion.ay} / ${lastMotion.az}`;
    }
  }

  async function requestMotionAccess() {
    const btn = qs('diag-btn-motion-perm');
    try {
      if (
        typeof global.DeviceMotionEvent !== 'undefined' &&
        typeof global.DeviceMotionEvent.requestPermission === 'function'
      ) {
        await global.DeviceMotionEvent.requestPermission();
      }
      if (
        typeof global.DeviceOrientationEvent !== 'undefined' &&
        typeof global.DeviceOrientationEvent.requestPermission === 'function'
      ) {
        await global.DeviceOrientationEvent.requestPermission();
      }
      bindMotionListeners();
      if (btn) btn.textContent = '✓ Sensores Ativos';
    } catch {
      if (btn) btn.textContent = '⚠️ Permissão Negada';
    }
  }

  function bindMotionListeners() {
    if (motionBound) return;
    motionBound = true;
    global.addEventListener('deviceorientation', handleDeviceOrientation);
    global.addEventListener('devicemotion', handleDeviceMotion);
  }

  const DeskDiagnostics = {
    init(rootEl, opts = {}) {
      containerEl = rootEl;
      options = opts || {};
      renderScaffold();
      bindMotionListeners();
    },

    activate() {
      active = true;
      fetchServerDiagnostics();
      loadLlmProviders();
      listMicrophones(false);
      refreshTtsVoices();
      updateGamepadInspector();
      if (!gamepadIntervalId) {
        gamepadIntervalId = global.setInterval(updateGamepadInspector, 60);
      }
    },

    deactivate() {
      active = false;
      if (gamepadIntervalId) {
        global.clearInterval(gamepadIntervalId);
        gamepadIntervalId = null;
      }
      if (loopbackTimer) {
        global.clearTimeout(loopbackTimer);
        loopbackTimer = null;
      }
      stopMicMonitor();
    },

    refreshVoices: refreshTtsVoices,

    getSelectedMicId() {
      const select = qs('diag-mic-select');
      return select ? select.value : '';
    },
  };

  global.DeskDiagnostics = DeskDiagnostics;
})(typeof window !== 'undefined' ? window : globalThis);
