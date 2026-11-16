const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const rootDir = path.resolve(__dirname, '../..');
const diagnosticsSource = fs.readFileSync(path.join(rootDir, 'static/diagnostics.js'), 'utf8');
const jarvisSource = fs.readFileSync(path.join(rootDir, 'static/cowork_jarvis.js'), 'utf8');

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function flush() {
  for (let i = 0; i < 8; i += 1) await Promise.resolve();
}

class Element {
  constructor(value = '') {
    this.value = value;
    this.textContent = '';
    this.innerHTML = '';
    this.disabled = false;
    this.attributes = {};
    this.style = {};
    this.listeners = {};
    this.options = [];
    const classes = new Set();
    this.classList = {
      add: (...items) => items.forEach((item) => classes.add(item)),
      remove: (...items) => items.forEach((item) => classes.delete(item)),
      contains: (item) => classes.has(item),
    };
  }

  addEventListener(type, callback) {
    (this.listeners[type] ||= []).push(callback);
  }

  dispatch(type, event = {}) {
    return (this.listeners[type] || []).map((callback) => callback(event)).at(-1);
  }

  setAttribute(name, value) {
    this.attributes[name] = value;
  }

  appendChild(option) {
    this.options.push(option);
    if (!this.value) this.value = option.value;
  }

  getTracks() {
    return [];
  }
}

function makeStream() {
  const track = { stopped: false, stop() { this.stopped = true; } };
  return { track, getTracks: () => [track] };
}

function makeDiagnosticsHarness(getUserMedia) {
  const ids = [
    'diag-btn-refresh-server', 'diag-btn-list-mics', 'diag-btn-mic-toggle', 'diag-btn-loopback',
    'diag-btn-test-browser-tts', 'diag-btn-test-server-tts', 'diag-btn-motion-perm',
    'diag-mic-select', 'diag-mic-badge', 'diag-mic-meter-fill', 'diag-loopback-status',
    'diag-loopback-audio', 'diag-server-info', 'diag-browser-voices', 'diag-server-voices',
    'diag-tts-mode-badge', 'diag-pad-status', 'diag-pad-id', 'diag-pad-axes', 'diag-pad-buttons',
    'diag-pad-last', 'diag-orient-val', 'diag-accel-val', 'diag-llm-provider', 'diag-llm-base-url',
    'diag-llm-model-select', 'diag-llm-model-custom', 'diag-btn-fetch-models', 'diag-btn-save-llm',
    'diag-llm-status', 'diag-llm-key-badge',
  ];
  const elements = Object.fromEntries(ids.map((id) => [id, new Element(id === 'diag-mic-select' ? 'mic-1' : '')]));
  const root = { querySelector: (selector) => elements[selector.slice(1)] || null };
  const intervalCallbacks = [];

  class AudioContextMock {
    state = 'running';
    createMediaStreamSource() { return { connect() {} }; }
    createAnalyser() {
      return {
        frequencyBinCount: 16,
        getByteTimeDomainData(data) { data.fill(128); },
      };
    }
    resume() { return Promise.resolve(); }
    close() { return Promise.resolve(); }
  }

  const window = {
    isSecureContext: true,
    location: { origin: 'http://localhost' },
    AudioContext: AudioContextMock,
    setInterval(callback) { intervalCallbacks.push(callback); return intervalCallbacks.length; },
    clearInterval() {},
    setTimeout() { return 1; },
    clearTimeout() {},
    requestAnimationFrame() { return 1; },
    cancelAnimationFrame() {},
    addEventListener() {},
    URL,
  };
  const document = {
    getElementById: (id) => elements[id] || null,
    createElement: () => new Element(),
    addEventListener() {},
    querySelectorAll: () => [],
  };
  const navigator = {
    getGamepads: () => [],
    mediaDevices: {
      getUserMedia,
      enumerateDevices: async () => [
        { kind: 'audioinput', deviceId: 'mic-1', label: 'Microfone 1' },
        { kind: 'audioinput', deviceId: 'mic-2', label: 'Microfone 2' },
      ],
    },
  };
  const context = {
    window, document, navigator,
    fetch: async () => ({ ok: false, status: 503, json: async () => ({}) }),
    Blob, URL, Uint8Array, setTimeout, clearTimeout,
  };
  vm.runInNewContext(diagnosticsSource, context, { filename: 'static/diagnostics.js' });
  window.DeskDiagnostics.init(root);
  window.DeskDiagnostics.activate();
  return { api: window.DeskDiagnostics, elements, intervalCallbacks };
}

