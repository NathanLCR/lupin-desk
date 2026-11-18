const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

const EditorPreview = require(path.join(__dirname, '../../static/editor/editor-preview.js'));

// ---------------------------------------------------------------- fake DOM

class FakeEl {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.parentNode = null;
    this.style = {};
    this.className = '';
    this.clientWidth = 0;
  }

  get lastChild() {
    return this.children.length ? this.children[this.children.length - 1] : null;
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  removeChild(child) {
    const i = this.children.indexOf(child);
    if (i !== -1) this.children.splice(i, 1);
    child.parentNode = null;
    return child;
  }
}

const doc = {
  createElement(tag) {
    return new FakeEl(tag);
  },
};

// ---------------------------------------------------------------- fakes

// Records every socket, every sent message, and lets a test fire the handlers.
function makeSocketClass(sockets) {
  return class FakeWS {
    constructor(url) {
      this.url = url;
      this.sent = [];
      this.closed = false;
      this.onopen = null;
      this.onmessage = null;
      this.onclose = null;
      this.onerror = null;
      sockets.push(this);
    }

    send(text) {
      if (this.closed) throw new Error('socket closed');
      this.sent.push(JSON.parse(text));
    }

    close() {
      this.closed = true;
    }
  };
}

// Timers are queued and fired by the test; no real time passes.
function makeWin(opts = {}) {
  const sockets = [];
  const timers = [];
  let nextId = 1;
  const win = {
    document: doc,
    sockets,
    timers,
    WebSocket: makeSocketClass(sockets),
    setTimeout(fn, ms) {
      const id = nextId++;
      timers.push({ id, fn, ms });
      return id;
    },
    clearTimeout(id) {
      const i = timers.findIndex((t) => t.id === id);
      if (i !== -1) timers.splice(i, 1);
    },
    runTimers() {
      while (timers.length) timers.shift().fn();
    },
  };
  if (opts.DeskDevice) win.DeskDevice = opts.DeskDevice;
  return win;
}

// Fake PanelRegistry.mount: records calls, returns handles that log topics, resizes and destroys.
function makeRegistryFakes(opts = {}) {
  const mounts = [];
  const handles = [];
  const topicCalls = [];
  const PanelRegistry = {
    mount(registry, el, widget, env) {
      mounts.push({ registry, el, widget, env });
      if (widget.type === 'bad') throw new Error('widget exploded');
      const handle = {
        widget,
        el,
        env,
        destroyCount: 0,
        resizeCount: 0,
        topics: [],
        onTopic(topic, data) {
          this.topics.push({ topic, data });
          topicCalls.push({ id: widget.id, topic, data });
        },
        resize() {
          this.resizeCount += 1;
        },
        destroy() {
          this.destroyCount += 1;
        },
      };
      handles.push(handle);
      return handle;
    },
  };
  const registry = {
    topicsCalls: [],
    topicsFor(widgets) {
      this.topicsCalls.push(widgets.map((w) => w.id));
      return opts.topics || widgets.map((w) => `${w.type}.state`);
    },
  };
  return { PanelRegistry, registry, mounts, handles, topicCalls };
}

function makeContainer(width) {
  const el = new FakeEl('div');
  el.clientWidth = width;
  return el;
}

function findAll(el, pred, out = []) {
  if (pred(el)) out.push(el);
  for (const child of el.children) findAll(child, pred, out);
  return out;
}

// Landscape 6x12 grid (not the default 12x6), two widgets on page 'home'.
function sixByTwelveLayout() {
  return {
    id: 'main',
    name: 'Main',
    version: 1,
    grid: {
      landscape: { cols: 6, rows: 12 },
      portrait: { cols: 4, rows: 8 },
    },
    pages: [
      {
        id: 'home',
        title: 'Home',
        landscape: [
          { id: 'a', type: 'clock', x: 0, y: 0, w: 3, h: 6, config: {} },
          { id: 'b', type: 'weather', x: 3, y: 6, w: 3, h: 6, config: {} },
        ],
        portrait: [],
      },
    ],
  };
}

const SIZE = { width: 960, height: 720 };

// ---------------------------------------------------------------- tests

