// Tests for static/panel/widgets-timers.js (Pomodoro and Timers widgets).
// Uses a local fake clock and XHR: the shared makeNetwork XHR cannot take send() without a body.
const assert = require('node:assert/strict');
const test = require('node:test');

const { makeDocument, findAll } = require('./panel-fakes.cjs');
const W = require('../../static/panel/widgets-timers.js');
const PanelRegistry = require('../../static/panel/registry.js');

const BASE_MS = 1700000000000;
const START_ISO = new Date(BASE_MS).toISOString();
const STATUS_URL = '/api/mac/status';
const TIMERS_URL = '/api/panel/timers';

function makeFakeTimers() {
  const state = { now: BASE_MS, timers: [], nextId: 1 };

  function add(fn, ms, repeat) {
    const id = state.nextId++;
    state.timers.push({ id, fn, ms: ms || 0, at: state.now + (ms || 0), repeat });
    return id;
  }

  function remove(id) {
    state.timers = state.timers.filter((t) => t.id !== id);
  }

  return {
    state,
    setInterval: (fn, ms) => add(fn, ms, true),
    setTimeout: (fn, ms) => add(fn, ms, false),
    clearInterval: remove,
    clearTimeout: remove,
    active: () => state.timers.length,
    advance(ms) {
      const end = state.now + ms;
      for (;;) {
        state.timers.sort((a, b) => a.at - b.at || a.id - b.id);
        const t = state.timers[0];
        if (!t || t.at > end) break;
        state.now = t.at;
        if (t.repeat) t.at += t.ms;
        else state.timers.shift();
        t.fn();
      }
      state.now = end;
    },
  };
}

function makeXhrStub() {
  const xhrs = [];
  class FakeXHR {
    constructor() {
      this.status = 0;
      this.responseText = '';
      this.url = null;
      this.method = null;
      this.responded = false;
      this.onload = null;
      this.onerror = null;
      this.ontimeout = null;
      xhrs.push(this);
    }

    open(method, url) {
      this.method = method;
      this.url = url;
    }

    send() {}
  }
  return { xhrs, FakeXHR };
}

// Runs fn with stubbed timers, XHR and clock; restores the globals afterwards.
function withEnv(fn) {
  const clock = makeFakeTimers();
  const net = makeXhrStub();
  const keys = ['setInterval', 'clearInterval', 'setTimeout', 'clearTimeout', 'XMLHttpRequest'];
  const saved = {};
  keys.forEach((k) => { saved[k] = global[k]; });

  global.setInterval = clock.setInterval;
  global.clearInterval = clock.clearInterval;
  global.setTimeout = clock.setTimeout;
  global.clearTimeout = clock.clearTimeout;
  global.XMLHttpRequest = net.FakeXHR;

  // Answers the newest unanswered request for url.
  net.respondTo = (url, data) => {
    for (let i = net.xhrs.length - 1; i >= 0; i--) {
      const xhr = net.xhrs[i];
      if (xhr.url === url && !xhr.responded) {
        xhr.responded = true;
        xhr.status = 200;
        xhr.responseText = JSON.stringify(data);
        xhr.onload();
        return;
      }
    }
    throw new Error('no pending request for ' + url);
  };
  net.countFor = (url) => net.xhrs.filter((x) => x.url === url).length;

  try {
    return fn({ clock, net, doc: makeDocument() });
  } finally {
    keys.forEach((k) => {
      if (saved[k] === undefined) delete global[k];
      else global[k] = saved[k];
    });
  }
}

function def(id) {
  return W.DEFS.filter((d) => d.id === id)[0];
}

function mount(env, id, config) {
  const el = env.doc.createElement('div');
  const sent = [];
  const ctx = {
    config: config || {},
    size: { width: 0, height: 0 },
    sendAction: (actionId, args) => sent.push({ id: actionId, args }),
    now: () => env.clock.state.now,
    el,
  };
  const instance = def(id).render(el, ctx);
  return { el, sent, instance };
}

function byClass(el, className) {
  return findAll(el, (n) => n.className === className);
}

function textOf(el, className) {
  const found = byClass(el, className);
  return found.length ? found[0].textContent : null;
}

// ---------------------------------------------------------------- pure helpers

test('formatDuration gives MM:SS, and H:MM:SS from one hour', () => {
  assert.equal(W.formatDuration(0), '00:00');
  assert.equal(W.formatDuration(65), '01:05');
  assert.equal(W.formatDuration(3599), '59:59');
  assert.equal(W.formatDuration(3600), '1:00:00');
  assert.equal(W.formatDuration(3661), '1:01:01');
  assert.equal(W.formatDuration(-5), '00:00');
  assert.equal(W.formatDuration(NaN), '00:00');
  assert.equal(W.formatDuration(undefined), '00:00');
});

