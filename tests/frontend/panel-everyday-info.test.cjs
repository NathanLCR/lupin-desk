const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

const { makeDocument, findAll } = require('./panel-fakes.cjs');
const PanelRegistry = require(path.join(__dirname, '../../static/panel/registry.js'));
const info = require(path.join(__dirname, '../../static/panel/widgets-info.js'));

// Fake timers and XMLHttpRequest, installed on the globals that widget-kit reads at call time.
function installEnv() {
  const saved = {
    XMLHttpRequest: global.XMLHttpRequest,
    setInterval: global.setInterval,
    clearInterval: global.clearInterval,
    setTimeout: global.setTimeout,
    clearTimeout: global.clearTimeout,
  };
  const requests = [];
  let now = 0;
  let nextId = 1;
  let timers = [];

  class FakeXhr {
    constructor() {
      this.status = 0;
      this.responseText = '';
      this.url = null;
      this.onload = null;
      this.onerror = null;
      this.ontimeout = null;
      requests.push(this);
    }

    open(method, url) {
      this.method = method;
      this.url = url;
    }

    send() {}

    respond(status, body) {
      this.status = status;
      this.responseText = body === undefined ? '' : JSON.stringify(body);
      if (this.onload) this.onload();
    }
  }

  function add(fn, ms, repeat) {
    const id = nextId++;
    timers.push({ id, fn, ms: ms || 0, at: now + (ms || 0), repeat, active: true });
    return id;
  }

  function remove(id) {
    timers.forEach((t) => { if (t.id === id) t.active = false; });
    timers = timers.filter((t) => t.active);
  }

  global.XMLHttpRequest = FakeXhr;
  global.setInterval = (fn, ms) => add(fn, ms, true);
  global.clearInterval = remove;
  global.setTimeout = (fn, ms) => add(fn, ms, false);
  global.clearTimeout = remove;

  const env = {
    requests,
    activeIntervals: () => timers.filter((t) => t.active && t.repeat).length,
    activeTimeouts: () => timers.filter((t) => t.active && !t.repeat).length,
    intervalMs: () => timers.filter((t) => t.active && t.repeat).map((t) => t.ms),
    tick(ms) {
      const end = now + ms;
      for (;;) {
        timers.sort((a, b) => a.at - b.at || a.id - b.id);
        const t = timers[0];
        if (!t || t.at > end) break;
        now = t.at;
        if (t.repeat) t.at += t.ms;
        else remove(t.id);
        t.fn();
      }
      now = end;
    },
    restore() {
      global.XMLHttpRequest = saved.XMLHttpRequest;
      global.setInterval = saved.setInterval;
      global.clearInterval = saved.clearInterval;
      global.setTimeout = saved.setTimeout;
      global.clearTimeout = saved.clearTimeout;
    },
    // Latest request whose URL starts with prefix.
    last(prefix) {
      for (let i = requests.length - 1; i >= 0; i--) {
        if (requests[i].url.indexOf(prefix) === 0) return requests[i];
      }
      throw new Error('no request for ' + prefix);
    },
  };
  return env;
}

// The panel fake keeps textContent as a plain field; this one clears children like a DOM does.
function makeDoc() {
  const doc = makeDocument();
  const create = doc.createElement;
  doc.createElement = (tag) => {
    const node = create(tag);
    let own = '';
    Object.defineProperty(node, 'textContent', {
      configurable: true,
      get() {
        return own + node.children.map((c) => c.textContent).join('');
      },
      set(value) {
        node.children.forEach((c) => { c.parentNode = null; });
        node.children = [];
        own = String(value);
      },
    });
    return node;
  };
  return doc;
}

function allText(node) {
  return node.textContent;
}

function byClass(node, className) {
  return findAll(node, (n) => n.className.split(' ').indexOf(className) >= 0);
}

function mountWidget(type, config, options) {
  const doc = makeDoc();
  const host = doc.createElement('div');
  host.clientWidth = 300;
  host.clientHeight = 200;
  const registry = PanelRegistry.create();
  info.registerAll(registry);
  const opts = options || {};
  const handle = PanelRegistry.mount(registry, host, { type, config: config || {} }, {
    sendAction: opts.sendAction || (() => {}),
    now: opts.now || (() => 0),
  });
  return { doc, host, handle };
}

// Runs fn with fake timers and network, always restoring the globals.
function withEnv(fn) {
  const env = installEnv();
  try {
    return fn(env);
  } finally {
    env.restore();
  }
}

// ----------------------------------------------------------------------- pure helpers

