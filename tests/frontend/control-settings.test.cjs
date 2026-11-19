const test = require('node:test');
const assert = require('node:assert/strict');
const { makeDocument, findAll } = require('./panel-fakes.cjs');
const CS = require('../../static/control_settings.js');

function texts(root) {
  return findAll(root, () => true).map((n) => n.textContent).filter(Boolean);
}
function buttons(root, label) {
  return findAll(root, (n) => n.tagName === 'BUTTON' && n.textContent === label);
}
const tick = () => new Promise((r) => setImmediate(r));

function setup(opts) {
  const o = opts || {};
  const doc = makeDocument();
  const root = doc.createElement('div');
  doc.body.appendChild(root);
  const calls = [];
  const state = {
    macros: [{ id: 1, name: 'Focus', steps: [{ action: 'volume.mute', delay_ms: 0 }] }],
    webhooks: [{ id: 2, name: 'Door', emit_signal: true, path: o.mac === false ? undefined : '/hooks/SECRETX' }],
    rules: [{ id: 3, trigger: 'app_front', match: 'Xcode', page_id: 'dev', enabled: true }],
  };
  const fetchJson = (url, init) => {
    const method = (init && init.method) || 'GET';
    calls.push(method + ' ' + url);
    if (url === '/api/client-info') return Promise.resolve({ is_mac: o.mac !== false });
    if (url === '/api/control/macros' && method === 'GET') return Promise.resolve({ macros: state.macros });
    if (url === '/api/control/webhooks' && method === 'GET') return Promise.resolve({ webhooks: state.webhooks });
    if (url === '/api/control/rules' && method === 'GET') return Promise.resolve({ rules: state.rules });
    if (url === '/api/layouts/default') return Promise.resolve({ pages: [{ id: 'dev', title: 'Dev' }] });
    if (url === '/api/shortcuts') return Promise.resolve({ shortcuts: [] });
    return Promise.resolve({ ok: true });
  };
  const confirms = [];
  const ctl = CS.mount(root, {
    doc, fetchJson, origin: 'http://mac.local:8000',
    confirm: (t) => { confirms.push(t); return o.confirm !== false; },
  });
  return { root, calls, confirms, ctl };
}

test('buildSteps enforces the limits', () => {
  assert.throws(() => CS.buildSteps([]), /at least one/);
  const many = Array.from({ length: 11 }, () => ({ action: 'volume.up', delay: 0 }));
  assert.throws(() => CS.buildSteps(many), /at most 10/);
  assert.throws(() => CS.buildSteps([{ action: 'volume.up', delay: 2001 }]), /0 to 2000/);
  const six = Array.from({ length: 6 }, () => ({ action: 'volume.up', delay: 2000 }));
  assert.throws(() => CS.buildSteps(six), /10 seconds/);
  assert.throws(() => CS.buildSteps([{ action: 'shortcut.run', slug: '', delay: 0 }]), /Shortcut/);
  const ok = CS.buildSteps([{ action: 'shortcut.run', slug: 'x', delay: '5' }]);
  assert.deepEqual(ok, [{ action: 'shortcut.run', delay_ms: 5, args: { slug: 'x' } }]);
});

test('lists macros, webhooks with URL, and rules on the Mac', async () => {
  const { root } = setup();
  await tick(); await tick();
  const all = texts(root).join('|');
  assert.match(all, /Focus/);
  assert.match(all, /http:\/\/mac\.local:8000\/hooks\/SECRETX/);
  assert.match(all, /When Xcode is in front, show Dev/);
});

test('non-Mac clients only see a notice', async () => {
  const { root, calls } = setup({ mac: false });
  await tick(); await tick();
  assert.match(texts(root).join('|'), /only be changed on the Mac/);
  assert.deepEqual(calls, ['GET /api/client-info']);
});

test('delete and rotate ask first and do nothing when declined', async () => {
  const { root, calls, confirms } = setup({ confirm: false });
  await tick(); await tick();
  buttons(root, 'Delete').forEach((b) => b.fire('click'));
  buttons(root, 'Rotate secret')[0].fire('click');
  await tick();
  assert.equal(confirms.length, 4);
  assert.ok(!calls.some((c) => c.startsWith('DELETE') || c.includes('rotate')));
});

test('confirmed delete and rotate call the routes', async () => {
  const { root, calls } = setup();
  await tick(); await tick();
  buttons(root, 'Rotate secret')[0].fire('click');
  await tick();
  buttons(root, 'Delete')[0].fire('click');
  await tick();
  assert.ok(calls.includes('POST /api/control/webhooks/2/rotate'));
  assert.ok(calls.includes('DELETE /api/control/macros/1'));
});

test('markup in names is shown as text, never parsed', async () => {
  const doc = makeDocument();
  const root = doc.createElement('div');
  doc.body.appendChild(root);
  const evil = '<img src=x onerror=alert(1)>';
  const fetchJson = (url) => {
    if (url === '/api/client-info') return Promise.resolve({ is_mac: true });
    if (url === '/api/control/macros') return Promise.resolve({ macros: [{ id: 1, name: evil, steps: [] }] });
    return Promise.resolve({});
  };
  CS.mount(root, { doc, fetchJson, confirm: () => true });
  await tick(); await tick();
  assert.ok(texts(root).includes(evil));
  assert.equal(findAll(root, (n) => n.tagName === 'IMG').length, 0);
});
