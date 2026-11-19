const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

const { makeDocument, findAll } = require('./panel-fakes.cjs');
const Editor = require(path.join(__dirname, '../../static/panel/widgets-image-editor.js'));
const PanelRegistry = require(path.join(__dirname, '../../static/panel/registry.js'));

function approx(a, b) {
  assert.ok(Math.abs(a - b) < 1e-9, a + ' vs ' + b);
}

test('dragBox moves a box and keeps it inside the image', () => {
  const box = { x: 0.2, y: 0.2, w: 0.4, h: 0.4 };
  const moved = Editor.dragBox(box, 'move', 0.1, -0.5);
  approx(moved.x, 0.3);
  approx(moved.y, 0);
  approx(moved.w, 0.4);
  const far = Editor.dragBox(box, 'move', 5, 5);
  approx(far.x, 0.6);
  approx(far.y, 0.6);
});

test('dragBox resizes from a corner and enforces a minimum size', () => {
  const box = { x: 0.2, y: 0.2, w: 0.4, h: 0.4 };
  const se = Editor.dragBox(box, 'se', 0.1, 0.1);
  approx(se.x, 0.2);
  approx(se.w, 0.5);
  approx(se.h, 0.5);
  const nw = Editor.dragBox(box, 'nw', -0.5, -0.5);
  approx(nw.x, 0);
  approx(nw.y, 0);
  approx(nw.w, 0.6);
  const tiny = Editor.dragBox(box, 'se', -5, -5);
  assert.ok(tiny.w >= 0.05 - 1e-9 && tiny.h >= 0.05 - 1e-9);
  const out = Editor.dragBox(box, 'ne', 5, 0);
  approx(out.x + out.w, 1);
});

test('buildOps orders edits and skips what is not set', () => {
  assert.deepEqual(Editor.buildOps({ crop: { x: 0, y: 0, w: 1, h: 1 }, width: '', height: '', format: '' }), []);
  const ops = Editor.buildOps({
    crop: { x: 0.1, y: 0.2, w: 0.5, h: 0.5 },
    width: '800',
    height: '',
    removeBackground: true,
    compress: true,
    quality: '55',
    format: 'png',
  });
  assert.deepEqual(ops.map((o) => o.op), ['crop', 'resize', 'remove_background', 'compress', 'convert']);
  assert.deepEqual(ops[1], { op: 'resize', width: 800 });
  assert.equal(ops[3].quality, 55);
  assert.equal(ops[4].format, 'png');
});

test('buildOps ignores bad numbers and unknown formats', () => {
  const ops = Editor.buildOps({ crop: null, width: 'abc', height: '-4', compress: true, quality: '900', format: 'bmp' });
  assert.deepEqual(ops, [{ op: 'compress', quality: 100 }]);
});

test('errorText maps Brain error codes and falls back safely', () => {
  assert.match(Editor.errorText('too_large'), /25 MB/);
  assert.match(Editor.errorText('unavailable'), /not available/);
  assert.equal(Editor.errorText('something_else'), Editor.errorText('edit_failed'));
});

function makeXhrStub(handler) {
  const requests = [];
  class Xhr {
    constructor() { this.headers = {}; this.status = 0; this.responseText = ''; }
    open(method, url) { this.method = method; this.url = url; }
    setRequestHeader(k, v) { this.headers[k] = v; }
    send(body) {
      requests.push({ method: this.method, url: this.url, body });
      const answer = handler(this.method, this.url, body);
      this.status = answer.status;
      this.responseText = JSON.stringify(answer.json);
      this.onload();
    }
  }
  return { Xhr, requests };
}

function render(handler) {
  const stub = makeXhrStub(handler);
  const previous = global.XMLHttpRequest;
  global.XMLHttpRequest = stub.Xhr;
  const doc = makeDocument();
  const host = doc.createElement('div');
  doc.body.appendChild(host);
  const instance = Editor.DEFS[0].render(host, { config: {}, sendAction() {}, el: host });
  return { host, doc, instance, stub, restore: () => { global.XMLHttpRequest = previous; } };
}

function byClass(root, name) {
  return findAll(root, (n) => !!n.classList && n.classList.contains(name));
}

