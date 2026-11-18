const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const SOURCE_PATH = path.join(__dirname, '../../static/panel/arrange-ui.js');
const source = fs.readFileSync(SOURCE_PATH, 'utf8');

const GRID = { cols: 12, rows: 6 };
// Stage is 1200x600, so each cell is 100x100 px. Cell centres: 100c+50, 100r+50.
const STAGE_RECT = { left: 0, top: 0, width: 1200, height: 600 };

// ---------- fake DOM ----------

class FakeNode {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.ownerDocument = null;
    this.parentNode = null;
    this.children = [];
    this.listeners = new Map();
    this.classes = new Set();
    this.classList = {
      add: (...names) => names.forEach((n) => this.classes.add(n)),
      remove: (...names) => names.forEach((n) => this.classes.delete(n)),
      contains: (n) => this.classes.has(n),
    };
    this.textContent = '';
    this.disabled = false;
    this.rect = null;
    this._value = undefined;
  }

  get value() {
    if (this._value !== undefined) return this._value;
    const first = this.children[0];
    return first ? first.value : '';
  }

  set value(v) {
    this._value = v;
  }

  get parentElement() {
    return this.parentNode;
  }

  appendChild(child) {
    if (child.parentNode) child.parentNode.removeChild(child);
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  removeChild(child) {
    const i = this.children.indexOf(child);
    if (i < 0) throw new Error('not a child');
    this.children.splice(i, 1);
    child.parentNode = null;
    return child;
  }

  addEventListener(type, fn) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(fn);
  }

  removeEventListener(type, fn) {
    const list = this.listeners.get(type) || [];
    const i = list.indexOf(fn);
    if (i >= 0) list.splice(i, 1);
  }

  listenerCount(type) {
    return (this.listeners.get(type) || []).length;
  }

  getBoundingClientRect() {
    return Object.assign({ left: 0, top: 0, width: 0, height: 0 }, this.rect || {});
  }
}

function makeDocument() {
  const doc = new FakeNode('#document');
  doc.ownerDocument = doc;
  doc.createElement = (tag) => {
    const el = new FakeNode(tag);
    el.ownerDocument = doc;
    return el;
  };
  return doc;
}

// Dispatches like a browser: runs listeners on the target, then bubbles up
// through parentNode until a listener calls stopPropagation.
function fire(target, type, init) {
  const ev = Object.assign({ type, target, currentTarget: null, defaultPrevented: false, propagationStopped: false, button: 0 }, init || {});
  ev.preventDefault = () => {
    ev.defaultPrevented = true;
  };
  ev.stopPropagation = () => {
    ev.propagationStopped = true;
  };
  let node = target;
  while (node) {
    ev.currentTarget = node;
    (node.listeners.get(type) || []).slice().forEach((fn) => fn(ev));
    if (ev.propagationStopped) break;
    node = node.parentNode;
  }
  return ev;
}

function mouse(x, y) {
  return { clientX: x, clientY: y, button: 0 };
}

function touch(x, y) {
  const t = { clientX: x, clientY: y };
  return { changedTouches: [t], touches: [t] };
}

function touchEnd(x, y) {
  return { changedTouches: [{ clientX: x, clientY: y }], touches: [] };
}

// Centre of a cell, in stage pixels, as [x, y] for spreading into the event helpers.
function centre(col, row) {
  return [col * 100 + 50, row * 100 + 50];
}

function findAll(node, cls, out = []) {
  node.children.forEach((c) => {
    if (c.classList.contains(cls)) out.push(c);
    findAll(c, cls, out);
  });
  return out;
}

function one(node, cls) {
  const found = findAll(node, cls);
  assert.equal(found.length, 1, `expected one .${cls}, got ${found.length}`);
  return found[0];
}

// ---------- fake timers ----------

function makeClock() {
  let now = 0;
  let seq = 0;
  let pending = [];
  return {
    setTimeout(fn, ms) {
      seq += 1;
      pending.push({ id: seq, fn, at: now + (ms || 0) });
      return seq;
    },
    clearTimeout(id) {
      pending = pending.filter((t) => t.id !== id);
    },
    advance(ms) {
      now += ms;
      const due = pending.filter((t) => t.at <= now).sort((a, b) => a.at - b.at || a.id - b.id);
      pending = pending.filter((t) => t.at > now);
      due.forEach((t) => t.fn());
    },
    pendingCount() {
      return pending.length;
    },
  };
}

