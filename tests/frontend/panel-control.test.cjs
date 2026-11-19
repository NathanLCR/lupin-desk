// Tests for static/panel/widgets-control.js (Control Deck widgets).
const assert = require('node:assert/strict');
const test = require('node:test');

const { makeDocument, findAll } = require('./panel-fakes.cjs');
const W = require('../../static/panel/widgets-control.js');
const PanelRegistry = require('../../static/panel/registry.js');

function def(id) {
  return W.DEFS.filter((d) => d.id === id)[0];
}

// Renders a widget with a stubbed XHR; `answers` maps url -> JSON. Timers are real but cleaned up by destroy.
function render(id, answers, config) {
  const calls = [];
  const sent = [];
  class Xhr {
    open(method, url) { this.url = url; }
    send() {
      const hit = (answers || {})[this.url];
      calls.push(this.url);
      setTimeout(() => {
        if (hit === undefined) { this.status = 404; this.responseText = ''; } else {
          this.status = 200; this.responseText = JSON.stringify(hit);
        }
        if (this.onload) this.onload();
      }, 0);
    }
  }
  const previous = global.XMLHttpRequest;
  global.XMLHttpRequest = Xhr;
  const doc = makeDocument();
  const host = doc.createElement('div');
  doc.body.appendChild(host);
  let instance;
  try {
    instance = def(id).render(host, {
      config: config || {}, sendAction: (a, b) => sent.push([a, b]), now: () => 0, el: host,
    });
  } finally {
    global.XMLHttpRequest = previous;
  }
  return { host, instance, sent, calls };
}

const buttons = (host) => findAll(host, (n) => n.tagName === 'BUTTON');
const allText = (host) => findAll(host, () => true).map((n) => n.textContent).join('|');
const tick = () => new Promise((resolve) => setTimeout(resolve, 10));
const clickByText = (host, text) => buttons(host).filter((b) => b.textContent === text)[0].fire('click');

test('every control widget registers with a valid id and the actions it sends', () => {
  const registry = PanelRegistry.create();
  W.registerAll(registry);
  assert.deepEqual(registry.list().map((d) => d.id).sort(), [
    'control.dock', 'control.macros', 'control.media', 'control.mic', 'control.volume', 'control.webhook',
  ]);
  W.registerAll(registry); // idempotent
});

test('label helpers cope with missing and odd data', () => {
  assert.equal(W.volumeLabel({ volume: 41.6, muted: false }), '42%');
  assert.equal(W.volumeLabel({ volume: 30, muted: true }), 'Muted');
  assert.equal(W.volumeLabel(null), '--');
  assert.equal(W.volumeLabel({ volume: null, muted: null }), '--');
  assert.equal(W.micLabel({ mic_muted: true }), 'Mic off');
  assert.equal(W.micLabel({ mic_muted: false }), 'Mic on');
  assert.equal(W.micLabel({}), 'Mic --');
  assert.deepEqual(W.macroList({ macros: [{ id: 1, name: 'A' }, { id: 'x' }, null] }), [{ id: 1, name: 'A' }]);
});

test('volume widget shows the level and sends only action ids', async () => {
  const r = render('control.volume', { '/api/control/audio': { volume: 40, muted: false, mic_muted: false } });
  await tick();
  assert.match(allText(r.host), /40%/);
  clickByText(r.host, '+');
  clickByText(r.host, '-');
  clickByText(r.host, 'Mute');
  assert.deepEqual(r.sent, [['volume.up', {}], ['volume.down', {}], ['volume.mute', {}]]);
  r.instance.destroy();
});

test('mic widget shows the state and toggles', async () => {
  const r = render('control.mic', { '/api/control/audio': { volume: 40, muted: false, mic_muted: true } });
  await tick();
  assert.equal(buttons(r.host)[0].textContent, 'Mic off');
  buttons(r.host)[0].fire('click');
  assert.deepEqual(r.sent, [['mic.toggle', {}]]);
  r.instance.destroy();
});

test('media widget sends the three media actions', () => {
  const r = render('control.media');
  clickByText(r.host, 'Prev');
  clickByText(r.host, 'Play/Pause');
  clickByText(r.host, 'Next');
  assert.deepEqual(r.sent.map((s) => s[0]), ['media.previous', 'media.play_pause', 'media.next']);
});

test('macros widget lists macros as text and runs one by id', async () => {
  const r = render('control.macros', { '/api/control/macros': { macros: [{ id: 3, name: '<b>Focus</b>' }] } });
  await tick();
  assert.match(allText(r.host), /<b>Focus<\/b>/);
  buttons(r.host)[0].fire('click');
  assert.deepEqual(r.sent, [['macro.run', { id: 3 }]]);
  r.instance.destroy();
});

test('macros widget says so when there are none', async () => {
  const r = render('control.macros', { '/api/control/macros': { macros: [] } });
  await tick();
  assert.match(allText(r.host), /No macros yet/);
  r.instance.destroy();
});

test('dock widget shows pinned shortcuts and open apps, hiding gated ones', async () => {
  const r = render('control.dock', {
    '/api/shortcuts': { shortcuts: [
      { slug: 'mission_control', title: 'Mission Control', pinned_on_deck: true, action_type: 'mac_command' },
      { slug: 'lock', title: 'Lock', pinned_on_deck: true, requires_confirmation: true },
      { slug: 'ask', title: 'Ask', pinned_on_deck: true, action_type: 'agent_prompt' },
      { slug: 'hidden', title: 'Hidden', pinned_on_deck: false },
    ] },
    '/api/mac/apps': { apps: [{ name: 'Safari', running: true, frontmost: true }, { name: 'Notes', running: false }] },
  });
  await tick();
  const text = allText(r.host);
  assert.match(text, /Mission Control/);
  assert.match(text, /Safari/);
  assert.ok(!/Lock|Ask|Hidden/.test(text));
  clickByText(r.host, 'Mission Control');
  clickByText(r.host, 'Safari');
  assert.deepEqual(r.sent, [['shortcut.run', { slug: 'mission_control' }], ['app.activate', { name: 'Safari' }]]);
  r.instance.destroy();
});

test('webhook widget loads its value and updates on the webhooks topic', async () => {
  const r = render('control.webhook', { '/api/control/webhooks': { webhooks: [
    { id: 1, name: 'Door', value: 'closed' }, { id: 2, name: 'Temp', value: '21' },
  ] } }, { hook: 2 });
  await tick();
  assert.match(allText(r.host), /Temp/);
  assert.match(allText(r.host), /21/);
  r.instance.onTopic('webhooks', { id: 1, name: 'Door', value: 'open' }); // another hook: ignored
  assert.ok(!/open/.test(allText(r.host)));
  r.instance.onTopic('webhooks', { id: 2, name: 'Temp', value: '<i>22</i>' });
  assert.match(allText(r.host), /<i>22<\/i>/);
  assert.deepEqual(def('control.webhook').topics, ['webhooks']);
  r.instance.destroy();
});

test('a failing request leaves the widget quiet instead of throwing', async () => {
  const r = render('control.volume', {});
  await tick();
  assert.match(allText(r.host), /--/);
  r.instance.destroy();
});
