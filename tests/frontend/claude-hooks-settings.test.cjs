const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

const Hooks = require(path.join(__dirname, '../../static/claude_hooks_settings.js'));

const STATUS = {
  installed: false,
  settings_file: '/Users/me/.claude/settings.json',
  adds: {
    PermissionRequest: [{ hooks: [{ type: 'command', command: 'curl http://127.0.0.1:8000/api/claude-hooks/permission' }] }],
    Stop: [{ hooks: [{ type: 'command', command: 'curl http://127.0.0.1:8000/api/claude-hooks/event' }] }],
  },
};

function fakeContainer() {
  const listeners = {};
  const nodes = {};
  return {
    innerHTML: '',
    addEventListener(type, fn) { listeners[type] = fn; },
    querySelector(selector) {
      nodes[selector] = nodes[selector] || { textContent: '', className: '' };
      return nodes[selector];
    },
    click(attr) { listeners.click({ target: { hasAttribute: (name) => name === attr } }); },
    nodes,
  };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 5));

test('describeAdds lists every command that would be added', () => {
  const text = Hooks.describeAdds(STATUS.adds);
  assert.ok(text.includes('PermissionRequest -> curl http://127.0.0.1:8000/api/claude-hooks/permission'));
  assert.ok(text.includes('Stop -> curl'));
  assert.equal(Hooks.describeAdds(null), '');
});

test('render shows the file, the exact commands, and escapes everything', () => {
  const evil = { installed: true, settings_file: '<img src=x>', adds: { Stop: [{ hooks: [{ command: '<script>' }] }] } };
  const html = Hooks.render(evil, true);
  assert.ok(!html.includes('<img') && !html.includes('<script>'));
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(html.includes('Installed.'));
  assert.ok(html.includes('data-hooks-remove>Remove'));
  assert.ok(html.includes('data-hooks-install disabled'));
});

test('render without edit rights has no buttons', () => {
  const html = Hooks.render(STATUS, false);
  assert.ok(!html.includes('data-hooks-install'));
  assert.ok(html.includes('Set this up on the Mac.'));
});

test('mount loads the status and Install posts then reloads', async () => {
  const calls = [];
  let installed = false;
  const container = fakeContainer();
  const bodies = [];
  await Hooks.mount(container, {
    confirm: () => true,
    fetchJson(url, options) {
      calls.push([url, (options && options.method) || 'GET']);
      if (options && options.body) bodies.push(options.body);
      if (url.endsWith('/install')) installed = true;
      return Promise.resolve(Object.assign({}, STATUS, { installed }));
    },
  });
  assert.ok(container.innerHTML.includes('Not installed.'));
  container.click('data-hooks-install');
  await flush();
  assert.deepEqual(calls.map((c) => c.join(' ')), [
    '/api/claude-hooks GET', '/api/claude-hooks/install POST', '/api/claude-hooks GET',
  ]);
  assert.deepEqual(bodies, [{ confirm: true }]);
  assert.ok(container.innerHTML.includes('Installed.'));
  assert.equal(container.nodes['[data-hooks-status]'].textContent, 'Hooks installed.');
});

test('declining the confirm step sends nothing', async () => {
  const calls = [];
  const container = fakeContainer();
  await Hooks.mount(container, {
    confirm: () => false,
    fetchJson(url, options) {
      calls.push(url + ((options && options.method) || ''));
      return Promise.resolve(STATUS);
    },
  });
  container.click('data-hooks-install');
  await flush();
  assert.deepEqual(calls, ['/api/claude-hooks']);
});

test('Remove stays available when only a backup is left', () => {
  const html = Hooks.render(Object.assign({}, STATUS, { installed: false, backup: true }), true);
  assert.ok(!/data-hooks-remove disabled/.test(html));
});

test('mount off the Mac shows read-only guidance and an error is reported, not thrown', async () => {
  const container = fakeContainer();
  await Hooks.mount(container, { fetchJson: () => Promise.reject(new Error('Claude Code hooks can only be managed on the Mac.')) });
  assert.ok(container.innerHTML.includes('Set this up on the Mac.'));
  assert.equal(container.nodes['[data-hooks-status]'].textContent, 'Claude Code hooks can only be managed on the Mac.');
  assert.equal(Hooks.mount(null), null);
});
