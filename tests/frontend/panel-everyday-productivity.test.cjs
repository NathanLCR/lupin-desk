const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

const { makeDocument, findAll } = require('./panel-fakes.cjs');
const PanelWidgets = require(path.join(__dirname, '../../static/panel/widgets-productivity.js'));
const PanelRegistry = require(path.join(__dirname, '../../static/panel/registry.js'));

const TASKS_URL = '/api/tasks?include_done=true';
const HOLD = { hold: true };

// Tiny XMLHttpRequest stub answering by URL. Unknown URLs get HTTP 404; 'network' fails;
// HOLD keeps the request open until the test calls respond() on it.
function makeXhrStub(answers) {
  const calls = [];
  const held = [];

  class StubXhr {
    constructor() {
      this.url = '';
      this.status = 0;
      this.responseText = '';
      this.onload = null;
      this.onerror = null;
      this.ontimeout = null;
    }

    open(method, url) {
      this.url = url;
    }

    send() {
      calls.push(this.url);
      if (!Object.prototype.hasOwnProperty.call(answers, this.url)) {
        this.status = 404;
        this.onload();
        return;
      }
      const answer = answers[this.url];
      if (answer === HOLD) {
        held.push(this);
        return;
      }
      if (answer === 'network') {
        this.onerror();
        return;
      }
      this.respond(answer);
    }

    respond(data) {
      this.status = 200;
      this.responseText = JSON.stringify(data);
      this.onload();
    }
  }

  return { Xhr: StubXhr, calls, held };
}

// Renders one widget definition into a fresh fake host, with the GET answered by the stub.
function renderDef(id, answers, sent) {
  const stub = makeXhrStub(answers);
  const previous = global.XMLHttpRequest;
  global.XMLHttpRequest = stub.Xhr;
  const doc = makeDocument();
  const host = doc.createElement('div');
  doc.body.appendChild(host);
  const def = PanelWidgets.DEFS.filter((d) => d.id === id)[0];
  let instance;
  try {
    instance = def.render(host, {
      config: {},
      size: { width: 0, height: 0 },
      sendAction: (actionId, args) => sent.push([actionId, args]),
      now: () => 0,
      el: host,
    });
  } finally {
    global.XMLHttpRequest = previous;
  }
  return { host, instance, stub, calls: stub.calls };
}

function byClass(root, name) {
  return findAll(root, (node) => !!node.classList && node.classList.contains(name));
}

function texts(root, name) {
  return byClass(root, name).map((node) => node.textContent);
}

function statusText(host) {
  return byClass(host, 'pn-status')[0].textContent;
}

test('orderTasks puts open tasks first and keeps each group in arrival order', () => {
  const ordered = PanelWidgets.orderTasks([
    { id: 1, title: 'a', done: true },
    { id: 2, title: 'b', done: false },
    { id: 3, title: 'c', done: true },
    { id: 4, title: 'd' },
  ]);
  assert.deepEqual(ordered.map((t) => t.id), [2, 4, 1, 3]);
  assert.deepEqual(PanelWidgets.orderTasks({ tasks: [{ id: 9, done: false }] }).map((t) => t.id), [9]);
  assert.deepEqual(PanelWidgets.orderTasks(null), []);
});

test('orderNotes sorts newest first and keeps notes without a date at the end', () => {
  const ordered = PanelWidgets.orderNotes([
    { id: 1, text: 'old', created_at: '2026-01-01T00:00:00Z' },
    { id: 2, text: 'undated' },
    { id: 3, text: 'new', created_at: '2026-03-01T00:00:00Z' },
    { id: 4, text: 'mid', created_at: '2026-02-01T00:00:00Z' },
  ]);
  assert.deepEqual(ordered.map((n) => n.id), [3, 4, 1, 2]);
  assert.deepEqual(PanelWidgets.orderNotes(undefined), []);
});

