const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const sourcePath = path.join(__dirname, '../../static/cowork_jarvis.js');
const source = fs.readFileSync(sourcePath, 'utf8');

class FakeElement {
  constructor(id, rect = { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 }) {
    this.id = id;
    this.tagName = id.includes('input') ? 'INPUT' : 'BUTTON';
    this.listeners = new Map();
    this.children = [];
    this.parentElement = null;
    this.classes = new Set();
    this.classList = {
      add: (name) => this.classes.add(name),
      remove: (name) => this.classes.delete(name),
      contains: (name) => this.classes.has(name),
      toggle: (name, force) => {
        const active = force === undefined ? !this.classes.has(name) : Boolean(force);
        if (active) this.classes.add(name);
        else this.classes.delete(name);
        return active;
      },
    };
    this.rect = rect;
    this.captureIds = [];
    this.title = '';
  }

  addEventListener(type, callback) {
    const handlers = this.listeners.get(type) || [];
    handlers.push(callback);
    this.listeners.set(type, handlers);
  }

  dispatch(type, values = {}) {
    const event = {
      type,
      target: this,
      preventDefault() { this.defaultPrevented = true; },
      stopPropagation() { this.propagationStopped = true; },
      ...values,
    };
    for (const callback of this.listeners.get(type) || []) callback(event);
    return event;
  }

  contains(element) {
    return element === this || this.children.some((child) => child.contains(element));
  }

  appendChild(child) {
    child.parentElement = this;
    this.children.push(child);
  }

  getBoundingClientRect() {
    return this.rect;
  }

  setPointerCapture(pointerId) {
    this.captureIds.push(pointerId);
  }
}

function makeHarness({ mini = true, bridge = true } = {}) {
  const faceRect = { left: 100, top: 100, right: 150, bottom: 150, width: 50, height: 50 };
  const elements = {
    stage: new FakeElement('stage'),
    'mini-pet-controls': new FakeElement('mini-pet-controls', {
      left: 20, top: 20, right: 80, bottom: 50, width: 60, height: 30,
    }),
    'mini-pet-drag': new FakeElement('mini-pet-drag'),
    'mini-pet-open': new FakeElement('mini-pet-open'),
    'mini-pet-mute': new FakeElement('mini-pet-mute'),
    'mini-pet-hide': new FakeElement('mini-pet-hide'),
  };
  elements['mini-pet-controls'].appendChild(elements['mini-pet-drag']);
  elements['mini-pet-controls'].appendChild(elements['mini-pet-open']);
  elements['mini-pet-controls'].appendChild(elements['mini-pet-mute']);
  elements['mini-pet-controls'].appendChild(elements['mini-pet-hide']);

  const calls = { ignore: [], begin: 0, end: 0, nudge: [], open: 0, hide: 0 };
  const electronAPI = bridge ? {
    setPetIgnoreMouse(value) { calls.ignore.push(value); },
    beginPetDrag() { calls.begin += 1; },
    endPetDrag() { calls.end += 1; },
    nudgePet(delta) { calls.nudge.push(delta); },
    openDashboard() { calls.open += 1; },
    hideMiniPet() { calls.hide += 1; },
  } : undefined;
  const intervalCallbacks = new Map();
  const clearedIntervals = [];
  const windowListeners = new Map();
  const documentListeners = new Map();
  let nextInterval = 0;
  const window = {
    location: { search: mini ? '?widget=minipet' : '' },
    electronAPI,
    EmoFace: { getHitboxRect: () => faceRect },
    addEventListener(type, callback) {
      const handlers = windowListeners.get(type) || [];
      handlers.push(callback);
      windowListeners.set(type, handlers);
    },
    setInterval(callback, delay) {
      const id = ++nextInterval;
      intervalCallbacks.set(id, { callback, delay });
      return id;
    },
    clearInterval(id) {
      intervalCallbacks.delete(id);
      clearedIntervals.push(id);
    },
    dispatch(type, values = {}) {
      const event = { type, ...values };
      for (const callback of windowListeners.get(type) || []) callback(event);
      return event;
    },
  };
  const body = new FakeElement('body');
  const document = {
    body,
    activeElement: null,
    hidden: false,
    getElementById: (id) => elements[id] || null,
    addEventListener(type, callback) {
      const handlers = documentListeners.get(type) || [];
      handlers.push(callback);
      documentListeners.set(type, handlers);
    },
    dispatch(type, values = {}) {
      const event = { type, ...values };
      for (const callback of documentListeners.get(type) || []) callback(event);
      return event;
    },
  };
  const fetchCalls = [];
  const context = {
    window,
    document,
    URLSearchParams,
    fetch: (...args) => {
      fetchCalls.push(args);
      return Promise.resolve({ ok: false, status: 503, json: async () => ({}) });
    },
    setTimeout,
    clearTimeout,
  };
  vm.runInNewContext(source, context, { filename: 'static/cowork_jarvis.js' });
  document.dispatch('DOMContentLoaded');

  return {
    body, calls, clearedIntervals, document, elements, faceRect, fetchCalls,
    intervalCallbacks, window,
    tick() { for (const { callback } of intervalCallbacks.values()) callback(); },
  };
}

