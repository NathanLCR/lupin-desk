const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const sourcePath = path.join(__dirname, '../../static/app.js');
const appSource = fs.readFileSync(sourcePath, 'utf8');

class FakeClassList {
  constructor(element) {
    this.element = element;
    this.values = new Set();
  }

  add(...names) {
    names.forEach((name) => this.values.add(name));
  }

  remove(...names) {
    names.forEach((name) => this.values.delete(name));
  }

  contains(name) {
    return this.values.has(name);
  }

  toggle(name, force) {
    const shouldAdd = force === undefined ? !this.contains(name) : Boolean(force);
    if (shouldAdd) this.add(name);
    else this.remove(name);
    return shouldAdd;
  }
}

class FakeElement {
  constructor(tagName = 'div', id = '') {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.classList = new FakeClassList(this);
    this.attributes = new Map();
    this.listeners = new Map();
    this.queryMap = new Map();
    this.children = [];
    this.parentElement = null;
    this.dataset = {};
    this.style = {};
    this.value = '';
    this.checked = false;
    this.disabled = false;
    this.inert = false;
    this.isConnected = true;
    this.textContent = '';
    this.clickCount = 0;
    this.focusCount = 0;
    this.onended = null;
    this.onerror = null;
    this.pausedCount = 0;
    this.playCount = 0;
    this.type = '';
  }

  addEventListener(type, callback) {
    const callbacks = this.listeners.get(type) || [];
    callbacks.push(callback);
    this.listeners.set(type, callbacks);
  }

  dispatch(type, event = {}) {
    const nextEvent = {
      target: this,
      preventDefault() {},
      stopPropagation() {},
      ...event,
    };
    for (const callback of this.listeners.get(type) || []) callback(nextEvent);
    return nextEvent;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }

  appendChild(child) {
    child.parentElement = this;
    this.children.push(child);
    return child;
  }

  remove() {
    this.isConnected = false;
    if (this.parentElement) {
      this.parentElement.children = this.parentElement.children.filter((child) => child !== this);
    }
  }

  focus() {
    this.focusCount += 1;
    if (this.ownerDocument) this.ownerDocument.activeElement = this;
  }

  click() {
    this.clickCount += 1;
    this.dispatch('click');
  }

  contains(candidate) {
    if (candidate === this) return true;
    return this.children.some((child) => child.contains(candidate));
  }

  closest(selector) {
    if (selector !== '.hidden') return null;
    for (let current = this; current; current = current.parentElement) {
      if (current.classList.contains('hidden')) return current;
    }
    return null;
  }

  querySelectorAll(selector) {
    if (this.queryMap.has(selector)) return this.queryMap.get(selector);
    return [];
  }

  scrollIntoView() {}

  pause() {
    this.pausedCount += 1;
  }

  play() {
    this.playCount += 1;
    return Promise.resolve();
  }
}

class FakeFileReader {
  readAsDataURL(blob) {
    blob.arrayBuffer().then((buffer) => {
      this.result = `data:${blob.type || 'application/octet-stream'};base64,${Buffer.from(buffer).toString('base64')}`;
      this.onloadend();
    });
  }
}

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
  await new Promise((resolve) => setImmediate(resolve));
}

