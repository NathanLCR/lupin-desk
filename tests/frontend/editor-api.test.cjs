const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

const EditorApi = require(path.join(__dirname, '../../static/editor/editor-api.js'));

// Fake fetch: records every call and answers with the responder's Response-like object.
function fakeFetch(responder) {
  const calls = [];
  const fn = async (url, options) => {
    calls.push({ url, options });
    return responder ? responder(url, options) : reply(200, '{}');
  };
  fn.calls = calls;
  return fn;
}

function reply(status, text) {
  return { ok: status >= 200 && status < 300, status, text: async () => text };
}

function api(responder) {
  const fetchFn = fakeFetch(responder);
  return { client: EditorApi.create(fetchFn), fetchFn };
}

test('module exposes create()', () => {
  assert.equal(typeof EditorApi.create, 'function');
  const client = EditorApi.create(fakeFetch());
  for (const name of [
    'listLayouts', 'listTemplates', 'getLayout', 'createLayout', 'saveLayout', 'deleteLayout',
    'listDevices', 'updateDevice', 'setPriority', 'getCredentials', 'saveCredentials', 'getClientInfo',
  ]) {
    assert.equal(typeof client[name], 'function', name);
  }
});

test('every method calls the contract URL with the contract verb and body', async () => {
  const layout = { id: 'main', name: 'Main', pages: [] };
  const cases = [
    { run: (c) => c.listLayouts(), method: 'GET', url: '/api/layouts', body: undefined },
    { run: (c) => c.listTemplates(), method: 'GET', url: '/api/layout-templates', body: undefined },
    { run: (c) => c.getLayout('main'), method: 'GET', url: '/api/layouts/main', body: undefined },
    { run: (c) => c.createLayout('Desk', 'starter'), method: 'POST', url: '/api/layouts', body: { name: 'Desk', template: 'starter' } },
    { run: (c) => c.saveLayout('main', layout), method: 'PUT', url: '/api/layouts/main', body: layout },
    { run: (c) => c.deleteLayout('main'), method: 'DELETE', url: '/api/layouts/main', body: undefined },
    { run: (c) => c.listDevices(), method: 'GET', url: '/api/devices', body: undefined },
    { run: (c) => c.updateDevice('dev1', { name: 'Desk Mac', roles: ['panel'] }), method: 'PUT', url: '/api/devices/dev1', body: { name: 'Desk Mac', roles: ['panel'] } },
    { run: (c) => c.setPriority(['a', 'b']), method: 'PUT', url: '/api/devices/priority', body: { order: ['a', 'b'] } },
    { run: (c) => c.getCredentials(), method: 'GET', url: '/api/credentials', body: undefined },
    { run: (c) => c.saveCredentials({ OPENAI_KEY: 'x' }), method: 'PUT', url: '/api/credentials', body: { values: { OPENAI_KEY: 'x' } } },
    { run: (c) => c.getClientInfo(), method: 'GET', url: '/api/client-info', body: undefined },
  ];

  for (const item of cases) {
    const { client, fetchFn } = api(() => reply(200, '{"ok":true}'));
    const result = await item.run(client);
    assert.deepEqual(result, { ok: true }, `${item.method} ${item.url} resolves parsed JSON`);
    assert.equal(fetchFn.calls.length, 1, `${item.method} ${item.url} makes one call`);
    const { url, options } = fetchFn.calls[0];
    assert.equal(url, item.url);
    assert.equal(options.method, item.method);
    if (item.body === undefined) {
      assert.equal(options.body, undefined, `${item.method} ${item.url} has no body`);
      assert.equal(Object.prototype.hasOwnProperty.call(options.headers, 'Content-Type'), false);
    } else {
      assert.deepEqual(JSON.parse(options.body), item.body);
      assert.equal(options.headers['Content-Type'], 'application/json');
    }
  }
});

test('GET and DELETE send no Content-Type header', async () => {
  const { client, fetchFn } = api();
  await client.listLayouts();
  await client.deleteLayout('x');
  for (const call of fetchFn.calls) {
    assert.deepEqual(call.options.headers, {});
  }
});