// Loads the real file in a vm context with no `module`, so it binds to
// window.PanelGrid, which is the stub passed in here.
function loadArrangeUI(gridStub) {
  const win = { PanelGrid: gridStub };
  const clock = makeClock();
  const sandbox = { window: win, setTimeout: clock.setTimeout, clearTimeout: clock.clearTimeout };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, { filename: SOURCE_PATH });
  return { PanelArrangeUI: win.PanelArrangeUI, clock };
}

// ---------- stubs ----------

function stubGrid() {
  return {
    snap(px, py, boxWidth, boxHeight, grid) {
      const x = Math.min(Math.max(Math.floor((px / boxWidth) * grid.cols), 0), grid.cols - 1);
      const y = Math.min(Math.max(Math.floor((py / boxHeight) * grid.rows), 0), grid.rows - 1);
      return { x, y };
    },
  };
}

function makeModel(initial) {
  const state = { widgets: initial.map((w) => Object.assign({}, w)), dirty: false };
  const model = {
    calls: [],
    addFails: false,
    moveFails: false,
    setDirty(v) {
      state.dirty = v;
    },
    widgets() {
      return state.widgets.map((w) => Object.assign({}, w));
    },
    isDirty() {
      return state.dirty;
    },
    find(id) {
      return state.widgets.find((w) => w.id === id) || null;
    },
    move(id, x, y) {
      model.calls.push(['move', id, x, y]);
      const w = model.find(id);
      if (!w || model.moveFails) return false;
      w.x = x;
      w.y = y;
      state.dirty = true;
      return true;
    },
    resize(id, w2, h2) {
      model.calls.push(['resize', id, w2, h2]);
      const w = model.find(id);
      if (!w) return false;
      w.w = w2;
      w.h = h2;
      state.dirty = true;
      return true;
    },
    remove(id) {
      model.calls.push(['remove', id]);
      const i = state.widgets.findIndex((w) => w.id === id);
      if (i < 0) return false;
      state.widgets.splice(i, 1);
      state.dirty = true;
      return true;
    },
    add(type) {
      model.calls.push(['add', type]);
      if (model.addFails) return null;
      const w = { id: 'new1', type, x: 0, y: 0, w: 2, h: 2, config: {} };
      state.widgets.push(w);
      state.dirty = true;
      return Object.assign({}, w);
    },
  };
  return model;
}

function makeRegistry() {
  const defs = [
    { id: 'clock', title: 'Clock' },
    { id: 'placeholder', title: 'Placeholder' },
  ];
  return {
    list() {
      return defs.slice();
    },
  };
}

// Builds a stage with two tiles' worth of widgets, a model, and a controller.
function setup() {
  const doc = makeDocument();
  const body = doc.createElement('body');
  doc.appendChild(body);
  const stage = doc.createElement('div');
  stage.rect = STAGE_RECT;
  body.appendChild(stage);

  const model = makeModel([
    { id: 'a', type: 'clock', x: 2, y: 1, w: 2, h: 2, config: {} },
    { id: 'b', type: 'placeholder', x: 6, y: 0, w: 3, h: 2, config: {} },
  ]);
  const counters = { change: 0, save: 0, cancel: 0 };
  const { PanelArrangeUI, clock } = loadArrangeUI(stubGrid());
  const ui = PanelArrangeUI.create({
    doc,
    stageEl: stage,
    model,
    registry: makeRegistry(),
    grid: GRID,
    onChange: () => {
      counters.change += 1;
    },
    onSave: () => {
      counters.save += 1;
    },
    onCancel: () => {
      counters.cancel += 1;
    },
  });

  function tileFor(id) {
    const tile = doc.createElement('div');
    stage.appendChild(tile);
    ui.attachTile(tile, id);
    return tile;
  }

  return { doc, body, stage, model, ui, counters, clock, tileFor, PanelArrangeUI };
}

// ---------- longPress ----------

