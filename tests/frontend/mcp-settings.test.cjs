const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

const Mcp = require(path.join(__dirname, '../../static/mcp_settings.js'));

test('escapeHtml neutralises markup and quotes from server text', () => {
  assert.equal(Mcp.escapeHtml('<script>alert("x")</script>'),
    '&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;');
  assert.equal(Mcp.escapeHtml("it's & <b>"), 'it&#39;s &amp; &lt;b&gt;');
  assert.equal(Mcp.escapeHtml(null), '');
  assert.equal(Mcp.escapeHtml(undefined), '');
  assert.equal(Mcp.escapeHtml(42), '42');
});

test('parseCommand splits on whitespace and drops empty parts', () => {
  assert.deepEqual(Mcp.parseCommand('npx   -y  some-server\t--flag'), ['npx', '-y', 'some-server', '--flag']);
  assert.deepEqual(Mcp.parseCommand('   '), []);
  assert.deepEqual(Mcp.parseCommand(''), []);
  assert.deepEqual(Mcp.parseCommand(undefined), []);
});

test('parseCommand does not interpret shell syntax', () => {
  assert.deepEqual(Mcp.parseCommand('echo "a b" $(whoami)'), ['echo', '"a', 'b"', '$(whoami)']);
});

test('parseEnvLines reads KEY=VALUE and keeps extra equals signs in the value', () => {
  const env = Mcp.parseEnvLines('TOKEN=abc=def\n\n  GITHUB_TOKEN = xyz  \r\nEMPTY=');
  assert.deepEqual(env, { TOKEN: 'abc=def', GITHUB_TOKEN: 'xyz', EMPTY: '' });
});

test('parseEnvLines rejects a line without a key', () => {
  assert.throws(() => Mcp.parseEnvLines('NO_EQUALS_HERE'), /KEY=VALUE/);
  assert.throws(() => Mcp.parseEnvLines('=value'), /KEY=VALUE/);
  assert.deepEqual(Mcp.parseEnvLines(''), {});
});

test('parseHeaderLines reads Name: value and keeps colons in the value', () => {
  const headers = Mcp.parseHeaderLines('Authorization: Bearer a:b\nX-Trace:  on  \n');
  assert.deepEqual(headers, { Authorization: 'Bearer a:b', 'X-Trace': 'on' });
});

test('parseHeaderLines rejects a line without a name', () => {
  assert.throws(() => Mcp.parseHeaderLines('just a value'), /Name: value/);
  assert.throws(() => Mcp.parseHeaderLines(': nothing'), /Name: value/);
});

test('riskLabel gives the plain-language label for each risk', () => {
  assert.equal(Mcp.riskLabel('read'), 'Read: runs without asking');
  assert.equal(Mcp.riskLabel('write'), 'Write: asks first');
  assert.equal(Mcp.riskLabel('external'), 'External: asks first');
});

test('riskLabel falls back to the safe default for unknown risks', () => {
  assert.equal(Mcp.riskLabel('constructor'), 'External: asks first');
  assert.equal(Mcp.riskLabel('admin'), 'External: asks first');
  assert.equal(Mcp.riskLabel(undefined), 'External: asks first');
});

test('buildAddPayload builds a stdio payload without http fields', () => {
  const payload = Mcp.buildAddPayload({
    id: ' github ',
    name: ' GitHub ',
    transport: 'stdio',
    command: 'npx -y server-github',
    env: 'GITHUB_TOKEN=ghp_123',
    url: 'https://ignored.example',
    headers: 'Authorization: ignored',
  });
  assert.deepEqual(payload, {
    id: 'github',
    name: 'GitHub',
    transport: 'stdio',
    command: ['npx', '-y', 'server-github'],
    env: { GITHUB_TOKEN: 'ghp_123' },
  });
});

test('buildAddPayload builds an http payload without stdio fields', () => {
  const payload = Mcp.buildAddPayload({
    id: 'docs',
    name: 'Docs',
    transport: 'http',
    url: ' https://example.com/mcp ',
    headers: 'Authorization: Bearer t0ken',
    command: 'ignored --flag',
    env: 'IGNORED=1',
  });
  assert.deepEqual(payload, {
    id: 'docs',
    name: 'Docs',
    transport: 'http',
    url: 'https://example.com/mcp',
    headers: { Authorization: 'Bearer t0ken' },
  });
});

test('buildAddPayload defaults to stdio and surfaces bad env lines', () => {
  const payload = Mcp.buildAddPayload({ id: 'x', name: 'X', command: 'run' });
  assert.equal(payload.transport, 'stdio');
  assert.deepEqual(payload.command, ['run']);
  assert.throws(() => Mcp.buildAddPayload({ transport: 'stdio', env: 'broken' }), /KEY=VALUE/);
});