function makeJarvisHarness({ providerResponse, fetchImpl, getUserMedia, AudioContext, MediaRecorder } = {}) {
  const elements = Object.fromEntries([
    'btn-vad-toggle', 'btn-jarvis-vision', 'btn-jarvis-clipboard', 'nathan-jarvis-output',
    'chat-input', 'chat-form',
  ].map((id) => [id, new Element()]));
  let submitCount = 0;
  elements['chat-form'].dispatchEvent = () => { submitCount += 1; };
  const intervals = [];
  const document = {
    getElementById: (id) => elements[id] || null,
    addEventListener(type, callback) {
      if (type === 'DOMContentLoaded') this.ready = callback;
    },
    querySelectorAll: () => [],
  };
  const defaultProviderResponse = {
    ok: true,
    status: 200,
    json: async () => ({
      presets: [{ id: 'local_proxy' }],
      active: { provider_id: 'local_proxy', base_url: 'http://127.0.0.1:31415/v1' },
    }),
  };

  const window = {
    location: { search: '' },
    confirm: () => true,
    AudioContext,
    addEventListener() {},
    setInterval(callback) { intervals.push(callback); return intervals.length; },
    clearInterval() {},
    setTimeout() { return 1; },
    clearTimeout() {},
  };
  const fetchCalls = [];
  const fetch = async (url, options = {}) => {
    fetchCalls.push({ url, options });
    if (fetchImpl) return fetchImpl(url, options);
    if (url === '/api/llm/providers') return providerResponse || defaultProviderResponse;
    return { ok: true, status: 200, json: async () => ({}) };
  };
  const context = {
    window, document, fetch, URL, URLSearchParams, Blob, FormData, AbortController, Event,
    navigator: { mediaDevices: { getUserMedia: getUserMedia || (async () => makeStream()) } },
    MediaRecorder, setTimeout, clearTimeout,
  };
  vm.runInNewContext(jarvisSource, context, { filename: 'static/cowork_jarvis.js' });
  document.ready();
  return { elements, fetchCalls, intervals, window, get submitCount() { return submitCount; } };
}

test('Jarvis bloqueia captura quando a consulta de provedor falha por HTTP', async () => {
  const harness = makeJarvisHarness({ providerResponse: { ok: false, status: 503, json: async () => ({}) } });
  await harness.elements['btn-jarvis-vision'].dispatch('click');

  assert.equal(harness.fetchCalls.some(({ url }) => url === '/api/jarvis/vision'), false);
  assert.match(harness.elements['nathan-jarvis-output'].textContent, /Nenhuma captura foi enviada/);
  assert.match(harness.elements['nathan-jarvis-output'].textContent, /tente novamente/);
});

for (const [label, active] of [
  ['ausente', null],
  ['desconhecido', { provider_id: 'provedor-novo', base_url: 'https://llm.example/v1' }],
  ['sem URL', { provider_id: 'local_proxy' }],
]) {
  test(`Jarvis bloqueia captura com dados de provedor ${label}`, async () => {
    const harness = makeJarvisHarness({
      providerResponse: {
        ok: true,
        status: 200,
        json: async () => ({ presets: [{ id: 'local_proxy' }], active }),
      },
    });
    await harness.elements['btn-jarvis-clipboard'].dispatch('click');

    assert.equal(harness.fetchCalls.some(({ url }) => url === '/api/jarvis/clipboard'), false);
    assert.match(harness.elements['nathan-jarvis-output'].textContent, /Nenhuma captura foi enviada/);
  });
}

