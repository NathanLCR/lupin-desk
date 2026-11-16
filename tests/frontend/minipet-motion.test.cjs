const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const sourcePath = path.join(__dirname, '../../static/face.js');
const source = fs.readFileSync(sourcePath, 'utf8');

class FakeElement {
  constructor() {
    this.attributes = new Map();
    this.style = {};
    this.dataset = {};
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
  }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
}

function makeHarness({ reducedMotion = false } = {}) {
  const ids = [
    '#emo-face-svg', '#lupin-full-rig', '#lupin-tail-group', '#lupin-body-group',
    '#lupin-leg-fl', '#lupin-leg-fr', '#lupin-leg-bl', '#lupin-leg-br',
    '#emo-face-head', '#emo-voice-wave',
    '[data-eye-look="left"]', '[data-eye-motion="left"]', '[data-eye-shape="left"]',
    '[data-clip-rect="left"]', '[data-eye-highlights="left"]', '[data-lid-upper="left"]',
    '[data-lid-lower="left"]', '[data-heart-group="left"]', '[data-error-x="left"]',
    '[data-dizzy-group="left"]', '[data-eye-look="right"]', '[data-eye-motion="right"]',
    '[data-eye-shape="right"]', '[data-clip-rect="right"]', '[data-eye-highlights="right"]',
    '[data-lid-upper="right"]', '[data-lid-lower="right"]', '[data-heart-group="right"]',
    '[data-error-x="right"]', '[data-dizzy-group="right"]',
  ];
  const nodes = new Map(ids.map((id) => [id, new FakeElement()]));
  const drawCalls = [];
  const canvasContext = {
    setTransform() {},
    clearRect() {},
    createRadialGradient() { return { addColorStop() {} }; },
    fillRect() { drawCalls.push('fillRect'); },
    stroke() { drawCalls.push('stroke'); },
    fill() { drawCalls.push('fill'); },
    beginPath() {},
    moveTo() {},
    lineTo() {},
    arc() {},
    save() {},
    restore() {},
    translate() {},
    bezierCurveTo() {},
    fillText() {},
  };
  const canvas = new FakeElement();
  canvas.getContext = () => canvasContext;
  nodes.set('.emo-particles-canvas', canvas);
  const voiceBars = Array.from({ length: 9 }, () => new FakeElement());
  const root = new FakeElement();
  root.clientWidth = 420;
  root.clientHeight = 300;
  root.querySelector = (selector) => nodes.get(selector) || null;
  root.querySelectorAll = (selector) => selector === '.emo-voice-bar' ? voiceBars : [];
  const container = {
    innerHTML: '',
    querySelector: (selector) => selector === '.emo-face-root' ? root : null,
  };
  const body = new FakeElement();
  body.classList.add('is-minipet');
  const document = { body };
  const rafs = new Map();
  const timers = new Map();
  let nextRaf = 0;
  let nextTimer = 0;
  let now = 0;
  const activeMotionListeners = new Set();
  const motionQuery = {
    matches: reducedMotion,
    adds: 0,
    removes: 0,
    addEventListener(type, callback) {
      assert.equal(type, 'change');
      this.adds += 1;
      activeMotionListeners.add(callback);
    },
    removeEventListener(type, callback) {
      assert.equal(type, 'change');
      this.removes += 1;
      activeMotionListeners.delete(callback);
    },
    change(matches) {
      this.matches = matches;
      for (const callback of [...activeMotionListeners]) callback({ matches });
    },
  };
  const window = {
    matchMedia: () => motionQuery,
    requestAnimationFrame(callback) {
      const id = ++nextRaf;
      rafs.set(id, callback);
      return id;
    },
    cancelAnimationFrame(id) { rafs.delete(id); },
    EmoAudio: null,
  };
  const context = {
    window,
    document,
    performance: { now: () => now },
    Math,
    Date,
    console,
    setTimeout(callback, delay) {
      const id = ++nextTimer;
      timers.set(id, { callback, delay });
      return id;
    },
    clearTimeout(id) { timers.delete(id); },
  };
  vm.runInNewContext(source, context, { filename: sourcePath });

  return {
    api: window.EmoFace,
    canvasContext,
    container,
    drawCalls,
    motionQuery,
    nodes,
    root,
    setNow(value) { now = value; },
    tick(timestamp) {
      now = timestamp;
      const frame = rafs.entries().next().value;
      assert.ok(frame, 'a face animation frame should be scheduled');
      rafs.delete(frame[0]);
      frame[1](timestamp);
    },
    timers,
    get activeMotionListenerCount() { return activeMotionListeners.size; },
  };
}

