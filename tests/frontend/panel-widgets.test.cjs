const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const sourcePath = path.join(__dirname, '../../static/panel/widgets.js');
const PanelWidgets = require(sourcePath);

// Minimal DOM: enough for createElement, appendChild, textContent, style and size.
class FakeElement {
  constructor(tagName, doc) {
    this.tagName = tagName.toUpperCase();
    this.ownerDocument = doc;
    this.children = [];
    this.style = {};
    this.className = '';
    this.clientWidth = 0;
    this.clientHeight = 0;
    this.textValue = '';
  }

  get textContent() {
    return this.textValue;
  }

  set textContent(value) {
    this.textValue = String(value);
  }

  appendChild(child) {
    this.children.push(child);
    child.parentNode = this;
    return child;
  }
}

function fakeDocument() {
  const doc = {
    createElement(tag) {
      return new FakeElement(tag, doc);
    }
  };
  return doc;
}

function findByClass(node, className) {
  if (node.className === className) return node;
  for (const child of node.children) {
    const found = findByClass(child, className);
    if (found) return found;
  }
  return null;
}

function fakeHost(width, height) {
  const el = new FakeElement('div', fakeDocument());
  el.clientWidth = width || 0;
  el.clientHeight = height || 0;
  return el;
}

function fakeRegistry() {
  return {
    defs: [],
    register(def) {
      this.defs.push(def);
    }
  };
}

// Fake timers and a controllable clock, installed for the duration of one test.
function withFakeClock(startDate, fn) {
  const RealDate = Date;
  const realSetInterval = global.setInterval;
  const realClearInterval = global.clearInterval;
  let fakeNow = startDate.getTime();
  const timers = [];
  let nextId = 1;

  function FakeDate(...args) {
    if (args.length === 0) return new RealDate(fakeNow);
    return new RealDate(...args);
  }
  FakeDate.now = () => fakeNow;
  FakeDate.prototype = RealDate.prototype;

  global.Date = FakeDate;
  global.setInterval = (fn, ms) => {
    const timer = { id: nextId++, fn, ms, active: true };
    timers.push(timer);
    return timer.id;
  };
  global.clearInterval = (id) => {
    const timer = timers.find((t) => t.id === id);
    if (timer) timer.active = false;
  };

  const clock = {
    timers,
    activeCount: () => timers.filter((t) => t.active).length,
    advanceTo(date) {
      fakeNow = date.getTime();
    },
    tick() {
      timers.filter((t) => t.active).forEach((t) => t.fn());
    }
  };

  try {
    return fn(clock);
  } finally {
    global.Date = RealDate;
    global.setInterval = realSetInterval;
    global.clearInterval = realClearInterval;
  }
}

test('formatTime zero pads hours and minutes on a 24h clock', () => {
  assert.equal(PanelWidgets.formatTime(new Date(2026, 10, 18, 9, 5)), '09:05');
  assert.equal(PanelWidgets.formatTime(new Date(2026, 0, 1, 0, 0)), '00:00');
  assert.equal(PanelWidgets.formatTime(new Date(2026, 0, 1, 23, 59)), '23:59');
  assert.equal(PanelWidgets.formatTime(new Date(2026, 5, 2, 13, 7)), '13:07');
});

test('formatDate gives short weekday, day without padding, short month', () => {
  assert.equal(PanelWidgets.formatDate(new Date(2026, 10, 18)), 'Wed 18 Nov');
  assert.equal(PanelWidgets.formatDate(new Date(2026, 0, 5)), 'Mon 5 Jan');
  assert.equal(PanelWidgets.formatDate(new Date(2026, 11, 31)), 'Thu 31 Dec');
});

test('registerBuiltins registers clock and placeholder through register(def)', () => {
  const registry = fakeRegistry();
  PanelWidgets.registerBuiltins(registry);

  const ids = registry.defs.map((d) => d.id).sort();
  assert.deepEqual(ids, ['clock', 'placeholder']);

  const clock = registry.defs.find((d) => d.id === 'clock');
  assert.equal(clock.title, 'Clock');
  assert.deepEqual(clock.sizes.default, { w: 4, h: 2 });
  assert.deepEqual(clock.sizes.min, { w: 2, h: 1 });
  assert.deepEqual(clock.sizes.max, { w: 12, h: 6 });
  assert.equal(typeof clock.render, 'function');

  const placeholder = registry.defs.find((d) => d.id === 'placeholder');
  assert.equal(placeholder.title, 'Placeholder');
  assert.deepEqual(placeholder.sizes.default, { w: 4, h: 2 });
});

