const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

const runtime = require(path.join(__dirname, '../../static/panel/runtime.js'));

// ---------------------------------------------------------------- fake DOM

function findAll(node, pred, out) {
  const acc = out || [];
  if (pred(node)) acc.push(node);
  for (const child of node.children) findAll(child, pred, acc);
  return acc;
}

class FakeElement {
  constructor(tag, doc) {
    this.tagName = String(tag).toUpperCase();
    this.ownerDocument = doc;
    this.children = [];
    this.parentNode = null;
    this.style = {};
    this.id = '';
    this.textContent = '';
    this.clientWidth = 0;
    this.clientHeight = 0;
    this.attributes = {};
    this.listeners = {};
    this._classes = [];
    this.classList = {
      add: (...names) => {
        for (const name of names) if (!this._classes.includes(name)) this._classes.push(name);
      },
      remove: (...names) => {
        this._classes = this._classes.filter((c) => !names.includes(c));
      },
      contains: (name) => this._classes.includes(name),
    };
  }

  get className() {
    return this._classes.join(' ');
  }

  set className(value) {
    this._classes = String(value).split(/\s+/).filter(Boolean);
  }

  get firstChild() {
    return this.children[0] || null;
  }

  get lastChild() {
    return this.children[this.children.length - 1] || null;
  }

  appendChild(child) {
    if (child.parentNode) child.parentNode.removeChild(child);
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index < 0) throw new Error('not a child');
    this.children.splice(index, 1);
    child.parentNode = null;
    return child;
  }

  addEventListener(type, fn) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(fn);
  }

  fire(type, event) {
    for (const fn of this.listeners[type] || []) fn(event || {});
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  getBoundingClientRect() {
    return { left: 0, top: 0, width: this.clientWidth, height: this.clientHeight };
  }
}

function makeDocument() {
  const listeners = {};
  const doc = {
    visibilityState: 'visible',
    body: null,
    createElement(tag) {
      return new FakeElement(tag, doc);
    },
    getElementById(id) {
      return findAll(doc.body, (el) => el.id === id)[0] || null;
    },
    addEventListener(type, fn) {
      if (!listeners[type]) listeners[type] = [];
      listeners[type].push(fn);
    },
    fire(type, event) {
      for (const fn of listeners[type] || []) fn(event || {});
    },
  };
  doc.body = new FakeElement('body', doc);
  return doc;
}

// ---------------------------------------------------------------- fake clock (win.setTimeout & co.)

function makeClock() {
  let now = 0;
  let nextId = 1;
  let timers = [];

  function add(fn, ms, repeat) {
    const id = nextId++;
    timers.push({ id, fn, ms: ms || 0, at: now + (ms || 0), repeat: !!repeat });
    return id;
  }

  function remove(id) {
    timers = timers.filter((t) => t.id !== id);
  }

  return {
    setTimeout: (fn, ms) => add(fn, ms, false),
    setInterval: (fn, ms) => add(fn, ms, true),
    clearTimeout: remove,
    clearInterval: remove,
    pending: () => timers.map((t) => t.ms),
    tick(ms) {
      const end = now + ms;
      for (;;) {
        timers.sort((a, b) => a.at - b.at || a.id - b.id);
        const t = timers[0];
        if (!t || t.at > end) break;
        now = t.at;
        if (t.repeat) t.at += t.ms;
        else timers.shift();
        t.fn();
      }
      now = end;
    },
  };
}

// ---------------------------------------------------------------- fake WebSocket and XMLHttpRequest

