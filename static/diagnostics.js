/**
 * Diagnostics Studio (/static/diagnostics.js -> window.DeskDiagnostics)
 * Checks the secure context, lists microphones, measures level in real time,
 * runs a 3s loopback, inspects TTS voices (Browser vs Mac server),
 * shows the live RG406H gamepad and motion sensors (with iOS permission).
 */
(function (global) {
  'use strict';

  const LOOPBACK_DURATION_MS = 3000;

  let containerEl = null;
  let options = {};
  let active = false;

  // Microphone / WebAudio state
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

  // Gamepad inspector and sensors state
  let gamepadIntervalId = null;
  let motionBound = false;
  let lastMotion = { ax: 0, ay: 0, az: 0, alpha: 0, beta: 0, gamma: 0, supported: false };

  // LLM provider and model selector state
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
        <!-- Card 1: Secure Context & Backend -->
        <section class="diag-card">
          <div class="diag-card-head">
            <h3>🔒 Secure Context & Server</h3>
            <span class="diag-pill ${isSecure ? 'is-ok' : 'is-err'}">
              ${isSecure ? 'isSecureContext: OK' : 'No HTTPS/Localhost'}
            </span>
          </div>
          <p class="diag-hint">
            Current origin: <code>${escapeHtml(originText)}</code>.
            ${
              isSecure
                ? 'Microphone, WakeLock and Gamepad available.'
                : 'The microphone requires HTTPS (port 8443) or an ADB tunnel (http://localhost:8000).'
            }
          </p>
          <div id="diag-server-info" class="diag-kv-list">
            <div class="diag-kv"><span>API status:</span><strong>Loading...</strong></div>
          </div>
          <button id="diag-btn-refresh-server" type="button" class="btn-secondary diag-btn-sm">
            ↻ Refresh Server Diagnostics
          </button>
        </section>

        <!-- Card 1b: LLM Provider & Model -->
        <section class="diag-card">
          <div class="diag-card-head">
            <h3>🧠 LLM Provider & Model</h3>
            <span id="diag-llm-key-badge" class="diag-pill">Loading...</span>
          </div>
          <label class="diag-field-label" for="diag-llm-provider">Provider (OpenAI-compatible)</label>
          <select id="diag-llm-provider" class="diag-select" aria-label="Select LLM provider">
            <option value="local_proxy">Local Proxy</option>
          </select>
          <label class="diag-field-label" for="diag-llm-base-url">Base URL</label>
          <input
            id="diag-llm-base-url"
            type="url"
            class="diag-input"
            placeholder="http://127.0.0.1:31415/v1"
            aria-label="LLM provider base URL"
          />
          <label class="diag-field-label" for="diag-llm-model-select">Model</label>
          <div class="diag-row">
            <select id="diag-llm-model-select" class="diag-select" aria-label="Select LLM model">
              <option value="">Loading models...</option>
            </select>
            <button id="diag-btn-fetch-models" type="button" class="btn-secondary diag-btn-sm" aria-label="Refresh LLM model list">
              ↻ List
            </button>
          </div>
          <input
            id="diag-llm-model-custom"
            type="text"
            class="diag-input"
            placeholder="Or type a model ID manually"
            aria-label="LLM model ID"
          />
          <div class="diag-btn-group">
            <button id="diag-btn-save-llm" type="button" class="btn-primary">
              💾 Save & Apply
            </button>
          </div>
          <p id="diag-llm-status" class="diag-hint">
            API keys are read only from the server's <code>.env</code>.
          </p>
        </section>

        <!-- Card 2: Microphone & 3s Loopback -->
        <section class="diag-card">
          <div class="diag-card-head">
            <h3>🎙️ Microphone & Loopback</h3>
            <span id="diag-mic-badge" class="diag-pill">Stopped</span>
          </div>
          <div class="diag-row">
            <select id="diag-mic-select" class="diag-select" aria-label="Select microphone">
              <option value="">System default microphone</option>
            </select>
            <button id="diag-btn-list-mics" type="button" class="btn-secondary diag-btn-sm" aria-label="Refresh microphone list">
              ↻ List
            </button>
          </div>
          <div class="diag-meter-wrap" aria-label="Microphone input level">
            <div id="diag-mic-meter-fill" class="diag-meter-fill"></div>
          </div>
          <div class="diag-btn-group">
            <button id="diag-btn-mic-toggle" type="button" class="btn-secondary">
              🎧 Monitor Level
            </button>
            <button id="diag-btn-loopback" type="button" class="btn-primary">
              ⏺️ Record 3s and play back
            </button>
          </div>
          <p id="diag-loopback-status" class="diag-hint">
            Use the loopback to confirm the built-in, USB-C or Bluetooth microphone on the RG406H/Mac/iPhone.
          </p>
          <audio id="diag-loopback-audio" class="diag-audio-player hidden" controls playsinline></audio>
        </section>

        <!-- Card 3: TTS Voice Inspector -->
        <section class="diag-card">
          <div class="diag-card-head">
            <h3>🗣️ TTS Voices (Hybrid)</h3>
            <span id="diag-tts-mode-badge" class="diag-pill is-ok">Browser</span>
          </div>
          <div class="diag-btn-group">
            <button id="diag-btn-test-browser-tts" type="button" class="btn-secondary">
              🔊 Test Browser
            </button>
            <button id="diag-btn-test-server-tts" type="button" class="btn-primary">
              🖥️ Test Mac Server
            </button>
          </div>
          <div class="diag-voices-columns">
            <div>
              <div class="diag-sublabel">Browser (speechSynthesis)</div>
              <ul id="diag-browser-voices" class="diag-mini-list"></ul>
            </div>
            <div>
              <div class="diag-sublabel">Mac server (/api/tts/voices)</div>
              <ul id="diag-server-voices" class="diag-mini-list"></ul>
            </div>
          </div>
        </section>

        <!-- Card 4: Live RG406H Gamepad Inspector -->
        <section class="diag-card">
          <div class="diag-card-head">
            <h3>🎮 Live RG406H Gamepad</h3>
            <span id="diag-pad-status" class="diag-pill">Waiting</span>
          </div>
          <p id="diag-pad-id" class="diag-hint">Press any button or move the analog stick on the controller.</p>
          <div id="diag-pad-axes" class="diag-axes-grid"></div>
          <div id="diag-pad-buttons" class="diag-pad-buttons"></div>
          <div id="diag-pad-last" class="diag-hint">Last action: —</div>
        </section>

        <!-- Card 5: Gyroscope & Accelerometer -->
        <section class="diag-card diag-card-wide">
          <div class="diag-card-head">
            <h3>🧭 Gyroscope & Accelerometer</h3>
            <button id="diag-btn-motion-perm" type="button" class="btn-secondary diag-btn-sm">
              📱 Enable Sensors (iOS / Motion)
            </button>
          </div>
          <div id="diag-motion-readout" class="diag-motion-grid">
            <div class="diag-kv"><span>Orientation (α / β / γ):</span><strong id="diag-orient-val">0° / 0° / 0°</strong></div>
            <div class="diag-kv"><span>Acceleration (X / Y / Z):</span><strong id="diag-accel-val">0.0 / 0.0 / 0.0</strong></div>
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
          options.onTestBrowserTts(
            typeof options.getTestPhrase === 'function'
              ? options.getTestPhrase('browser')
              : 'Hi! The browser voice test is working.',
          );
        }
      });
    }

    if (btnTestServer) {
      btnTestServer.addEventListener('click', () => {
        if (typeof options.onTestServerTts === 'function') {
          options.onTestServerTts(
            typeof options.getTestPhrase === 'function'
              ? options.getTestPhrase('server')
              : "Hi! The Mac server's offline voice test is working.",
          );
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
        target.innerHTML = `<div class="diag-kv"><span>HTTP error:</span><strong>${res.status}</strong></div>`;
        return;
      }
      const data = await res.json();
      const sttInfo = data.stt || {};
      const ttsInfo = data.tts || {};
      const sttOk = Boolean(sttInfo.available ?? data.stt_available);
      const ttsOk = Boolean(ttsInfo.available ?? data.tts_available);
      const engineName = sttInfo.engine || data.stt_engine || (sttOk ? 'active' : 'unavailable');

      target.innerHTML = `
        <div class="diag-kv"><span>Local STT:</span><strong>${sttOk ? `Available (${escapeHtml(engineName)})` : 'Unavailable'}</strong></div>
        <div class="diag-kv"><span>Mac server TTS:</span><strong>${ttsOk ? 'Available (say + afconvert)' : 'Unavailable'}</strong></div>
        <div class="diag-kv"><span>LLM model:</span><strong>${escapeHtml(data.llm_model || data.model || '—')}</strong></div>
        <div class="diag-kv"><span>HTTPS port:</span><strong>${escapeHtml(data.https_port || 8443)}</strong></div>
      `;
    } catch {
      target.innerHTML = '<div class="diag-kv"><span>Server:</span><strong>Offline / Reconnecting</strong></div>';
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
      badge.textContent = `⚠️ Missing ${envName}`;
    } else {
      badge.classList.add('is-warn');
      badge.textContent = `No key (${envName})`;
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
      opt.textContent = 'No models listed — type one below';
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
        statusEl.textContent = 'Could not load the LLM providers from the server.';
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
            ? `✓ ${data.models.length} models loaded from /models.`
            : `Using suggested list (${data.error || '/models endpoint unavailable'}).`;
      }
    } catch (err) {
      if (showFeedback && statusEl) {
        statusEl.textContent = `Error listing models: ${err.message || err}`;
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
        statusEl.textContent = `✓ Applied and saved: ${llmActive.model} (${llmActive.base_url}).`;
      }
      await fetchServerDiagnostics();
    } catch (err) {
      if (statusEl) {
        statusEl.textContent = `Error saving provider: ${err.message || err}`;
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
        opt.textContent = 'No microphone detected';
        select.appendChild(opt);
        return;
      }

      inputs.forEach((dev, idx) => {
        const opt = document.createElement('option');
        opt.value = dev.deviceId || '';
        opt.textContent = dev.label || `Microphone ${idx + 1}`;
        select.appendChild(opt);
      });

      if (currentVal && inputs.some((d) => d.deviceId === currentVal)) {
        select.value = currentVal;
      }
    } catch (err) {
      const status = qs('diag-loopback-status');
      if (active && requestId === micRequestId && status) {
        status.textContent = `Microphone permission denied or blocked: ${err.message || err}. Check the permission and try again.`;
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
      if (status) status.textContent = 'Microphone API unavailable in this browser/origin.';
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
        badge.textContent = 'Listening';
        badge.classList.add('is-ok');
      }
      if (toggleBtn) toggleBtn.textContent = '⏹️ Stop Monitor';
      return true;
    } catch (err) {
      if (requestId === micRequestId && status) {
        status.textContent = `Failed to open microphone: ${err.message || err}. Check the permission and try again.`;
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
      badge.textContent = 'Stopped';
      badge.classList.remove('is-ok');
    }
    const toggleBtn = qs('diag-btn-mic-toggle');
    if (toggleBtn) {
      toggleBtn.disabled = false;
      toggleBtn.textContent = '🎧 Monitor Level';
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
      if (status) status.textContent = 'MediaRecorder is not supported in this browser.';
      return;
    }

    loopbackRecording = true;
    if (btn) btn.disabled = true;
    if (status) status.textContent = 'Recording 3 seconds... speak close to the microphone!';

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
      if (status) status.textContent = `Loopback ready (${Math.round(blob.size / 1024)} KB). Playing back...`;
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
      modeBadge.textContent = m === 'server' ? 'Mac server' : 'Browser';
    }

    if (browserList) {
      browserList.innerHTML = '';
      if ('speechSynthesis' in global) {
        const voices = global.speechSynthesis.getVoices() || [];
        const wanted = typeof options.getVoiceLang === 'function' ? options.getVoiceLang() : 'pt';
        const ptVoices = voices.filter((v) => new RegExp('^' + wanted, 'i').test(v.lang));
        const shown = (ptVoices.length > 0 ? ptVoices : voices).slice(0, 8);
        if (shown.length === 0) {
          browserList.innerHTML = '<li>No voices listed yet</li>';
        } else {
          shown.forEach((v) => {
            const li = document.createElement('li');
            li.textContent = `${v.name} (${v.lang})`;
            browserList.appendChild(li);
          });
        }
      } else {
        browserList.innerHTML = '<li>speechSynthesis unavailable</li>';
      }
    }

    if (serverList) {
      try {
        const res = await fetch('/api/tts/voices');
        if (!res.ok) {
          serverList.innerHTML = '<li>Error querying /api/tts/voices</li>';
          return;
        }
        const data = await res.json();
        const voices = Array.isArray(data) ? data : data.voices || [];
        serverList.innerHTML = '';
        if (voices.length === 0) {
          serverList.innerHTML = '<li>No Mac voices found</li>';
          return;
        }
        voices.slice(0, 8).forEach((v) => {
          const li = document.createElement('li');
          const name = typeof v === 'string' ? v : v.name || v.voice || 'Voice';
          const lang = typeof v === 'object' && v.lang ? ` (${v.lang})` : '';
          li.textContent = `${name}${lang}`;
          serverList.appendChild(li);
        });
      } catch {
        serverList.innerHTML = '<li>Server unavailable</li>';
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
      statusEl.textContent = snap.connected ? 'Connected' : 'Disconnected';
      statusEl.classList.toggle('is-ok', snap.connected);
    }
    if (idEl) {
      idEl.textContent = snap.connected
        ? `${snap.id} (mapping: ${snap.mapping})`
        : 'Press any button on the RG406H controller to wake the Gamepad API.';
    }
    if (lastEl) {
      lastEl.textContent = `Last action: ${snap.lastAction || '—'}`;
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
      if (btn) btn.textContent = '✓ Sensors Active';
    } catch {
      if (btn) btn.textContent = '⚠️ Permission Denied';
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