test('registerBuiltins skips types already in a registry that has get()', () => {
  const registry = fakeRegistry();
  registry.get = (id) => registry.defs.find((d) => d.id === id) || null;
  PanelWidgets.registerBuiltins(registry);
  PanelWidgets.registerBuiltins(registry);
  assert.equal(registry.defs.length, 2);
});

test('clock shows HH:MM and the date, then ticks every second', () => {
  const registry = fakeRegistry();
  PanelWidgets.registerBuiltins(registry);
  const clockDef = registry.defs.find((d) => d.id === 'clock');

  withFakeClock(new Date(2026, 10, 18, 9, 5), (clock) => {
    const el = fakeHost(400, 200);
    const instance = clockDef.render(el, { config: {}, size: { width: 400, height: 200 } });

    const time = findByClass(el, 'pn-clock-time');
    const date = findByClass(el, 'pn-clock-date');
    assert.equal(time.textContent, '09:05');
    assert.equal(date.textContent, 'Wed 18 Nov');

    assert.equal(clock.activeCount(), 1);
    assert.equal(clock.timers[0].ms, 1000);

    clock.advanceTo(new Date(2026, 10, 18, 9, 6));
    clock.tick();
    assert.equal(time.textContent, '09:06');

    clock.advanceTo(new Date(2026, 10, 19, 0, 0));
    clock.tick();
    assert.equal(time.textContent, '00:00');
    assert.equal(date.textContent, 'Thu 19 Nov');

    instance.destroy();
    assert.equal(clock.activeCount(), 0, 'destroy clears the timer');

    clock.advanceTo(new Date(2026, 10, 19, 0, 1));
    clock.tick();
    assert.equal(time.textContent, '00:00', 'no updates after destroy');

    instance.destroy();
    assert.equal(clock.activeCount(), 0, 'second destroy is harmless');
  });
});

test('clock font size follows the tile size and onResize rescales', () => {
  const registry = fakeRegistry();
  PanelWidgets.registerBuiltins(registry);
  const clockDef = registry.defs.find((d) => d.id === 'clock');

  withFakeClock(new Date(2026, 10, 18, 9, 5), () => {
    const el = fakeHost(400, 200);
    const instance = clockDef.render(el, { config: {}, size: { width: 400, height: 200 } });
    const time = findByClass(el, 'pn-clock-time');
    const large = parseFloat(time.style.fontSize);
    assert.ok(large > 0);

    instance.onResize({ width: 200, height: 100 });
    const small = parseFloat(time.style.fontSize);
    assert.ok(small > 0 && small < large, `expected ${small} < ${large}`);
    instance.destroy();
  });
});

test('clock renders with a zero-size tile without throwing', () => {
  const registry = fakeRegistry();
  PanelWidgets.registerBuiltins(registry);
  const clockDef = registry.defs.find((d) => d.id === 'clock');

  withFakeClock(new Date(2026, 10, 18, 9, 5), () => {
    const el = fakeHost(0, 0);
    const instance = clockDef.render(el, { config: {}, size: { width: 0, height: 0 } });
    assert.equal(findByClass(el, 'pn-clock-time').textContent, '09:05');
    instance.destroy();
  });
});

test('placeholder shows config.text or the default message', () => {
  const registry = fakeRegistry();
  PanelWidgets.registerBuiltins(registry);
  const placeholder = registry.defs.find((d) => d.id === 'placeholder');

  const bare = fakeHost(100, 100);
  const instanceBare = placeholder.render(bare, { config: {} });
  assert.equal(findByClass(bare, 'pn-placeholder').textContent, 'Widget coming soon');
  assert.ok(instanceBare === null || instanceBare === undefined, 'placeholder has no instance');

  const custom = fakeHost(100, 100);
  placeholder.render(custom, { config: { text: 'Soon: calendar' } });
  assert.equal(findByClass(custom, 'pn-placeholder').textContent, 'Soon: calendar');

  const missingConfig = fakeHost(100, 100);
  placeholder.render(missingConfig, { config: { text: '' } });
  assert.equal(findByClass(missingConfig, 'pn-placeholder').textContent, 'Widget coming soon');
});

test('widgets.js stays ES5 (no arrow functions, let/const, classes or template literals)', () => {
  const source = fs.readFileSync(sourcePath, 'utf8');
  const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
  assert.equal(/=>/.test(code), false, 'arrow function');
  assert.equal(/\b(let|const)\s+[A-Za-z_$]/.test(code), false, 'let/const');
  assert.equal(/\bclass\s+[A-Za-z_$]/.test(code), false, 'class');
  assert.equal(/`/.test(code), false, 'template literal');
  assert.equal(/\.(includes|startsWith|endsWith|find|findIndex)\(/.test(code), false, 'ES2015 string/array method');
});