function makeNetwork() {
  const net = { sockets: [], xhrs: [] };

  class FakeWebSocket {
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.sent = [];
      this.onopen = null;
      this.onmessage = null;
      this.onclose = null;
      net.sockets.push(this);
    }

    send(data) {
      this.sent.push(JSON.parse(data));
    }

    open() {
      this.readyState = 1;
      if (this.onopen) this.onopen({});
    }

    message(obj) {
      if (this.onmessage) this.onmessage({ data: JSON.stringify(obj) });
    }

    close() {
      this.readyState = 3;
      if (this.onclose) this.onclose({});
    }
  }

  class FakeXHR {
    constructor() {
      this.readyState = 0;
      this.status = 0;
      this.responseText = '';
      this.method = null;
      this.url = null;
      this.body = undefined;
      this.headers = {};
      this.onreadystatechange = null;
      net.xhrs.push(this);
    }

    open(method, url) {
      this.method = method;
      this.url = url;
      this.readyState = 1;
    }

    setRequestHeader(name, value) {
      this.headers[name] = value;
    }

    send(body) {
      this.body = body === null ? null : JSON.parse(body);
    }

    respond(status, data) {
      this.status = status;
      this.responseText = data === undefined ? '' : JSON.stringify(data);
      this.readyState = 4;
      if (this.onreadystatechange) this.onreadystatechange();
    }
  }

  net.WebSocket = FakeWebSocket;
  net.XMLHttpRequest = FakeXHR;
  return net;
}

// ---------------------------------------------------------------- stubs for the sibling modules

function makeStubs() {
  const mounts = [];
  const pets = [];
  const longPresses = [];
  const controllers = [];
  const models = [];
  const widgetRegistrations = [];
  const topicMap = { clock: [], weather: ['weather.now'], placeholder: [], broken: [] };

  const registry = {
    topicsFor(widgets) {
      const out = [];
      for (const w of widgets) {
        for (const t of topicMap[w.type] || []) if (!out.includes(t)) out.push(t);
      }
      return out.sort();
    },
  };

  const PanelRegistry = {
    shared: registry,
    mount(reg, el, widget, env) {
      if (widget.type === 'broken') {
        const failed = { widget, failed: true, error: 'boom', onTopic() {}, resize() {}, destroy() {} };
        mounts.push({ registry: reg, el, widget, env, handle: failed });
        return failed;
      }
      const handle = {
        widget,
        failed: false,
        error: null,
        calls: [],
        onTopic(topic, data) {
          handle.calls.push(['onTopic', topic, data]);
        },
        resize() {
          handle.calls.push(['resize']);
        },
        destroy() {
          handle.calls.push(['destroy']);
        },
      };
      mounts.push({ registry: reg, el, widget, env, handle });
      return handle;
    },
  };

  const DEFAULT_GRID = { landscape: { cols: 12, rows: 6 }, portrait: { cols: 6, rows: 12 } };
  const PanelGrid = {
    orientationFor: (w, h) => (w > h ? 'landscape' : 'portrait'),
    gridFor: (layout, o) => (layout && layout.grid && layout.grid[o]) || DEFAULT_GRID[o],
    pickVariant(page, o) {
      const other = o === 'landscape' ? 'portrait' : 'landscape';
      if (Array.isArray(page[o]) && page[o].length) return { orientation: o, widgets: page[o] };
      if (Array.isArray(page[other]) && page[other].length) return { orientation: other, widgets: page[other] };
      return { orientation: o, widgets: [] };
    },
    cellRect: (w, grid) => ({
      left: (w.x / grid.cols) * 100,
      top: (w.y / grid.rows) * 100,
      width: (w.w / grid.cols) * 100,
      height: (w.h / grid.rows) * 100,
    }),
  };

  const PanelArrangeModel = {
    create({ widgets, grid, registry: reg }) {
      const initial = widgets.map((w) => Object.assign({}, w));
      let current = widgets.map((w) => Object.assign({}, w));
      const model = {
        grid,
        registry: reg,
        cancelled: 0,
        widgets: () => current.map((w) => Object.assign({}, w)),
        move(id, x, y) {
          const found = current.find((c) => c.id === id);
          if (!found) return false;
          found.x = x;
          found.y = y;
          return true;
        },
        remove(id) {
          const before = current.length;
          current = current.filter((c) => c.id !== id);
          return current.length !== before;
        },
        cancel() {
          model.cancelled += 1;
          current = initial.map((w) => Object.assign({}, w));
        },
        toPayload(pageId, orientation) {
          return {
            page_id: pageId,
            orientation,
            widgets: current.map(({ id, type, x, y, w, h }) => ({ id, type, x, y, w, h })),
          };
        },
      };
      models.push(model);
      return model;
    },
  };

  const PanelArrangeUI = {
    longPress(el, ms, cb) {
      const rec = { el, ms, cb, detached: false };
      longPresses.push(rec);
      return () => {
        rec.detached = true;
      };
    },
    create(opts) {
      const controller = {
        opts,
        entered: false,
        exited: false,
        attached: [],
        enter() {
          controller.entered = true;
        },
        attachTile(el, id) {
          controller.attached.push(id);
        },
        exit() {
          controller.exited = true;
        },
      };
      controllers.push(controller);
      return controller;
    },
  };

  const PanelPet = {
    create(doc, pageEl) {
      const pet = {
        pageEl,
        destroyed: false,
        calls: [],
        setState(s) {
          pet.calls.push(['setState', s]);
        },
        setEmotion(e) {
          pet.calls.push(['setEmotion', e]);
        },
        destroy() {
          pet.destroyed = true;
          pet.calls.push(['destroy']);
        },
      };
      pets.push(pet);
      return pet;
    },
  };

  const PanelWidgets = {
    registerBuiltins(reg) {
      widgetRegistrations.push(reg);
    },
  };

  const DeskDevice = {
    helloFields: () => ({ device_id: 'dev-test-1', app_version: 'test' }),
  };

  return {
    globals: { PanelGrid, PanelRegistry, PanelArrangeModel, PanelArrangeUI, PanelPet, PanelWidgets, DeskDevice },
    mounts,
    pets,
    longPresses,
    controllers,
    models,
    registry,
    widgetRegistrations,
  };
}