test('module exposes create()', () => {
  assert.equal(typeof EditorPreview.create, 'function');
});

test('show mounts one handle per widget at percent rects from the layout grid', () => {
  const win = makeWin();
  const fakes = makeRegistryFakes();
  win.PanelRegistry = fakes.PanelRegistry;
  const container = makeContainer(480);
  const preview = EditorPreview.create(container, { registry: fakes.registry, wsUrl: 'ws://x/ws', win });

  preview.show(sixByTwelveLayout(), 'home', 'landscape', SIZE);

  assert.equal(fakes.mounts.length, 2);
  const tiles = fakes.mounts.map((m) => m.el.parentNode);
  assert.deepEqual(tiles.map((t) => t.className), ['pn-tile', 'pn-tile']);
  assert.deepEqual(tiles.map((t) => t.style.left), ['0%', '50%']);
  assert.deepEqual(tiles.map((t) => t.style.top), ['0%', '50%']);
  assert.deepEqual(tiles.map((t) => t.style.width), ['50%', '50%']);
  assert.deepEqual(tiles.map((t) => t.style.height), ['50%', '50%']);
  assert.equal(fakes.mounts[0].el.className, 'pn-tile-inner');
  assert.equal(fakes.mounts[0].widget.id, 'a');
  assert.equal(fakes.mounts[1].widget.id, 'b');

  const stage = findAll(container, (el) => el.className === 'pn-stage');
  assert.equal(stage.length, 1);
  const frame = findAll(container, (el) => el.className === 'ed-pv-frame');
  assert.equal(frame.length, 1);
  assert.equal(frame[0].style.width, '960px');
  assert.equal(frame[0].style.height, '720px');
  assert.equal(frame[0].style.transform, 'scale(0.5)');
  assert.equal(frame[0].style.transformOrigin, '0 0');
});

test('show scales down to the container width and never scales up', () => {
  const win = makeWin();
  const fakes = makeRegistryFakes();
  win.PanelRegistry = fakes.PanelRegistry;
  const container = makeContainer(2000);
  const preview = EditorPreview.create(container, { registry: fakes.registry, win });

  preview.show(sixByTwelveLayout(), 'home', 'landscape', SIZE);

  const frame = findAll(container, (el) => el.className === 'ed-pv-frame')[0];
  assert.equal(frame.style.transform, 'scale(1)');
  const wrap = findAll(container, (el) => el.className === 'ed-pv')[0];
  assert.equal(wrap.style.height, '720px');
});

test('show calls resize on every mounted handle after layout', () => {
  const win = makeWin();
  const fakes = makeRegistryFakes();
  win.PanelRegistry = fakes.PanelRegistry;
  const preview = EditorPreview.create(makeContainer(960), { registry: fakes.registry, win });

  preview.show(sixByTwelveLayout(), 'home', 'landscape', SIZE);

  assert.deepEqual(fakes.handles.map((h) => h.resizeCount), [1, 1]);
});

test('re-show destroys the handles of the previous page variant', () => {
  const win = makeWin();
  const fakes = makeRegistryFakes();
  win.PanelRegistry = fakes.PanelRegistry;
  const container = makeContainer(960);
  const preview = EditorPreview.create(container, { registry: fakes.registry, win });

  preview.show(sixByTwelveLayout(), 'home', 'landscape', SIZE);
  const first = fakes.handles.slice();
  preview.show(sixByTwelveLayout(), 'home', 'landscape', SIZE);

  assert.deepEqual(first.map((h) => h.destroyCount), [1, 1]);
  assert.deepEqual(fakes.handles.slice(2).map((h) => h.destroyCount), [0, 0]);
  assert.equal(findAll(container, (el) => el.className === 'pn-tile').length, 2);
});

test('a throwing widget mount does not break the other tiles', () => {
  const win = makeWin();
  const fakes = makeRegistryFakes();
  win.PanelRegistry = fakes.PanelRegistry;
  const container = makeContainer(960);
  const preview = EditorPreview.create(container, { registry: fakes.registry, win });
  const layout = sixByTwelveLayout();
  layout.pages[0].landscape.push({ id: 'c', type: 'bad', x: 0, y: 6, w: 2, h: 2, config: {} });

  assert.doesNotThrow(() => preview.show(layout, 'home', 'landscape', SIZE));

  assert.deepEqual(fakes.mounts.map((m) => m.widget.id), ['a', 'b', 'c']);
  assert.equal(fakes.handles.length, 2);
});

