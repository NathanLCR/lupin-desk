const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const sourcePath = path.join(__dirname, '../../static/app.js');
const appSource = fs.readFileSync(sourcePath, 'utf8');

class FakeElement {
  constructor(id) {
    this.id = id;
    this.textContent = '';
    this.title = '';
    this.attributes = new Map();
    this.listeners = new Map();
    this.classes = new Set();
    this.classList = {
      add: (name) => this.classes.add(name),
      remove: (name) => this.classes.delete(name),
      contains: (name) => this.classes.has(name),
      toggle: (name, force) => {
        const add = force === undefined ? !this.classes.has(name) : Boolean(force);
        if (add) this.classes.add(name);
        else this.classes.delete(name);
        return add;
      },
    };
  }

  addEventListener(type, callback) {
    const callbacks = this.listeners.get(type) || [];
    callbacks.push(callback);
    this.listeners.set(type, callbacks);
  }

  dispatch(type, event = {}) {
    for (const callback of this.listeners.get(type) || []) callback({ target: this, ...event });
  }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) || null; }
  getBoundingClientRect() { return { left: 0, top: 0, width: 100, height: 100 }; }
}

function makeBroadcastBus() {
  const channels = new Set();
  const messages = [];
  class FakeBroadcastChannel {
    constructor(name) {
      this.name = name;
      this.listeners = [];
      channels.add(this);
    }
    addEventListener(type, callback) {
      if (type === 'message') this.listeners.push(callback);
    }
    postMessage(data) {
      messages.push({ channel: this, data });
      for (const target of channels) {
        if (target !== this && target.name === this.name) {
          target.listeners.forEach((callback) => callback({ data }));
        }
      }
    }
  }
  return { BroadcastChannel: FakeBroadcastChannel, messages };
}

function makeHarness({ href = 'http://localhost/', bus = null, elements = [] } = {}) {
  const byId = new Map(elements.map((id) => [id, new FakeElement(id)]));
  const documentListeners = new Map();
  const windowListeners = new Map();
  const storage = new Map();
  const face = {
    currentState: 'idle', currentEmotion: 'neutral', musicPlaying: false, initCount: 0,
    init() { this.initCount += 1; },
    getState() { return this.currentState; },
    getEmotion() { return this.currentEmotion; },
    setState(value) { this.currentState = value; },
    setEmotion(value) { this.currentEmotion = value; },
    setMusicPlaying(value) { this.musicPlaying = Boolean(value); },
    lookAt() {}, reactToTouch() {},
  };
  const audio = {
    initCount: 0, muted: null, purrStops: 0, chirps: 0,
    init() { this.initCount += 1; },
    setMuted(value) { this.muted = Boolean(value); },
    purr(active) { if (!active) this.purrStops += 1; },
    chirp() { this.chirps += 1; },
  };
  let fetchCount = 0;
  let socketCount = 0;
  let diagnosticsCount = 0;
  let timerCount = 0;
  let speechCancelCount = 0;
  const document = {
    readyState: 'loading',
    activeElement: null,
    body: new FakeElement('body'),
    documentElement: { style: { setProperty() {} } },
    getElementById(id) { return byId.get(id) || null; },
    querySelectorAll() { return []; },
    addEventListener(type, callback) {
      const callbacks = documentListeners.get(type) || [];
      callbacks.push(callback);
      documentListeners.set(type, callbacks);
    },
  };
  const window = {
    location: { href, origin: new URL(href).origin, host: 'localhost', protocol: 'http:' },
    history: { replaceState() {} },
    localStorage: {
      getItem(key) { return storage.has(key) ? storage.get(key) : null; },
      setItem(key, value) { storage.set(key, String(value)); },
      removeItem(key) { storage.delete(key); },
    },
    fetch: async () => { fetchCount += 1; return { ok: true, status: 200, json: async () => ({}) }; },
    setTimeout() { timerCount += 1; return timerCount; },
    clearTimeout() {},
    setInterval() { timerCount += 1; return timerCount; },
    clearInterval() {},
    requestAnimationFrame(callback) { callback(); },
    addEventListener(type, callback) {
      const callbacks = windowListeners.get(type) || [];
      callbacks.push(callback);
      windowListeners.set(type, callbacks);
    },
    dispatchEvent(event) {
      (windowListeners.get(event.type) || []).forEach((callback) => callback(event));
    },
    LupinFace: face,
    EmoAudio: audio,
    DeskDiagnostics: { init() { diagnosticsCount += 1; }, refreshVoices() {} },
    ...(bus ? { BroadcastChannel: bus.BroadcastChannel } : {}),
  };
  class FakeWebSocket { constructor() { socketCount += 1; } }
  const context = {
    window, document, navigator: {}, URL, Headers, Request, AbortController,
    WebSocket: FakeWebSocket,
    CustomEvent: class CustomEvent { constructor(type, init) { this.type = type; this.detail = init?.detail; } },
    SpeechSynthesisUtterance: class { constructor(text) { this.text = text; } },
    console, setImmediate,
  };
  window.speechSynthesis = {
    speaking: false, getVoices: () => [], speak() {}, cancel() { speechCancelCount += 1; },
    addEventListener() {},
  };
  const instrumented = appSource.replace(
    /\n\}\)\(\);\s*$/,
    `\n  globalThis.__appTest = { state, init, initPetSync, syncTtsUI, syncPreferencesFromStorage, applyFaceState, applyFaceEmotion };\n})();`
  );
  assert.notEqual(instrumented, appSource);
  vm.runInNewContext(instrumented, context, { filename: sourcePath });
  return {
    app: context.__appTest, window, document, elements: byId, storage, face, audio,
    get fetchCount() { return fetchCount; },
    get socketCount() { return socketCount; },
    get diagnosticsCount() { return diagnosticsCount; },
    get timerCount() { return timerCount; },
    get speechCancelCount() { return speechCancelCount; },
  };
}

