const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

const PanelArrangeModel = require(path.join(__dirname, '../../static/panel/arrange-model.js'));
const PanelRegistry = require(path.join(__dirname, '../../static/panel/registry.js'));

const LANDSCAPE = { cols: 12, rows: 6 };

function registry() {
  const reg = PanelRegistry.create();
  reg.register({
    id: 'clock',
    title: 'Clock',
    sizes: { min: { w: 2, h: 1 }, max: { w: 12, h: 6 }, default: { w: 4, h: 2 } },
    render() {}
  });
  reg.register({
    id: 'wide',
    title: 'Wide',
    sizes: { min: { w: 3, h: 2 }, max: { w: 6, h: 3 }, default: { w: 6, h: 3 } },
    render() {}
  });
  reg.register({ id: 'note', title: 'Note', render() {} });
  return reg;
}

function model(widgets, options = {}) {
  return PanelArrangeModel.create(Object.assign({
    widgets,
    grid: LANDSCAPE,
    registry: registry(),
    idFn: sequenceIds(['new1', 'new2', 'new3'])
  }, options));
}

function sequenceIds(ids) {
  const queue = ids.slice();
  return () => queue.shift() || 'exhausted';
}

const starter = () => [
  { id: 'a', type: 'clock', x: 0, y: 0, w: 4, h: 2, config: { format: '24h' } },
  { id: 'b', type: 'wide', x: 0, y: 2, w: 6, h: 3, config: {} }
];

test('widgets() returns a copy the caller cannot use to change the model', () => {
  const m = model(starter());
  const list = m.widgets();
  list[0].x = 9;
  list.pop();
  assert.equal(m.widgets().length, 2);
  assert.equal(m.widgets()[0].x, 0);
});

test('create clamps widgets that do not fit the grid', () => {
  const m = model([{ id: 'a', type: 'clock', x: 11, y: 5, w: 20, h: 20, config: {} }]);
  assert.deepEqual(m.widgets()[0], { id: 'a', type: 'clock', x: 0, y: 0, w: 12, h: 6, config: {} });
});

test('a fresh model is not dirty', () => {
  assert.equal(model(starter()).isDirty(), false);
});

test('move to a free spot succeeds and makes the model dirty', () => {
  const m = model(starter());
  assert.equal(m.move('a', 6, 0), true);
  const moved = m.widgets().find((w) => w.id === 'a');
  assert.deepEqual([moved.x, moved.y], [6, 0]);
  assert.equal(m.isDirty(), true);
});

test('move onto another widget is rejected and changes nothing', () => {
  const m = model(starter());
  assert.equal(m.move('a', 0, 2), false);
  const widgets = m.widgets();
  assert.deepEqual([widgets[0].x, widgets[0].y], [0, 0]);
  assert.equal(m.isDirty(), false);
});

test('move clamps the target into the grid before checking collisions', () => {
  const m = model(starter());
  assert.equal(m.move('a', 100, 100), true);
  const moved = m.widgets().find((w) => w.id === 'a');
  assert.deepEqual([moved.x, moved.y], [8, 4]);
});

test('move of an unknown id returns false', () => {
  assert.equal(model(starter()).move('ghost', 0, 0), false);
});

test('move back to the original position is not dirty', () => {
  const m = model(starter());
  m.move('a', 6, 0);
  m.move('a', 0, 0);
  assert.equal(m.isDirty(), false);
});

test('resize clamps to the registry min and max sizes', () => {
  const m = model(starter());
  assert.equal(m.resize('a', 1, 0), true);
  let a = m.widgets().find((w) => w.id === 'a');
  assert.deepEqual([a.w, a.h], [2, 1]);

  assert.equal(m.resize('b', 12, 12), true);
  const b = m.widgets().find((w) => w.id === 'b');
  assert.deepEqual([b.w, b.h], [6, 3]);
});

test('resize is limited by the grid edge so the widget keeps its origin', () => {
  const m = model([{ id: 'a', type: 'clock', x: 10, y: 4, w: 2, h: 2, config: {} }]);
  assert.equal(m.resize('a', 9, 9), true);
  const a = m.widgets()[0];
  assert.deepEqual([a.x, a.y, a.w, a.h], [10, 4, 2, 2]);
});

test('resize that would collide is rejected', () => {
  const m = model(starter());
  assert.equal(m.resize('a', 4, 3), false);
  const a = m.widgets().find((w) => w.id === 'a');
  assert.deepEqual([a.w, a.h], [4, 2]);
});

test('resize of an unknown id returns false', () => {
  assert.equal(model(starter()).resize('ghost', 2, 2), false);
});