test('normalizeList always returns an array of records with an id', () => {
  assert.deepEqual(PanelWidgets.normalizeList(undefined, 'tasks'), []);
  assert.deepEqual(PanelWidgets.normalizeList(null, 'tasks'), []);
  assert.deepEqual(PanelWidgets.normalizeList('text', 'tasks'), []);
  assert.deepEqual(PanelWidgets.normalizeList(42, 'tasks'), []);
  assert.deepEqual(PanelWidgets.normalizeList({ tasks: 'nope' }, 'tasks'), []);
  assert.deepEqual(
    PanelWidgets.normalizeList({ tasks: [{ id: 1 }, null, 'x', { title: 'no id' }, { id: '' }] }, 'tasks'),
    [{ id: 1 }],
  );
  assert.deepEqual(PanelWidgets.normalizeList([{ id: 7 }], 'notes'), [{ id: 7 }]);
});

test('checklist renders the GET result with open tasks first and done ones struck through', () => {
  const sent = [];
  const { host, calls } = renderDef('checklist', {
    [TASKS_URL]: {
      tasks: [
        { id: 1, title: 'Done one', done: true },
        { id: 2, title: 'Open', done: false },
      ],
    },
  }, sent);

  assert.deepEqual(calls, [TASKS_URL]);
  const rows = byClass(host, 'pn-task');
  assert.equal(rows.length, 2);
  assert.equal(texts(host, 'pn-task-title')[0], 'Open');
  assert.equal(rows[0].classList.contains('pn-done'), false);
  assert.equal(rows[1].classList.contains('pn-done'), true);
  assert.equal(statusText(host), '');
});

test('checklist topic update re-renders the list as the full truth', () => {
  const sent = [];
  const { host, instance } = renderDef('checklist', { [TASKS_URL]: { tasks: [] } }, sent);
  assert.equal(statusText(host), 'No tasks yet.');

  instance.onTopic('tasks', { tasks: [{ id: 5, title: 'Pay rent', done: false }] });
  assert.deepEqual(texts(host, 'pn-task-title'), ['Pay rent']);
  assert.equal(statusText(host), '');

  instance.onTopic('tasks', { tasks: [] });
  assert.equal(byClass(host, 'pn-task').length, 0);
  assert.equal(statusText(host), 'No tasks yet.');
});

test('checklist toggle, remove and add send the exact action ids and args', () => {
  const sent = [];
  const { host } = renderDef('checklist', {
    [TASKS_URL]: { tasks: [{ id: 2, title: 'Open', done: false }] },
  }, sent);

  byClass(host, 'pn-check-row')[0].fire('click');
  byClass(host, 'pn-remove')[0].fire('click');

  const input = byClass(host, 'pn-input')[0];
  input.value = '  Buy milk  ';
  byClass(host, 'pn-add-btn')[0].fire('click');
  assert.equal(input.value, '');

  input.value = 'Call mum';
  input.fire('keydown', { key: 'Enter' });
  assert.equal(input.value, '');

  input.value = '   ';
  byClass(host, 'pn-add-btn')[0].fire('click');
  input.value = 'Other';
  input.fire('keydown', { key: 'a' });

  assert.deepEqual(sent, [
    ['tasks.toggle', { id: 2 }],
    ['tasks.remove', { id: 2 }],
    ['tasks.add', { title: 'Buy milk' }],
    ['tasks.add', { title: 'Call mum' }],
  ]);
});

test('checklist ignores topics it does not follow and stops after destroy', () => {
  const sent = [];
  const { host, instance } = renderDef('checklist', { [TASKS_URL]: { tasks: [] } }, sent);

  instance.onTopic('notes', { notes: [{ id: 1, text: 'nope' }] });
  assert.equal(byClass(host, 'pn-task').length, 0);

  instance.destroy();
  instance.onTopic('tasks', { tasks: [{ id: 3, title: 'late', done: false }] });
  assert.equal(byClass(host, 'pn-task').length, 0);
});

test('a GET answer that arrives after a topic update does not overwrite it', () => {
  const sent = [];
  const { host, instance, stub } = renderDef('checklist', { [TASKS_URL]: HOLD }, sent);
  instance.onTopic('tasks', { tasks: [{ id: 1, title: 'From topic', done: false }] });

  stub.held[0].respond({ tasks: [{ id: 2, title: 'Stale GET', done: false }] });
  assert.deepEqual(texts(host, 'pn-task-title'), ['From topic']);
});