test('pomodoroRemaining counts from started_at + duration and returns null when unreadable', () => {
  const T0 = Date.parse(START_ISO);
  const active = { active: true, duration_minutes: 25, started_at: START_ISO };
  assert.equal(W.pomodoroRemaining(null, T0), null);
  assert.equal(W.pomodoroRemaining({ active: false, duration_minutes: 25, started_at: START_ISO }, T0), null);
  assert.equal(W.pomodoroRemaining(active, T0), 1500);
  assert.equal(W.pomodoroRemaining(active, T0 + 1000), 1499);
  assert.equal(W.pomodoroRemaining(active, T0 + 1500 * 1000), 0);
  assert.equal(W.pomodoroRemaining(active, T0 + 2000 * 1000), 0);
  const T1 = Date.parse('2026-11-18T10:00:00Z');
  assert.equal(
    W.pomodoroRemaining({ active: true, duration_minutes: 25, started_at: '2026-11-18T07:00:00-03:00' }, T1),
    1500
  );
  assert.equal(W.pomodoroRemaining({ active: true, duration_minutes: 25, started_at: 'nope' }, T0), null);
  assert.equal(W.pomodoroRemaining({ active: true, duration_minutes: 25, started_at: null }, T0), null);
});

test('timersWithRemaining subtracts elapsed whole seconds, clamps at 0 and skips bad entries', () => {
  const list = [
    { id: 'a', label: ' Tea ', seconds: 300, remaining: 120 },
    { id: 'b', label: '', seconds: 600, remaining: 10 },
    null,
    'x',
    { label: 'no id', seconds: 60, remaining: 60 },
  ];
  assert.deepEqual(W.timersWithRemaining(list, 1000, 1000 + 30000), [
    { id: 'a', label: 'Tea', seconds: 300, remaining: 90 },
    { id: 'b', label: '', seconds: 600, remaining: 0 },
  ]);
  assert.equal(W.timersWithRemaining(list, 1000, 1000 + 999)[0].remaining, 120);
  assert.deepEqual(W.timersWithRemaining(null, 0, 0), []);
});

test('sanitizePresets keeps valid integer minutes, caps at six, and falls back to defaults', () => {
  assert.deepEqual(W.sanitizePresets(undefined), [1, 5, 10, 25]);
  assert.deepEqual(W.sanitizePresets([2, 0, 'x', 7.5, 3]), [2, 3]);
  assert.deepEqual(W.sanitizePresets([0, -1]), [1, 5, 10, 25]);
  assert.deepEqual(W.sanitizePresets([1, 2, 3, 4, 5, 6, 7, 8]), [1, 2, 3, 4, 5, 6]);
});

// ---------------------------------------------------------------- countdown behaviour

test('pomodoro shows MM:SS from the server start time, ticks each second, then Done', () => {
  withEnv((env) => {
    const m = mount(env, 'pomodoro');
    env.net.respondTo(STATUS_URL, {
      pomodoro: { active: true, duration_minutes: 25, started_at: START_ISO },
    });
    assert.equal(textOf(m.el, 'pn-pomo-time'), '25:00');
    assert.equal(textOf(m.el, 'pn-pomo-btn'), 'Stop');

    env.clock.advance(1000);
    assert.equal(textOf(m.el, 'pn-pomo-time'), '24:59');

    env.clock.advance(1499 * 1000);
    assert.equal(textOf(m.el, 'pn-pomo-time'), 'Done');
    m.instance.destroy();
  });
});

test('timers count down locally from the received remaining seconds', () => {
  withEnv((env) => {
    const m = mount(env, 'timers');
    env.net.respondTo(TIMERS_URL, {
      timers: [{ id: 't1', label: '', seconds: 300, remaining: 300 }],
    });
    assert.equal(textOf(m.el, 'pn-timer-label'), '05:00');
    assert.equal(textOf(m.el, 'pn-timer-countdown'), '05:00');

    env.clock.advance(2000);
    assert.equal(textOf(m.el, 'pn-timer-countdown'), '04:58');
    m.instance.destroy();
  });
});

test('timers shows the empty state when there are no timers', () => {
  withEnv((env) => {
    const m = mount(env, 'timers');
    env.net.respondTo(TIMERS_URL, { timers: [] });
    assert.equal(textOf(m.el, 'pn-timer-empty'), 'No timers');
    m.instance.destroy();
  });
});

// ---------------------------------------------------------------- buttons send exact actions

test('pomodoro button starts when idle and stops when active, then re-polls after 700 ms', () => {
  withEnv((env) => {
    const m = mount(env, 'pomodoro');
    env.net.respondTo(STATUS_URL, { pomodoro: { active: false, duration_minutes: 25, started_at: null } });
    const btn = byClass(m.el, 'pn-pomo-btn')[0];
    assert.equal(btn.type, 'button');
    assert.equal(btn.textContent, 'Start');

    const before = env.net.countFor(STATUS_URL);
    btn.fire('click');
    assert.deepEqual(m.sent, [{ id: 'pomodoro.start', args: {} }]);
    env.clock.advance(700);
    assert.equal(env.net.countFor(STATUS_URL), before + 1);

    env.net.respondTo(STATUS_URL, { pomodoro: { active: true, duration_minutes: 25, started_at: START_ISO } });
    assert.equal(btn.textContent, 'Stop');
    btn.fire('click');
    assert.deepEqual(m.sent[1], { id: 'pomodoro.stop', args: {} });
    m.instance.destroy();
  });
});