// ---------------------------------------------------------------- harness

const LAYOUT = {
  id: 'starter',
  name: 'Starter',
  version: 1,
  updated_at: '2026-11-18T10:00:00+00:00',
  grid: { landscape: { cols: 12, rows: 6 }, portrait: { cols: 6, rows: 12 } },
  pages: [
    {
      id: 'home',
      title: 'Home',
      landscape: [
        { id: 'w1', type: 'clock', x: 0, y: 0, w: 8, h: 6, config: {} },
        { id: 'w2', type: 'weather', x: 8, y: 0, w: 4, h: 3, config: {} },
      ],
      portrait: [{ id: 'w1', type: 'clock', x: 0, y: 0, w: 6, h: 4, config: {} }],
    },
    {
      id: 'second',
      title: 'Second',
      landscape: [{ id: 'w3', type: 'placeholder', x: 0, y: 0, w: 4, h: 2, config: { text: 'hi' } }],
      portrait: [],
    },
  ],
};

function clone(obj) {
  return JSON.parse(JSON.stringify(obj));
}

function setup(options = {}) {
  const clock = makeClock();
  const net = makeNetwork();
  const stubs = makeStubs();
  const win = {
    document: makeDocument(),
    innerWidth: 1280,
    innerHeight: 720,
    location: { protocol: 'http:', host: 'panel.test:8000' },
    navigator: { getGamepads: () => [] },
    WebSocket: net.WebSocket,
    XMLHttpRequest: net.XMLHttpRequest,
    setTimeout: clock.setTimeout,
    clearTimeout: clock.clearTimeout,
    setInterval: clock.setInterval,
    clearInterval: clock.clearInterval,
    listeners: {},
    addEventListener(type, fn) {
      if (!win.listeners[type]) win.listeners[type] = [];
      win.listeners[type].push(fn);
    },
    fire(type) {
      for (const fn of win.listeners[type] || []) fn({});
    },
    ...stubs.globals,
  };
  if (options.beforeStart) options.beforeStart(win);
  const panel = runtime.start({ win, doc: win.document, wsUrl: 'ws://panel.test/ws' });
  const h = { clock, net, win, doc: win.document, stubs, panel };
  h.sock = () => net.sockets[net.sockets.length - 1];
  h.byClass = (cls) => findAll(win.document.body, (el) => el.classList.contains(cls));
  h.viewport = () => h.byClass('pn-viewport')[0];
  h.statusEl = () => h.byClass('pn-status')[0];
  h.layoutGets = () => net.xhrs.filter((x) => x.method === 'GET' && x.url.indexOf('/api/layouts/') === 0);
  h.lastLayoutGet = () => {
    const gets = h.layoutGets();
    return gets[gets.length - 1];
  };
  return h;
}

