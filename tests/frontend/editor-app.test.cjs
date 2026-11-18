const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const MODULE_PATH = path.join(__dirname, '../../static/editor/editor.js');
const EditorApp = require(MODULE_PATH);
const PanelRegistry = require(path.join(__dirname, '../../static/panel/registry.js'));

class FakeNode {
  constructor(doc, nodeName, data) {
    this.ownerDocument = doc;
    this.nodeName = nodeName;
    this.data = data === undefined ? '' : String(data);
    this.childList = [];
    this.parentNode = null;
    this.attributes = {};
    this.listeners = {};
    this.style = {};
    this.className = '';
    this.value = '';
    this.checked = false;
    this.disabled = false;
  }

  get firstChild() {
    return this.childList[0] || null;
  }

  get textContent() {
    if (this.nodeName === '#text') return this.data;
    return this.childList.map((child) => child.textContent).join('');
  }

  set textContent(value) {
    this.childList.forEach((child) => { child.parentNode = null; });
    this.childList = [];
    if (value !== '' && value !== null && value !== undefined) {
      this.appendChild(this.ownerDocument.createTextNode(String(value)));
    }
  }

  appendChild(child) {
    if (child.parentNode) child.parentNode.removeChild(child);
    child.parentNode = this;
    this.childList.push(child);
    return child;
  }

  removeChild(child) {
    const i = this.childList.indexOf(child);
    if (i !== -1) {
      this.childList.splice(i, 1);
      child.parentNode = null;
    }
    return child;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;
  }

  addEventListener(type, fn) {
    (this.listeners[type] = this.listeners[type] || []).push(fn);
  }

  dispatch(type, extra) {
    const event = Object.assign({ type, target: this, preventDefault() {} }, extra || {});
    (this.listeners[type] || []).slice().forEach((fn) => fn.call(this, event));
    return event;
  }

  click() {
    if (!this.disabled) this.dispatch('click');
  }
}

class FakeDocument {
  createElement(tag) {
    return new FakeNode(this, tag.toLowerCase());
  }

  createTextNode(text) {
    return new FakeNode(this, '#text', text);
  }
}

function all(root, pred) {
  const out = [];
  (function visit(node) {
    if (node.nodeName !== '#text' && pred(node)) out.push(node);
    node.childList.forEach(visit);
  })(root);
  return out;
}

const byTag = (root, tag) => all(root, (n) => n.nodeName === tag);
const byClass = (root, cls) => all(root, (n) => n.className.split(/\s+/).includes(cls));
const byAria = (root, label) => all(root, (n) => n.getAttribute('aria-label') === label)[0];
const button = (root, text) => byTag(root, 'button').find((n) => n.textContent === text);

async function flush() {
  for (let i = 0; i < 6; i += 1) await Promise.resolve();
}

function starterDoc() {
  return {
    id: 'starter',
    name: 'Starter',
    version: 1,
    grid: { landscape: { cols: 12, rows: 6 }, portrait: { cols: 6, rows: 12 } },
    pages: [
      {
        id: 'home',
        title: 'Home',
        landscape: [{ id: 'clock-1', type: 'clock', x: 0, y: 0, w: 4, h: 2, config: {} }],
        portrait: [{ id: 'clock-1', type: 'clock', x: 0, y: 0, w: 6, h: 4, config: {} }],
      },
    ],
  };
}

function makeRegistry() {
  const reg = PanelRegistry.create();
  reg.register({ id: 'clock', title: 'Clock', sizes: { default: { w: 4, h: 2 } }, render: () => null });
  reg.register({ id: 'notes', title: 'Notes', sizes: { default: { w: 3, h: 3 } }, render: () => null });
  return reg;
}

function makeFakeApi({ isMac = true } = {}) {
  const layouts = new Map([['starter', starterDoc()]]);
  const calls = [];
  return {
    calls,
    async getClientInfo() {
      calls.push('getClientInfo');
      return { is_mac: isMac };
    },
    async listLayouts() {
      calls.push('listLayouts');
      return {
        layouts: Array.from(layouts.values()).map((l) => ({ id: l.id, name: l.name, updated_at: '2026-11-18T00:00:00Z' })),
      };
    },
    async listTemplates() {
      calls.push('listTemplates');
      return { templates: [{ id: 'starter', name: 'Starter' }, { id: 'home', name: 'Home' }] };
    },
    async getLayout(id) {
      calls.push(`getLayout:${id}`);
      return JSON.parse(JSON.stringify(layouts.get(id)));
    },
    async createLayout(name, template) {
      calls.push(`createLayout:${name}:${template}`);
      const id = name.toLowerCase().replace(/[^a-z0-9]+/g, '-');
      const doc = Object.assign(starterDoc(), { id, name });
      layouts.set(id, doc);
      return JSON.parse(JSON.stringify(doc));
    },
    async saveLayout(id, payload) {
      calls.push(`saveLayout:${id}`);
      const saved = Object.assign(JSON.parse(JSON.stringify(payload)), { id });
      layouts.set(id, saved);
      return JSON.parse(JSON.stringify(saved));
    },
    async deleteLayout(id) {
      calls.push(`deleteLayout:${id}`);
      layouts.delete(id);
      return { ok: true };
    },
  };
}