test('formatTemp rounds and adds the degree sign', () => {
  assert.equal(info.formatTemp(21.6), '22°C');
  assert.equal(info.formatTemp(-0.4), '0°C');
  assert.equal(info.formatTemp(-5.5), '-5°C');
  assert.equal(info.formatTemp('x'), '--°C');
  assert.equal(info.formatTemp(null), '--°C');
});

test('weatherUrl appends only the config values that are provided', () => {
  assert.equal(info.weatherUrl({}), '/api/weather');
  assert.equal(info.weatherUrl(null), '/api/weather');
  assert.equal(info.weatherUrl({ lat: -23.5, lon: -46.6, city: 'São Paulo' }),
    '/api/weather?lat=-23.5&lon=-46.6&city=S%C3%A3o%20Paulo');
  assert.equal(info.weatherUrl({ lat: 'north', city: '' }), '/api/weather');
});

test('sortEvents puts all-day first, then by start time, without mutating the input', () => {
  const input = [
    { start: '14:00', title: 'Standup', all_day: false },
    { start: '09:30', title: 'Dentist' },
    { title: 'Holiday', all_day: true },
    { start: 'soon', title: 'Odd' },
  ];
  const copy = input.slice();
  const sorted = info.sortEvents(input);
  assert.deepEqual(sorted.map((e) => e.title), ['Holiday', 'Dentist', 'Standup', 'Odd']);
  assert.deepEqual(input, copy);
  assert.deepEqual(info.sortEvents(null), []);
  assert.deepEqual(info.sortEvents('nope'), []);
  assert.deepEqual(info.sortEvents([null, 3, { start: '08:00', title: 'Ok' }]).map((e) => e.title), ['Ok']);
});

test('nextEventIndex finds the earliest timed event still to come, in local time', () => {
  const events = [
    { start: '14:00', title: 'Later' },
    { start: '09:30', title: 'Past' },
    { start: '11:00', title: 'Next' },
    { start: '11:00', title: 'Same time', all_day: true },
  ];
  const at1030 = new Date(2026, 10, 18, 10, 30).getTime();
  assert.equal(info.nextEventIndex(events, at1030), 2);
  const at1500 = new Date(2026, 10, 18, 15, 0).getTime();
  assert.equal(info.nextEventIndex(events, at1500), -1);
  assert.equal(info.nextEventIndex(events, NaN), -1);
  assert.equal(info.nextEventIndex(null, at1030), -1);
});

test('registerAll registers the three widgets on a fresh registry and is idempotent', () => {
  const registry = PanelRegistry.create();
  info.registerAll(registry);
  info.registerAll(registry);
  assert.deepEqual(registry.list().map((d) => d.id), ['calendar', 'now_playing', 'weather']);
  const weather = registry.get('weather');
  assert.equal(weather.title, 'Weather');
  assert.deepEqual(weather.sizes.min, { w: 2, h: 1 });
  assert.deepEqual(weather.sizes.default, { w: 3, h: 2 });
  assert.deepEqual(weather.sizes.max, { w: 6, h: 4 });
  assert.deepEqual(registry.get('now_playing').actions, ['media.play_pause', 'media.next', 'media.previous']);
  assert.deepEqual(registry.get('calendar').sizes.default, { w: 3, h: 3 });
});

// ----------------------------------------------------------------------------- weather

test('weather renders temperature, condition, city and feels-like', () => withEnv((env) => {
  const { host, handle } = mountWidget('weather');
  assert.equal(handle.failed, false);
  assert.equal(env.last('/api/weather').url, '/api/weather');
  env.last('/api/weather').respond(200, {
    ok: true, offline: false, city: 'Lisbon', temperature_c: 21.6, apparent_c: 19.4,
    wind_kmh: 10, is_day: 1, condition: 'Clear', effect: 'none',
  });
  const text = allText(host);
  assert.ok(text.indexOf('22°C') >= 0);
  assert.ok(text.indexOf('Clear') >= 0);
  assert.ok(text.indexOf('Lisbon') >= 0);
  assert.ok(text.indexOf('feels like 19°C') >= 0);
  handle.destroy();
}));

test('weather hides the feels-like line when apparent_c is not a number', () => withEnv((env) => {
  const { host, handle } = mountWidget('weather');
  env.last('/api/weather').respond(200, { ok: true, offline: false, temperature_c: 5, condition: 'Rain', apparent_c: null });
  assert.equal(allText(host).indexOf('feels like'), -1);
  assert.ok(allText(host).indexOf('Rain') >= 0);
  handle.destroy();
}));

