const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const sourcePath = path.join(__dirname, '../../static/lupin.js');
const source = fs.readFileSync(sourcePath, 'utf8');
const table = JSON.parse(
  fs.readFileSync(path.join(__dirname, '../../static/lupin/expressions.json'), 'utf8'),
);

class FakeElement {
  constructor(tag) {
    this.tag = tag;
    this.attributes = new Map();
    this.style = { setProperty() {} };
    this.dataset = {};
    this.children = [];
    this.parentNode = null;
    this.hidden = false;
    this.className = '';
    this.classes = new Set();
    this.classList = {
      add: (n) => this.classes.add(n),
      remove: (n) => this.classes.delete(n),
      contains: (n) => this.classes.has(n),
      toggle: (n, force) => {
        const on = force === undefined ? !this.classes.has(n) : Boolean(force);
        if (on) this.classes.add(n);
        else this.classes.delete(n);
        return on;
      },
    };
  }
  setAttribute(n, v) { this.attributes.set(n, String(v)); }
  getAttribute(n) { return this.attributes.get(n) ?? null; }
  appendChild(el) { el.parentNode = this; this.children.push(el); return el; }
  removeChild(el) { this.children = this.children.filter((c) => c !== el); el.parentNode = null; }
  set textContent(_) { this.children = []; }
  getBoundingClientRect() { return { left: 0, top: 0, width: 480, height: 320 }; }
}

