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
    setNow(ts) { now = ts; },
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

function findByClass(el, classPart) {
  let found = null;
  const walk = (node) => {
    if (found) return;
    if (node.className && node.className.split(/\s+/).includes(classPart)) {
      found = node;
      return;
    }
    node.children.forEach(walk);
  };
  walk(el);
  return found;
}

test('the v3 table covers the 12 expressions and 5 states with valid layer variants', () => {
  const { api } = makeHarness();
  assert.equal(table.version, 3);
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

test('each of the 8 layers shows a single variant and expressions switch eyes and mouth', async () => {
  const h = await start();
  let v = visible(h);
  assert.deepEqual(Object.keys(v).sort(), ['collar', 'ear-left', 'ear-right', 'eyes', 'head', 'mouth', 'tail', 'torso']);
  assert.deepEqual(v.eyes, ['open']);
  assert.deepEqual(v.mouth, ['closed']);
  h.api.setEmotion('love');
  v = visible(h);
  assert.deepEqual(v.eyes, ['in-love']);
  assert.deepEqual(v.mouth, ['in-love']);
  h.api.setEmotion('angry');
  v = visible(h);
  assert.deepEqual(v.eyes, ['angry']);
  assert.deepEqual(v.mouth, ['angry']);
  for (const lista of Object.values(v)) assert.equal(lista.length, 1);
});

test('a temporary emotion returns to neutral after the timeout', async () => {
  const h = await start();
  h.api.setEmotion('surprised', { durationMs: 900 });
  assert.equal(h.api.getEmotion(), 'surprised');
  assert.deepEqual(visible(h).eyes, ['surprised']);
  h.runTimers();
  assert.equal(h.api.getEmotion(), 'neutral');
  assert.deepEqual(visible(h).eyes, ['open']);
  assert.deepEqual(visible(h).mouth, ['closed']);
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

test('speaking uses 3 mouth levels, holds for 60 ms, lights collar, and preserves active expression', async () => {
  const h = await start();
  assert.deepEqual(visible(h).collar, ['off']);
  h.api.setEmotion('curious');
  h.api.setState('speaking');
  assert.deepEqual(visible(h).collar, ['lit']);

  h.api.setAudioLevel(0.8);
  h.tick(100);
  assert.deepEqual(visible(h).mouth, ['talk-open']);
  assert.deepEqual(visible(h).eyes, ['curious']);

  // Rapid drop within 60 ms holds talk-open against flicker
  h.api.setAudioLevel(0.45);
  h.tick(130);
  assert.deepEqual(visible(h).mouth, ['talk-open']);

  // After >= 60 ms hold, switches to talk-mid and then closed
  h.tick(170);
  assert.deepEqual(visible(h).mouth, ['talk-mid']);
  h.api.setAudioLevel(0.05);
  h.tick(240);
  assert.deepEqual(visible(h).mouth, ['closed']);

  h.api.setState('idle');
  assert.deepEqual(visible(h).collar, ['off']);
});

test('blink covers all open-eyed expressions and leaves closed/special expressions unblinked', () => {
  const { api } = makeHarness();
  for (const emotion of ['neutral', 'curious', 'skeptical', 'surprised', 'sad', 'angry']) {
    const r = api.resolveLayers(table, { emotion, state: 'idle', blinking: true, audioLevel: 0 });
    assert.equal(r.layers.eyes, 'closed', emotion);
  }
  for (const [emotion, expectedEyes] of [
    ['happy', 'happy'],
    ['wink', 'winking'],
    ['love', 'in-love'],
    ['sleepy', 'sleepy'],
    ['dizzy', 'dizzy'],
  ]) {
    const r = api.resolveLayers(table, { emotion, state: 'idle', blinking: true, audioLevel: 0 });
    assert.equal(r.layers.eyes, expectedEyes, emotion);
  }
});

test('full-body dance Trick swaps bust for dance-1 and dance-2 and returns at the end', async () => {
  const h = await start();
  const root = h.container.children[0];
  assert.equal(h.api.playTrick('dance'), true);
  assert.ok(root.classes.has('lupin-full-body'));
  assert.ok(h.api.isTrickPlaying());
  const stage = root.children[0];
  const body = stage.children.find((c) => c.className === 'lupin-body');
  assert.equal(body.hidden, false);
  assert.match(body.getAttribute('src'), /body\/dance-1\.svg$/);
  // Advance to the first 420 ms frame swap timer
  const firstSwap = [...h.timers.values()][0];
  firstSwap.cb();
  assert.match(body.getAttribute('src'), /body\/dance-2\.svg$/);
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

test('2D motion animates breathing, sway, squash on expression change, ears, tail, and eyes-only gaze', async () => {
  const h = await start();
  const root = h.container.children[0];
  const breath = findByClass(root, 'lupin-breath');
  const headGroup = findByClass(root, 'lupin-head-group');
  const earL = findByClass(root, 'lupin-layer-ear-left');
  const tail = findByClass(root, 'lupin-layer-tail');
  const eyes = findByClass(root, 'lupin-layer-eyes');
  const mouth = findByClass(root, 'lupin-layer-mouth');

  h.api.lookAt(1, -1);
  h.tick(875);
  assert.match(breath.style.transform, /^scale\(/);
  assert.match(headGroup.style.transform, /^rotate\(/);
  assert.doesNotMatch(headGroup.style.transform, /scale\(/);
  assert.match(earL.style.transform, /^rotate\(/);
  assert.match(tail.style.transform, /^rotate\(/);
  assert.match(eyes.style.transform, /^translate\(/);
  assert.equal(mouth.style.transform, undefined);

  // Blinking must NOT trigger squash on headGroup
  h.setNow(900);
  h.api.blink();
  h.tick(950);
  assert.doesNotMatch(headGroup.style.transform, /scale\(/);

  // Changing Expression triggers squash during the 220 ms window and settles after
  h.setNow(1000);
  h.api.setEmotion('angry');
  h.tick(1060);
  assert.match(headGroup.style.transform, /scale\(/);
  h.tick(1280);
  assert.doesNotMatch(headGroup.style.transform, /scale\(/);
  // Angry ear droop moves ear-left toward negative rotation
  assert.match(earL.style.transform, /^rotate\(-/);
});

test('reduced motion settles the face, stops all continuous motion, and skips body choreography', async () => {
  const h = await start({ reducedMotion: true });
  const root = h.container.children[0];
  const breath = findByClass(root, 'lupin-breath');
  const headGroup = findByClass(root, 'lupin-head-group');
  const tail = findByClass(root, 'lupin-layer-tail');
  const eyes = findByClass(root, 'lupin-layer-eyes');

  h.api.blink();
  assert.deepEqual(visible(h).eyes, ['open']);
  h.api.lookAt(1, 1);
  h.api.setEmotion('curious');
  h.tick(500);
  assert.equal(breath.style.transform || '', '');
  assert.equal(tail.style.transform || '', '');
  assert.equal(eyes.style.transform || '', '');
  assert.equal(headGroup.style.transform, 'rotate(7.00deg)');

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