function open(h) {
  h.sock().open();
}

function welcome(h, extra) {
  const msg = Object.assign({ type: 'welcome', roles: ['panel'], layout_id: null, device_id: 'dev-test-1', active: true }, extra || {});
  h.sock().message(msg);
}

// open + welcome + answer the layout GET with `layout`
function boot(h, welcomeExtra, layout) {
  open(h);
  welcome(h, welcomeExtra);
  h.lastLayoutGet().respond(200, layout || LAYOUT);
}

function padWith(l1, r1) {
  const buttons = [];
  for (let i = 0; i < 6; i += 1) buttons.push({ pressed: i === 4 ? l1 : i === 5 ? r1 : false });
  return { buttons };
}

// ---------------------------------------------------------------- pager and HTTP

test('createPager clamps to the page range and fires onChange only on change', () => {
  const pager = runtime.createPager(3);
  const seen = [];
  pager.onChange((index) => seen.push(index));
  assert.equal(pager.index(), 0);
  assert.equal(pager.count(), 3);

  pager.prev();
  assert.equal(pager.index(), 0);
  pager.next();
  pager.next();
  pager.next();
  assert.equal(pager.index(), 2);
  pager.goTo(2);
  pager.goTo(-5);
  assert.equal(pager.index(), 0);
  assert.deepEqual(seen, [1, 2, 0]);

  pager.goTo(2);
  pager.setCount(2);
  assert.equal(pager.index(), 1);
  assert.equal(pager.count(), 2);
  assert.deepEqual(seen, [1, 2, 0, 2, 1]);

  pager.setCount(0);
  assert.equal(pager.index(), 0);
  pager.next();
  assert.equal(pager.index(), 0);
});

test('sendJSON sends JSON bodies, parses replies and reports HTTP errors', () => {
  const net = makeNetwork();
  const results = [];
  runtime.sendJSON('PUT', '/api/layouts/starter/arrange', { page_id: 'home' }, (err, data) => results.push({ err, data }), net.XMLHttpRequest);
  const put = net.xhrs[0];
  assert.equal(put.method, 'PUT');
  assert.equal(put.url, '/api/layouts/starter/arrange');
  assert.deepEqual(put.body, { page_id: 'home' });
  assert.equal(put.headers['Content-Type'], 'application/json');
  put.respond(200, { id: 'starter' });
  assert.equal(results[0].err, null);
  assert.deepEqual(results[0].data, { id: 'starter' });

  runtime.getJSON('/api/layouts/missing', (err, data) => results.push({ err, data }), net.XMLHttpRequest);
  net.xhrs[1].respond(404, { detail: 'nope' });
  assert.equal(results[1].err.status, 404);
  assert.equal(results[1].data, null);
  assert.equal(net.xhrs[1].method, 'GET');
  assert.equal(net.xhrs[1].body, null);
});

// ---------------------------------------------------------------- connection and layout

test('the hello carries body panel, protocol 1 and the DeskDevice fields', () => {
  const h = setup();
  open(h);
  const hello = h.sock().sent[0];
  assert.equal(hello.type, 'hello');
  assert.equal(hello.body, 'panel');
  assert.equal(hello.protocol, 1);
  assert.equal(hello.device_id, 'dev-test-1');
  assert.equal(h.sock().url, 'ws://panel.test/ws');
  assert.equal(h.stubs.widgetRegistrations.length, 1);
});

test('welcome with the panel role loads the default layout and renders its pages', () => {
  const h = setup();
  boot(h);
  assert.equal(h.layoutGets().length, 1);
  assert.equal(h.layoutGets()[0].url, '/api/layouts/default');

  const pages = h.panel.pages();
  assert.deepEqual(pages.map((p) => p.kind), ['widgets', 'widgets']);
  assert.equal(h.panel.pager.count(), 2);
  assert.deepEqual(h.stubs.mounts.map((m) => m.widget.id), ['w1', 'w2', 'w3']);

  const tile = pages[0].tiles[0].tileEl;
  assert.equal(tile.style.left, '0%');
  assert.match(tile.style.width, /^66\.66/);
  assert.equal(pages[0].pageEl.style.left, '0%');
  assert.equal(pages[1].pageEl.style.left, '100%');
  assert.equal(h.viewport().children.length, 2);
  assert.equal(h.statusEl().style.display, 'none');
  assert.equal(h.byClass('pn-dots')[0].style.display, '');
});