function makeHarness({ reducedMotion = false } = {}) {
  const timers = new Map();
  let nextTimer = 0;
  let nextRaf = 0;
  const rafs = new Map();
  let now = 0;
  const listeners = new Set();
  const motionQuery = {
    matches: reducedMotion,
    addEventListener(type, cb) { listeners.add(cb); },
    removeEventListener(type, cb) { listeners.delete(cb); },
    change(matches) { this.matches = matches; for (const cb of [...listeners]) cb({ matches }); },
  };
  const window = {
    matchMedia: () => motionQuery,
    requestAnimationFrame(cb) { const id = ++nextRaf; rafs.set(id, cb); return id; },
    cancelAnimationFrame(id) { rafs.delete(id); },
    fetch: async () => ({ ok: true, json: async () => table }),
    EmoAudio: null,
    document: { createElement: (tag) => new FakeElement(tag), body: new FakeElement('body') },
  };
  const context = {
    window,
    document: window.document,
    performance: { now: () => now },
    Math, Date, console, Promise,
    setTimeout(cb, delay) { const id = ++nextTimer; timers.set(id, { cb, delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
  };
  vm.runInNewContext(source, context, { filename: sourcePath });
  const container = new FakeElement('div');
  return {
    api: window.LupinFace,
    container,
    motionQuery,
    timers,
    get listenerCount() { return listeners.size; },
    tick(ts) {
      now = ts;
      const frame = rafs.entries().next().value;
      assert.ok(frame, 'an animation frame must be scheduled');
      rafs.delete(frame[0]);
      frame[1](ts);
    },
    runTimers() {
      const pending = [...timers.entries()];
      timers.clear();
      pending.forEach(([, t]) => t.cb());
    },
  };
}

async function start(opts) {
  const h = makeHarness(opts);
  h.api.init(h.container);
  await new Promise((resolve) => setImmediate(resolve));
  return h;
}

function visible(h) {
  const root = h.container.children[0];
  const layers = {};
  const find = (el) => {
    if (el.dataset && el.dataset.layer) {
      const active = el.children.filter((img) => !img.hidden);
      layers[el.dataset.layer] = active.map((img) => img.getAttribute('src').split('/').pop().replace('.svg', ''));
    }
    el.children.forEach(find);
  };
  find(root);
  return layers;
}

test('the table covers the 12 expressions and 5 states with variants that exist', () => {
  const { api } = makeHarness();
  assert.equal(api.getSupportedEmotions().length, 12);
  for (const emotion of api.getSupportedEmotions()) {
    assert.ok(table.expressions[emotion], `expression ${emotion} has no row in the table`);
    const r = api.resolveLayers(table, { emotion, state: 'idle', blinking: false, audioLevel: 0 });
    for (const [layer, variant] of Object.entries(r.layers)) {
      assert.ok(table.layers[layer].includes(variant), `${emotion}: ${layer}/${variant} does not exist`);
    }
  }
  for (const state of api.getSupportedStates()) {
    assert.ok(table.states[state], `state ${state} has no row in the table`);
  }
});

test('each layer shows a single variant and the expression switches the pose', async () => {
  const h = await start();
  let v = visible(h);
  assert.deepEqual(v.pose, ['neutral']);
  h.api.setEmotion('love');
  assert.deepEqual(visible(h).pose, ['in-love']);
  h.api.setEmotion('angry');
  v = visible(h);
  assert.deepEqual(v.pose, ['angry']);
  for (const lista of Object.values(v)) assert.equal(lista.length, 1);
});

test('a temporary emotion returns to neutral after the timeout', async () => {
  const h = await start();
  h.api.setEmotion('surprised', { durationMs: 900 });
  assert.equal(h.api.getEmotion(), 'surprised');
  h.runTimers();
  assert.equal(h.api.getEmotion(), 'neutral');
  assert.deepEqual(visible(h).pose, ['neutral']);
});

test('unknown state and emotion values are ignored', async () => {
  const h = await start();
  const aviso = console.warn;
  console.warn = () => {};
  try {
    h.api.setEmotion('too-happy');
    h.api.setState('flying');
  } finally {
    console.warn = aviso;
  }
  assert.equal(h.api.getEmotion(), 'neutral');
  assert.equal(h.api.getState(), 'idle');
});

test('speaking lights the collar wave and opens the mouth according to the audio level', async () => {
  const h = await start();
  assert.deepEqual(visible(h).collar, ['off']);
  h.api.setState('speaking');
  assert.deepEqual(visible(h).collar, ['lit']);
  h.api.setAudioLevel(0.8);
  h.tick(100);
  assert.deepEqual(visible(h).pose, ['happy']);
  h.api.setAudioLevel(0.02);
  h.tick(300);
  assert.deepEqual(visible(h).pose, ['neutral']);
  h.api.setState('idle');
  assert.deepEqual(visible(h).collar, ['off']);
});

test('blink uses the closed-eyes pose when the table has one', () => {
  const { api } = makeHarness();
  const t = JSON.parse(JSON.stringify(table));
  t.blink = { neutral: 'sleepy' };
  const r = api.resolveLayers(t, { emotion: 'neutral', state: 'idle', blinking: true, audioLevel: 0 });
  assert.equal(r.layers.pose, 'sleepy');
  t.blink = {};
  const sem = api.resolveLayers(t, { emotion: 'neutral', state: 'idle', blinking: true, audioLevel: 0 });
  assert.equal(sem.layers.pose, 'neutral');
  const real = api.resolveLayers(table, { emotion: 'neutral', state: 'idle', blinking: true, audioLevel: 0 });
  assert.equal(real.layers.pose, 'blink');
});

test('full-body Trick swaps the bust for the frames and returns at the end', async () => {
  const h = await start();
  const root = h.container.children[0];
  assert.equal(h.api.playTrick('dance'), true);
  assert.ok(root.classes.has('lupin-full-body'));
  assert.ok(h.api.isTrickPlaying());
  const stage = root.children[0];
  const body = stage.children.find((c) => c.className === 'lupin-body');
  assert.equal(body.hidden, false);
  assert.match(body.getAttribute('src'), /body\/wave-1\.svg$/);
  h.runTimers();
  assert.equal(body.hidden, true);
  assert.ok(!root.classes.has('lupin-full-body'));
  assert.equal(h.api.isTrickPlaying(), false);
});

test('bust Tricks do not use the full body', async () => {
  const h = await start();
  const root = h.container.children[0];
  for (const id of ['sing', 'meditate', 'celebrate']) {
    assert.equal(h.api.playTrick(id), true);
    assert.ok(!root.classes.has('lupin-full-body'), id);
  }
  assert.equal(h.api.playTrick('fly'), false);
});

test('reduced motion settles the face and skips the body choreography', async () => {
  const h = await start({ reducedMotion: true });
  const root = h.container.children[0];
  h.api.blink();
  assert.deepEqual(visible(h).pose, ['neutral']);
  assert.equal(h.api.playTrick('nap'), true);
  assert.ok(!root.classes.has('lupin-full-body'));
  assert.equal(h.api.getEmotion(), 'sleepy');
});

test('reinit keeps only one motion-preference listener', async () => {
  const h = makeHarness();
  h.api.init(h.container);
  assert.equal(h.listenerCount, 1);
  h.api.init(h.container);
  assert.equal(h.listenerCount, 1);
});