test('mini-pet inicia só controles/hit-testing e não carrega módulos Cowork', () => {
  const harness = makeHarness();

  assert.equal(harness.body.classList.contains('is-minipet'), true);
  assert.equal(harness.fetchCalls.length, 0);
  assert.equal(harness.intervalCallbacks.size, 1);
  assert.equal(harness.intervalCallbacks.values().next().value.delay, 100);
  assert.deepEqual(harness.calls.ignore, [true]);
});

test('hit-test acompanha o hitbox móvel e inclui a barra mesmo sem movimento', () => {
  const harness = makeHarness();
  const controls = harness.elements['mini-pet-controls'];

  harness.window.dispatch('pointermove', { clientX: 120, clientY: 120 });
  assert.equal(controls.classList.contains('is-visible'), true);
  assert.equal(harness.body.classList.contains('minipet-interacting'), true);
  assert.equal(harness.calls.ignore.at(-1), false);

  harness.faceRect.left = 300;
  harness.faceRect.right = 350;
  harness.faceRect.top = 300;
  harness.faceRect.bottom = 350;
  harness.tick();
  assert.equal(controls.classList.contains('is-visible'), false);
  assert.equal(harness.calls.ignore.at(-1), true);

  harness.window.dispatch('pointermove', { clientX: 30, clientY: 30 });
  assert.equal(controls.classList.contains('is-visible'), true);
  assert.equal(harness.calls.ignore.at(-1), false);
  harness.window.dispatch('pointerleave');
  assert.equal(controls.classList.contains('is-visible'), false);
  assert.equal(harness.calls.ignore.at(-1), true);
});

test('foco da barra mantém controles visíveis e janela interativa sem ponteiro', () => {
  const harness = makeHarness();
  harness.document.activeElement = harness.elements['mini-pet-open'];
  harness.document.dispatch('focusin');

  assert.equal(harness.elements['mini-pet-controls'].classList.contains('is-visible'), true);
  assert.equal(harness.calls.ignore.at(-1), false);
  harness.document.activeElement = null;
  harness.document.dispatch('focusout');
  assert.equal(harness.elements['mini-pet-controls'].classList.contains('is-visible'), false);
  assert.equal(harness.calls.ignore.at(-1), true);
});