test('checklist shows an error text when the GET fails and recovers from the topic', () => {
  const sent = [];
  const { host, instance } = renderDef('checklist', { [TASKS_URL]: 'network' }, sent);
  assert.equal(statusText(host), 'Could not load tasks.');

  instance.onTopic('tasks', { tasks: [{ id: 4, title: 'Back', done: false }] });
  assert.deepEqual(texts(host, 'pn-task-title'), ['Back']);
});

test('checklist survives odd data without throwing', () => {
  const sent = [];
  const { host, instance } = renderDef('checklist', { [TASKS_URL]: { tasks: 'bad' } }, sent);
  assert.equal(statusText(host), 'No tasks yet.');

  instance.onTopic('tasks', null);
  instance.onTopic('tasks', undefined);
  instance.onTopic('tasks', 'garbage');
  assert.equal(byClass(host, 'pn-task').length, 0);

  instance.onTopic('tasks', { tasks: [{ id: 8, done: true }, { id: 9, title: { odd: true } }] });
  assert.equal(byClass(host, 'pn-task').length, 2);
});

test('notes renders newest first and sends notes.add and notes.remove', () => {
  const sent = [];
  const { host } = renderDef('notes', {
    '/api/notes': {
      notes: [
        { id: 1, text: 'old', created_at: '2026-01-01T00:00:00Z' },
        { id: 2, text: 'new', created_at: '2026-02-01T00:00:00Z' },
      ],
    },
  }, sent);

  assert.deepEqual(texts(host, 'pn-note-text'), ['new', 'old']);

  byClass(host, 'pn-remove')[0].fire('click');
  const input = byClass(host, 'pn-input')[0];
  input.value = ' Idea ';
  byClass(host, 'pn-add-btn')[0].fire('click');

  assert.deepEqual(sent, [
    ['notes.remove', { id: 2 }],
    ['notes.add', { text: 'Idea' }],
  ]);
});

test('a note containing markup stays literal text', () => {
  const sent = [];
  const { host, instance } = renderDef('notes', { '/api/notes': { notes: [] } }, sent);
  instance.onTopic('notes', { notes: [{ id: 3, text: '<b>x</b>', created_at: '2026-02-01T00:00:00Z' }] });

  const noteText = byClass(host, 'pn-note-text');
  assert.equal(noteText.length, 1);
  assert.equal(noteText[0].textContent, '<b>x</b>');
  assert.equal(noteText[0].children.length, 0);
  assert.equal(findAll(host, (node) => node.tagName === 'B').length, 0);
});

test('habits shows streak only when positive, the time when set, and done rows', () => {
  const sent = [];
  const { host } = renderDef('habits', {
    '/api/habits': {
      habits: [
        { id: 3, name: 'Water', days: [], time: '08:00', created_at: 'x', streak: 4, done_today: false },
        { id: 4, name: 'Read', days: [], time: null, created_at: 'x', streak: 0, done_today: true },
      ],
    },
  }, sent);

  assert.deepEqual(texts(host, 'pn-habit-name'), ['Water', 'Read']);
  assert.deepEqual(texts(host, 'pn-habit-streak'), ['4 day streak']);
  assert.deepEqual(texts(host, 'pn-habit-time'), ['08:00']);

  const rows = byClass(host, 'pn-habit');
  assert.equal(rows[0].classList.contains('pn-done'), false);
  assert.equal(rows[1].classList.contains('pn-done'), true);

  const checks = byClass(host, 'pn-check');
  checks[0].fire('click');
  checks[1].fire('click');
  assert.deepEqual(sent, [
    ['habits.checkin', { id: 3, done: true }],
    ['habits.checkin', { id: 4, done: false }],
  ]);
});

