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

  class FakeWebSocket {}
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
      openMemoryDrawer, closeMemoryDrawer, trapDialogFocus, setSettingsOpen, cycleSettingsTab, setMode, cycleMode,
      promptForPairingToken, fetchMacStatus, enqueueServerAudio, fetchDataConsent, renderDataConsent, toggleDataConsent,
    };\n})();`
  );
  assert.notEqual(instrumentedSource, appSource, 'the app IIFE must accept instrumentation only in the test');
  vm.runInNewContext(instrumentedSource, context, { filename: sourcePath });
  const app = context.__appTest;
  app.state.ws = ws;
  return { app, context, document, window, elements, ws, wsMessages, timers, mediaRecorders };
}

function event(key, options = {}) {
  return {
    key,
    shiftKey: false,
    prevented: false,
    preventDefault() { this.prevented = true; },
    stopPropagation() {},
    ...options,
  };
}

test('each PTT recording keeps its own chunks even after the previous recorder emits data', async () => {
  const harness = makeHarness();
  const { app, wsMessages, mediaRecorders } = harness;
  const data = (text) => new Blob([text.repeat(500)], { type: 'audio/webm' });

  await app.startPtt();
  const firstRecorder = mediaRecorders[0];
  firstRecorder.ondataavailable({ data: data('A') });
  await app.stopPttAndSend();

  await app.startPtt();
  const secondRecorder = mediaRecorders[1];
  firstRecorder.ondataavailable({ data: data('X') });
  secondRecorder.ondataavailable({ data: data('B') });
  await app.stopPttAndSend();

  const audioMessages = wsMessages.filter((message) => message.type === 'audio');
  assert.equal(audioMessages.length, 2);
  assert.equal(Buffer.from(audioMessages[1].data, 'base64').toString(), 'B'.repeat(500));
});

test('interrupting TTS discards queued audio and ignores stale playback', async () => {
  const harness = makeHarness();
  const { app, elements } = harness;
  app.state.ttsMode = 'server';
  app.enqueueServerAudio(new Blob(['fala antiga']));
  await flush();
  assert.equal(elements.get('server-tts-audio').playCount, 1);

  app.stopSpeaking();
  assert.equal(app.state.ttsPlaying, false);
  assert.equal(app.state.ttsQueue.length, 0);
});

test('a cancelled playback callback does not affect a later TTS utterance', async () => {
  const harness = makeHarness();
  const { app, elements } = harness;
  const audio = elements.get('server-tts-audio');
  app.state.ttsMode = 'server';
  app.enqueueServerAudio(new Blob(['áudio']));
  await flush();
  assert.equal(audio.playCount, 1);
  const staleOnEnded = audio.onended;

  app.stopSpeaking();
  app.enqueueServerAudio(new Blob(['áudio novo']));
  await flush();
  assert.equal(audio.playCount, 2);
  staleOnEnded();
  assert.equal(app.state.ttsPlaying, true);
  app.stopSpeaking();
  assert.equal(app.state.ttsPlaying, false);
});

test('barge-in sends interrupt even when the speech is between sentences', () => {
  const { app, wsMessages } = makeHarness();
  app.handleWsMessage({ type: 'delta', text: 'primeira frase' });
  app.state.ttsPlaying = false;
  app.state.ttsQueue = [];
  app.triggerBargeIn();
  assert.deepEqual(wsMessages, [{ type: 'interrupt' }]);
  assert.equal(app.state.backendTurnActive, false);
});

test('queued approvals are resolved by their original ID in the native callback', async () => {
  const pending = [];
  const harness = makeHarness();
  const { app, window, wsMessages } = harness;
  window.electronAPI = { confirmWrite: () => new Promise((resolve) => pending.push(resolve)) };

  const first = { approval_id: 'aprovacao-1', title: 'Primeira', risk: 'write' };
  const second = { approval_id: 'aprovacao-2', title: 'Segunda', risk: 'write' };
  app.showToolApproval(first);
  first.title = 'Alterada depois';
  app.showToolApproval(second);
  assert.equal(app.state.pendingApprovalId, 'aprovacao-1');
  assert.equal(app.state.approvalQueue[0].title, 'Primeira');
  assert.equal(Object.isFrozen(app.state.approvalQueue[0]), true);

  pending[1](true);
  await flush();
  assert.equal(wsMessages[0].approval_id, 'aprovacao-2');
  assert.equal(app.state.pendingApprovalId, 'aprovacao-1');
  pending[0](false);
  await flush();
  assert.deepEqual(wsMessages.map((message) => [message.approval_id, message.approved]), [
    ['aprovacao-2', true],
    ['aprovacao-1', false],
  ]);
  assert.equal(app.state.pendingApprovalId, null);
});

test('gamepad navigates and activates the modal/drawer before the underlying tiles', () => {
  const harness = makeHarness();
  const { app, elements } = harness;
  const modal = elements.get('shortcut-modal');
  const drawer = elements.get('memory-drawer');
  const dock = elements.get('mode-dock');
  const modalAction = new FakeElement('button', 'modal-action');
  const drawerAction = new FakeElement('button', 'drawer-action');
  const hiddenTile = new FakeElement('div', 'hidden-tile');
  modalAction.parentElement = modal;
  modalAction.ownerDocument = harness.document;
  drawerAction.parentElement = drawer;
  drawerAction.ownerDocument = harness.document;
  hiddenTile.parentElement = dock;
  hiddenTile.ownerDocument = harness.document;
  modal.queryMap.set('button, input:not([type="hidden"]), select, textarea, [tabindex]:not([tabindex="-1"])', [modalAction]);
  drawer.queryMap.set('button, input:not([type="hidden"]), select, textarea, [tabindex]:not([tabindex="-1"])', [drawerAction]);
  dock.queryMap.set('[data-nav-tile]', [hiddenTile]);
  app.state.mode = 'dock';
  app.state.shortcutModalOpen = true;
  app.state.memoryOpen = true;

  let gamepadHandlers;
  harness.window.DeskGamepad = { init(handlers) { gamepadHandlers = handlers; } };
  app.initGamepad();
  gamepadHandlers.onDpad('down');
  assert.equal(harness.document.activeElement, modalAction);
  gamepadHandlers.onConfirm();
  assert.equal(modalAction.clickCount, 1);
  assert.equal(hiddenTile.clickCount, 0);

  app.state.shortcutModalOpen = false;
  app.state.gamepadFocusIndex = -1;
  gamepadHandlers.onDpad('down');
  assert.equal(harness.document.activeElement, drawerAction);
  gamepadHandlers.onConfirm();
  assert.equal(drawerAction.clickCount, 1);
  assert.equal(hiddenTile.clickCount, 0);
});

test('Enter on a child of the key does not run the parent shortcut; agent_prompt uses WebSocket', async () => {
  const harness = makeHarness();
  const { app, elements, wsMessages } = harness;
  app.state.shortcuts = [{
    id: 'prompt-1',
    slug: 'prompt',
    title: 'Prompt',
    action_type: 'agent_prompt',
    requires_confirmation: true,
    payload: { prompt: 'texto seguro' },
  }];
  app.renderShortcutsGrid();
  const tile = elements.get('shortcuts-grid').children[0];
  const innerKey = event('Enter', { target: tile.children[0] });
  tile.dispatch('keydown', innerKey);
  assert.equal(wsMessages.length, 0);

  tile.dispatch('keydown', event('Enter', { target: tile }));
  await flush();
  assert.deepEqual(wsMessages, [{ type: 'run_shortcut', id: 'prompt-1' }]);
});

test('a sensitive shortcut and the HTTP 409 fallback request approval via WebSocket', async () => {
  let restCalls = 0;
  const harness = makeHarness({ fetch: async () => { restCalls += 1; return { ok: true, status: 200, json: async () => ({}) }; } });
  const { app, wsMessages } = harness;
  await app.runShortcut({ id: 41, title: 'Sensitive shortcut', action_type: 'keystroke', requires_confirmation: true });
  assert.equal(restCalls, 0);
  assert.deepEqual(wsMessages, [{ type: 'run_shortcut', id: 41 }]);

  let fallbackWsCalls = 0;
  const fallback = makeHarness({
    fetch: async () => ({
      ok: false,
      status: 409,
      json: async () => ({ detail: { code: 'approval_required', message: 'Confirme pelo WebSocket.' } }),
    }),
  });
  fallback.app.state.ws.send = (message) => {
    fallbackWsCalls += 1;
    fallback.wsMessages.push(JSON.parse(message));
  };
  await fallback.app.runShortcut({ id: 42, title: 'Atalho atualizado', action_type: 'keystroke' });
  assert.equal(fallbackWsCalls, 1);
  assert.deepEqual(fallback.wsMessages, [{ type: 'run_shortcut', id: 42 }]);
});

test('modal traps focus and returns it to the element that opened it', () => {
  const harness = makeHarness();
  const { app, elements, document } = harness;
  const modal = elements.get('shortcut-modal');
  const first = new FakeElement('button', 'first');
  const last = new FakeElement('button', 'last');
  const opener = new FakeElement('button', 'opener');
  first.parentElement = modal;
  first.ownerDocument = document;
  last.parentElement = modal;
  last.ownerDocument = document;
  opener.ownerDocument = document;
  modal.queryMap.set('button, input:not([type="hidden"]), select, textarea, [tabindex]:not([tabindex="-1"])', [first, last]);
  app.state.shortcutModalOpen = true;
  document.activeElement = last;
  const tab = event('Tab');
  app.trapDialogFocus(tab);
  assert.equal(tab.prevented, true);
  assert.equal(document.activeElement, first);

  app.state.overlayReturnFocus = opener;
  app.closeShortcutModal();
  assert.equal(app.state.shortcutModalOpen, false);
  assert.equal(document.activeElement, opener);
});

test('drawer traps focus and returns it to the element that opened it', () => {
  const harness = makeHarness();
  const { app, elements, document } = harness;
  const drawer = elements.get('memory-drawer');
  const first = new FakeElement('button', 'drawer-first');
  const last = new FakeElement('button', 'drawer-last');
  const opener = new FakeElement('button', 'drawer-opener');
  first.ownerDocument = document;
  first.parentElement = drawer;
  last.ownerDocument = document;
  last.parentElement = drawer;
  opener.ownerDocument = document;
  drawer.queryMap.set('button, input:not([type="hidden"]), select, textarea, [tabindex]:not([tabindex="-1"])', [first, last]);
  app.state.memoryOpen = true;
  document.activeElement = last;
  const tab = event('Tab');
  app.trapDialogFocus(tab);
  assert.equal(tab.prevented, true);
  assert.equal(document.activeElement, first);

  app.state.overlayReturnFocus = opener;
  app.closeMemoryDrawer();
  assert.equal(app.state.memoryOpen, false);
  assert.equal(document.activeElement, opener);
});

test('Pet has no bar: Settings opens and L1/R1 switch section, outside it Mode', () => {
  const harness = makeHarness();
  const { app, document } = harness;
  document.getElementById('btn-mode-nathan').classList.add('hidden');
  assert.equal(typeof app.showHud, 'undefined');
  assert.equal(app.state.settingsOpen, false);
  app.setSettingsOpen(true);
  assert.equal(app.state.settingsOpen, true);
  assert.equal(app.state.settingsTab, 'voice');
  app.cycleSettingsTab(1);
  assert.equal(app.state.settingsTab, 'brain');
  app.cycleSettingsTab(-1);
  app.cycleSettingsTab(-1);
  assert.equal(app.state.settingsTab, 'diagnostics');
  app.setSettingsOpen(false);
  assert.equal(app.state.mode, 'pet');
  app.cycleMode(1);
  assert.equal(app.state.mode, 'dock');
  app.cycleMode(1);
  assert.equal(app.state.mode, 'pet');
});

test('fetchMacStatus uses faceApi without depending on getFace', async () => {
  const harness = makeHarness({
    fetch: async () => ({
      ok: true,
      json: async () => ({ active_app: 'Finder', now_playing: { playing: true, track: 'Faixa' } }),
    }),
  });
  let musicPlaying;
  harness.window.LupinFace = {
    setMusicPlaying(value) { musicPlaying = value; },
    setAccessory() {},
  };
  await harness.app.fetchMacStatus();
  assert.equal(musicPlaying, true);
  assert.equal(harness.elements.get('now-playing-title').textContent, 'Faixa');
});

test('pairing limits Tab to the dialog and restores focus on close', () => {
  const harness = makeHarness();
  const { app, document, elements } = harness;
  const input = document.getElementById('desk-pairing-input');
  input.tagName = 'INPUT';
  const cancel = document.getElementById('desk-pairing-cancel');
  cancel.tagName = 'BUTTON';
  const save = document.getElementById('desk-pairing-save');
  save.tagName = 'BUTTON';
  const opener = new FakeElement('button', 'pairing-opener');
  input.ownerDocument = document;
  cancel.ownerDocument = document;
  save.ownerDocument = document;
  opener.ownerDocument = document;
  document.activeElement = opener;

  app.promptForPairingToken();
  const overlay = document.body.children.at(-1);
  assert.equal(document.activeElement, input);
  document.activeElement = save;
  const tab = overlay.dispatch('keydown', event('Tab'));
  assert.equal(tab.prevented, true);
  assert.equal(document.activeElement, input);
  overlay.dispatch('keydown', event('Escape'));
  assert.equal(document.activeElement, opener);
  assert.equal(overlay.isConnected, false);
});

test('dictation: armed recording sends audio flagged as dictation and shows the result caption', async () => {
  const harness = makeHarness();
  const { app, wsMessages, mediaRecorders } = harness;
  const data = new Blob(['A'.repeat(500)], { type: 'audio/webm' });

  await app.startPtt();
  mediaRecorders[0].ondataavailable({ data });
  await app.stopPttAndSend();
  assert.equal(wsMessages.filter((m) => m.type === 'audio')[0].dictation, undefined);

  app.state.dictation.armed = true;
  await app.startPtt();
  mediaRecorders[1].ondataavailable({ data });
  await app.stopPttAndSend();
  assert.equal(wsMessages.filter((m) => m.type === 'audio')[1].dictation, true);

  app.handleWsMessage({ type: 'dictation_result', ok: true, message: 'Inserted.' });
  assert.equal(app.els.captionText.textContent, 'Inserted.');
});

test('data consent renders and toggles files in cloud and local Ollama modes', async () => {
  let serverPayload = {
    calendar: false,
    email: false,
    files: false,
    receiver: 'Claude',
    can_edit: true,
    local: false,
  };
  const putBodies = [];
  const harness = makeHarness({
    fetch: async (url, init = {}) => {
      if (url === '/api/data-consent' && init.method === 'PUT') {
        const body = JSON.parse(init.body);
        putBodies.push(body);
        serverPayload = { ...serverPayload, ...body };
        return { ok: true, status: 200, json: async () => serverPayload };
      }
      if (url === '/api/data-consent') {
        return { ok: true, status: 200, json: async () => serverPayload };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    },
  });
  harness.window.LupinLocalMode = require('../../static/local_mode.js');
  const { app, elements } = harness;

  await app.fetchDataConsent();
  assert.equal(elements.get('consent-files-label').textContent, 'Let Claude see the contents of your files');
  assert.equal(elements.get('btn-consent-files').textContent, 'Off');
  assert.equal(elements.get('btn-consent-files').disabled, false);

  await app.toggleDataConsent('files');
  assert.deepEqual(putBodies, [{ files: true }]);
  assert.equal(elements.get('btn-consent-files').textContent, 'On');
  assert.equal(elements.get('btn-consent-files').getAttribute('aria-checked'), 'true');

  serverPayload = {
    calendar: true,
    email: true,
    files: true,
    receiver: 'Ollama',
    can_edit: false,
    local: true,
  };
  await app.fetchDataConsent();
  assert.equal(elements.get('consent-files-label').textContent, 'Your files stay on this Mac');
  assert.equal(elements.get('btn-consent-files').textContent, 'On');
  assert.equal(elements.get('btn-consent-files').disabled, true);
});
