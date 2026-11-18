const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

const PanelGrid = require(path.join(__dirname, '../../static/panel/grid.js'));

const LANDSCAPE = { cols: 12, rows: 6 };
const PORTRAIT = { cols: 6, rows: 12 };

test('orientationFor is landscape when wider, portrait otherwise, landscape when equal', () => {
  assert.equal(PanelGrid.orientationFor(960, 720), 'landscape');
  assert.equal(PanelGrid.orientationFor(720, 960), 'portrait');
  assert.equal(PanelGrid.orientationFor(800, 800), 'landscape');
});

test('gridFor uses the layout grid when present and the default otherwise', () => {
  const layout = { grid: { landscape: { cols: 8, rows: 4 } } };
  assert.deepEqual(PanelGrid.gridFor(layout, 'landscape'), { cols: 8, rows: 4 });
  assert.deepEqual(PanelGrid.gridFor(layout, 'portrait'), PORTRAIT);
  assert.deepEqual(PanelGrid.gridFor({}, 'landscape'), LANDSCAPE);
  assert.deepEqual(PanelGrid.gridFor(null, 'portrait'), PORTRAIT);
});

test('pickVariant uses the requested orientation when it has widgets', () => {
  const page = {
    landscape: [{ id: 'a', x: 0, y: 0, w: 1, h: 1 }],
    portrait: [{ id: 'b', x: 0, y: 0, w: 1, h: 1 }]
  };
  const variant = PanelGrid.pickVariant(page, 'portrait');
  assert.equal(variant.orientation, 'portrait');
  assert.equal(variant.widgets[0].id, 'b');
});

test('pickVariant falls back to the other orientation when the requested one is empty', () => {
  const page = { landscape: [{ id: 'a', x: 0, y: 0, w: 1, h: 1 }], portrait: [] };
  const variant = PanelGrid.pickVariant(page, 'portrait');
  assert.equal(variant.orientation, 'landscape');
  assert.equal(variant.widgets[0].id, 'a');
});

test('pickVariant returns the requested orientation with no widgets when both are empty', () => {
  const variant = PanelGrid.pickVariant({ landscape: [], portrait: undefined }, 'portrait');
  assert.equal(variant.orientation, 'portrait');
  assert.deepEqual(variant.widgets, []);
});

test('pickVariant returns a copy of the widget array', () => {
  const page = { landscape: [{ id: 'a', x: 0, y: 0, w: 1, h: 1 }], portrait: [] };
  PanelGrid.pickVariant(page, 'landscape').widgets.pop();
  assert.equal(page.landscape.length, 1);
});

test('cellRect gives percentages on a 12x6 grid', () => {
  assert.deepEqual(PanelGrid.cellRect({ x: 0, y: 0, w: 12, h: 6 }, LANDSCAPE), {
    left: 0, top: 0, width: 100, height: 100
  });
  assert.deepEqual(PanelGrid.cellRect({ x: 6, y: 3, w: 6, h: 3 }, LANDSCAPE), {
    left: 50, top: 50, width: 50, height: 50
  });
});

test('cellRect gives percentages on a 6x12 grid', () => {
  const rect = PanelGrid.cellRect({ x: 1, y: 2, w: 2, h: 4 }, PORTRAIT);
  assert.ok(Math.abs(rect.left - 100 / 6) < 1e-9);
  assert.ok(Math.abs(rect.top - 200 / 12) < 1e-9);
  assert.ok(Math.abs(rect.width - 200 / 6) < 1e-9);
  assert.ok(Math.abs(rect.height - 400 / 12) < 1e-9);
});

test('clampWidget shrinks an oversized widget and pulls it back inside the grid', () => {
  const clamped = PanelGrid.clampWidget({ id: 'a', type: 'clock', x: 11, y: 5, w: 20, h: 20, config: { k: 1 } }, LANDSCAPE);
  assert.deepEqual(clamped, { id: 'a', type: 'clock', x: 0, y: 0, w: 12, h: 6, config: { k: 1 } });
});