test('timers preset buttons send timers.start with seconds, and cancel sends timers.cancel', () => {
  withEnv((env) => {
    const m = mount(env, 'timers');
    env.net.respondTo(TIMERS_URL, { timers: [{ id: 't1', label: 'Eggs', seconds: 180, remaining: 180 }] });

    const presets = byClass(m.el, 'pn-timer-preset');
    assert.deepEqual(presets.map((p) => p.textContent), ['1 min', '5 min', '10 min', '25 min']);
    presets[1].fire('click');
    assert.deepEqual(m.sent, [{ id: 'timers.start', args: { seconds: 300 } }]);

    byClass(m.el, 'pn-remove')[0].fire('click');
    assert.deepEqual(m.sent[1], { id: 'timers.cancel', args: { id: 't1' } });
    m.instance.destroy();
  });
});

test('timers config presets override the defaults', () => {
  withEnv((env) => {
    const m = mount(env, 'timers', { presets: [2, 0, 'x', 7.5, 3] });
    const labels = byClass(m.el, 'pn-timer-preset').map((p) => p.textContent);
    assert.deepEqual(labels, ['2 min', '3 min']);
    m.instance.destroy();
  });
});

// ---------------------------------------------------------------- topic updates

test('timers topic message re-renders the rows and an empty list shows the empty state', () => {
  withEnv((env) => {
    const m = mount(env, 'timers');
    m.instance.onTopic('timers', {
      timers: [
        { id: 'n1', label: 'Eggs', seconds: 180, remaining: 180 },
        { id: 'n2', label: '', seconds: 60, remaining: 60 },
      ],
    });
    assert.deepEqual(byClass(m.el, 'pn-timer-label').map((n) => n.textContent), ['Eggs', '01:00']);
    assert.deepEqual(byClass(m.el, 'pn-timer-countdown').map((n) => n.textContent), ['03:00', '01:00']);

    m.instance.onTopic('timers', { timers: [] });
    assert.equal(byClass(m.el, 'pn-timer-row').length, 0);
    assert.equal(textOf(m.el, 'pn-timer-empty'), 'No timers');
    m.instance.destroy();
  });
});

test('signal:timer_done topic re-polls the pomodoro status right away', () => {
  withEnv((env) => {
    const m = mount(env, 'pomodoro');
    const before = env.net.countFor(STATUS_URL);
    m.instance.onTopic('signal:timer_done', {});
    assert.equal(env.net.countFor(STATUS_URL), before + 1);
    m.instance.destroy();
  });
});

// ---------------------------------------------------------------- lifecycle

test('destroy clears every interval and timeout of both widgets', () => {
  withEnv((env) => {
    const pomo = mount(env, 'pomodoro');
    const timers = mount(env, 'timers');
    env.net.respondTo(STATUS_URL, { pomodoro: { active: true, duration_minutes: 25, started_at: START_ISO } });
    byClass(pomo.el, 'pn-pomo-btn')[0].fire('click'); // leaves a pending re-poll timeout
    assert.ok(env.clock.active() > 0);

    pomo.instance.destroy();
    timers.instance.destroy();
    assert.equal(env.clock.active(), 0);

    // The timers GET is still in flight: its late answer must not throw or render rows.
    env.net.respondTo(TIMERS_URL, { timers: [{ id: 'z', label: 'late', seconds: 60, remaining: 60 }] });
    assert.equal(byClass(timers.el, 'pn-timer-row').length, 0);
    assert.equal(textOf(timers.el, 'pn-timer-empty'), 'No timers');
  });
});

test('a stale initial GET /api/panel/timers response does not overwrite an earlier topic update', () => {
  withEnv((env) => {
    const m = mount(env, 'timers');
    m.instance.onTopic('timers', {
      timers: [{ id: 'fresh', label: 'Tea', seconds: 180, remaining: 180 }],
    });
    assert.deepEqual(byClass(m.el, 'pn-timer-label').map((n) => n.textContent), ['Tea']);

    env.net.respondTo(TIMERS_URL, {
      timers: [{ id: 'stale', label: 'Old', seconds: 60, remaining: 60 }],
    });
    assert.deepEqual(byClass(m.el, 'pn-timer-label').map((n) => n.textContent), ['Tea']);
    m.instance.destroy();
  });
});

test('registerAll adds pomodoro and timers to a fresh registry, and is safe to run twice', () => {
  const registry = PanelRegistry.create();
  W.registerAll(registry);
  W.registerAll(registry);

  assert.deepEqual(registry.list().map((d) => d.id), ['pomodoro', 'timers']);
  const pomodoro = registry.get('pomodoro');
  assert.equal(pomodoro.title, 'Pomodoro');
  assert.deepEqual(pomodoro.sizes.default, { w: 3, h: 2 });
  assert.deepEqual(pomodoro.topics, ['signal:timer_done']);
  assert.deepEqual(pomodoro.actions, ['pomodoro.start', 'pomodoro.stop']);
  const timers = registry.get('timers');
  assert.deepEqual(timers.topics, ['timers']);
  assert.deepEqual(timers.actions, ['timers.start', 'timers.cancel']);
});