test('definition registers with its topic and actions', () => {
  const registry = PanelRegistry.createRegistry ? PanelRegistry.createRegistry() : null;
  const def = Editor.DEFS[0];
  assert.equal(def.id, 'image-editor');
  assert.deepEqual(def.topics, ['images']);
  assert.deepEqual(def.actions, ['image.edit', 'image.discard']);
  if (registry) {
    Editor.registerAll(registry);
    assert.ok(registry.get('image-editor'));
  }
});

test('upload, crop edit and download link flow', () => {
  const { host, stub, restore, instance } = render((method, url) => {
    if (url === '/api/images/last') return { status: 200, json: { pending: null } };
    if (method === 'POST' && url === '/api/images') return { status: 200, json: { id: 'a'.repeat(32), format: 'png' } };
    if (url.endsWith('/edit')) return { status: 200, json: { id: 'b'.repeat(32), name: 'lupin-1.png', format: 'png' } };
    return { status: 404, json: {} };
  });
  try {
    const file = byClass(host, 'pn-imged-file')[0];
    file.files = [{ size: 1000, name: 'x.png' }];
    file.fire('change');
    const img = byClass(host, 'pn-imged-img')[0];
    assert.equal(img.attributes.src, '/api/images/' + 'a'.repeat(32) + '/preview');

    // drag the south-east handle in
    const stage = byClass(host, 'pn-imged-stage')[0];
    stage.clientWidth = 200;
    stage.clientHeight = 100;
    byClass(host, 'pn-imged-se')[0].fire('mousedown', { clientX: 200, clientY: 100 });
    host.ownerDocument.fire('mousemove', { clientX: 100, clientY: 50 });
    host.ownerDocument.fire('mouseup', {});
    const crop = byClass(host, 'pn-imged-crop')[0];
    assert.equal(crop.style.width, '50%');

    byClass(host, 'pn-imged-btn')[0].fire('click');
    const edit = stub.requests.filter((r) => r.url.endsWith('/edit'))[0];
    const sent = JSON.parse(edit.body);
    assert.equal(sent.ops[0].op, 'crop');
    approx(sent.ops[0].w, 0.5);

    const link = byClass(host, 'pn-imged-download')[0];
    assert.equal(link.attributes.href, '/api/images/results/' + 'b'.repeat(32));
    assert.match(link.textContent, /lupin-1\.png/);
    instance.destroy();
  } finally {
    restore();
  }
});

test('oversize file is refused before upload and server errors are shown', () => {
  const { host, stub, restore } = render((method, url) => {
    if (url === '/api/images/last') return { status: 200, json: { pending: null } };
    return { status: 415, json: { detail: 'not_image' } };
  });
  try {
    const file = byClass(host, 'pn-imged-file')[0];
    file.files = [{ size: 26 * 1024 * 1024 }];
    file.fire('change');
    assert.match(byClass(host, 'pn-imged-status')[0].textContent, /25 MB/);
    assert.equal(stub.requests.filter((r) => r.method === 'POST').length, 0);
    file.files = [{ size: 10 }];
    file.fire('change');
    assert.match(byClass(host, 'pn-imged-status')[0].textContent, /not an image/);
  } finally {
    restore();
  }
});

test('topic updates load a pending photo and show a voice-edit result', () => {
  const { host, instance, restore } = render(() => ({ status: 200, json: { pending: null } }));
  try {
    instance.onTopic('images', { pending: { id: 'c'.repeat(32), format: 'jpg' }, result: null });
    assert.equal(byClass(host, 'pn-imged-img')[0].attributes.src, '/api/images/' + 'c'.repeat(32) + '/preview');
    instance.onTopic('images', { pending: null, result: { id: 'd'.repeat(32), name: 'r.png', format: 'png' } });
    assert.equal(byClass(host, 'pn-imged-download')[0].attributes.href, '/api/images/results/' + 'd'.repeat(32));
    instance.onTopic('other', { pending: { id: 'e'.repeat(32) } });
    assert.equal(byClass(host, 'pn-imged-img')[0].attributes.src, '');
  } finally {
    restore();
  }
});

test('names from the server are shown as text, never markup', () => {
  const { host, instance, restore } = render(() => ({ status: 200, json: { pending: null } }));
  try {
    instance.onTopic('images', { result: { id: 'f'.repeat(32), name: '<img src=x onerror=1>.png', format: 'png' } });
    const link = byClass(host, 'pn-imged-download')[0];
    assert.equal(link.textContent, 'Download <img src=x onerror=1>.png');
    assert.equal(link.children.length, 0);
  } finally {
    restore();
  }
});