test('clampWidget forces w and h to at least one cell and rounds non-integers', () => {
  const small = PanelGrid.clampWidget({ id: 'a', x: 2, y: 2, w: 0, h: -3 }, LANDSCAPE);
  assert.equal(small.w, 1);
  assert.equal(small.h, 1);
  const rounded = PanelGrid.clampWidget({ id: 'a', x: 1.4, y: 2.6, w: 3.7, h: 2.2 }, LANDSCAPE);
  assert.deepEqual([rounded.x, rounded.y, rounded.w, rounded.h], [1, 3, 4, 2]);
  const broken = PanelGrid.clampWidget({ id: 'a', x: NaN, y: 'x', w: NaN, h: undefined }, LANDSCAPE);
  assert.deepEqual([broken.x, broken.y, broken.w, broken.h], [0, 0, 1, 1]);
});

test('clampWidget does not mutate its input', () => {
  const input = { id: 'a', x: 11, y: 5, w: 20, h: 20 };
  const result = PanelGrid.clampWidget(input, LANDSCAPE);
  assert.notEqual(result, input);
  assert.deepEqual(input, { id: 'a', x: 11, y: 5, w: 20, h: 20 });
});

test('overlaps is false for rectangles that only touch an edge or corner', () => {
  const a = { x: 0, y: 0, w: 2, h: 2 };
  assert.equal(PanelGrid.overlaps(a, { x: 2, y: 0, w: 2, h: 2 }), false);
  assert.equal(PanelGrid.overlaps(a, { x: 0, y: 2, w: 2, h: 2 }), false);
  assert.equal(PanelGrid.overlaps(a, { x: 2, y: 2, w: 2, h: 2 }), false);
});

test('overlaps is true for partial and contained rectangles', () => {
  const a = { x: 0, y: 0, w: 4, h: 4 };
  assert.equal(PanelGrid.overlaps(a, { x: 3, y: 3, w: 2, h: 2 }), true);
  assert.equal(PanelGrid.overlaps(a, { x: 1, y: 1, w: 1, h: 1 }), true);
});

test('collides ignores the widget itself (same id) and edge-touching neighbours', () => {
  const others = [
    { id: 'a', x: 0, y: 0, w: 4, h: 4 },
    { id: 'b', x: 4, y: 0, w: 2, h: 2 }
  ];
  assert.equal(PanelGrid.collides({ id: 'a', x: 0, y: 0, w: 4, h: 4 }, others), false);
  assert.equal(PanelGrid.collides({ id: 'c', x: 3, y: 0, w: 2, h: 2 }, others), true);
  assert.equal(PanelGrid.collides({ id: 'c', x: 6, y: 0, w: 2, h: 2 }, others), false);
});

test('findFreeSpot returns the first free position scanning rows then columns', () => {
  const widgets = [{ id: 'a', x: 0, y: 0, w: 12, h: 2 }];
  assert.deepEqual(PanelGrid.findFreeSpot(widgets, 4, 2, LANDSCAPE), { x: 0, y: 2 });
  const gap = [{ id: 'a', x: 0, y: 0, w: 6, h: 2 }];
  assert.deepEqual(PanelGrid.findFreeSpot(gap, 4, 2, LANDSCAPE), { x: 6, y: 0 });
});

test('findFreeSpot returns null when the grid is full or the size cannot fit', () => {
  const full = [{ id: 'a', x: 0, y: 0, w: 12, h: 6 }];
  assert.equal(PanelGrid.findFreeSpot(full, 1, 1, LANDSCAPE), null);
  assert.equal(PanelGrid.findFreeSpot([], 13, 1, LANDSCAPE), null);
  assert.equal(PanelGrid.findFreeSpot([], 1, 7, LANDSCAPE), null);
});

test('snap maps a pixel point to the cell under it', () => {
  assert.deepEqual(PanelGrid.snap(0, 0, 120, 60, LANDSCAPE), { x: 0, y: 0 });
  assert.deepEqual(PanelGrid.snap(65, 35, 120, 60, LANDSCAPE), { x: 6, y: 3 });
});

test('snap clamps points outside the stage to the last cell', () => {
  assert.deepEqual(PanelGrid.snap(-50, -50, 120, 60, LANDSCAPE), { x: 0, y: 0 });
  assert.deepEqual(PanelGrid.snap(500, 500, 120, 60, LANDSCAPE), { x: 11, y: 5 });
});

test('snap returns the first cell for a zero-sized stage', () => {
  assert.deepEqual(PanelGrid.snap(10, 10, 0, 0, LANDSCAPE), { x: 0, y: 0 });
});
