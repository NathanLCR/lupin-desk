const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

const PanelRegistry = require(path.join(__dirname, '../../static/panel/registry.js'));

// Minimal DOM: enough for PanelRegistry.mount (children, text, class, sizes).
class FakeElement {
  constructor(tag, doc) {
    this.tagName = tag;
    this.ownerDocument = doc;
    this.children = [];
    this.className = '';
    this.ownText = '';
    this.clientWidth = 0;
    this.clientHeight = 0;
  }

  get textContent() {
    return this.ownText + this.children.map((child) => child.textContent).join('');
  }

  set textContent(value) {
    this.children = [];
    this.ownText = String(value);
  }

  appendChild(child) {
    this.children.push(child);
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

function tile(width = 320, height = 240) {
  const el = fakeDocument().createElement('div');
  el.clientWidth = width;
  el.clientHeight = height;
  return el;
}

function registryWith(...defs) {
  const registry = PanelRegistry.create();
  defs.forEach((def) => registry.register(def));
  return registry;
}

test('register fills in default sizes, topics and actions', () => {
  const registry = registryWith({ id: 'note', title: 'Note', render() {} });
  const def = registry.get('note');
  assert.deepEqual(def.sizes.min, { w: 1, h: 1 });
  assert.deepEqual(def.sizes.max, { w: 12, h: 12 });
  assert.deepEqual(def.sizes.default, { w: 2, h: 2 });
  assert.deepEqual(def.topics, []);
  assert.deepEqual(def.actions, []);
});

test('register keeps declared sizes, topics and actions', () => {
  const registry = registryWith({
    id: 'weather.now',
    title: 'Weather',
    sizes: { min: { w: 2, h: 1 }, max: { w: 6, h: 3 }, default: { w: 4, h: 2 } },
    topics: ['weather'],
    actions: ['weather.refresh'],
    render() {}
  });
  const def = registry.get('weather.now');
  assert.deepEqual(def.sizes.default, { w: 4, h: 2 });
  assert.deepEqual(def.topics, ['weather']);
  assert.deepEqual(def.actions, ['weather.refresh']);
});

test('register rejects invalid ids, missing titles and missing render functions', () => {
  const registry = PanelRegistry.create();
  assert.throws(() => registry.register({ id: 'Bad Id', title: 'x', render() {} }));
  assert.throws(() => registry.register({ id: '1clock', title: 'x', render() {} }));
  assert.throws(() => registry.register({ id: 'clock', render() {} }));
  assert.throws(() => registry.register({ id: 'clock', title: 'Clock' }));
  assert.throws(() => registry.register(null));
  assert.equal(registry.get('clock'), null);
});

test('register rejects a duplicate id', () => {
  const registry = registryWith({ id: 'clock', title: 'Clock', render() {} });
  assert.throws(() => registry.register({ id: 'clock', title: 'Other', render() {} }), /already registered/);
});

test('list returns definitions sorted by title, then id', () => {
  const registry = registryWith(
    { id: 'zeta', title: 'Clock', render() {} },
    { id: 'alpha', title: 'Clock', render() {} },
    { id: 'mid', title: 'Board', render() {} }
  );
  assert.deepEqual(registry.list().map((def) => def.id), ['mid', 'alpha', 'zeta']);
});

test('get returns null for unknown ids, including prototype names', () => {
  const registry = PanelRegistry.create();
  assert.equal(registry.get('missing'), null);
  assert.equal(registry.get('constructor'), null);
});

test('topicsFor returns the sorted unique topics of the widgets, ignoring unknown types', () => {
  const registry = registryWith(
    { id: 'a', title: 'A', topics: ['weather', 'layout'], render() {} },
    { id: 'b', title: 'B', topics: ['layout', 'clock.tick'], render() {} }
  );
  const topics = registry.topicsFor([
    { id: 'w1', type: 'a' },
    { id: 'w2', type: 'b' },
    { id: 'w3', type: 'unknown' }
  ]);
  assert.deepEqual(topics, ['clock.tick', 'layout', 'weather']);
  assert.deepEqual(registry.topicsFor([]), []);
});

test('PanelRegistry.shared is a registry', () => {
  assert.equal(typeof PanelRegistry.shared.register, 'function');
  assert.equal(typeof PanelRegistry.shared.get, 'function');
});

test('mount clears the tile and calls render with the context', () => {
  const registry = registryWith({
    id: 'clock',
    title: 'Clock',
    render(el) {
      el.appendChild(el.ownerDocument.createElement('span'));
    }
  });
  const el = tile(300, 200);
  el.appendChild(el.ownerDocument.createElement('p'));
  const widget = { id: 'w1', type: 'clock', x: 0, y: 0, w: 4, h: 2, config: { format: '24h' } };

  const handle = PanelRegistry.mount(registry, el, widget, {});

  assert.equal(handle.failed, false);
  assert.equal(handle.error, null);
  assert.equal(handle.widget, widget);
  assert.equal(el.children.length, 1);
  assert.equal(el.children[0].tagName, 'span');
});

test('mount passes the widget, config, size, sendAction and element to render', () => {
  let received = null;
  const registry = registryWith({
    id: 'clock',
    title: 'Clock',
    render(el, ctx) {
      received = { el, ctx };
    }
  });
  const el = tile(300, 200);
  const sendAction = () => {};
  const widget = { id: 'w1', type: 'clock', x: 0, y: 0, w: 4, h: 2, config: { format: '24h' } };

  PanelRegistry.mount(registry, el, widget, { sendAction });

  assert.equal(received.el, el);
  assert.equal(received.ctx.widget, widget);
  assert.deepEqual(received.ctx.config, { format: '24h' });
  assert.deepEqual(received.ctx.size, { width: 300, height: 200 });
  assert.equal(received.ctx.sendAction, sendAction);
  assert.equal(received.ctx.el, el);
});

test('mount gives an empty config when the widget has none', () => {
  let config = null;
  const registry = registryWith({ id: 'clock', title: 'Clock', render(el, ctx) { config = ctx.config; } });
  PanelRegistry.mount(registry, tile(), { id: 'w1', type: 'clock', x: 0, y: 0, w: 1, h: 1 }, {});
  assert.deepEqual(config, {});
});

test('a render that throws becomes an error tile instead of rethrowing', () => {
  const registry = registryWith({
    id: 'weather.now',
    title: 'Weather',
    render() {
      throw new Error('no forecast yet');
    }
  });
  const el = tile();
  let handle = null;
  assert.doesNotThrow(() => {
    handle = PanelRegistry.mount(registry, el, { id: 'w1', type: 'weather.now', x: 0, y: 0, w: 4, h: 2 }, {});
  });

  assert.equal(handle.failed, true);
  assert.equal(handle.error, 'no forecast yet');
  assert.equal(el.children.length, 1);
  const box = el.children[0];
  assert.equal(box.tagName, 'div');
  assert.equal(box.className, 'pn-error');
  assert.equal(box.children[0].tagName, 'strong');
  assert.equal(box.children[0].textContent, 'Weather');
  assert.equal(box.children[1].tagName, 'span');
  assert.equal(box.children[1].textContent, 'no forecast yet');
});

test('an unknown widget type becomes an error tile named after the type', () => {
  const registry = PanelRegistry.create();
  const el = tile();
  const handle = PanelRegistry.mount(registry, el, { id: 'w1', type: 'ghost', x: 0, y: 0, w: 1, h: 1 }, {});

  assert.equal(handle.failed, true);
  assert.match(handle.error, /ghost/);
  assert.equal(el.children[0].className, 'pn-error');
  assert.equal(el.children[0].children[0].textContent, 'ghost');
});

test('an error message is kept as text, never parsed as markup', () => {
  const registry = registryWith({
    id: 'bad',
    title: 'Bad',
    render() {
      throw new Error('<img src=x onerror=alert(1)>');
    }
  });
  const el = tile();
  PanelRegistry.mount(registry, el, { id: 'w1', type: 'bad', x: 0, y: 0, w: 1, h: 1 }, {});
  assert.equal(el.children[0].children[1].textContent, '<img src=x onerror=alert(1)>');
  assert.equal(el.children[0].children[1].children.length, 0);
});

test('onTopic is forwarded only for topics the widget declared', () => {
  const calls = [];
  const registry = registryWith({
    id: 'weather.now',
    title: 'Weather',
    topics: ['weather'],
    render() {
      return { onTopic: (topic, data) => calls.push([topic, data]) };
    }
  });
  const handle = PanelRegistry.mount(registry, tile(), { id: 'w1', type: 'weather.now', x: 0, y: 0, w: 4, h: 2 }, {});

  handle.onTopic('other', { ignored: true });
  handle.onTopic('weather', { temp: 21 });

  assert.deepEqual(calls, [['weather', { temp: 21 }]]);
});

test('an onTopic that throws becomes an error tile and later calls do nothing', () => {
  let calls = 0;
  const registry = registryWith({
    id: 'weather.now',
    title: 'Weather',
    topics: ['weather'],
    render() {
      return {
        onTopic() {
          calls += 1;
          throw new Error('bad payload');
        }
      };
    }
  });
  const el = tile();
  const handle = PanelRegistry.mount(registry, el, { id: 'w1', type: 'weather.now', x: 0, y: 0, w: 4, h: 2 }, {});

  assert.doesNotThrow(() => handle.onTopic('weather', {}));
  assert.equal(handle.failed, true);
  assert.equal(handle.error, 'bad payload');
  assert.equal(el.children[0].className, 'pn-error');
  assert.equal(el.children[0].children[0].textContent, 'Weather');

  assert.doesNotThrow(() => handle.onTopic('weather', {}));
  assert.equal(calls, 1);
});

test('a resize that throws becomes an error tile', () => {
  const registry = registryWith({
    id: 'clock',
    title: 'Clock',
    render() {
      return { onResize() { throw new Error('no room'); } };
    }
  });
  const el = tile();
  const handle = PanelRegistry.mount(registry, el, { id: 'w1', type: 'clock', x: 0, y: 0, w: 4, h: 2 }, {});
  el.clientWidth = 50;
  assert.doesNotThrow(() => handle.resize());
  assert.equal(handle.failed, true);
  assert.equal(handle.error, 'no room');
});

test('resize forwards the current tile size to onResize', () => {
  let size = null;
  const registry = registryWith({
    id: 'clock',
    title: 'Clock',
    render() {
      return { onResize(next) { size = next; } };
    }
  });
  const el = tile(300, 200);
  const handle = PanelRegistry.mount(registry, el, { id: 'w1', type: 'clock', x: 0, y: 0, w: 4, h: 2 }, {});
  el.clientWidth = 120;
  el.clientHeight = 80;
  handle.resize();
  assert.deepEqual(size, { width: 120, height: 80 });
});

test('destroy calls instance.destroy once', () => {
  let destroyed = 0;
  const registry = registryWith({
    id: 'clock',
    title: 'Clock',
    render() {
      return { destroy() { destroyed += 1; } };
    }
  });
  const handle = PanelRegistry.mount(registry, tile(), { id: 'w1', type: 'clock', x: 0, y: 0, w: 4, h: 2 }, {});
  handle.destroy();
  handle.destroy();
  assert.equal(destroyed, 1);
});

test('destroy swallows errors thrown by instance.destroy', () => {
  const registry = registryWith({
    id: 'clock',
    title: 'Clock',
    render() {
      return { destroy() { throw new Error('timer already gone'); } };
    }
  });
  const handle = PanelRegistry.mount(registry, tile(), { id: 'w1', type: 'clock', x: 0, y: 0, w: 4, h: 2 }, {});
  assert.doesNotThrow(() => handle.destroy());
  assert.equal(handle.failed, false);
});

test('destroy on a failed handle does nothing', () => {
  let destroyed = 0;
  const registry = registryWith({
    id: 'clock',
    title: 'Clock',
    topics: ['tick'],
    render() {
      return {
        onTopic() { throw new Error('boom'); },
        destroy() { destroyed += 1; }
      };
    }
  });
  const handle = PanelRegistry.mount(registry, tile(), { id: 'w1', type: 'clock', x: 0, y: 0, w: 4, h: 2 }, {});
  handle.onTopic('tick', {});
  assert.equal(handle.failed, true);
  assert.doesNotThrow(() => handle.destroy());
  assert.equal(destroyed, 0);
});

test('a render that returns nothing still mounts with no-op hooks', () => {
  const registry = registryWith({ id: 'note', title: 'Note', render() {} });
  const handle = PanelRegistry.mount(registry, tile(), { id: 'w1', type: 'note', x: 0, y: 0, w: 2, h: 2 }, {});
  assert.equal(handle.failed, false);
  assert.doesNotThrow(() => {
    handle.onTopic('anything', {});
    handle.resize();
    handle.destroy();
  });
});