test('ids are encoded with encodeURIComponent', async () => {
  const { client, fetchFn } = api();
  await client.getLayout('a/b c');
  await client.saveLayout('a/b c', { id: 'a/b c' });
  await client.deleteLayout('a/b c');
  await client.updateDevice('a/b c', { name: 'n' });
  const encoded = '/' + encodeURIComponent('a/b c');
  assert.equal(fetchFn.calls[0].url, '/api/layouts' + encoded);
  assert.equal(fetchFn.calls[1].url, '/api/layouts' + encoded);
  assert.equal(fetchFn.calls[2].url, '/api/layouts' + encoded);
  assert.equal(fetchFn.calls[3].url, '/api/devices' + encoded);
  assert.equal(encodeURIComponent('a/b c'), 'a%2Fb%20c');
});

test('an error with a string detail rejects with that detail and the status', async () => {
  const { client } = api(() => reply(409, '{"detail":"starter cannot be deleted"}'));
  await assert.rejects(client.deleteLayout('starter'), (err) => {
    assert.ok(err instanceof Error);
    assert.equal(err.status, 409);
    assert.equal(err.message, 'starter cannot be deleted');
    return true;
  });
});

test('an error with an array detail uses the first item msg', async () => {
  const body = '{"detail":[{"msg":"name too long","loc":["body","name"]},{"msg":"second"}]}';
  const { client } = api(() => reply(422, body));
  await assert.rejects(client.createLayout('x', 'starter'), (err) => {
    assert.equal(err.status, 422);
    assert.equal(err.message, 'name too long');
    return true;
  });
});

test('an error with no JSON body falls back to HTTP status', async () => {
  const { client } = api(() => reply(500, '<html>Internal Server Error</html>'));
  await assert.rejects(client.listLayouts(), (err) => {
    assert.equal(err.status, 500);
    assert.equal(err.message, 'HTTP 500');
    return true;
  });
});

test('an error with an empty body falls back to HTTP status', async () => {
  const { client } = api(() => reply(404, ''));
  await assert.rejects(client.getLayout('missing'), (err) => {
    assert.equal(err.status, 404);
    assert.equal(err.message, 'HTTP 404');
    return true;
  });
});

test('an error with a JSON body that has no detail falls back to HTTP status', async () => {
  const { client } = api(() => reply(400, '{"error":"nope"}'));
  await assert.rejects(client.listDevices(), (err) => {
    assert.equal(err.message, 'HTTP 400');
    return true;
  });
});

test('a successful empty body resolves to null instead of throwing', async () => {
  const { client } = api(() => reply(200, ''));
  assert.equal(await client.deleteLayout('x'), null);
});

test('a successful non-JSON body resolves to null', async () => {
  const { client } = api(() => reply(200, 'plain text'));
  assert.equal(await client.getClientInfo(), null);
});

test('a network failure rejects with the Brain message', async () => {
  const fetchFn = async () => { throw new TypeError('fetch failed'); };
  const client = EditorApi.create(fetchFn);
  await assert.rejects(client.listLayouts(), (err) => {
    assert.ok(err instanceof Error);
    assert.equal(err.message, 'Could not reach the Brain.');
    return true;
  });
});

test('a synchronous throw from fetchFn is also a network failure', async () => {
  const client = EditorApi.create(() => { throw new TypeError('boom'); });
  await assert.rejects(client.listTemplates(), (err) => {
    assert.equal(err.message, 'Could not reach the Brain.');
    return true;
  });
});

test('error messages never include the request body', async () => {
  const secret = 'sk-live-SECRET-VALUE-42';
  const name = 'SECRET-NAME-77';

  const failing = api(() => reply(500, 'not json'));
  await assert.rejects(failing.client.saveCredentials({ OPENAI_KEY: secret }), (err) => {
    assert.ok(!err.message.includes(secret));
    assert.ok(!String(err.stack).includes(secret));
    return true;
  });

  const badRequest = api(() => reply(400, '{"detail":"bad request"}'));
  await assert.rejects(badRequest.client.createLayout(name, 'starter'), (err) => {
    assert.ok(!err.message.includes(name));
    assert.equal(err.message, 'bad request');
    return true;
  });

  const offline = EditorApi.create(async () => { throw new Error('offline ' + secret); });
  await assert.rejects(offline.saveCredentials({ OPENAI_KEY: secret }), (err) => {
    assert.ok(!err.message.includes(secret));
    assert.equal(err.message, 'Could not reach the Brain.');
    return true;
  });
});