test('a layout_id from welcome is used instead of the default alias', () => {
  const h = setup();
  boot(h, { layout_id: 'desk-main' }, Object.assign(clone(LAYOUT), { id: 'desk-main' }));
  assert.equal(h.layoutGets()[0].url, '/api/layouts/desk-main');
  assert.equal(h.panel.layout().id, 'desk-main');
});

test('welcome with the body role prepends the Pet page', () => {
  const h = setup();
  boot(h, { roles: ['panel', 'body'] });
  assert.equal(h.stubs.pets.length, 1);
  const pet = h.stubs.pets[0];
  assert.equal(h.panel.pages()[0].kind, 'pet');
  assert.equal(h.panel.pages()[0].pageEl, pet.pageEl);
  assert.equal(h.panel.pager.count(), 3);
  assert.equal(h.viewport().children[0], pet.pageEl);

  h.sock().message({ type: 'emotion', emotion: 'happy' });
  h.sock().message({ type: 'state', state: 'listening' });
  assert.deepEqual(pet.calls, [['setEmotion', 'happy'], ['setState', 'listening']]);
});

test('a role message that removes the body role destroys the Pet page', () => {
  const h = setup();
  boot(h, { roles: ['panel', 'body'] });
  const pet = h.stubs.pets[0];
  h.sock().message({ type: 'role', roles: ['panel'], layout_id: null });
  assert.equal(pet.destroyed, true);
  assert.deepEqual(h.panel.pages().map((p) => p.kind), ['widgets', 'widgets']);
});

test('subscribes to layout plus the widget topics once the layout is rendered', () => {
  const h = setup();
  boot(h);
  const subs = h.sock().sent.filter((m) => m.type === 'subscribe');
  assert.ok(subs.length >= 2);
  assert.deepEqual(subs[0].topics, ['layout']);
  assert.deepEqual(subs[subs.length - 1].topics, ['layout', 'weather.now']);
});

test('a topic message is forwarded to the tiles handles', () => {
  const h = setup();
  boot(h);
  h.sock().message({ type: 'topic', topic: 'weather.now', data: { temp: 21 } });
  const weather = h.stubs.mounts.find((m) => m.widget.type === 'weather');
  const clock = h.stubs.mounts.find((m) => m.widget.type === 'clock');
  assert.deepEqual(weather.handle.calls, [['onTopic', 'weather.now', { temp: 21 }]]);
  assert.deepEqual(clock.handle.calls, [['onTopic', 'weather.now', { temp: 21 }]]);
});

test('a layout topic for the current layout reloads it; another layout is ignored', () => {
  const h = setup();
  boot(h);
  assert.equal(h.layoutGets().length, 1);

  h.sock().message({ type: 'topic', topic: 'layout', data: { layout_id: 'other-layout' } });
  assert.equal(h.layoutGets().length, 1);

  h.sock().message({ type: 'topic', topic: 'layout', data: { layout_id: 'starter' } });
  assert.equal(h.layoutGets().length, 2);
  assert.equal(h.layoutGets()[1].url, '/api/layouts/default');
});

test('sendAction sends an action message only while connected', () => {
  const h = setup();
  assert.equal(h.panel.sendAction('clock.set', { x: 1 }), false);
  boot(h);
  assert.equal(h.panel.sendAction('clock.set', { x: 1 }), true);
  assert.deepEqual(h.sock().sent[h.sock().sent.length - 1], { type: 'action', id: 'clock.set', args: { x: 1 } });
  assert.equal(h.panel.sendAction('ping'), true);
  assert.deepEqual(h.sock().sent[h.sock().sent.length - 1], { type: 'action', id: 'ping', args: {} });

  const env = h.stubs.mounts[0].env;
  env.sendAction('clock.set', { x: 2 });
  assert.deepEqual(h.sock().sent[h.sock().sent.length - 1], { type: 'action', id: 'clock.set', args: { x: 2 } });
});