test('VAD desligado invalida e aborta a transcrição já iniciada', async () => {
  const sttRequest = deferred();
  const vadStream = makeStream();
  const mediaRecorders = [];
  let vadGetUserMediaResolve;

  class MediaRecorderMock {
    constructor() {
      this.state = 'inactive';
      this.mimeType = 'audio/webm';
      mediaRecorders.push(this);
    }
    start() { this.state = 'recording'; }
    stop() {
      this.state = 'inactive';
      this.ondataavailable?.({ data: new Blob([new Uint8Array(900)]) });
      this.onstop?.();
    }
  }
  class AudioContextMock {
    createMediaStreamSource() { return { connect() {} }; }
    createAnalyser() {
      return { fftSize: 512, getByteTimeDomainData(data) { data.fill(255); } };
    }
    close() { return Promise.resolve(); }
  }
  let harnessSttSignal;
  const harness = makeJarvisHarness({
    AudioContext: AudioContextMock,
    MediaRecorder: MediaRecorderMock,
    getUserMedia: () => new Promise((resolve) => { vadGetUserMediaResolve = resolve; }),
    fetchImpl: async (url, options = {}) => {
      if (url === '/api/llm/providers') {
        return { ok: true, status: 200, json: async () => ({ presets: [{ id: 'local_proxy' }], active: { provider_id: 'local_proxy', base_url: 'http://localhost/v1' } }) };
      }
      if (url === '/api/stt') {
        harnessSttSignal = options.signal;
        return sttRequest.promise;
      }
      return { ok: true, status: 200, json: async () => ({}) };
    },
  });

  const toggle = harness.elements['btn-vad-toggle'];
  const enabling = toggle.dispatch('click');
  vadGetUserMediaResolve(vadStream);
  await enabling;
  harness.intervals.at(-1)();
  assert.equal(mediaRecorders.length, 1);
  mediaRecorders[0].stop();
  await flush();
  assert.ok(harnessSttSignal);

  await toggle.dispatch('click');
  assert.equal(harnessSttSignal.aborted, true);
  sttRequest.resolve({ ok: true, status: 200, json: async () => ({ text: 'transcrição tardia' }) });
  await flush();

  assert.equal(harness.submitCount, 0);
  assert.equal(vadStream.track.stopped, true);
});

test('Diagnóstico encerra o stream retornado por getUserMedia após desativação', async () => {
  const pending = deferred();
  const stream = makeStream();
  const harness = makeDiagnosticsHarness(() => pending.promise);

  const starting = harness.elements['diag-btn-mic-toggle'].dispatch('click');
  harness.api.deactivate();
  pending.resolve(stream);
  await starting;

  assert.equal(stream.track.stopped, true);
  assert.equal(harness.elements['diag-btn-mic-toggle'].disabled, false);
  assert.equal(harness.elements['diag-mic-badge'].textContent, 'Parado');
});

test('Diagnóstico encerra o stream temporário de permissão após desativação', async () => {
  const pending = deferred();
  const stream = makeStream();
  const harness = makeDiagnosticsHarness(() => pending.promise);

  const listing = harness.elements['diag-btn-list-mics'].dispatch('click');
  harness.api.deactivate();
  pending.resolve(stream);
  await listing;

  assert.equal(stream.track.stopped, true);
});

test('Diagnóstico reinicia o monitor com o microfone selecionado', async () => {
  const streams = [makeStream(), makeStream()];
  const constraints = [];
  const harness = makeDiagnosticsHarness(async (constraint) => {
    constraints.push(constraint);
    return streams[constraints.length - 1];
  });
  const select = harness.elements['diag-mic-select'];

  await harness.elements['diag-btn-mic-toggle'].dispatch('click');
  assert.equal(constraints.length, 1);
  select.value = 'mic-2';
  select.dispatch('change');
  await flush();

  assert.equal(streams[0].track.stopped, true);
  assert.equal(constraints[1].audio.deviceId.exact, 'mic-2');
  assert.equal(streams[1].track.stopped, false);
  harness.api.deactivate();
});