function makeHarness({ fetch: fetchStub, navigator: navigatorStub, speech = true } = {}) {
  const elements = new Map();
  const timers = new Map();
  const documentListeners = new Map();
  let timerId = 0;
  const document = {
    readyState: 'loading',
    activeElement: null,
    body: new FakeElement('body', 'body'),
    listeners: documentListeners,
    getElementById(id) {
      if (!elements.has(id)) {
        const element = new FakeElement('div', id);
        element.ownerDocument = document;
        elements.set(id, element);
      }
      return elements.get(id);
    },
    createElement(tagName) {
      const element = new FakeElement(tagName);
      element.ownerDocument = document;
      return element;
    },
    querySelectorAll() {
      return [];
    },
    addEventListener(type, callback) {
      const callbacks = documentListeners.get(type) || [];
      callbacks.push(callback);
      documentListeners.set(type, callbacks);
    },
  };
  document.body.ownerDocument = document;
  document.activeElement = document.body;

  const wsMessages = [];
  const ws = {
    readyState: 1,
    send(message) {
      wsMessages.push(JSON.parse(message));
    },
  };
  const nativeFetch = fetchStub || (async () => ({ ok: true, status: 200, json: async () => ({}) }));
  const window = {
    location: {
      href: 'http://localhost/',
      origin: 'http://localhost',
      host: 'localhost',
      protocol: 'http:',
    },
    history: { replaceState() {} },
    localStorage: {
      values: new Map(),
      getItem(key) { return this.values.get(key) || null; },
      setItem(key, value) { this.values.set(key, String(value)); },
      removeItem(key) { this.values.delete(key); },
    },
    fetch: nativeFetch,
    setTimeout(callback) {
      timerId += 1;
      timers.set(timerId, callback);
      return timerId;
    },
    clearTimeout(id) { timers.delete(id); },
    setInterval(callback) {
      timerId += 1;
      timers.set(timerId, callback);
      return timerId;
    },
    clearInterval(id) { timers.delete(id); },
    addEventListener() {},
    dispatchEvent() {},
    LupinFace: null,
    EmoAudio: null,
  };
  if (speech) {
    window.speechSynthesis = {
      speaking: false,
      getVoices: () => [],
      speak() {},
      cancel() {},
      addEventListener() {},
    };
  }

  const sockets = [];
  class FakeWebSocket {
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.listeners = {};
      this.sent = [];
      sockets.push(this);
    }
    addEventListener(type, cb) { (this.listeners[type] ||= []).push(cb); }
    send(message) { this.sent.push(JSON.parse(message)); }
    emit(type, event = {}) { (this.listeners[type] || []).forEach((cb) => cb(event)); }
    open() { this.readyState = 1; this.emit('open'); }
  }
  FakeWebSocket.OPEN = 1;
  FakeWebSocket.CONNECTING = 0;
  class FakeUtterance {
    constructor(text) { this.text = text; }
  }
  class FakeMediaRecorder {
    static isTypeSupported() { return false; }
    constructor(stream) {
      this.stream = stream;
      this.state = 'inactive';
      this.mimeType = 'audio/webm';
      this.ondataavailable = null;
      this.onstop = null;
      this.stopped = false;
      mediaRecorders.push(this);
    }
    start() { this.state = 'recording'; }
    stop() {
      this.state = 'inactive';
      this.stopped = true;
      if (this.onstop) this.onstop();
    }
  }
  const mediaRecorders = [];
  const navigator = navigatorStub || {
    mediaDevices: {
      async getUserMedia() {
        const track = { stopped: false, stop() { this.stopped = true; } };
        return { getTracks: () => [track], track };
      },
    },
  };

  const context = {
    window,
    document,
    navigator,
    fetch: nativeFetch,
    Blob,
    FileReader: FakeFileReader,
    URL,
    AbortController,
    SpeechSynthesisUtterance: FakeUtterance,
    WebSocket: FakeWebSocket,
    MediaRecorder: FakeMediaRecorder,
    CustomEvent: class CustomEvent { constructor(type, init) { this.type = type; this.detail = init && init.detail; } },
    console,
    setImmediate,
    Headers,
    Request,
    Buffer,
    atob,
  };
  window.MediaRecorder = FakeMediaRecorder;
  const instrumentedSource = appSource.replace(
    /\n\}\)\(\);\s*$/,
    `\n  globalThis.__appTest = {
      state, els, startPtt, stopPttAndSend, stopSpeaking, enqueueTtsSentence,
      triggerBargeIn, handleWsMessage, showToolApproval, resolveToolApproval,
      initGamepad, moveGamepadFocus, activateGamepadFocused, getNavigableTiles,
      renderShortcutsGrid, runShortcut, openShortcutModal, closeShortcutModal,
      openMemoryDrawer, closeMemoryDrawer, trapDialogFocus,
      promptForPairingToken, fetchMacStatus, enqueueServerAudio, connectWebSocket, sendHello, toggleTtsMode,
      setMode, cycleMode,
    };\n})();`
  );
  assert.notEqual(instrumentedSource, appSource, 'the app IIFE must accept instrumentation only in the test');
  vm.runInNewContext(instrumentedSource, context, { filename: sourcePath });
  const app = context.__appTest;
  return { sockets, app, context, document, window, elements, ws, wsMessages, timers, mediaRecorders };
}


const b64 = (text) => Buffer.from(text).toString('base64');

function connected(harness) {
  harness.app.connectWebSocket();
  const socket = harness.sockets[0];
  socket.open();
  return socket;
}