test('a failing layout fetch shows an error and retries after 5 seconds', () => {
  const h = setup();
  open(h);
  welcome(h);
  h.lastLayoutGet().respond(500, { detail: 'boom' });
  assert.equal(h.statusEl().textContent, 'Could not load layout');
  assert.equal(h.statusEl().style.display, '');

  h.clock.tick(4999);
  assert.equal(h.layoutGets().length, 1);
  h.clock.tick(1);
  assert.equal(h.layoutGets().length, 2);
  h.lastLayoutGet().respond(200, LAYOUT);
  assert.equal(h.statusEl().style.display, 'none');
  assert.equal(h.panel.pages().length, 2);
});

test('reconnect backs off 1s, 2s, 4s, 8s, then 10s, and resets after an open', () => {
  const h = setup();
  open(h);
  h.sock().close();
  assert.equal(h.statusEl().textContent, 'Reconnecting...');

  const expected = [1000, 2000, 4000, 8000, 10000, 10000];
  for (const delay of expected) {
    const before = h.net.sockets.length;
    h.clock.tick(delay - 1);
    assert.equal(h.net.sockets.length, before, `no reconnect before ${delay}ms`);
    h.clock.tick(1);
    assert.equal(h.net.sockets.length, before + 1, `reconnect at ${delay}ms`);
    h.sock().close();
  }

  // the last close above left a 10s reconnect pending; let it run, open the socket, then close it again
  h.clock.tick(10000);
  h.sock().open();
  h.sock().close();
  const before = h.net.sockets.length;
  h.clock.tick(999);
  assert.equal(h.net.sockets.length, before);
  h.clock.tick(1);
  assert.equal(h.net.sockets.length, before + 1);
});

// ---------------------------------------------------------------- navigation

test('a horizontal swipe changes the page, a vertical one does not', () => {
  const h = setup();
  boot(h);
  const vp = h.viewport();

  vp.fire('touchstart', { touches: [{ clientX: 300, clientY: 100 }] });
  vp.fire('touchend', { changedTouches: [{ clientX: 200, clientY: 110 }] });
  assert.equal(h.panel.pager.index(), 1);
  assert.equal(h.panel.pages()[0].pageEl.style.left, '-100%');
  assert.equal(h.panel.pages()[1].pageEl.style.left, '0%');

  vp.fire('touchstart', { touches: [{ clientX: 300, clientY: 100 }] });
  vp.fire('touchend', { changedTouches: [{ clientX: 200, clientY: 300 }] });
  assert.equal(h.panel.pager.index(), 1);

  vp.fire('touchstart', { touches: [{ clientX: 100, clientY: 100 }] });
  vp.fire('touchend', { changedTouches: [{ clientX: 130, clientY: 100 }] });
  assert.equal(h.panel.pager.index(), 1);

  vp.fire('mousedown', { clientX: 100, clientY: 100 });
  vp.fire('mouseup', { clientX: 200, clientY: 100 });
  assert.equal(h.panel.pager.index(), 0);
});

test('arrow, page and volume keys change the page and clamp at the ends', () => {
  const h = setup();
  boot(h, {}, Object.assign(clone(LAYOUT), { pages: LAYOUT.pages.concat([{ id: 'third', landscape: [], portrait: [] }]) }));
  const press = (event) => {
    let prevented = false;
    h.doc.fire('keydown', Object.assign({ preventDefault: () => (prevented = true) }, event));
    return prevented;
  };
  const pager = h.panel.pager;

  assert.equal(press({ key: 'ArrowRight' }), true);
  assert.equal(pager.index(), 1);
  assert.equal(press({ key: 'PageDown' }), true);
  assert.equal(pager.index(), 2);
  press({ key: 'AudioVolumeDown' });
  assert.equal(pager.index(), 2);
  press({ keyCode: 175 });
  assert.equal(pager.index(), 1);
  press({ key: 'VolumeUp' });
  assert.equal(pager.index(), 0);
  press({ key: 'PageUp' });
  assert.equal(pager.index(), 0);
  press({ key: 'ArrowLeft' });
  assert.equal(pager.index(), 0);

  assert.equal(press({ key: 'ArrowRight', target: { tagName: 'INPUT' } }), false);
  assert.equal(pager.index(), 0);

  assert.equal(press({ key: 'a' }), false);
});