test('mantém caminhada, passada e cauda quando o sistema permite movimento', () => {
  const harness = makeHarness();
  harness.api.init(harness.container);
  harness.tick(8000);
  harness.tick(16000);
  harness.tick(16016);

  assert.match(harness.nodes.get('#lupin-full-rig').getAttribute('transform'), /translate\((?!0\.00 0\.00)/);
  assert.notEqual(harness.nodes.get('#lupin-leg-fl').getAttribute('transform'), 'rotate(0 356 490)');
  assert.notEqual(harness.nodes.get('#lupin-tail-group').getAttribute('transform'), 'translate(514, 520) rotate(0 0 24)');
});

test('mudança ao vivo para movimento reduzido assenta o corpo e preserva expressão e piscada', () => {
  const harness = makeHarness();
  harness.api.init(harness.container);
  harness.tick(8000);
  harness.tick(16000);
  assert.match(harness.nodes.get('#lupin-full-rig').getAttribute('transform'), /translate\((?!0\.00 0\.00)/);

  harness.api.playAnimation('laugh');
  harness.motionQuery.change(true);
  assert.equal(harness.nodes.get('#lupin-full-rig').getAttribute('transform'), 'translate(0 0)');
  assert.equal(harness.nodes.get('#lupin-tail-group').getAttribute('transform'), 'translate(514, 520) rotate(0 0 24)');
  assert.equal(harness.nodes.get('#lupin-leg-fl').getAttribute('transform'), 'rotate(0 356 490)');

  harness.api.setEmotion('dizzy');
  harness.api.setState('thinking');
  harness.api.setWeather('rain');
  assert.equal(harness.api.getEmotion(), 'dizzy');
  assert.equal(harness.api.getState(), 'thinking');
  harness.tick(32000);
  assert.equal(harness.root.dataset.emotion, 'dizzy');
  assert.ok(Number(harness.nodes.get('[data-dizzy-group="left"]').style.opacity) > 0);
  assert.match(harness.nodes.get('#emo-face-head').getAttribute('transform'), /^translate\(0\.00 0\.00\)/);

  assert.equal(harness.api.playTrick('dance'), true);
  assert.equal(harness.api.getEmotion(), 'excited');
  harness.tick(32016);
  assert.equal(harness.nodes.get('#lupin-full-rig').getAttribute('transform'), 'translate(0.00 0.00)');
  assert.match(harness.nodes.get('#emo-face-head').getAttribute('transform'), /^translate\(0\.00 0\.00\)/);
  assert.ok(harness.drawCalls.length === 0, 'clima e partículas decorativas ficam parados');
  assert.equal(harness.api.playAnimation('yawn'), true);
  harness.setNow(32016);
  const lidBeforeBlink = harness.nodes.get('[data-lid-upper="left"]').getAttribute('d');
  harness.api.blink();
  harness.tick(32032);
  assert.notEqual(harness.nodes.get('[data-lid-upper="left"]').getAttribute('d'), lidBeforeBlink);
});

test('reinit remove o listener anterior e registra apenas um listener de preferência', () => {
  const harness = makeHarness();
  harness.api.init(harness.container);
  assert.equal(harness.activeMotionListenerCount, 1);

  harness.api.init(harness.container);
  assert.equal(harness.motionQuery.removes, 1);
  assert.equal(harness.activeMotionListenerCount, 1);
  harness.motionQuery.change(true);
  assert.equal(harness.nodes.get('#lupin-full-rig').getAttribute('transform'), 'translate(0 0)');
  assert.equal(harness.motionQuery.adds, 2);
});