test('weather shows a calm line when offline, not ok, failed or null', () => withEnv((env) => {
  const { host, handle } = mountWidget('weather');
  env.last('/api/weather').respond(200, { ok: true, offline: true });
  assert.equal(allText(host), 'Weather unavailable');

  env.tick(15 * 60 * 1000);
  env.last('/api/weather').respond(200, { ok: false, offline: false, temperature_c: 3 });
  assert.equal(allText(host), 'Weather unavailable');

  env.tick(15 * 60 * 1000);
  env.last('/api/weather').respond(500, {});
  assert.equal(allText(host), 'Weather unavailable');

  env.tick(15 * 60 * 1000);
  env.last('/api/weather').respond(200, null);
  assert.equal(allText(host), 'Weather unavailable');
  handle.destroy();
}));

test('weather polls immediately and then every 15 minutes', () => withEnv((env) => {
  const { handle } = mountWidget('weather');
  assert.equal(env.requests.length, 1);
  assert.deepEqual(env.intervalMs(), [15 * 60 * 1000]);
  env.tick(15 * 60 * 1000 - 1);
  assert.equal(env.requests.length, 1);
  env.tick(1);
  assert.equal(env.requests.length, 2);
  handle.destroy();
}));

test('weather passes configured lat, lon and city to the request', () => withEnv((env) => {
  const { handle } = mountWidget('weather', { lat: 38.7, lon: -9.1, city: 'Lisbon & co' });
  assert.equal(env.last('/api/weather').url,
    '/api/weather?lat=38.7&lon=-9.1&city=Lisbon%20%26%20co');
  handle.destroy();
}));

// ------------------------------------------------------------------------ now playing

test('now playing shows track, artist and app, with a pause button while playing', () => withEnv((env) => {
  const { host, handle } = mountWidget('now_playing');
  env.last('/api/mac/status').respond(200, {
    now_playing: { app: 'Music', state: 'playing', track: 'Song A', artist: 'Band B' },
  });
  const text = allText(host);
  assert.ok(text.indexOf('Song A') >= 0);
  assert.ok(text.indexOf('Band B') >= 0);
  assert.ok(text.indexOf('Music') >= 0);
  const playBtn = byClass(host, 'pn-np-btn')[1];
  assert.equal(playBtn.textContent, '⏸');
  assert.equal(playBtn.attributes.title, 'Pause');
  handle.destroy();
}));

test('now playing shows a play button while paused', () => withEnv((env) => {
  const { host, handle } = mountWidget('now_playing');
  env.last('/api/mac/status').respond(200, {
    now_playing: { app: 'Spotify', state: 'paused', track: 'Song C', artist: 'Band D' },
  });
  const playBtn = byClass(host, 'pn-np-btn')[1];
  assert.equal(playBtn.textContent, '▶');
  assert.equal(playBtn.attributes.title, 'Play');
  handle.destroy();
}));

test('now playing shows Nothing playing for null or odd data, and an unavailable line on error', () => withEnv((env) => {
  const { host, handle } = mountWidget('now_playing');
  env.last('/api/mac/status').respond(200, { now_playing: null });
  assert.ok(allText(host).indexOf('Nothing playing') >= 0);

  env.tick(5000);
  env.last('/api/mac/status').respond(200, { now_playing: 'weird' });
  assert.ok(allText(host).indexOf('Nothing playing') >= 0);

  env.tick(5000);
  env.last('/api/mac/status').respond(503, {});
  assert.ok(allText(host).indexOf('Media unavailable') >= 0);
  handle.destroy();
}));

test('now playing polls every 5 seconds', () => withEnv((env) => {
  const { handle } = mountWidget('now_playing');
  assert.deepEqual(env.intervalMs(), [5000]);
  handle.destroy();
}));

test('now playing buttons send the right action ids and re-poll after 700 ms', () => withEnv((env) => {
  const sent = [];
  const { host, handle } = mountWidget('now_playing', {}, {
    sendAction: (id, args) => sent.push({ id, args }),
  });
  env.last('/api/mac/status').respond(200, { now_playing: { state: 'playing', track: 'T' } });
  const buttons = byClass(host, 'pn-np-btn');
  assert.equal(buttons.length, 3);
  buttons.forEach((b) => assert.equal(b.attributes.type, 'button'));

  const before = env.requests.length;
  buttons[0].fire('click');
  buttons[1].fire('click');
  buttons[2].fire('click');
  assert.deepEqual(sent, [
    { id: 'media.previous', args: {} },
    { id: 'media.play_pause', args: {} },
    { id: 'media.next', args: {} },
  ]);
  assert.equal(env.requests.length, before, 'no poll before the 700 ms delay');
  env.tick(700);
  assert.equal(env.requests.length, before + 1);
  handle.destroy();
}));