function makeStubs() {
  const events = [];
  const winListeners = {};
  const win = {
    location: { protocol: 'http:', host: '127.0.0.1:8000' },
    addEventListener(type, fn) {
      (winListeners[type] = winListeners[type] || []).push(fn);
    },
    removeEventListener(type, fn) {
      winListeners[type] = (winListeners[type] || []).filter((f) => f !== fn);
    },
  };
  const devices = {
    refreshes: [],
    destroyed: false,
    mount() {
      return {
        refresh: (l) => devices.refreshes.push(l),
        destroy: () => { devices.destroyed = true; },
      };
    },
  };
  const preview = {
    shows: [],
    liveStates: [],
    destroyed: false,
    create() {
      return {
        show: (layout, pageId, orientation, size) => preview.shows.push({ layout, pageId, orientation, size }),
        setLive: (on) => preview.liveStates.push(on),
        destroy: () => { preview.destroyed = true; },
      };
    },
  };
  return { win, winListeners, devices, preview, events };
}

test('editor.js never uses innerHTML', () => {
  const source = fs.readFileSync(MODULE_PATH, 'utf8');
  assert.equal(source.includes('innerHTML'), false);
});

test('non-Mac client renders a notice and skips loading layouts or devices', async () => {
  const doc = new FakeDocument();
  const root = doc.createElement('div');
  const api = makeFakeApi({ isMac: false });
  const stubs = makeStubs();

  const handle = EditorApp.mount(root, {
    doc,
    win: stubs.win,
    api,
    registry: makeRegistry(),
    devices: stubs.devices,
    preview: stubs.preview,
  });
  await handle.ready;

  assert.deepEqual(api.calls, ['getClientInfo']);
  assert.ok(root.textContent.includes('only available on the Mac'));
  assert.equal(stubs.preview.shows.length, 0);
  assert.equal(stubs.devices.refreshes.length, 0);
  handle.destroy();
});

test('Mac editor loads layout, edits pages/widgets/config, saves, creates, duplicates, deletes and cleans up', async () => {
  const doc = new FakeDocument();
  const root = doc.createElement('div');
  const api = makeFakeApi({ isMac: true });
  const stubs = makeStubs();

  const handle = EditorApp.mount(root, {
    doc,
    win: stubs.win,
    api,
    registry: makeRegistry(),
    devices: stubs.devices,
    preview: stubs.preview,
  });
  await handle.ready;

  assert.equal(byClass(root, 'ed-grid-dims')[0].textContent, '12 × 6');
  assert.equal(button(root, 'Save').disabled, true);
  assert.equal(button(root, 'Delete').disabled, true);
  assert.ok(stubs.preview.shows.length >= 1);

  // Add a widget and edit its position and JSON config.
  byAria(root, 'Widget type').value = 'notes';
  button(root, 'Add widget').click();
  assert.equal(byClass(root, 'ed-tile').length, 2);
  assert.equal(button(root, 'Save').disabled, false);

  const wInput = byAria(root, 'Widget W');
  wInput.value = '4';
  wInput.dispatch('change');
  assert.equal(wInput.value, '4');

  const cfgArea = byAria(root, 'Widget config JSON');
  cfgArea.value = '{"limit": 5}';
  button(root, 'Apply config').click();

  // Invalid JSON shows alert without crashing (re-query because renderInspector rebuilt the textarea).
  byAria(root, 'Widget config JSON').value = '{bad';
  button(root, 'Apply config').click();
  assert.ok(byClass(root, 'editor-error')[0].textContent.includes('valid JSON'));

  // Add and rename page, switch orientation, copy variant.
  button(root, 'Add page').click();
  assert.equal(byClass(root, 'ed-tab').length, 2);
  const pageTitle = byAria(root, 'Page title');
  pageTitle.value = 'Work';
  button(root, 'Rename page').click();
  assert.equal(byClass(root, 'ed-tab')[1].textContent, 'Work');

  button(root, 'Portrait').click();
  assert.equal(byClass(root, 'ed-grid-dims')[0].textContent, '6 × 12');

  // Save layout.
  button(root, 'Save').click();
  await flush();
  assert.ok(api.calls.includes('saveLayout:starter'));
  assert.equal(button(root, 'Save').disabled, true);

  // Preview preset and Live checkbox.
  const presetSelect = byAria(root, 'Preview device size');
  presetSelect.value = '600x800';
  presetSelect.dispatch('change');
  assert.deepEqual(stubs.preview.shows.at(-1).size, { width: 600, height: 800 });

  const liveBox = byTag(root, 'input').find((n) => n.attributes.type === 'checkbox');
  liveBox.checked = true;
  liveBox.dispatch('change');
  assert.deepEqual(stubs.preview.liveStates, [true]);

  // Create from template, duplicate, and delete.
  byAria(root, 'New layout name').value = 'Desk Mode';
  button(root, 'Create').click();
  await flush();
  assert.ok(api.calls.includes('createLayout:Desk Mode:starter'));
  assert.equal(button(root, 'Delete').disabled, false);

  button(root, 'Duplicate').click();
  await flush();
  assert.ok(api.calls.some((c) => c.startsWith('createLayout:Desk Mode copy')));

  button(root, 'Delete').click();
  await flush();
  assert.ok(api.calls.some((c) => c.startsWith('deleteLayout:')));

  handle.destroy();
  assert.equal(stubs.devices.destroyed, true);
  assert.equal(stubs.preview.destroyed, true);
  assert.equal(root.childList.length, 0);
  assert.equal((stubs.winListeners.mousemove || []).length, 0);
});