test('gamepad L1 and R1 change pages on the press edge only', () => {
  const h = setup();
  boot(h, {}, Object.assign(clone(LAYOUT), { pages: LAYOUT.pages.concat([{ id: 'third', landscape: [], portrait: [] }]) }));
  let pads = [];
  h.win.navigator.getGamepads = () => pads;

  pads = [padWith(false, true)];
  h.clock.tick(100);
  assert.equal(h.panel.pager.index(), 1);
  h.clock.tick(100);
  assert.equal(h.panel.pager.index(), 1, 'held button does not repeat');

  pads = [padWith(false, false)];
  h.clock.tick(100);
  pads = [padWith(true, false)];
  h.clock.tick(100);
  assert.equal(h.panel.pager.index(), 0);
});

// ---------------------------------------------------------------- orientation

test('an orientation change re-renders with the portrait variant after the debounce', () => {
  const h = setup();
  boot(h);
  assert.equal(h.panel.orientation(), 'landscape');
  assert.equal(h.panel.pages()[0].tiles[0].tileEl.style.width.slice(0, 5), '66.66');

  h.win.innerWidth = 720;
  h.win.innerHeight = 1280;
  h.win.fire('resize');
  h.clock.tick(149);
  assert.equal(h.panel.orientation(), 'landscape');
  h.clock.tick(1);
  assert.equal(h.panel.orientation(), 'portrait');

  const home = h.panel.pages()[0];
  assert.equal(home.orientation, 'portrait');
  assert.equal(home.tiles.length, 1);
  assert.equal(home.tiles[0].tileEl.style.width, '100%');
  assert.equal(h.layoutGets().length, 1, 'the layout is not fetched again');
});

// ---------------------------------------------------------------- widget failures

test('a widget whose mount fails does not break the page', () => {
  const h = setup();
  const layout = clone(LAYOUT);
  layout.pages[0].landscape.push({ id: 'w9', type: 'broken', x: 8, y: 3, w: 4, h: 3, config: {} });
  boot(h, {}, layout);
  const home = h.panel.pages()[0];
  assert.equal(home.tiles.length, 3);
  const broken = home.tiles.find((t) => t.id === 'w9');
  assert.equal(broken.handle.failed, true);
  assert.equal(h.panel.pages().length, 2);

  h.sock().message({ type: 'topic', topic: 'weather.now', data: { temp: 1 } });
  const weather = h.stubs.mounts.find((m) => m.widget.type === 'weather');
  assert.deepEqual(weather.handle.calls, [['onTopic', 'weather.now', { temp: 1 }]]);
});

// ---------------------------------------------------------------- arrange mode

