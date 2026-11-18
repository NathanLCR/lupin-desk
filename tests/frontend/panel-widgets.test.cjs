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

// ---- Clock upgrade: zones, seconds, analog face, pure helpers ----

FakeElement.prototype.setAttribute = function (name, value) {
  if (!this.attrs) this.attrs = {};
  this.attrs[name] = String(value);
};

FakeElement.prototype.getAttribute = function (name) {
  return this.attrs && Object.prototype.hasOwnProperty.call(this.attrs, name)
    ? this.attrs[name]
    : null;
};

function fakeSvgDocument() {
  const doc = {
    createElement(tag) {
      return new FakeElement(tag, doc);
    },
    createElementNS(ns, tag) {
      const el = new FakeElement(tag, doc);
      el.namespaceURI = ns;
      return el;
    }
  };
  return doc;
}

function fakeSvgHost(width, height) {
  const el = new FakeElement('div', fakeSvgDocument());
  el.clientWidth = width || 0;
  el.clientHeight = height || 0;
  return el;
}

function findAll(node, pred, out = []) {
  if (pred(node)) out.push(node);
  node.children.forEach((child) => findAll(child, pred, out));
  return out;
}

function clockDef() {
  const registry = fakeRegistry();
  PanelWidgets.registerBuiltins(registry);
  return registry.defs.find((d) => d.id === 'clock');
}