test('longPress fires after the hold time when the touch stays still', () => {
  const { PanelArrangeUI, clock } = loadArrangeUI(stubGrid());
  const doc = makeDocument();
  const el = doc.createElement('div');
  let fired = 0;
  PanelArrangeUI.longPress(el, 500, () => {
    fired += 1;
  });

  fire(el, 'touchstart', touch(10, 10));
  clock.advance(499);
  assert.equal(fired, 0);
  clock.advance(1);
  assert.equal(fired, 1);
});

test('longPress keeps running for a move of exactly 10px and cancels beyond it', () => {
  const { PanelArrangeUI, clock } = loadArrangeUI(stubGrid());
  const doc = makeDocument();
  const el = doc.createElement('div');
  let fired = 0;
  PanelArrangeUI.longPress(el, 500, () => {
    fired += 1;
  });

  fire(el, 'touchstart', touch(10, 10));
  fire(el, 'touchmove', touch(16, 18)); // 6px right, 8px down = exactly 10px
  clock.advance(500);
  assert.equal(fired, 1);

  let firedAfterMove = 0;
  const other = doc.createElement('div');
  PanelArrangeUI.longPress(other, 500, () => {
    firedAfterMove += 1;
  });
  fire(other, 'touchstart', touch(10, 10));
  fire(other, 'touchmove', touch(30, 10)); // 20px
  clock.advance(1000);
  assert.equal(firedAfterMove, 0);
});

test('longPress is cancelled by touchend before the hold time', () => {
  const { PanelArrangeUI, clock } = loadArrangeUI(stubGrid());
  const doc = makeDocument();
  const el = doc.createElement('div');
  let fired = 0;
  PanelArrangeUI.longPress(el, 500, () => {
    fired += 1;
  });

  fire(el, 'touchstart', touch(10, 10));
  clock.advance(200);
  fire(el, 'touchend', touchEnd(10, 10));
  clock.advance(1000);
  assert.equal(fired, 0);
  assert.equal(clock.pendingCount(), 0);
});

test('longPress with a mouse fires when held still and is cancelled by a far move or by mouseup on the document', () => {
  const { PanelArrangeUI, clock } = loadArrangeUI(stubGrid());
  const doc = makeDocument();
  const el = doc.createElement('div');
  let fired = 0;
  PanelArrangeUI.longPress(el, 500, () => {
    fired += 1;
  });

  fire(el, 'mousedown', mouse(10, 10));
  clock.advance(500);
  assert.equal(fired, 1);

  fire(el, 'mousedown', mouse(10, 10));
  fire(doc, 'mousemove', mouse(10, 40)); // 30px
  clock.advance(1000);
  assert.equal(fired, 1);

  fire(el, 'mousedown', mouse(10, 10));
  fire(doc, 'mouseup', mouse(10, 10));
  clock.advance(1000);
  assert.equal(fired, 1);
});

test('longPress detach cancels a pending timer and removes every listener', () => {
  const { PanelArrangeUI, clock } = loadArrangeUI(stubGrid());
  const doc = makeDocument();
  const el = doc.createElement('div');
  let fired = 0;
  const detach = PanelArrangeUI.longPress(el, 500, () => {
    fired += 1;
  });

  fire(el, 'touchstart', touch(10, 10));
  assert.equal(clock.pendingCount(), 1);
  detach();
  assert.equal(clock.pendingCount(), 0);
  clock.advance(1000);
  assert.equal(fired, 0);

  assert.equal(el.listenerCount('touchstart'), 0);
  assert.equal(el.listenerCount('touchmove'), 0);
  assert.equal(el.listenerCount('mousedown'), 0);
  assert.equal(doc.listenerCount('mousemove'), 0);
  assert.equal(doc.listenerCount('mouseup'), 0);
});

// ---------- controller ----------

test('enter() adds the class and a toolbar listing registry types', () => {
  const c = setup();
  c.ui.enter();

  assert.equal(c.ui.isActive(), true);
  assert.equal(c.stage.classList.contains('pn-arranging'), true);
  const toolbar = one(c.stage, 'pn-toolbar');
  const select = one(toolbar, 'pn-arrange-type');
  assert.deepEqual(select.children.map((o) => o.value), ['clock', 'placeholder']);
  assert.deepEqual(select.children.map((o) => o.textContent), ['Clock', 'Placeholder']);
  assert.equal(one(toolbar, 'pn-arrange-add').textContent, 'Add');
  assert.equal(one(toolbar, 'pn-arrange-save').textContent, 'Save');
  assert.equal(one(toolbar, 'pn-arrange-cancel').textContent, 'Cancel');
});