test('arrange saves the payload to the arrange endpoint and replaces the layout', () => {
  const h = setup();
  boot(h);
  assert.equal(h.stubs.longPresses.length, 3, 'one long press per widget tile');

  h.stubs.longPresses[0].cb();
  assert.equal(h.panel.isArranging(), true);
  const controller = h.stubs.controllers[0];
  assert.equal(controller.entered, true);
  assert.deepEqual(controller.attached, ['w1', 'w2']);

  const model = h.stubs.models[0];
  assert.equal(model.move('w1', 4, 0), true);
  assert.equal(model.remove('w2'), true);
  controller.opts.onChange();

  const home = h.panel.pages()[0];
  assert.deepEqual(home.tiles.map((t) => t.id), ['w1']);
  assert.match(home.tiles[0].tileEl.style.left, /^33\.33/);
  const weatherMount = h.stubs.mounts.find((m) => m.widget.type === 'weather');
  assert.deepEqual(weatherMount.handle.calls.slice(-1), [['destroy']]);
  const clockMount = h.stubs.mounts.find((m) => m.widget.type === 'clock' && m.widget.id === 'w1');
  assert.deepEqual(clockMount.handle.calls, [['resize']], 'a moved tile resizes, not remounts');

  controller.opts.onSave();
  const put = h.net.xhrs.find((x) => x.method === 'PUT');
  assert.equal(put.url, '/api/layouts/starter/arrange');
  assert.deepEqual(put.body, {
    page_id: 'home',
    orientation: 'landscape',
    widgets: [{ id: 'w1', type: 'clock', x: 4, y: 0, w: 8, h: 6 }],
  });

  const saved = clone(LAYOUT);
  saved.pages[0].landscape = [{ id: 'w1', type: 'clock', x: 4, y: 0, w: 8, h: 6, config: {} }];
  put.respond(200, saved);
  assert.equal(h.panel.isArranging(), false);
  assert.equal(controller.exited, true);
  assert.equal(h.panel.layout().pages[0].landscape.length, 1);
  assert.equal(h.panel.pages()[0].tiles.length, 1);
  assert.equal(h.statusEl().style.display, 'none');
});

test('a failed arrange save shows an error and stays in arrange mode', () => {
  const h = setup();
  boot(h);
  h.stubs.longPresses[0].cb();
  const controller = h.stubs.controllers[0];
  controller.opts.onSave();
  const put = h.net.xhrs.find((x) => x.method === 'PUT');
  put.respond(422, { detail: 'invalid' });
  assert.equal(h.statusEl().textContent, 'Could not save');
  assert.equal(h.panel.isArranging(), true);
  assert.equal(controller.exited, false);
});

test('cancelling arrange restores the layout and exits', () => {
  const h = setup();
  boot(h);
  h.stubs.longPresses[0].cb();
  const controller = h.stubs.controllers[0];
  h.stubs.models[0].move('w1', 4, 0);
  controller.opts.onChange();
  assert.match(h.panel.pages()[0].tiles[0].tileEl.style.left, /^33\.33/);

  controller.opts.onCancel();
  assert.equal(h.stubs.models[0].cancelled, 1);
  assert.equal(h.panel.isArranging(), false);
  assert.equal(controller.exited, true);
  assert.equal(h.panel.pages()[0].tiles[0].tileEl.style.left, '0%');
  assert.equal(h.net.xhrs.filter((x) => x.method === 'PUT').length, 0);
});

test('swipes are ignored while arranging', () => {
  const h = setup();
  boot(h);
  h.stubs.longPresses[0].cb();
  const vp = h.viewport();
  vp.fire('touchstart', { touches: [{ clientX: 300, clientY: 100 }] });
  vp.fire('touchend', { changedTouches: [{ clientX: 200, clientY: 100 }] });
  assert.equal(h.panel.pager.index(), 0);
});

// ---------------------------------------------------------------- wake lock

test('the wake lock is requested for the screen and again when the page becomes visible', () => {
  const requests = [];
  const h = setup({
    beforeStart(win) {
      win.navigator.wakeLock = {
        request(type) {
          requests.push(type);
          return Promise.resolve({ released: false });
        },
      };
    },
  });
  assert.deepEqual(requests, ['screen']);

  h.doc.visibilityState = 'hidden';
  h.doc.fire('visibilitychange');
  assert.deepEqual(requests, ['screen']);

  h.doc.visibilityState = 'visible';
  h.doc.fire('visibilitychange');
  assert.deepEqual(requests, ['screen', 'screen']);
});

test('start works without a wake lock, a Pet or DeskDevice', () => {
  const h = setup({
    beforeStart(win) {
      delete win.navigator.wakeLock;
      delete win.DeskDevice;
      delete win.PanelPet;
    },
  });
  open(h);
  assert.equal(h.sock().sent[0].body, 'panel');
  welcome(h, { roles: ['panel', 'body'] });
  h.lastLayoutGet().respond(200, LAYOUT);
  assert.deepEqual(h.panel.pages().map((p) => p.kind), ['widgets', 'widgets']);
});