function closeTo(actual, expected) {
  assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} is not ${expected}`);
}

test('clock keeps its id, empty topics and actions, and sizes', () => {
  const clock = clockDef();
  assert.equal(clock.id, 'clock');
  assert.deepEqual(clock.topics, []);
  assert.deepEqual(clock.actions, []);
  assert.deepEqual(clock.sizes.default, { w: 4, h: 2 });
  assert.deepEqual(clock.sizes.min, { w: 2, h: 1 });
  assert.deepEqual(clock.sizes.max, { w: 12, h: 6 });
});

test('zoneTime formats HH:MM in the given IANA zone', () => {
  const instant = new Date(Date.UTC(2026, 10, 18, 12, 5));
  assert.equal(PanelWidgets.zoneTime(instant, 'UTC'), '12:05');
  assert.equal(PanelWidgets.zoneTime(instant, 'Asia/Tokyo'), '21:05');
  assert.equal(PanelWidgets.zoneTime(instant, 'America/New_York'), '07:05');
  assert.equal(PanelWidgets.zoneTime(new Date(Date.UTC(2026, 10, 18, 0, 0)), 'UTC'), '00:00',
    'midnight is 00:00, not 24:00');
});

test('zoneTime gives --:-- for a bad zone or when the engine throws', () => {
  const instant = new Date(Date.UTC(2026, 10, 18, 12, 5));
  assert.equal(PanelWidgets.zoneTime(instant, 'Mars/Olympus_Mons'), '--:--');

  const original = Date.prototype.toLocaleTimeString;
  Date.prototype.toLocaleTimeString = function () {
    throw new RangeError('old engine');
  };
  try {
    assert.equal(PanelWidgets.zoneTime(instant, 'UTC'), '--:--');
  } finally {
    Date.prototype.toLocaleTimeString = original;
  }
});

test('analogAngles maps time to hour, minute and second degrees', () => {
  const a = PanelWidgets.analogAngles(new Date(2026, 10, 18, 3, 30, 15));
  closeTo(a.hour, 105);
  closeTo(a.minute, 181.5);
  closeTo(a.second, 90);

  assert.deepEqual(PanelWidgets.analogAngles(new Date(2026, 10, 18, 0, 0, 0)),
    { hour: 0, minute: 0, second: 0 });

  const c = PanelWidgets.analogAngles(new Date(2026, 10, 18, 12, 59, 59));
  closeTo(c.hour, 29.5);
  closeTo(c.minute, 359.9);
  closeTo(c.second, 354);
});

test('normalizeZones keeps up to 4 valid {label, tz} entries', () => {
  assert.deepEqual(PanelWidgets.normalizeZones(undefined), []);
  assert.deepEqual(PanelWidgets.normalizeZones('NYC'), []);
  assert.deepEqual(PanelWidgets.normalizeZones([
    null,
    'Tokyo',
    { label: 5, tz: 'Asia/Tokyo' },
    { label: 'NoTz' },
    { label: 'NYC', tz: 'America/New_York', extra: 1 }
  ]), [{ label: 'NYC', tz: 'America/New_York' }]);

  const many = [];
  for (let i = 0; i < 6; i++) many.push({ label: 'Z' + i, tz: 'UTC' });
  const out = PanelWidgets.normalizeZones(many);
  assert.equal(out.length, 4);
  assert.deepEqual(out.map((z) => z.label), ['Z0', 'Z1', 'Z2', 'Z3']);
});

test('digital clock shows zone rows and HH:MM:SS when seconds is on', () => {
  const def = clockDef();
  const start = new Date(2026, 10, 18, 9, 5, 7);
  withFakeClock(start, (clock) => {
    const el = fakeHost(400, 300);
    const zones = [
      { label: 'Tokyo', tz: 'Asia/Tokyo' },
      { label: 'Nowhere', tz: 'Mars/Base' }
    ];
    const instance = def.render(el, { config: { zones, seconds: true }, size: { width: 400, height: 300 } });

    assert.equal(findByClass(el, 'pn-clock-time').textContent, '09:05:07');
    assert.equal(findByClass(el, 'pn-clock-date').textContent, 'Wed 18 Nov');
    assert.equal(findAll(el, (n) => n.className === 'pn-clock-zone').length, 2);

    const labels = findAll(el, (n) => n.className === 'pn-clock-zone-label').map((n) => n.textContent);
    assert.deepEqual(labels, ['Tokyo', 'Nowhere']);
    const values = findAll(el, (n) => n.className === 'pn-clock-zone-time').map((n) => n.textContent);
    assert.deepEqual(values, [PanelWidgets.zoneTime(start, 'Asia/Tokyo'), '--:--']);

    clock.advanceTo(new Date(2026, 10, 18, 9, 6, 0));
    clock.tick();
    assert.equal(findByClass(el, 'pn-clock-time').textContent, '09:06:00');

    instance.destroy();
    assert.equal(clock.activeCount(), 0, 'destroy clears the timer');
  });
});

test('digital clock without zones or seconds keeps the plain HH:MM face', () => {
  const def = clockDef();
  withFakeClock(new Date(2026, 10, 18, 9, 5, 7), (clock) => {
    const el = fakeHost(400, 300);
    const instance = def.render(el, { config: { style: 'digital' }, size: { width: 400, height: 300 } });
    assert.equal(findByClass(el, 'pn-clock-time').textContent, '09:05');
    assert.equal(findAll(el, (n) => n.className === 'pn-clock-zones').length, 0);
    instance.destroy();
    assert.equal(clock.activeCount(), 0);
  });
});

test('analog clock draws an SVG face with 12 ticks and three hands, updated every second', () => {
  const def = clockDef();
  const start = new Date(2026, 10, 18, 3, 30, 15);
  withFakeClock(start, (clock) => {
    const el = fakeSvgHost(400, 300);
    const instance = def.render(el, {
      config: { style: 'analog', zones: [{ label: 'UTC', tz: 'UTC' }] },
      size: { width: 400, height: 300 }
    });

    const svg = findAll(el, (n) => n.tagName === 'SVG')[0];
    assert.ok(svg, 'svg element is present');
    assert.equal(svg.namespaceURI, 'http://www.w3.org/2000/svg');
    assert.equal(svg.getAttribute('viewBox'), '0 0 100 100');
    assert.equal(svg.getAttribute('width'), '100%');
    assert.equal(svg.getAttribute('height'), '100%');

    assert.equal(findAll(svg, (n) => n.getAttribute('data-role') === 'tick').length, 12);

    const hour = findAll(svg, (n) => n.getAttribute('data-hand') === 'hour')[0];
    const minute = findAll(svg, (n) => n.getAttribute('data-hand') === 'minute')[0];
    const second = findAll(svg, (n) => n.getAttribute('data-hand') === 'second')[0];
    assert.equal(hour.getAttribute('transform'), 'rotate(105 50 50)');
    assert.equal(minute.getAttribute('transform'), 'rotate(181.5 50 50)');
    assert.equal(second.getAttribute('transform'), 'rotate(90 50 50)');

    assert.equal(findByClass(el, 'pn-clock-time'), null, 'no digital time on the analog face');
    assert.equal(findByClass(el, 'pn-clock-date').textContent, 'Wed 18 Nov');
    assert.equal(findByClass(el, 'pn-clock-zone-time').textContent, PanelWidgets.zoneTime(start, 'UTC'));

    const face = findByClass(el, 'pn-clock-face');
    assert.equal(face.style.width, '210px', 'face is min(0.9w, 0.7h) square');

    assert.equal(clock.activeCount(), 1);
    assert.equal(clock.timers[0].ms, 1000);
    clock.advanceTo(new Date(2026, 10, 18, 3, 30, 16));
    clock.tick();
    assert.equal(second.getAttribute('transform'), 'rotate(96 50 50)');

    instance.onResize({ width: 200, height: 100 });
    assert.equal(face.style.width, '70px');

    instance.destroy();
    assert.equal(clock.activeCount(), 0, 'destroy clears the analog timer');
  });
});

test('analog style falls back to the digital face without createElementNS', () => {
  const def = clockDef();
  withFakeClock(new Date(2026, 10, 18, 9, 5, 7), (clock) => {
    const el = fakeHost(400, 300);
    const instance = def.render(el, { config: { style: 'analog' }, size: { width: 400, height: 300 } });
    assert.equal(findByClass(el, 'pn-clock-time').textContent, '09:05');
    assert.equal(findAll(el, (n) => n.tagName === 'SVG').length, 0);
    instance.destroy();
    assert.equal(clock.activeCount(), 0);
  });
});