test('arrastar termina no pointerup, cancel, perda de captura, blur e hide', () => {
  for (const ending of ['pointerup', 'pointercancel', 'lostpointercapture', 'blur', 'hide']) {
    const harness = makeHarness();
    const drag = harness.elements['mini-pet-drag'];
    const down = drag.dispatch('pointerdown', { button: 0, isPrimary: true, pointerId: 7 });

    assert.equal(down.defaultPrevented, true, `${ending}: pointerdown impedido`);
    assert.equal(down.propagationStopped, true, `${ending}: pointerdown não propaga`);
    assert.deepEqual(drag.captureIds, [7]);
    assert.equal(harness.calls.begin, 1);

    if (ending === 'hide') harness.elements['mini-pet-hide'].dispatch('click');
    else if (ending === 'blur') harness.window.dispatch('blur');
    else drag.dispatch(ending);

    assert.equal(harness.calls.end, 1, `${ending}: encerra o arraste uma vez`);
    if (ending === 'hide') assert.equal(harness.calls.hide, 1);
    drag.dispatch('lostpointercapture');
    assert.equal(harness.calls.end, 1, `${ending}: evento posterior não duplica encerramento`);
  }
});

test('abrir, ocultar e mute não duplicam integração de app', () => {
  const harness = makeHarness();
  const openEvent = harness.elements['mini-pet-open'].dispatch('click');
  assert.equal(harness.calls.open, 1);
  assert.equal(openEvent.propagationStopped, true);
  assert.equal(harness.elements['mini-pet-mute'].listeners.has('click'), false);

  harness.elements['mini-pet-hide'].dispatch('click');
  assert.equal(harness.calls.hide, 1);
  assert.equal(harness.intervalCallbacks.size, 0);
  assert.equal(harness.calls.ignore.at(-1), true);
});

test('setas nudgem 10px ou 30px e Escape oculta o mini-pet', () => {
  const harness = makeHarness();
  const dispatchKey = (key, values = {}) => harness.document.dispatch('keydown', {
    key,
    preventDefault() { this.defaultPrevented = true; },
    ...values,
  });

  const left = dispatchKey('ArrowLeft');
  const up = dispatchKey('ArrowUp', { shiftKey: true });
  assert.equal(harness.calls.nudge.length, 2);
  assert.deepEqual([harness.calls.nudge[0].x, harness.calls.nudge[0].y], [-10, 0]);
  assert.deepEqual([harness.calls.nudge[1].x, harness.calls.nudge[1].y], [0, -30]);
  assert.equal(left.defaultPrevented, true);
  assert.equal(up.defaultPrevented, true);

  const input = new FakeElement('chat-input');
  harness.document.dispatch('keydown', { key: 'ArrowRight', target: input, preventDefault() {} });
  assert.equal(harness.calls.nudge.length, 2);

  dispatchKey('Escape');
  assert.equal(harness.calls.hide, 1);
  assert.equal(harness.intervalCallbacks.size, 0);
});

test('pausa hit-test e encerra arraste quando a página fica oculta', () => {
  const harness = makeHarness();
  harness.elements['mini-pet-drag'].dispatch('pointerdown', { button: 0, isPrimary: true, pointerId: 2 });
  harness.document.hidden = true;
  harness.document.dispatch('visibilitychange');

  assert.equal(harness.calls.end, 1);
  assert.equal(harness.intervalCallbacks.size, 0);
  assert.equal(harness.calls.ignore.at(-1), true);
  harness.document.hidden = false;
  harness.document.dispatch('visibilitychange');
  assert.equal(harness.intervalCallbacks.size, 1);
});

test('mini-pet funciona em preview sem electronAPI', () => {
  const harness = makeHarness({ bridge: false });
  harness.window.dispatch('pointermove', { clientX: 120, clientY: 120 });
  harness.elements['mini-pet-drag'].dispatch('pointerdown', { button: 0, isPrimary: true, pointerId: 1 });
  harness.document.dispatch('keydown', { key: 'ArrowRight', preventDefault() {} });
  harness.document.dispatch('keydown', { key: 'Escape', preventDefault() {} });
  assert.equal(harness.intervalCallbacks.size, 0);
});