test('enter() twice does not duplicate the toolbar', () => {
  const c = setup();
  c.ui.enter();
  c.ui.enter();
  assert.equal(findAll(c.stage, 'pn-toolbar').length, 1);
});

test('Add calls model.add with the selected type and onChange, and shows No space on null', () => {
  const c = setup();
  c.ui.enter();
  const toolbar = one(c.stage, 'pn-toolbar');
  const select = one(toolbar, 'pn-arrange-type');
  const add = one(toolbar, 'pn-arrange-add');

  select.value = 'placeholder';
  fire(add, 'click');
  assert.deepEqual(c.model.calls, [['add', 'placeholder']]);
  assert.equal(c.counters.change, 1);
  assert.equal(one(toolbar, 'pn-arrange-status').textContent, '');

  c.model.addFails = true;
  fire(add, 'click');
  assert.deepEqual(c.model.calls[1], ['add', 'placeholder']);
  assert.equal(one(toolbar, 'pn-arrange-status').textContent, 'No space');
  assert.equal(c.counters.change, 1);
});

test('Save is disabled when not dirty and enabled after a change', () => {
  const c = setup();
  c.ui.enter();
  const toolbar = one(c.stage, 'pn-toolbar');
  const save = one(toolbar, 'pn-arrange-save');
  assert.equal(save.disabled, true);

  fire(one(toolbar, 'pn-arrange-add'), 'click');
  assert.equal(save.disabled, false);
});

test('Save refreshes after a drag, and Save and Cancel call their callbacks', () => {
  const c = setup();
  c.ui.enter();
  const toolbar = one(c.stage, 'pn-toolbar');
  const save = one(toolbar, 'pn-arrange-save');
  const cancel = one(toolbar, 'pn-arrange-cancel');

  // Clicking Save while not dirty does nothing.
  fire(save, 'click');
  assert.equal(c.counters.save, 0);

  const tile = c.tileFor('a');
  fire(tile, 'mousedown', mouse(...centre(3, 1)));
  fire(c.doc, 'mousemove', mouse(...centre(4, 1)));
  fire(c.doc, 'mouseup', mouse(...centre(4, 1)));
  assert.equal(save.disabled, false);

  fire(save, 'click');
  assert.equal(c.counters.save, 1);
  fire(cancel, 'click');
  assert.equal(c.counters.cancel, 1);
});

test('attachTile adds a remove button and a resize handle', () => {
  const c = setup();
  c.ui.enter();
  const tile = c.tileFor('a');

  const remove = one(tile, 'pn-arrange-remove');
  assert.equal(remove.textContent, '×');
  one(tile, 'pn-arrange-resize');
});

test('touch drag moves the widget by the cell under the pointer minus the grab offset', () => {
  const c = setup();
  c.ui.enter();
  const tile = c.tileFor('a'); // origin (2,1)

  // Grab at cell (3,1): offset = (1,0).
  fire(tile, 'touchstart', touch(...centre(3, 1)));
  const moveEv = fire(tile, 'touchmove', touch(...centre(6, 4)));
  assert.equal(moveEv.defaultPrevented, true);
  // Same cell again: no second move call.
  fire(tile, 'touchmove', touch(...centre(6, 4)));
  fire(tile, 'touchend', touchEnd(...centre(6, 4)));

  assert.deepEqual(c.model.calls, [['move', 'a', 5, 4]]);
  assert.deepEqual(c.model.find('a').x, 5);
  assert.deepEqual(c.model.find('a').y, 4);
  assert.equal(c.counters.change, 1);
  assert.equal(c.stage.children.length, 2); // toolbar + tile
});