test('resize without a registry is limited only by the grid', () => {
  const m = model([{ id: 'a', type: 'unknown', x: 0, y: 0, w: 2, h: 2, config: {} }], { registry: null });
  assert.equal(m.resize('a', 20, 20), true);
  const a = m.widgets()[0];
  assert.deepEqual([a.w, a.h], [12, 6]);
});

test('remove deletes the widget and makes the model dirty', () => {
  const m = model(starter());
  assert.equal(m.remove('a'), true);
  assert.deepEqual(m.widgets().map((w) => w.id), ['b']);
  assert.equal(m.isDirty(), true);
  assert.equal(m.remove('a'), false);
});

test('add places a widget with the default size at the first free spot', () => {
  const m = model(starter());
  const added = m.add('clock');
  assert.deepEqual(added, { id: 'new1', type: 'clock', x: 4, y: 0, w: 4, h: 2, config: {} });
  assert.equal(m.widgets().length, 3);
  assert.equal(m.isDirty(), true);
});

test('add on an empty grid uses the top-left corner', () => {
  const m = model([]);
  assert.deepEqual(m.add('clock'), { id: 'new1', type: 'clock', x: 0, y: 0, w: 4, h: 2, config: {} });
});

test('add falls back to a 2x2 default for types without a default size', () => {
  const m = model([]);
  const added = m.add('note');
  assert.deepEqual([added.w, added.h], [2, 2]);
});

test('add shrinks the default size to fit a narrow grid', () => {
  const m = model([], { grid: { cols: 3, rows: 12 } });
  const added = m.add('wide');
  assert.deepEqual([added.w, added.h], [3, 3]);
});

test('add returns a copy that does not change the model when edited', () => {
  const m = model([]);
  const added = m.add('clock');
  added.x = 9;
  assert.equal(m.widgets()[0].x, 0);
});

test('add skips an id that is already used', () => {
  const m = model([{ id: 'new1', type: 'note', x: 0, y: 0, w: 1, h: 1, config: {} }], {
    idFn: sequenceIds(['new1', 'new2'])
  });
  assert.equal(m.add('clock').id, 'new2');
});

test('add returns null when the grid is full', () => {
  const m = model([{ id: 'a', type: 'note', x: 0, y: 0, w: 12, h: 6, config: {} }]);
  assert.equal(m.add('clock'), null);
  assert.equal(m.canAdd('clock'), false);
  assert.equal(m.widgets().length, 1);
});

test('add returns null for an unknown type', () => {
  const m = model([]);
  assert.equal(m.add('ghost'), null);
  assert.equal(m.canAdd('ghost'), false);
});

test('add returns null when the model has no registry', () => {
  const m = model([], { registry: null });
  assert.equal(m.add('clock'), null);
  assert.equal(m.canAdd('clock'), false);
});

test('canAdd is true when a free spot exists for the type', () => {
  assert.equal(model([]).canAdd('clock'), true);
});

test('generated ids use the w prefix and six characters by default', () => {
  const m = PanelArrangeModel.create({ widgets: [], grid: LANDSCAPE, registry: registry() });
  const id = m.add('note').id;
  assert.match(id, /^w[a-z0-9]{6}$/);
});

test('cancel restores the initial widgets after moves, adds and removals', () => {
  const m = model(starter());
  m.move('a', 6, 0);
  m.remove('b');
  m.add('clock');
  assert.equal(m.isDirty(), true);

  m.cancel();

  assert.equal(m.isDirty(), false);
  assert.deepEqual(m.widgets().map((w) => [w.id, w.x, w.y, w.w, w.h]), [
    ['a', 0, 0, 4, 2],
    ['b', 0, 2, 6, 3]
  ]);
});

test('isDirty compares id, type and geometry but not config', () => {
  const m = model(starter());
  assert.equal(m.isDirty(), false);
  m.resize('b', 6, 3);
  assert.equal(m.isDirty(), false);
  m.resize('b', 5, 3);
  assert.equal(m.isDirty(), true);
});

test('toPayload has page_id, orientation and widgets without config', () => {
  const m = model(starter());
  const payload = m.toPayload('home', 'landscape');
  assert.deepEqual(payload, {
    page_id: 'home',
    orientation: 'landscape',
    widgets: [
      { id: 'a', type: 'clock', x: 0, y: 0, w: 4, h: 2 },
      { id: 'b', type: 'wide', x: 0, y: 2, w: 6, h: 3 }
    ]
  });
  payload.widgets.forEach((w) => assert.equal(Object.prototype.hasOwnProperty.call(w, 'config'), false));
});

test('toPayload reflects the current arrangement', () => {
  const m = model(starter());
  m.move('a', 6, 0);
  m.remove('b');
  assert.deepEqual(m.toPayload('home', 'portrait').widgets, [
    { id: 'a', type: 'clock', x: 6, y: 0, w: 4, h: 2 }
  ]);
});
