const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

const { makeDocument, findAll } = require('./panel-fakes.cjs');
const Mon = require(path.join(__dirname, '../../static/panel/widgets-monitoring.js'));
const PanelRegistry = require(path.join(__dirname, '../../static/panel/registry.js'));

const SAMPLE = {
  cpu: { percent: 42.4, cores: 8 },
  ram: { percent: 61, used: 10 * 1024 ** 3, total: 16 * 1024 ** 3 },
  disks: [{ mount: '/', percent: 40, used: 100 * 1024 ** 3, total: 250 * 1024 ** 3 }],
  net: { up_bps: 2048, down_bps: 3 * 1024 * 1024 },
  ping: { ms: 12.4, target: '1.1.1.1' },
  processes: [{ pid: 1, name: '<b>evil</b>', cpu: 50, mem: 2.5 }],
};

function mount(id) {
  const doc = makeDocument();
  const host = doc.createElement('div');
  doc.body.appendChild(host);
  const def = Mon.DEFS.filter((d) => d.id === id)[0];
  const handle = def.render(host, { config: {}, sendAction() {}, now: () => 0, el: host });
  return { host, handle, def };
}

function byClass(root, name) {
  return findAll(root, (n) => !!n.classList && n.classList.contains(name));
}

test('every definition registers on a registry and follows the monitor topic', () => {
  const registry = PanelRegistry.createRegistry ? PanelRegistry.createRegistry() : null;
  assert.equal(Mon.DEFS.length, 5);
  Mon.DEFS.forEach((d) => {
    assert.deepEqual(d.topics, ['monitor']);
    assert.deepEqual(d.actions, []);
  });
  if (registry) {
    Mon.registerAll(registry);
    Mon.DEFS.forEach((d) => assert.ok(registry.get(d.id), d.id));
  }
});

test('formatters handle bytes, rates, ping and missing values', () => {
  assert.equal(Mon.formatBytes(512), '512 B');
  assert.equal(Mon.formatBytes(1536), '1.5 KB');
  assert.equal(Mon.formatBytes(null), '--');
  assert.equal(Mon.formatRate(3 * 1024 * 1024), '3 MB/s');
  assert.equal(Mon.formatPing(12.4), '12 ms');
  assert.equal(Mon.formatPing(null), 'offline');
  assert.equal(Mon.formatPercent(42.4), '42%');
  assert.equal(Mon.formatPercent(undefined), '--');
});

test('history keeps the newest entries and clamps to 0..100', () => {
  const h = [];
  for (let i = 0; i < Mon.HISTORY + 10; i++) Mon.pushHistory(h, i === 0 ? 500 : i);
  assert.equal(h.length, Mon.HISTORY);
  assert.equal(h[h.length - 1], Mon.HISTORY + 9);
  assert.deepEqual(Mon.pushHistory([], -5), [0]);
});

test('cpu widget shows a waiting state, then the percentage and a sparkline', () => {
  const { host, handle } = mount('mac-cpu');
  assert.match(byClass(host, 'pn-mon-status')[0].textContent, /Waiting/);
  handle.onTopic('monitor', SAMPLE);
  assert.equal(byClass(host, 'pn-mon-status')[0].textContent, '');
  assert.equal(byClass(host, 'pn-mon-big')[0].textContent, '42%');
  assert.equal(byClass(host, 'pn-mon-fill')[0].style.width, '42.4%');
  handle.onTopic('monitor', SAMPLE);
  assert.equal(byClass(host, 'pn-mon-col').length, 2);
});

test('memory, disks and network widgets render their data', () => {
  let m = mount('mac-memory');
  m.handle.onTopic('monitor', SAMPLE);
  assert.equal(byClass(m.host, 'pn-mon-big')[0].textContent, '61%');
  assert.deepEqual(byClass(m.host, 'pn-mon-value').map((n) => n.textContent), ['10 GB of 16 GB']);

  m = mount('mac-disks');
  m.handle.onTopic('monitor', SAMPLE);
  assert.equal(byClass(m.host, 'pn-mon-disk').length, 1);
  assert.equal(byClass(m.host, 'pn-mon-label')[0].textContent, '/');

  m = mount('mac-network');
  m.handle.onTopic('monitor', SAMPLE);
  assert.deepEqual(byClass(m.host, 'pn-mon-value').map((n) => n.textContent), ['3 MB/s', '2 KB/s', '12 ms']);
});

test('process names are set as text, never as markup', () => {
  const { host, handle } = mount('mac-processes');
  handle.onTopic('monitor', SAMPLE);
  assert.equal(byClass(host, 'pn-mon-proc-name')[0].textContent, '<b>evil</b>');
  assert.equal(byClass(host, 'pn-mon-proc-cpu')[0].textContent, '50%');
});

test('bad or foreign messages are ignored and destroy stops updates', () => {
  const { host, handle } = mount('mac-cpu');
  handle.onTopic('tasks', SAMPLE);
  handle.onTopic('monitor', null);
  handle.onTopic('monitor', 'text');
  assert.equal(byClass(host, 'pn-mon-big').length, 0);
  handle.onTopic('monitor', {});
  assert.equal(byClass(host, 'pn-mon-big')[0].textContent, '--');
  handle.destroy();
  handle.onTopic('monitor', SAMPLE);
  assert.equal(byClass(host, 'pn-mon-big')[0].textContent, '--');
});

test('a missing ping shows offline and a missing section does not throw', () => {
  const { host, handle } = mount('mac-network');
  handle.onTopic('monitor', { ping: { ms: null } });
  assert.deepEqual(byClass(host, 'pn-mon-value').map((n) => n.textContent), ['--', '--', 'offline']);
});