test('mouse drag moves the widget and detaches document listeners on mouseup', () => {
  const c = setup();
  c.ui.enter();
  const tile = c.tileFor('a');

  fire(tile, 'mousedown', mouse(...centre(3, 1)));
  fire(c.doc, 'mousemove', mouse(...centre(6, 4)));
  assert.deepEqual(c.model.calls, [['move', 'a', 5, 4]]);
  fire(c.doc, 'mouseup', mouse(...centre(6, 4)));

  assert.equal(c.doc.listenerCount('mousemove'), 0);
  assert.equal(c.doc.listenerCount('mouseup'), 0);
  fire(c.doc, 'mousemove', mouse(...centre(8, 4)));
  assert.equal(c.model.calls.length, 1);
});

test('a refused move does not call onChange', () => {
  const c = setup();
  c.ui.enter();
  const tile = c.tileFor('a');
  c.model.moveFails = true;

  fire(tile, 'mousedown', mouse(...centre(3, 1)));
  fire(c.doc, 'mousemove', mouse(...centre(6, 4)));
  fire(c.doc, 'mouseup', mouse(...centre(6, 4)));
  assert.equal(c.model.calls.length, 1);
  assert.equal(c.counters.change, 0);
});

test('resize handle calls model.resize with the cell under the pointer', () => {
  const c = setup();
  c.ui.enter();
  const tile = c.tileFor('a'); // origin (2,1)
  const resize = one(tile, 'pn-arrange-resize');

  fire(resize, 'mousedown', mouse(...centre(3, 2)));
  fire(c.doc, 'mousemove', mouse(...centre(5, 3)));
  fire(c.doc, 'mouseup', mouse(...centre(5, 3)));

  // w = 5 - 2 + 1 = 4, h = 3 - 1 + 1 = 3
  assert.deepEqual(c.model.calls, [['resize', 'a', 4, 3]]);
  assert.equal(c.model.find('a').w, 4);
  assert.equal(c.model.find('a').h, 3);
  assert.equal(c.counters.change, 1);
});

test('resize never goes below one cell', () => {
  const c = setup();
  c.ui.enter();
  const tile = c.tileFor('a');
  const resize = one(tile, 'pn-arrange-resize');

  fire(resize, 'mousedown', mouse(...centre(3, 2)));
  fire(c.doc, 'mousemove', mouse(...centre(0, 0)));
  fire(c.doc, 'mouseup', mouse(...centre(0, 0)));
  assert.deepEqual(c.model.calls, [['resize', 'a', 1, 1]]);
});

test('touch resize calls model.resize and prevents default on touchmove', () => {
  const c = setup();
  c.ui.enter();
  const tile = c.tileFor('a');
  const resize = one(tile, 'pn-arrange-resize');

  fire(resize, 'touchstart', touch(...centre(3, 2)));
  const ev = fire(resize, 'touchmove', touch(...centre(5, 3)));
  fire(resize, 'touchend', touchEnd(...centre(5, 3)));

  assert.equal(ev.defaultPrevented, true);
  assert.deepEqual(c.model.calls, [['resize', 'a', 4, 3]]);
});

test('the remove button calls model.remove, removes its handles, and calls onChange', () => {
  const c = setup();
  c.ui.enter();
  const tile = c.tileFor('a');
  const save = one(c.stage, 'pn-arrange-save');

  fire(one(tile, 'pn-arrange-remove'), 'click');

  assert.deepEqual(c.model.calls, [['remove', 'a']]);
  assert.equal(c.model.widgets().some((w) => w.id === 'a'), false);
  assert.equal(findAll(tile, 'pn-arrange-remove').length, 0);
  assert.equal(findAll(tile, 'pn-arrange-resize').length, 0);
  assert.equal(c.counters.change, 1);
  assert.equal(save.disabled, false);
});