test('live is off by default: show opens no socket', () => {
  const win = makeWin();
  const fakes = makeRegistryFakes();
  win.PanelRegistry = fakes.PanelRegistry;
  const preview = EditorPreview.create(makeContainer(960), { registry: fakes.registry, wsUrl: 'ws://x/ws', win });

  preview.show(sixByTwelveLayout(), 'home', 'landscape', SIZE);

  assert.equal(win.sockets.length, 0);
});

test('setLive(true) sends hello with body "editor" and omits device_id even when DeskDevice exists', () => {
  const win = makeWin({ DeskDevice: { getId: () => 'dev-42' } });
  const fakes = makeRegistryFakes();
  win.PanelRegistry = fakes.PanelRegistry;
  const preview = EditorPreview.create(makeContainer(960), { registry: fakes.registry, wsUrl: 'ws://x/ws', win });

  preview.setLive(true);
  assert.equal(win.sockets.length, 1);
  assert.equal(win.sockets[0].url, 'ws://x/ws');
  win.sockets[0].onopen();

  const hello = win.sockets[0].sent[0];
  assert.deepEqual(hello, { type: 'hello', body: 'editor', name: 'Layout editor' });
  assert.equal('device_id' in hello, false);
  preview.destroy();
});

test('hello omits device_id when there is no DeskDevice', () => {
  const win = makeWin();
  const fakes = makeRegistryFakes();
  win.PanelRegistry = fakes.PanelRegistry;
  const preview = EditorPreview.create(makeContainer(960), { registry: fakes.registry, wsUrl: 'ws://x/ws', win });

  preview.setLive(true);
  win.sockets[0].onopen();

  const hello = win.sockets[0].sent[0];
  assert.equal(hello.body, 'editor');
  assert.equal('device_id' in hello, false);
  preview.destroy();
});

test('subscribe topics come from registry.topicsFor for the widgets shown, re-sent on show', () => {
  const win = makeWin();
  const fakes = makeRegistryFakes({ topics: ['clock.state', 'weather.state'] });
  win.PanelRegistry = fakes.PanelRegistry;
  const preview = EditorPreview.create(makeContainer(960), { registry: fakes.registry, wsUrl: 'ws://x/ws', win });

  preview.setLive(true);
  win.sockets[0].onopen();
  preview.show(sixByTwelveLayout(), 'home', 'landscape', SIZE);

  const subs = win.sockets[0].sent.filter((m) => m.type === 'subscribe');
  assert.equal(subs.length, 2);
  assert.deepEqual(subs[0], { type: 'subscribe', topics: ['clock.state', 'weather.state'] });
  assert.deepEqual(subs[1], { type: 'subscribe', topics: ['clock.state', 'weather.state'] });
  assert.deepEqual(fakes.registry.topicsCalls[fakes.registry.topicsCalls.length - 1], ['a', 'b']);
  preview.destroy();
});

test('subscribe is sent when the socket becomes ready after show', () => {
  const win = makeWin();
  const fakes = makeRegistryFakes({ topics: ['clock.state'] });
  win.PanelRegistry = fakes.PanelRegistry;
  const preview = EditorPreview.create(makeContainer(960), { registry: fakes.registry, wsUrl: 'ws://x/ws', win });

  preview.show(sixByTwelveLayout(), 'home', 'landscape', SIZE);
  preview.setLive(true);
  win.sockets[0].onopen();

  const types = win.sockets[0].sent.map((m) => m.type);
  assert.deepEqual(types, ['hello', 'subscribe']);
  assert.deepEqual(win.sockets[0].sent[1].topics, ['clock.state']);
  preview.destroy();
});