const pref = {
  ttsEnabled: 'desk_assistant_tts_enabled',
  ttsMode: 'desk_assistant_tts_mode',
  petSoundsEnabled: 'desk_assistant_pet_sounds_enabled',
};

test('mini-pet applies the combined mute and keeps accessible state', () => {
  const harness = makeHarness({ href: 'http://localhost/?widget=minipet', elements: ['face-container', 'mini-pet-mute', 'btn-tts', 'btn-tts-mode', 'btn-pet-sounds'] });
  harness.app.init();
  const button = harness.elements.get('mini-pet-mute');

  button.dispatch('click');
  assert.equal(harness.app.state.ttsEnabled, false);
  assert.equal(harness.app.state.petSoundsEnabled, false);
  assert.equal(button.textContent, 'Unmute');
  assert.equal(button.title, 'Unmute');
  assert.equal(button.getAttribute('aria-pressed'), 'true');
  assert.equal(harness.elements.get('btn-pet-sounds').getAttribute('aria-pressed'), 'false');
  assert.equal(harness.elements.get('btn-tts').getAttribute('aria-pressed'), 'false');

  button.dispatch('click');
  assert.equal(harness.app.state.ttsEnabled, true);
  assert.equal(harness.app.state.petSoundsEnabled, true);
  assert.equal(button.textContent, 'Mute');
  assert.equal(button.title, 'Mute');
  assert.equal(button.getAttribute('aria-pressed'), 'false');

  harness.storage.set(pref.ttsEnabled, 'false');
  harness.storage.set(pref.petSoundsEnabled, 'false');
  harness.window.dispatchEvent({ type: 'storage', key: pref.ttsEnabled });
  assert.equal(button.textContent, 'Unmute');
  assert.equal(harness.elements.get('btn-pet-sounds').getAttribute('aria-pressed'), 'false');
  assert.equal(harness.audio.muted, true, 'the widget must not synthesize local audio');
  assert.equal(harness.audio.chirps, 0);
});

test('storage syncs preferences and silences ongoing speech and purring', () => {
  const harness = makeHarness({ elements: ['btn-tts', 'btn-tts-mode', 'btn-pet-sounds'] });
  harness.app.state.ttsPlaying = true;
  harness.storage.set(pref.ttsEnabled, 'false');
  harness.storage.set(pref.ttsMode, 'server');
  harness.storage.set(pref.petSoundsEnabled, 'false');

  harness.app.syncPreferencesFromStorage({ key: pref.ttsEnabled });
  assert.equal(harness.app.state.ttsEnabled, false);
  assert.equal(harness.app.state.ttsMode, 'server');
  assert.equal(harness.app.state.petSoundsEnabled, false);
  assert.equal(harness.app.state.ttsPlaying, false);
  assert.equal(harness.speechCancelCount, 1);
  assert.equal(harness.audio.muted, true);
  assert.ok(harness.audio.purrStops > 0);
  assert.equal(harness.elements.get('btn-pet-sounds').getAttribute('aria-pressed'), 'false');
});

test('mini-pet initializes only face, muted audio, preferences, touch and sync; does not open services', () => {
  const harness = makeHarness({ href: 'http://localhost/?widget=minipet', elements: ['face-container', 'mini-pet-mute'] });
  harness.app.init();

  assert.equal(harness.face.initCount, 1);
  assert.equal(harness.audio.initCount, 1);
  assert.equal(harness.fetchCount, 0);
  assert.equal(harness.socketCount, 0);
  assert.equal(harness.diagnosticsCount, 0);
  assert.equal(harness.timerCount, 0);
  assert.equal(harness.app.state.ttsQueue.length, 0);
});

test('dashboard mirrors only a visual snapshot; mini-pet neither echoes nor plays duplicate audio', () => {
  const bus = makeBroadcastBus();
  const dashboard = makeHarness({ bus });
  const widget = makeHarness({ href: 'http://localhost/?widget=minipet', bus, elements: ['face-container', 'mini-pet-mute'] });
  dashboard.app.applyFaceState('thinking');
  dashboard.app.applyFaceEmotion('curious');
  dashboard.app.state.musicPlaying = true;
  dashboard.app.initPetSync();
  widget.app.init();

  assert.equal(widget.face.currentState, 'thinking');
  assert.equal(widget.face.currentEmotion, 'curious');
  assert.equal(widget.face.musicPlaying, true);
  assert.equal(dashboard.audio.chirps, 1);
  assert.equal(widget.audio.chirps, 0);
  assert.equal(widget.app.state.ttsQueue.length, 0);
  assert.equal(widget.fetchCount, 0);
  assert.equal(bus.messages.length, 3, 'widget sends a request but does not echo the received snapshot');
  assert.equal(bus.messages.filter(({ data }) => data.type === 'request').length, 1);
  assert.equal(bus.messages.filter(({ data }) => data.type === 'snapshot').length, 2);
});