test('handles stop propagation so the tile drag and the runtime swipe never see them', () => {
  const c = setup();
  c.ui.enter();
  const tile = c.tileFor('a');
  const resize = one(tile, 'pn-arrange-resize');
  const remove = one(tile, 'pn-arrange-remove');

  let bodyTouch = 0;
  let bodyMouse = 0;
  let tileSpy = 0;
  c.body.addEventListener('touchstart', () => {
    bodyTouch += 1;
  });
  c.body.addEventListener('mousedown', () => {
    bodyMouse += 1;
  });
  tile.addEventListener('mousedown', () => {
    tileSpy += 1;
  });

  const events = [
    fire(resize, 'touchstart', touch(...centre(3, 2))),
    fire(remove, 'touchstart', touch(...centre(2, 1))),
    fire(remove, 'mousedown', mouse(...centre(2, 1))),
  ];
  events.forEach((ev) => assert.equal(ev.propagationStopped, true, `${ev.type} was not stopped`));
  assert.equal(bodyTouch, 0);
  assert.equal(bodyMouse, 0);
  assert.equal(tileSpy, 0);
  // Handle presses do not start a move.
  assert.equal(c.model.calls.some((call) => call[0] === 'move'), false);

  // Clean up the touch resize, then check a mouse press on the resize handle.
  fire(resize, 'touchend', touchEnd(...centre(3, 2)));
  const mouseEv = fire(resize, 'mousedown', mouse(...centre(3, 2)));
  assert.equal(mouseEv.propagationStopped, true);
  assert.equal(bodyMouse, 0);
  assert.equal(tileSpy, 0);
  fire(c.doc, 'mouseup', mouse(...centre(3, 2)));

  const clickEv = fire(remove, 'click', {});
  assert.equal(clickEv.propagationStopped, true);
});

test('exit removes the toolbar, handles, class, and every listener', () => {
  const c = setup();
  c.ui.enter();
  const toolbar = one(c.stage, 'pn-toolbar');
  const save = one(toolbar, 'pn-arrange-save');
  const tile = c.tileFor('a');

  // Start a mouse drag so exit has to clean up document listeners too.
  fire(tile, 'mousedown', mouse(...centre(3, 1)));
  assert.equal(c.doc.listenerCount('mousemove'), 1);

  c.ui.exit();

  assert.equal(c.ui.isActive(), false);
  assert.equal(c.stage.classList.contains('pn-arranging'), false);
  assert.equal(findAll(c.stage, 'pn-toolbar').length, 0);
  assert.equal(findAll(tile, 'pn-arrange-remove').length, 0);
  assert.equal(findAll(tile, 'pn-arrange-resize').length, 0);
  assert.equal(c.doc.listenerCount('mousemove'), 0);
  assert.equal(c.doc.listenerCount('mouseup'), 0);
  assert.equal(tile.listenerCount('mousedown'), 0);
  assert.equal(tile.listenerCount('touchstart'), 0);
  assert.equal(tile.listenerCount('touchmove'), 0);
  assert.equal(tile.listenerCount('touchend'), 0);
  assert.equal(save.listenerCount('click'), 0);

  // After exit, pressing the tile does nothing.
  const before = c.model.calls.length;
  fire(tile, 'mousedown', mouse(...centre(3, 1)));
  fire(c.doc, 'mousemove', mouse(...centre(6, 4)));
  assert.equal(c.model.calls.length, before);
});

test('enter works again after exit', () => {
  const c = setup();
  c.ui.enter();
  c.ui.exit();
  c.ui.enter();
  assert.equal(findAll(c.stage, 'pn-toolbar').length, 1);
  assert.equal(c.stage.classList.contains('pn-arranging'), true);
});

test('attachTile is a no-op while not arranging', () => {
  const c = setup();
  c.tileFor('a');
  const tile = c.stage.children[c.stage.children.length - 1];
  assert.equal(findAll(tile, 'pn-arrange-remove').length, 0);
});

// ---------- module shape ----------

test('the module exports the API for Node', () => {
  const api = require(SOURCE_PATH);
  assert.equal(typeof api.create, 'function');
  assert.equal(typeof api.longPress, 'function');
});

test('the source stays ES5 (no arrows, let/const, classes, template literals, spread, or ES2015+ built-ins)', () => {
  assert.doesNotMatch(source, /=>/);
  assert.doesNotMatch(source, /\b(let|const|class)\s/);
  assert.doesNotMatch(source, /`/);
  assert.doesNotMatch(source, /\.\.\./);
  assert.doesNotMatch(source, /\.(find|includes|startsWith|endsWith|findIndex)\(/);
  assert.doesNotMatch(source, /Object\.assign|Array\.from|new (Map|Set|Promise)\b/);
});
