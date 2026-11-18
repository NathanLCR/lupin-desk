const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const MODULE_PATH = path.join(__dirname, '../../static/editor/editor-devices.js');
const EditorDevices = require(MODULE_PATH);

// ---- Minimal fake DOM -------------------------------------------------------

class FakeNode {
  constructor(doc, nodeName, data) {
    this.ownerDocument = doc;
    this.nodeName = nodeName;
    this.data = data === undefined ? '' : String(data);
    this.childList = [];
    this.parentNode = null;
    this.attributes = {};
    this.listeners = {};
    this.className = '';
    this.value = '';
    this.checked = false;
    this.disabled = false;
    this.draggable = false;
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
    const index = this.childList.indexOf(child);
    if (index !== -1) {
      this.childList.splice(index, 1);
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
    if (this.disabled) return;
    this.dispatch('click');
  }

  focus() {
    this.ownerDocument.activeElement = this;
  }

  blur() {
    if (this.ownerDocument.activeElement === this) this.ownerDocument.activeElement = null;
  }
}

class FakeDocument {
  constructor() {
    this.activeElement = null;
  }

  createElement(tag) {
    return new FakeNode(this, tag.toLowerCase());
  }

  createTextNode(text) {
    return new FakeNode(this, '#text', text);
  }
}

function all(root, predicate) {
  const out = [];
  (function visit(node) {
    if (node.nodeName !== '#text' && predicate(node)) out.push(node);
    node.childList.forEach(visit);
  })(root);
  return out;
}

const byClass = (root, cls) => all(root, (n) => n.className.split(/\s+/).includes(cls));
const byTag = (root, tag) => all(root, (n) => n.nodeName === tag);
const checkboxesIn = (root) => byTag(root, 'input').filter((n) => n.attributes.type === 'checkbox');
const buttonIn = (root, label) => byTag(root, 'button').find((n) => n.textContent === label);

// Every string a user could read from the DOM: text, attribute values, input values.
function visibleStrings(root) {
  const out = [];
  all(root, () => true).forEach((node) => {
    out.push(node.textContent);
    Object.values(node.attributes).forEach((v) => out.push(v));
    if (node.nodeName === 'input' || node.nodeName === 'select') out.push(String(node.value));
  });
  return out;
}

// ---- Fake api ---------------------------------------------------------------

const LAYOUTS = [
  { id: 'desk', name: 'Desk', updated_at: '2026-11-18T10:00:00Z' },
  { id: 'night', name: 'Night', updated_at: '2026-11-18T10:00:00Z' }
];

function deviceFixtures() {
  return [
    { id: 'body-a', name: 'Living Room Body', kind: 'body', roles: ['body', 'panel'], layout_id: 'desk', body_priority: 0, last_seen: '', screen: { width: 960, height: 720 }, connected: true, active: true },
    { id: 'body-b', name: 'Kitchen Body', kind: 'body', roles: ['body'], layout_id: null, body_priority: 1, last_seen: '2026-11-18T12:00:00Z', screen: null, connected: false, active: false },
    { id: 'body-c', name: 'Office Body', kind: 'body', roles: ['body', 'panel'], layout_id: 'night', body_priority: null, last_seen: '', screen: null, connected: false, active: false },
    { id: 'panel-d', name: 'Tablet', kind: 'panel', roles: ['panel'], layout_id: 'night', body_priority: null, last_seen: '', screen: null, connected: true, active: false },
    { id: 'mac', name: 'This Mac', kind: 'editor', roles: ['body'], layout_id: 'desk', body_priority: 5, last_seen: '', screen: null, connected: true, active: false }
  ];
}

function credentialFixtures() {
  return [
    { key: 'LLM_API_KEY', label: 'LLM API key', value: 'sk-old-0000' },
    { key: 'SEARCH_KEY', label: 'Search key', value: '' }
  ];
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function makeApi() {
  const store = {
    devices: clone(deviceFixtures()),
    secrets: {}
  };
  credentialFixtures().forEach((c) => { store.secrets[c.key] = c.value; });

  const calls = [];
  const failures = {};

  function maybeFail(method) {
    if (failures[method]) {
      const error = failures[method];
      delete failures[method];
      return Promise.reject(error);
    }
    return null;
  }

  function maskedCredentials() {
    return {
      credentials: credentialFixtures().map((c) => {
        const value = store.secrets[c.key] || '';
        return { key: c.key, label: c.label, set: value !== '', preview: value ? '••••' + value.slice(-4) : '' };
      })
    };
  }

  const api = {
    calls,
    failures,
    store,
    listDevices() {
      calls.push(['listDevices']);
      return maybeFail('listDevices') || Promise.resolve({ devices: clone(store.devices) });
    },
    updateDevice(id, fields) {
      calls.push(['updateDevice', id, clone(fields)]);
      const failed = maybeFail('updateDevice');
      if (failed) return failed;
      const device = store.devices.find((d) => d.id === id);
      Object.assign(device, clone(fields));
      return Promise.resolve(clone(device));
    },
    setPriority(order) {
      calls.push(['setPriority', order.slice()]);
      const failed = maybeFail('setPriority');
      if (failed) return failed;
      order.forEach((id, index) => {
        store.devices.find((d) => d.id === id).body_priority = index;
      });
      return Promise.resolve({ devices: clone(store.devices) });
    },
    getCredentials() {
      calls.push(['getCredentials']);
      return Promise.resolve(maskedCredentials());
    },
    saveCredentials(values) {
      calls.push(['saveCredentials', clone(values)]);
      const failed = maybeFail('saveCredentials');
      if (failed) return failed;
      Object.keys(values).forEach((key) => { store.secrets[key] = values[key]; });
      return Promise.resolve(maskedCredentials());
    }
  };
  return api;
}

// ---- Harness ----------------------------------------------------------------

const realSetInterval = globalThis.setInterval;
const realClearInterval = globalThis.clearInterval;
const intervals = new Map();
let nextIntervalId = 1;

globalThis.setInterval = (fn, ms) => {
  const id = nextIntervalId;
  nextIntervalId += 1;
  intervals.set(id, { fn, ms });
  return id;
};
globalThis.clearInterval = (id) => {
  intervals.delete(id);
};

test.after(() => {
  globalThis.setInterval = realSetInterval;
  globalThis.clearInterval = realClearInterval;
  delete globalThis.document;
});

const flush = () => new Promise((resolve) => setImmediate(resolve));

async function mountDevices(options) {
  const opts = options || {};
  intervals.clear();
  const doc = new FakeDocument();
  globalThis.document = doc;
  const container = doc.createElement('div');
  const api = makeApi();
  let layoutsChanged = 0;
  const handle = EditorDevices.mount(container, {
    api,
    onLayoutsChanged: () => { layoutsChanged += 1; }
  });
  handle.refresh(opts.layouts || LAYOUTS);
  await flush();
  return {
    doc,
    container,
    api,
    handle,
    layoutsChanged: () => layoutsChanged,
    deviceRows: () => byClass(container, 'device-row'),
    priorityNames: () => byClass(container, 'priority-name').map((n) => n.textContent),
    priorityRow: (name) => byClass(container, 'priority-row').find((li) => byClass(li, 'priority-name')[0].textContent === name),
    credentialRows: () => byClass(container, 'credential-row')
  };
}

// ---- Pure helpers -----------------------------------------------------------

test('formatLastSeen shows never for an empty value and local date/time otherwise', () => {
  assert.equal(EditorDevices.formatLastSeen(''), 'never');
  assert.equal(EditorDevices.formatLastSeen(null), 'never');
  assert.equal(EditorDevices.formatLastSeen(undefined), 'never');
  assert.equal(EditorDevices.formatLastSeen('not a date', new Date(2026, 10, 18)), 'unknown');

  const seen = new Date(2026, 10, 18, 14, 5);
  const iso = seen.toISOString();
  const pad = (n) => (n < 10 ? '0' + n : String(n));
  const sameDayNow = new Date(2026, 10, 18, 20, 0);
  const laterNow = new Date(2026, 10, 20, 9, 0);

  assert.equal(EditorDevices.formatLastSeen(iso, sameDayNow), 'Today 14:05');
  assert.equal(EditorDevices.formatLastSeen(iso, laterNow), '2026-11-18 ' + pad(14) + ':' + pad(5));
});

test('orderBodyDevices keeps only Body devices, sorts by priority with nulls last, and is stable', () => {
  const input = [
    { id: 'p', roles: ['panel'], body_priority: 0 },
    { id: 'n1', roles: ['body'], body_priority: null },
    { id: 'b', roles: ['body', 'panel'], body_priority: 2 },
    { id: 'a', roles: ['body'], body_priority: 1 },
    { id: 'n2', roles: ['body'], body_priority: null }
  ];
  const snapshot = clone(input);

  assert.deepEqual(EditorDevices.orderBodyDevices(input).map((d) => d.id), ['a', 'b', 'n1', 'n2']);
  assert.deepEqual(input, snapshot, 'input must not be mutated');
  assert.deepEqual(EditorDevices.orderBodyDevices(null), []);
});

test('moveId moves one id by delta, clamps at the ends, and copies unknown input', () => {
  const ids = ['a', 'b', 'c'];
  assert.deepEqual(EditorDevices.moveId(ids, 'c', -1), ['a', 'c', 'b']);
  assert.deepEqual(EditorDevices.moveId(ids, 'b', 1), ['a', 'c', 'b']);
  assert.deepEqual(EditorDevices.moveId(ids, 'a', -1), ['a', 'b', 'c']);
  assert.deepEqual(EditorDevices.moveId(ids, 'a', 5), ['b', 'c', 'a']);
  assert.deepEqual(EditorDevices.moveId(ids, 'x', 1), ['a', 'b', 'c']);
  assert.deepEqual(ids, ['a', 'b', 'c'], 'input must not be mutated');
});

test('the module never uses innerHTML', () => {
  const source = fs.readFileSync(MODULE_PATH, 'utf8');
  assert.doesNotMatch(source, /innerHTML/);
});

// ---- Devices section --------------------------------------------------------

test('device rows render for every non-editor device with its state', async () => {
  const view = await mountDevices();
  const rows = view.deviceRows();
  assert.equal(rows.length, 4, 'editor kind is excluded');

  const living = rows[0];
  const nameInput = byTag(living, 'input')[0];
  assert.equal(nameInput.value, 'Living Room Body');
  assert.match(living.textContent, /Active Body/);
  assert.match(living.textContent, /960x720/);
  assert.match(living.textContent, /Last seen: never/);

  const kitchen = rows[1];
  assert.doesNotMatch(kitchen.textContent, /Active Body/);
  assert.equal(
    byClass(kitchen, 'device-seen')[0].textContent,
    'Last seen: ' + EditorDevices.formatLastSeen('2026-11-18T12:00:00Z')
  );

  const selects = byTag(living, 'select');
  assert.deepEqual(byTag(selects[0], 'option').map((o) => o.textContent), ['(none)', 'Desk', 'Night']);
  assert.equal(selects[0].value, 'desk');
  assert.equal(byTag(kitchen, 'select')[0].value, '');

  assert.deepEqual(view.priorityNames(), ['Living Room Body', 'Kitchen Body', 'Office Body']);
});

test('changing a role calls updateDevice with the new roles', async () => {
  const view = await mountDevices();
  const panelBox = checkboxesIn(view.deviceRows()[0])[1];
  panelBox.checked = false;
  panelBox.dispatch('change');
  await flush();

  assert.deepEqual(view.api.calls.filter((c) => c[0] === 'updateDevice'), [
    ['updateDevice', 'body-a', { roles: ['body'] }]
  ]);
});

test('unchecking the last role is refused, reverted and shown as an alert', async () => {
  const view = await mountDevices();
  const bodyBox = checkboxesIn(view.deviceRows()[1])[0];
  bodyBox.checked = false;
  bodyBox.dispatch('change');
  await flush();

  assert.equal(view.api.calls.filter((c) => c[0] === 'updateDevice').length, 0);
  const alert = byTag(view.container, 'p').find((p) => p.attributes.role === 'alert');
  assert.match(alert.textContent, /at least one role/);
  assert.equal(checkboxesIn(view.deviceRows()[1])[0].checked, true);
});

test('renaming saves once on change and blur', async () => {
  const view = await mountDevices();
  const nameInput = byTag(view.deviceRows()[1], 'input')[0];
  nameInput.value = 'Kitchen Renamed';
  nameInput.dispatch('change');
  nameInput.dispatch('blur');
  await flush();

  assert.deepEqual(view.api.calls.filter((c) => c[0] === 'updateDevice'), [
    ['updateDevice', 'body-b', { name: 'Kitchen Renamed' }]
  ]);
  assert.equal(byTag(view.deviceRows()[1], 'input')[0].value, 'Kitchen Renamed');
});

test('changing the layout sends layout_id (null for none) and notifies the parent', async () => {
  const view = await mountDevices();
  const select = byTag(view.deviceRows()[1], 'select')[0];
  select.value = 'night';
  select.dispatch('change');
  await flush();

  const select2 = byTag(view.deviceRows()[0], 'select')[0];
  select2.value = '';
  select2.dispatch('change');
  await flush();

  assert.deepEqual(view.api.calls.filter((c) => c[0] === 'updateDevice'), [
    ['updateDevice', 'body-b', { layout_id: 'night' }],
    ['updateDevice', 'body-a', { layout_id: null }]
  ]);
  assert.equal(view.layoutsChanged(), 2);
});

test('an up button reorders Body priority through setPriority and re-renders from the response', async () => {
  const view = await mountDevices();
  const officeUp = buttonIn(view.priorityRow('Office Body'), 'Up');
  assert.equal(officeUp.attributes['aria-label'], 'Move Office Body up');
  officeUp.click();
  await flush();

  assert.deepEqual(view.api.calls.filter((c) => c[0] === 'setPriority'), [
    ['setPriority', ['body-a', 'body-c', 'body-b']]
  ]);
  assert.deepEqual(view.priorityNames(), ['Living Room Body', 'Office Body', 'Kitchen Body']);
});

test('dragging a Body row onto another calls setPriority with the new order', async () => {
  const view = await mountDevices();
  const dataTransfer = { data: {}, setData(key, value) { this.data[key] = value; } };

  view.priorityRow('Living Room Body').dispatch('dragstart', { dataTransfer });
  view.priorityRow('Office Body').dispatch('dragover', { dataTransfer });
  view.priorityRow('Office Body').dispatch('drop', { dataTransfer });
  await flush();

  assert.deepEqual(view.api.calls.filter((c) => c[0] === 'setPriority'), [
    ['setPriority', ['body-b', 'body-c', 'body-a']]
  ]);
  assert.deepEqual(view.priorityNames(), ['Kitchen Body', 'Office Body', 'Living Room Body']);
});

test('a rejected call shows its message in an alert and reverts the field', async () => {
  const view = await mountDevices();
  view.api.failures.updateDevice = new Error('Device is busy');
  const nameInput = byTag(view.deviceRows()[0], 'input')[0];
  nameInput.value = 'Renamed';
  nameInput.dispatch('change');
  await flush();

  const alert = byTag(view.container, 'p').find((p) => p.attributes.role === 'alert' && p.textContent !== '');
  assert.equal(alert.textContent, 'Device is busy');
  assert.equal(byTag(view.deviceRows()[0], 'input')[0].value, 'Living Room Body');
});

test('the 5 second refresh runs while mounted, keeps a focused input, and stops on destroy', async () => {
  const view = await mountDevices();
  assert.equal(intervals.size, 1);
  const [{ fn, ms }] = intervals.values();
  assert.equal(ms, 5000);

  const nameInput = byTag(view.deviceRows()[0], 'input')[0];
  nameInput.focus();
  nameInput.value = 'draft name';
  const listsBefore = view.api.calls.filter((c) => c[0] === 'listDevices').length;
  fn();
  await flush();
  assert.equal(view.api.calls.filter((c) => c[0] === 'listDevices').length, listsBefore + 1);
  assert.equal(byTag(view.deviceRows()[0], 'input')[0], nameInput, 'focused input is not redrawn');
  assert.equal(nameInput.value, 'draft name');

  nameInput.blur();
  fn();
  await flush();
  assert.equal(byTag(view.deviceRows()[0], 'input')[0].value, 'Living Room Body');

  view.handle.destroy();
  assert.equal(intervals.size, 0);
  assert.equal(view.container.childList.length, 0);
});

// ---- Credentials section ----------------------------------------------------

test('credential rows show status and masked preview, with an empty password input', async () => {
  const view = await mountDevices();
  const [llm, search] = view.credentialRows();

  assert.match(llm.textContent, /LLM API key/);
  assert.match(llm.textContent, /Set \(••••0000\)/);
  assert.match(search.textContent, /Not set/);

  const llmInput = byTag(llm, 'input')[0];
  assert.equal(llmInput.attributes.type, 'password');
  assert.equal(llmInput.attributes.placeholder, 'Enter new value');
  assert.equal(llmInput.attributes.autocomplete, 'off');
  assert.equal(llmInput.value, '');

  assert.ok(view.container.textContent.includes('Stored in .env on this Mac. Never sent to devices.'));
});

test('saving a credential sends only the typed key, clears the input, and never shows the full value', async () => {
  const view = await mountDevices();
  const secret = 'sk-new-SECRET-9876';
  const logged = [];
  const originals = {};
  ['log', 'info', 'warn', 'error', 'debug'].forEach((method) => {
    originals[method] = console[method];
    console[method] = (...args) => { logged.push(args.map(String).join(' ')); };
  });

  try {
    const [llm] = view.credentialRows();
    const input = byTag(llm, 'input')[0];
    input.value = secret;
    buttonIn(llm, 'Save').click();
    await flush();

    assert.deepEqual(view.api.calls.filter((c) => c[0] === 'saveCredentials'), [
      ['saveCredentials', { LLM_API_KEY: secret }]
    ]);

    const [llmAfter] = view.credentialRows();
    assert.equal(byTag(llmAfter, 'input')[0].value, '');
    assert.match(llmAfter.textContent, /Set \(••••9876\)/);

    const everything = visibleStrings(view.container).join('\n');
    assert.ok(!everything.includes(secret), 'full secret must not appear in the DOM');
    assert.ok(!everything.includes('SECRET-9876'), 'secret fragments must not appear in the DOM');
    assert.ok(!logged.some((line) => line.includes('SECRET')), 'secret must not be logged');
  } finally {
    Object.keys(originals).forEach((method) => { console[method] = originals[method]; });
  }
});

test('Save with an empty input sends nothing and shows an alert', async () => {
  const view = await mountDevices();
  const [llm] = view.credentialRows();
  buttonIn(llm, 'Save').click();
  await flush();

  assert.equal(view.api.calls.filter((c) => c[0] === 'saveCredentials').length, 0);
  const alert = byTag(view.container, 'p').find((p) => p.attributes.role === 'alert' && p.textContent !== '');
  assert.match(alert.textContent, /Type a new value first/);
});

test('Clear sends an empty string for that key only and shows Not set', async () => {
  const view = await mountDevices();
  const [llm] = view.credentialRows();
  buttonIn(llm, 'Clear').click();
  await flush();

  assert.deepEqual(view.api.calls.filter((c) => c[0] === 'saveCredentials'), [
    ['saveCredentials', { LLM_API_KEY: '' }]
  ]);
  const [llmAfter] = view.credentialRows();
  assert.match(llmAfter.textContent, /Not set/);
  assert.equal(byTag(llmAfter, 'input')[0].value, '');
});