test('topic messages reach every mounted handle', () => {
  const win = makeWin();
  const fakes = makeRegistryFakes();
  win.PanelRegistry = fakes.PanelRegistry;
  const preview = EditorPreview.create(makeContainer(960), { registry: fakes.registry, wsUrl: 'ws://x/ws', win });

  preview.show(sixByTwelveLayout(), 'home', 'landscape', SIZE);
  preview.setLive(true);
  win.sockets[0].onopen();
  win.sockets[0].onmessage({ data: JSON.stringify({ type: 'topic', topic: 'clock.state', data: { hour: 9 } }) });
  win.sockets[0].onmessage({ data: 'not json' });

  assert.deepEqual(fakes.handles[0].topics, [{ topic: 'clock.state', data: { hour: 9 } }]);
  assert.deepEqual(fakes.handles[1].topics, [{ topic: 'clock.state', data: { hour: 9 } }]);
  preview.destroy();
});

test('no action message is ever sent, even when a widget calls sendAction', () => {
  const win = makeWin();
  const fakes = makeRegistryFakes();
  win.PanelRegistry = fakes.PanelRegistry;
  const preview = EditorPreview.create(makeContainer(960), { registry: fakes.registry, wsUrl: 'ws://x/ws', win });

  preview.show(sixByTwelveLayout(), 'home', 'landscape', SIZE);
  preview.setLive(true);
  win.sockets[0].onopen();

  const sendAction = fakes.mounts[0].env.sendAction;
  assert.equal(typeof sendAction, 'function');
  assert.equal(sendAction('press', { x: 1 }), false);

  const allTypes = win.sockets.flatMap((s) => s.sent.map((m) => m.type));
  assert.equal(allTypes.includes('action'), false);
  for (const type of allTypes) assert.ok(['hello', 'subscribe'].includes(type), type);
  preview.destroy();
});

test('a closed socket reconnects after 3 seconds while live is on', () => {
  const win = makeWin();
  const fakes = makeRegistryFakes();
  win.PanelRegistry = fakes.PanelRegistry;
  const preview = EditorPreview.create(makeContainer(960), { registry: fakes.registry, wsUrl: 'ws://x/ws', win });

  preview.setLive(true);
  win.sockets[0].onclose();

  assert.equal(win.timers.length, 1);
  assert.equal(win.timers[0].ms, 3000);
  win.runTimers();
  assert.equal(win.sockets.length, 2);
  preview.destroy();
});

test('setLive(false) closes the socket and cancels the reconnect timer', () => {
  const win = makeWin();
  const fakes = makeRegistryFakes();
  win.PanelRegistry = fakes.PanelRegistry;
  const preview = EditorPreview.create(makeContainer(960), { registry: fakes.registry, wsUrl: 'ws://x/ws', win });

  preview.setLive(true);
  win.sockets[0].onclose();
  assert.equal(win.timers.length, 1);

  preview.setLive(false);
  assert.equal(win.timers.length, 0);
  win.runTimers();
  assert.equal(win.sockets.length, 1);
  preview.destroy();
});

test('destroy closes the socket, clears timers and destroys handles', () => {
  const win = makeWin();
  const fakes = makeRegistryFakes();
  win.PanelRegistry = fakes.PanelRegistry;
  const container = makeContainer(960);
  const preview = EditorPreview.create(container, { registry: fakes.registry, wsUrl: 'ws://x/ws', win });

  preview.show(sixByTwelveLayout(), 'home', 'landscape', SIZE);
  preview.setLive(true);
  win.sockets[0].onopen();
  win.sockets[0].onclose();
  assert.equal(win.timers.length, 1);

  preview.destroy();

  assert.equal(win.timers.length, 0);
  win.runTimers();
  assert.equal(win.sockets.length, 1);
  assert.equal(fakes.handles.every((h) => h.destroyCount === 1), true);
  assert.equal(container.children.length, 0);
});

test('destroy closes an open socket', () => {
  const win = makeWin();
  const fakes = makeRegistryFakes();
  win.PanelRegistry = fakes.PanelRegistry;
  const preview = EditorPreview.create(makeContainer(960), { registry: fakes.registry, wsUrl: 'ws://x/ws', win });

  preview.setLive(true);
  win.sockets[0].onopen();
  preview.destroy();

  assert.equal(win.sockets[0].closed, true);
});