test('now playing survives a sendAction that throws', () => withEnv((env) => {
  const { host, handle } = mountWidget('now_playing', {}, {
    sendAction: () => { throw new Error('boom'); },
  });
  env.last('/api/mac/status').respond(200, { now_playing: null });
  byClass(host, 'pn-np-btn')[0].fire('click');
  assert.equal(handle.failed, false);
  handle.destroy();
}));

// --------------------------------------------------------------------------- calendar

test('calendar lists today with all-day first and marks the next event', () => withEnv((env) => {
  const nowMs = new Date(2026, 10, 18, 10, 0).getTime();
  const { host, handle } = mountWidget('calendar', {}, { now: () => nowMs });
  env.last('/api/panel/calendar').respond(200, {
    ok: true,
    events: [
      { start: '14:00', title: 'Review' },
      { start: '09:30', title: 'Dentist' },
      { start: '00:00', title: 'Holiday', all_day: true },
    ],
  });
  const rows = byClass(host, 'pn-cal-row');
  assert.equal(rows.length, 3);
  assert.equal(rows[0].children[0].textContent, 'All day');
  assert.equal(rows[0].children[1].textContent, 'Holiday');
  assert.equal(rows[1].children[0].textContent, '09:30');
  assert.equal(rows[2].children[1].textContent, 'Review');
  const next = byClass(host, 'pn-cal-next');
  assert.equal(next.length, 1);
  assert.equal(next[0].children[1].textContent, 'Review');
  handle.destroy();
}));

test('calendar shows empty and unavailable states', () => withEnv((env) => {
  const { host, handle } = mountWidget('calendar');
  env.last('/api/panel/calendar').respond(200, { ok: true, events: [] });
  assert.equal(allText(host), 'No events today');

  env.tick(60000);
  env.last('/api/panel/calendar').respond(200, { ok: false, events: [] });
  assert.equal(allText(host), 'Calendar unavailable');

  env.tick(60000);
  env.last('/api/panel/calendar').respond(200, null);
  assert.equal(allText(host), 'Calendar unavailable');

  env.tick(60000);
  env.last('/api/panel/calendar').respond(200, { ok: true, events: 'nope' });
  assert.equal(allText(host), 'No events today');
  handle.destroy();
}));

test('calendar limits rows to config max, default 6', () => withEnv((env) => {
  const events = [];
  for (let i = 0; i < 9; i++) events.push({ start: '0' + i + ':00', title: 'E' + i });

  const limited = mountWidget('calendar', { max: 2 });
  env.last('/api/panel/calendar').respond(200, { ok: true, events });
  assert.equal(byClass(limited.host, 'pn-cal-row').length, 2);

  const defaults = mountWidget('calendar');
  env.last('/api/panel/calendar').respond(200, { ok: true, events });
  assert.equal(byClass(defaults.host, 'pn-cal-row').length, 6);

  limited.handle.destroy();
  defaults.handle.destroy();
}));

test('calendar polls every 60 seconds and is read-only', () => withEnv((env) => {
  const { host, handle } = mountWidget('calendar');
  assert.deepEqual(env.intervalMs(), [60000]);
  assert.equal(byClass(host, 'pn-np-btn').length, 0);
  assert.equal(byClass(host, 'pn-cal-row').length, 0);
  handle.destroy();
}));

// ----------------------------------------------------------------------- lifecycle

test('destroy clears every poll timer and any pending re-poll', () => withEnv((env) => {
  const a = mountWidget('weather');
  const b = mountWidget('now_playing');
  const c = mountWidget('calendar');
  assert.equal(env.activeIntervals(), 3);

  byClass(b.host, 'pn-np-btn')[0].fire('click');
  assert.equal(env.activeTimeouts(), 1);

  a.handle.destroy();
  b.handle.destroy();
  c.handle.destroy();
  assert.equal(env.activeIntervals(), 0);
  assert.equal(env.activeTimeouts(), 0);

  const before = env.requests.length;
  env.tick(15 * 60 * 1000);
  assert.equal(env.requests.length, before);
}));

test('a response that arrives after destroy does not touch the tile', () => withEnv((env) => {
  const { host, handle } = mountWidget('weather');
  const req = env.last('/api/weather');
  handle.destroy();
  req.respond(200, { ok: true, offline: false, temperature_c: 9, condition: 'Snow' });
  assert.equal(allText(host), 'Loading weather');
}));