test('hello is sent when the WebSocket opens, with audio according to the TTS mode', () => {
  const harness = makeHarness();
  const socket = connected(harness);
  assert.deepEqual(socket.sent[0], { type: 'hello', body: 'web', protocol: 1, audio: [] });

  harness.app.state.ttsMode = 'browser';
  harness.app.toggleTtsMode();
  assert.equal(harness.app.state.ttsMode, 'server');
  assert.deepEqual(socket.sent.at(-1), { type: 'hello', body: 'web', protocol: 1, audio: ['m4a'] });
});

test('on Android (RG406H) the hello presents itself as rg406h-web', () => {
  const harness = makeHarness({ navigator: { userAgent: 'Mozilla/5.0 (Linux; Android 13; RG406H)' } });
  const socket = connected(harness);
  assert.equal(socket.sent[0].body, 'rg406h-web');
});

test('outside the Active Body the device becomes a Dock without Pet, and returns when Lupin comes back', () => {
  const harness = makeHarness();
  const { app, document } = harness;
  connected(harness);
  app.setMode('pet');
  app.handleWsMessage({ type: 'welcome', protocol: 1, active_body: 'esp32', active: false });
  assert.equal(app.state.mode, 'dock');
  assert.ok(document.body.classList.contains('lupin-in-other-body'));
  app.setMode('pet');
  assert.equal(app.state.mode, 'dock', 'without Lupin there is no Pet Mode');
  for (let i = 0; i < 3; i += 1) {
    app.cycleMode(1);
    assert.notEqual(app.state.mode, 'pet');
  }
  app.setMode('dock');

  app.handleWsMessage({ type: 'active_body', active_body: 'rg406h-web', active: true });
  assert.equal(app.state.mode, 'pet');
  assert.ok(!document.body.classList.contains('lupin-in-other-body'));
});

test('without Lupin, the device does not speak the sentences through the browser', () => {
  const harness = makeHarness();
  const { app } = harness;
  connected(harness);
  app.state.ttsMode = 'browser';
  app.state.ttsEnabled = true;
  app.handleWsMessage({ type: 'active_body', active_body: 'esp32', active: false });
  app.enqueueTtsSentence('Oi!');
  assert.equal(app.state.ttsQueue.length, 0);
});

test('touching the face sends touch (not pet) and welcome/mood are stored', () => {
  const harness = makeHarness();
  const socket = connected(harness);
  harness.app.handleWsMessage({ type: 'welcome', protocol: 1, active_body: 'rg406h-web' });
  harness.app.handleWsMessage({ type: 'mood', energy: 0.5, kind: 'pet' });
  assert.equal(harness.app.state.activeBody, 'rg406h-web');
  assert.equal(harness.app.state.mood.kind, 'pet');
  assert.ok(!socket.sent.some((m) => m.type === 'pet'));
});

test('audio chunks are reassembled and played only when last arrives', async () => {
  const harness = makeHarness();
  const { app, elements } = harness;
  app.state.ttsMode = 'server';
  const audio = elements.get('server-tts-audio');
  app.handleWsMessage({ type: 'audio', sentence: 0, seq: 0, last: false, mime: 'audio/mp4', data: b64('ab') });
  await flush();
  assert.equal(audio.playCount, 0);
  app.handleWsMessage({ type: 'audio', sentence: 0, seq: 1, last: true, mime: 'audio/mp4', data: b64('cd') });
  await flush();
  assert.equal(audio.playCount, 1);
  assert.equal(app.state.audioChunks.size, 0);
});

test('interrupted clears pending chunks and the audio queue', async () => {
  const harness = makeHarness();
  const { app, elements } = harness;
  app.state.ttsMode = 'server';
  app.handleWsMessage({ type: 'audio', sentence: 0, seq: 0, last: true, data: b64('x') });
  app.handleWsMessage({ type: 'audio', sentence: 1, seq: 0, last: true, data: b64('y') });
  app.handleWsMessage({ type: 'audio', sentence: 2, seq: 0, last: false, data: b64('z') });
  await flush();
  assert.equal(app.state.ttsQueue.length, 1);
  assert.equal(app.state.audioChunks.size, 1);
  app.handleWsMessage({ type: 'interrupted' });
  assert.equal(app.state.ttsQueue.length, 0);
  assert.equal(app.state.audioChunks.size, 0);
  assert.equal(app.state.ttsPlaying, false);
  assert.equal(elements.get('server-tts-audio').playCount, 1);
});