test('habits topic update re-renders and empty data shows a text state', () => {
  const sent = [];
  const { host, instance } = renderDef('habits', { '/api/habits': { habits: [] } }, sent);
  assert.equal(statusText(host), 'No habits yet.');

  instance.onTopic('habits', { habits: [{ id: 5, name: 'Stretch', streak: -2, done_today: false }] });
  assert.deepEqual(texts(host, 'pn-habit-name'), ['Stretch']);
  assert.equal(byClass(host, 'pn-habit-streak').length, 0);
  assert.equal(statusText(host), '');
});

test('habits without data or with a failed GET never throws', () => {
  const sent = [];
  const failed = renderDef('habits', { '/api/habits': 'network' }, sent);
  assert.equal(statusText(failed.host), 'Could not load habits.');

  const odd = renderDef('habits', { '/api/habits': {} }, sent);
  assert.equal(statusText(odd.host), 'No habits yet.');
  odd.instance.onTopic('habits', [{ id: 6, name: 'Plain' }]);
  assert.deepEqual(texts(odd.host, 'pn-habit-name'), ['Plain']);
});

test('registerAll adds the three widget types to a fresh registry', () => {
  const registry = PanelRegistry.create();
  PanelWidgets.registerAll(registry);
  PanelWidgets.registerAll(registry);

  assert.deepEqual(registry.list().map((d) => d.id), ['checklist', 'habits', 'notes']);
  assert.deepEqual(registry.get('checklist').topics, ['tasks']);
  assert.deepEqual(registry.get('checklist').actions, ['tasks.add', 'tasks.toggle', 'tasks.remove']);
  assert.deepEqual(registry.get('notes').actions, ['notes.add', 'notes.remove']);
  assert.deepEqual(registry.get('habits').actions, ['habits.checkin']);
  assert.deepEqual(registry.get('checklist').sizes.default, { w: 3, h: 4 });
  assert.deepEqual(registry.get('checklist').sizes.max, { w: 6, h: 8 });
  assert.equal(registry.topicsFor([{ type: 'checklist' }, { type: 'habits' }]).join(','), 'habits,tasks');
});

test('a widget mounted through the registry follows its topic', () => {
  const stub = makeXhrStub({ '/api/notes': { notes: [] } });
  const previous = global.XMLHttpRequest;
  global.XMLHttpRequest = stub.Xhr;
  const sent = [];
  const registry = PanelRegistry.create();
  PanelWidgets.registerAll(registry);
  const doc = makeDocument();
  const host = doc.createElement('div');
  doc.body.appendChild(host);

  let handle;
  try {
    handle = PanelRegistry.mount(registry, host, { type: 'notes' }, {
      sendAction: (actionId, args) => sent.push([actionId, args]),
    });
  } finally {
    global.XMLHttpRequest = previous;
  }

  assert.equal(handle.failed, false);
  handle.onTopic('notes', { notes: [{ id: 11, text: 'Hello', created_at: '2026-02-01T00:00:00Z' }] });
  assert.deepEqual(texts(host, 'pn-note-text'), ['Hello']);
});

test('checklist onTopic refreshes with include_done=true so done tasks remain visible', () => {
  const sent = [];
  const stub = makeXhrStub({
    [TASKS_URL]: {
      tasks: [
        { id: 1, title: 'Open task', done: false },
        { id: 2, title: 'Done task', done: true },
      ],
    },
  });
  const previous = global.XMLHttpRequest;
  global.XMLHttpRequest = stub.Xhr;
  const doc = makeDocument();
  const host = doc.createElement('div');
  doc.body.appendChild(host);
  const def = PanelWidgets.DEFS.filter((d) => d.id === 'checklist')[0];
  try {
    const instance = def.render(host, {
      config: {},
      size: { width: 0, height: 0 },
      sendAction: (actionId, args) => sent.push([actionId, args]),
      now: () => 0,
      el: host,
    });
    assert.equal(stub.calls.length, 1);
    instance.onTopic('tasks', { tasks: [{ id: 1, title: 'Open task', done: false }] });
    assert.equal(stub.calls.length, 2);
    assert.deepEqual(texts(host, 'pn-task-title'), ['Open task', 'Done task']);
    instance.destroy();
  } finally {
    global.XMLHttpRequest = previous;
  }
});
