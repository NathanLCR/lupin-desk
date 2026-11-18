const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

const EditorModel = require(path.join(__dirname, '../../static/editor/editor-model.js'));
const PanelGrid = require(path.join(__dirname, '../../static/panel/grid.js'));

const ID_RE = /^[A-Za-z0-9_-]{1,32}$/;

function deepFreeze(value) {
  if (value && typeof value === 'object') {
    Object.getOwnPropertyNames(value).forEach((key) => deepFreeze(value[key]));
    Object.freeze(value);
  }
  return value;
}

function widget(id, x, y, w, h, extra) {
  return Object.assign({ id, type: 'clock', x, y, w, h, config: {} }, extra || {});
}

function makeLayout(grid, pages) {
  return {
    id: 'lay-1',
    name: 'Desk',
    version: 1,
    updated_at: '2026-11-18T10:00:00Z',
    grid: grid || {
      landscape: { cols: 12, rows: 6 },
      portrait: { cols: 6, rows: 12 }
    },
    pages: pages || [
      {
        id: 'p1',
        title: 'Main',
        landscape: [widget('a', 0, 0, 4, 2), widget('b', 4, 0, 4, 2)],
        portrait: [widget('c', 0, 0, 3, 3)]
      },
      { id: 'p2', title: 'Second', landscape: [], portrait: [] }
    ]
  };
}

function frozenLayout(grid, pages) {
  return deepFreeze(makeLayout(grid, pages));
}

function snapshot(layout) {
  return JSON.stringify(layout);
}

function allWidgets(layout, pageId, orientation) {
  const page = layout.pages.find((p) => p.id === pageId);
  return page[orientation];
}

function assertNoOverlap(widgets) {
  for (let i = 0; i < widgets.length; i++) {
    for (let j = i + 1; j < widgets.length; j++) {
      assert.equal(PanelGrid.overlaps(widgets[i], widgets[j]), false,
        `${widgets[i].id} overlaps ${widgets[j].id}`);
    }
  }
}

const GRIDS = {
  default: undefined,
  swapped: {
    landscape: { cols: 6, rows: 12 },
    portrait: { cols: 12, rows: 6 }
  },
  custom: {
    landscape: { cols: 6, rows: 12 },
    portrait: { cols: 6, rows: 12 }
  }
};

// ---------- newId ----------

test('newId returns prefix-1 when nothing is taken', () => {
  assert.equal(EditorModel.newId('clock', []), 'clock-1');
  assert.equal(EditorModel.newId('clock', undefined), 'clock-1');
});

test('newId picks the smallest free n', () => {
  assert.equal(EditorModel.newId('clock', ['clock-1', 'clock-3']), 'clock-2');
  assert.equal(EditorModel.newId('clock', ['clock-1', 'clock-2']), 'clock-3');
});

test('newId sanitises the prefix to [A-Za-z0-9_-]', () => {
  assert.equal(EditorModel.newId('my widget!/x', []), 'mywidgetx-1');
  assert.equal(EditorModel.newId('a_b-c', []), 'a_b-c-1');
});

test('newId falls back to a default prefix when the sanitised prefix is empty', () => {
  const id = EditorModel.newId('!!!', []);
  assert.match(id, ID_RE);
  assert.equal(id, 'item-1');
});

test('newId keeps the whole id at most 32 characters and matches the regex', () => {
  const long = 'x'.repeat(80);
  const first = EditorModel.newId(long, []);
  assert.equal(first.length, 32);
  assert.match(first, ID_RE);
  assert.equal(first, 'x'.repeat(30) + '-1');

  const taken = [first];
  const second = EditorModel.newId(long, taken);
  assert.equal(second.length, 32);
  assert.match(second, ID_RE);
  assert.notEqual(second, first);
  assert.equal(second, 'x'.repeat(30) + '-2');
});

test('newId never returns an id already in existingIds', () => {
  const existing = ['w-1', 'w-2', 'w-3', 'w-4', 'w-5'];
  const id = EditorModel.newId('w', existing);
  assert.equal(existing.includes(id), false);
  assert.equal(id, 'w-6');
});

// ---------- renameLayout ----------

test('renameLayout trims the name and does not mutate the input', () => {
  const layout = frozenLayout();
  const before = snapshot(layout);
  const out = EditorModel.renameLayout(layout, '  Office  ');
  assert.equal(out.name, 'Office');
  assert.equal(out.id, layout.id);
  assert.notEqual(out, layout);
  assert.equal(snapshot(layout), before);
});

test('renameLayout ignores an empty or whitespace name', () => {
  const layout = makeLayout();
  assert.deepEqual(EditorModel.renameLayout(layout, '   '), layout);
  assert.deepEqual(EditorModel.renameLayout(layout, ''), layout);
});

test('renameLayout cuts the name at 60 characters', () => {
  const out = EditorModel.renameLayout(makeLayout(), 'n'.repeat(75));
  assert.equal(out.name.length, 60);
});

// ---------- addPage ----------

test('addPage appends an empty page with a fresh id', () => {
  const layout = frozenLayout();
  const before = snapshot(layout);
  const result = EditorModel.addPage(layout, '  Music  ');
  assert.match(result.pageId, ID_RE);
  assert.equal(result.layout.pages.length, 3);
  const page = result.layout.pages[2];
  assert.equal(page.id, result.pageId);
  assert.equal(page.title, 'Music');
  assert.deepEqual(page.landscape, []);
  assert.deepEqual(page.portrait, []);
  assert.equal(snapshot(layout), before);
});

test('addPage cuts the title at 40 characters', () => {
  const result = EditorModel.addPage(makeLayout(), 't'.repeat(60));
  assert.equal(result.layout.pages[2].title.length, 40);
});

test('addPage refuses past 12 pages and returns pageId null', () => {
  const pages = [];
  for (let i = 0; i < 12; i++) {
    pages.push({ id: 'p' + i, title: 'P' + i, landscape: [], portrait: [] });
  }
  const layout = frozenLayout(undefined, pages);
  const result = EditorModel.addPage(layout, 'Extra');
  assert.equal(result.pageId, null);
  assert.equal(result.layout.pages.length, 12);
});

test('addPage gives a new id that does not collide with existing page ids', () => {
  const layout = makeLayout(undefined, [
    { id: 'page-1', title: 'A', landscape: [], portrait: [] }
  ]);
  const result = EditorModel.addPage(layout, 'B');
  assert.equal(result.pageId, 'page-2');
});

// ---------- renamePage ----------

test('renamePage trims, cuts at 40 and ignores empty titles', () => {
  const layout = frozenLayout();
  const before = snapshot(layout);
  assert.equal(EditorModel.renamePage(layout, 'p1', '  Work  ').pages[0].title, 'Work');
  assert.equal(EditorModel.renamePage(layout, 'p1', 'z'.repeat(50)).pages[0].title.length, 40);
  assert.equal(EditorModel.renamePage(layout, 'p1', '   ').pages[0].title, 'Main');
  assert.equal(EditorModel.renamePage(layout, 'nope', 'X').pages[0].title, 'Main');
  assert.equal(snapshot(layout), before);
});

// ---------- removePage ----------

test('removePage removes the page and keeps the others in order', () => {
  const layout = frozenLayout();
  const before = snapshot(layout);
  const out = EditorModel.removePage(layout, 'p1');
  assert.deepEqual(out.pages.map((p) => p.id), ['p2']);
  assert.equal(snapshot(layout), before);
});

test('removePage never removes the last page', () => {
  const layout = makeLayout(undefined, [{ id: 'only', title: 'Only', landscape: [], portrait: [] }]);
  assert.deepEqual(EditorModel.removePage(layout, 'only'), layout);
});

test('removePage with an unknown page id leaves the layout unchanged', () => {
  const layout = makeLayout();
  assert.deepEqual(EditorModel.removePage(layout, 'missing'), layout);
});

// ---------- movePage ----------

test('movePage moves a page by one step and clamps at the ends', () => {
  const layout = frozenLayout();
  const before = snapshot(layout);
  assert.deepEqual(EditorModel.movePage(layout, 'p1', 1).pages.map((p) => p.id), ['p2', 'p1']);
  assert.deepEqual(EditorModel.movePage(layout, 'p2', -1).pages.map((p) => p.id), ['p2', 'p1']);
  assert.deepEqual(EditorModel.movePage(layout, 'p1', -1).pages.map((p) => p.id), ['p1', 'p2']);
  assert.deepEqual(EditorModel.movePage(layout, 'p2', 1).pages.map((p) => p.id), ['p1', 'p2']);
  assert.equal(snapshot(layout), before);
});

test('movePage with a large delta clamps to the first or last position', () => {
  const pages = ['a', 'b', 'c', 'd'].map((id) => ({ id, title: id, landscape: [], portrait: [] }));
  const layout = frozenLayout(undefined, pages);
  assert.deepEqual(EditorModel.movePage(layout, 'b', 10).pages.map((p) => p.id), ['a', 'c', 'd', 'b']);
  assert.deepEqual(EditorModel.movePage(layout, 'c', -10).pages.map((p) => p.id), ['c', 'a', 'b', 'd']);
});

// ---------- addWidget ----------

test('addWidget places a widget at the first free spot and reports its id', () => {
  const layout = frozenLayout();
  const before = snapshot(layout);
  const result = EditorModel.addWidget(layout, 'p1', 'landscape', {
    id: 'clock',
    sizes: { default: { w: 4, h: 2 } }
  });
  assert.match(result.widgetId, ID_RE);
  const placed = allWidgets(result.layout, 'p1', 'landscape');
  assert.equal(placed.length, 3);
  const added = placed[2];
  assert.equal(added.id, result.widgetId);
  assert.equal(added.type, 'clock');
  assert.deepEqual([added.x, added.y, added.w, added.h], [8, 0, 4, 2]);
  assert.deepEqual(added.config, {});
  assertNoOverlap(placed);
  assert.equal(snapshot(layout), before);
});

test('addWidget uses an id unique within that variant only', () => {
  const layout = makeLayout(undefined, [
    {
      id: 'p1',
      title: 'Main',
      landscape: [widget('clock-1', 0, 0, 2, 2)],
      portrait: []
    }
  ]);
  const result = EditorModel.addWidget(layout, 'p1', 'landscape', {
    id: 'clock',
    sizes: { default: { w: 2, h: 2 } }
  });
  assert.equal(result.widgetId, 'clock-2');
  assert.deepEqual(allWidgets(result.layout, 'p1', 'portrait'), []);
});

test('addWidget does not add the widget to the other orientation', () => {
  const layout = frozenLayout();
  const result = EditorModel.addWidget(layout, 'p2', 'portrait', {
    id: 'clock',
    sizes: { default: { w: 2, h: 2 } }
  });
  assert.equal(allWidgets(result.layout, 'p2', 'landscape').length, 0);
  assert.equal(allWidgets(result.layout, 'p2', 'portrait').length, 1);
});

test('addWidget shrinks to 1x1 when the default does not fit but 1x1 does', () => {
  // Landscape 12x6 with a 12x5 widget blocking almost everything.
  const layout = makeLayout(undefined, [
    { id: 'p1', title: 'Main', landscape: [widget('big', 0, 0, 12, 5)], portrait: [] }
  ]);
  const result = EditorModel.addWidget(layout, 'p1', 'landscape', {
    id: 'clock',
    sizes: { default: { w: 4, h: 2 } }
  });
  assert.notEqual(result.widgetId, null);
  const added = allWidgets(result.layout, 'p1', 'landscape')[1];
  assert.deepEqual([added.x, added.y, added.w, added.h], [0, 5, 1, 1]);
  assertNoOverlap(allWidgets(result.layout, 'p1', 'landscape'));
});

test('addWidget returns widgetId null and leaves the layout when there is no room', () => {
  const layout = makeLayout(undefined, [
    { id: 'p1', title: 'Main', landscape: [widget('full', 0, 0, 12, 6)], portrait: [] }
  ]);
  const before = snapshot(layout);
  const result = EditorModel.addWidget(layout, 'p1', 'landscape', {
    id: 'clock',
    sizes: { default: { w: 1, h: 1 } }
  });
  assert.equal(result.widgetId, null);
  assert.equal(snapshot(result.layout), before);
  assert.equal(snapshot(layout), before);
});

test('addWidget returns widgetId null at 36 widgets per variant', () => {
  const widgets = [];
  for (let i = 0; i < 36; i++) widgets.push(widget('w' + i, 0, 0, 1, 1));
  const layout = makeLayout(undefined, [{ id: 'p1', title: 'Main', landscape: widgets, portrait: [] }]);
  const result = EditorModel.addWidget(layout, 'p1', 'landscape', {
    id: 'clock',
    sizes: { default: { w: 1, h: 1 } }
  });
  assert.equal(result.widgetId, null);
  assert.equal(allWidgets(result.layout, 'p1', 'landscape').length, 36);
});

test('addWidget with an unknown page returns widgetId null', () => {
  const result = EditorModel.addWidget(makeLayout(), 'nope', 'landscape', {
    id: 'clock',
    sizes: { default: { w: 1, h: 1 } }
  });
  assert.equal(result.widgetId, null);
});

test('addWidget uses the grid of each orientation (6x12 landscape, 12x6 portrait)', () => {
  const layout = frozenLayout(GRIDS.swapped);
  const landscape = EditorModel.addWidget(layout, 'p2', 'landscape', {
    id: 'clock',
    sizes: { default: { w: 6, h: 12 } }
  });
  assert.deepEqual(
    [allWidgets(landscape.layout, 'p2', 'landscape')[0].w, allWidgets(landscape.layout, 'p2', 'landscape')[0].h],
    [6, 12]
  );
  const portrait = EditorModel.addWidget(layout, 'p2', 'portrait', {
    id: 'clock',
    sizes: { default: { w: 12, h: 6 } }
  });
  assert.deepEqual(
    [allWidgets(portrait.layout, 'p2', 'portrait')[0].w, allWidgets(portrait.layout, 'p2', 'portrait')[0].h],
    [12, 6]
  );
  // A 7-wide widget cannot fit a 6-column landscape grid: it is clamped to 6.
  const clamped = EditorModel.addWidget(layout, 'p2', 'landscape', {
    id: 'wide',
    sizes: { default: { w: 7, h: 2 } }
  });
  assert.equal(allWidgets(clamped.layout, 'p2', 'landscape')[0].w, 6);
});

// ---------- updateWidget ----------

test('updateWidget moves a widget and reports ok true without mutating the input', () => {
  const layout = frozenLayout();
  const before = snapshot(layout);
  const result = EditorModel.updateWidget(layout, 'p1', 'landscape', 'a', { x: 8, y: 3 });
  assert.equal(result.ok, true);
  const moved = allWidgets(result.layout, 'p1', 'landscape').find((w) => w.id === 'a');
  assert.deepEqual([moved.x, moved.y, moved.w, moved.h], [8, 3, 4, 2]);
  assert.equal(snapshot(layout), before);
});

test('updateWidget clamps values to the grid of that orientation', () => {
  const layout = makeLayout(undefined, [
    { id: 'p1', title: 'Main', landscape: [widget('a', 0, 0, 2, 2)], portrait: [] }
  ]);
  const result = EditorModel.updateWidget(layout, 'p1', 'landscape', 'a', { x: 100, y: -5, w: 50, h: 0 });
  assert.equal(result.ok, true);
  const w = allWidgets(result.layout, 'p1', 'landscape').find((x) => x.id === 'a');
  assert.deepEqual([w.x, w.y, w.w, w.h], [0, 0, 12, 1]);
});

test('updateWidget clamps to the 6x12 grid when that is the landscape grid', () => {
  const layout = frozenLayout(GRIDS.swapped, [
    { id: 'p1', title: 'Main', landscape: [widget('a', 0, 0, 2, 2)], portrait: [] }
  ]);
  const result = EditorModel.updateWidget(layout, 'p1', 'landscape', 'a', { x: 99, y: 99, w: 99, h: 99 });
  assert.equal(result.ok, true);
  const w = allWidgets(result.layout, 'p1', 'landscape')[0];
  assert.deepEqual([w.x, w.y, w.w, w.h], [0, 0, 6, 12]);
});

test('updateWidget returns ok false and leaves the layout when it would overlap', () => {
  const layout = frozenLayout();
  const before = snapshot(layout);
  const result = EditorModel.updateWidget(layout, 'p1', 'landscape', 'a', { x: 3 });
  assert.equal(result.ok, false);
  assert.equal(snapshot(result.layout), before);
});

test('updateWidget returns ok false for unknown page or widget ids', () => {
  const layout = frozenLayout();
  const before = snapshot(layout);
  const badPage = EditorModel.updateWidget(layout, 'nope', 'landscape', 'a', { x: 1 });
  assert.equal(badPage.ok, false);
  assert.equal(snapshot(badPage.layout), before);
  const badWidget = EditorModel.updateWidget(layout, 'p1', 'landscape', 'zzz', { x: 1 });
  assert.equal(badWidget.ok, false);
  assert.equal(snapshot(badWidget.layout), before);
});

test('updateWidget keeps the widget type and config', () => {
  const layout = makeLayout(undefined, [
    { id: 'p1', title: 'Main', landscape: [widget('a', 0, 0, 2, 2, { config: { city: 'Lisbon' } })], portrait: [] }
  ]);
  const result = EditorModel.updateWidget(layout, 'p1', 'landscape', 'a', { x: 4 });
  const w = allWidgets(result.layout, 'p1', 'landscape')[0];
  assert.equal(w.type, 'clock');
  assert.deepEqual(w.config, { city: 'Lisbon' });
});

// ---------- removeWidget ----------

test('removeWidget removes only the target widget', () => {
  const layout = frozenLayout();
  const before = snapshot(layout);
  const out = EditorModel.removeWidget(layout, 'p1', 'landscape', 'a');
  assert.deepEqual(allWidgets(out, 'p1', 'landscape').map((w) => w.id), ['b']);
  assert.equal(snapshot(layout), before);
});

test('removeWidget with unknown ids leaves the layout unchanged', () => {
  const layout = makeLayout();
  assert.deepEqual(EditorModel.removeWidget(layout, 'p1', 'landscape', 'zzz'), layout);
  assert.deepEqual(EditorModel.removeWidget(layout, 'nope', 'landscape', 'a'), layout);
});

// ---------- setWidgetConfig ----------

test('setWidgetConfig replaces the config with a copy', () => {
  const layout = frozenLayout();
  const before = snapshot(layout);
  const config = { city: 'Porto', units: { temp: 'C' } };
  const out = EditorModel.setWidgetConfig(layout, 'p1', 'landscape', 'a', config);
  assert.deepEqual(allWidgets(out, 'p1', 'landscape')[0].config, config);
  config.city = 'changed';
  assert.equal(allWidgets(out, 'p1', 'landscape')[0].config.city, 'Porto');
  assert.equal(snapshot(layout), before);
});

test('setWidgetConfig rejects non-object config and returns the layout unchanged', () => {
  const layout = makeLayout();
  for (const bad of [null, 'text', 42, true, ['a'], undefined]) {
    assert.deepEqual(EditorModel.setWidgetConfig(layout, 'p1', 'landscape', 'a', bad), layout);
  }
});

test('setWidgetConfig with an unknown widget leaves the layout unchanged', () => {
  const layout = makeLayout();
  assert.deepEqual(EditorModel.setWidgetConfig(layout, 'p1', 'landscape', 'zzz', { a: 1 }), layout);
});

// ---------- copyVariant ----------

test('copyVariant scales landscape to portrait on the default 12x6 -> 6x12 grids', () => {
  const layout = frozenLayout(undefined, [
    {
      id: 'p1',
      title: 'Main',
      landscape: [widget('a', 0, 0, 6, 3), widget('b', 6, 3, 6, 3)],
      portrait: [widget('old', 0, 0, 1, 1)]
    }
  ]);
  const before = snapshot(layout);
  const out = EditorModel.copyVariant(layout, 'p1', 'landscape', 'portrait');
  // x and w scale by 6/12 = 0.5, y and h by 12/6 = 2.
  assert.deepEqual(allWidgets(out, 'p1', 'portrait'), [
    { id: 'a', type: 'clock', x: 0, y: 0, w: 3, h: 6, config: {} },
    { id: 'b', type: 'clock', x: 3, y: 6, w: 3, h: 6, config: {} }
  ]);
  assert.equal(snapshot(layout), before);
});

test('copyVariant scales portrait to landscape on the default grids', () => {
  const layout = frozenLayout(undefined, [
    {
      id: 'p1',
      title: 'Main',
      landscape: [],
      portrait: [widget('a', 0, 0, 3, 6)]
    }
  ]);
  const out = EditorModel.copyVariant(layout, 'p1', 'portrait', 'landscape');
  // x and w scale by 12/6 = 2, y and h by 6/12 = 0.5.
  assert.deepEqual(allWidgets(out, 'p1', 'landscape'), [
    { id: 'a', type: 'clock', x: 0, y: 0, w: 6, h: 3, config: {} }
  ]);
});

test('copyVariant scales correctly on a swapped grid (6x12 landscape, 12x6 portrait)', () => {
  const layout = frozenLayout(GRIDS.swapped, [
    {
      id: 'p1',
      title: 'Main',
      landscape: [widget('a', 0, 0, 3, 6)],
      portrait: []
    }
  ]);
  const out = EditorModel.copyVariant(layout, 'p1', 'landscape', 'portrait');
  // landscape 6x12 -> portrait 12x6: x,w *2 and y,h *0.5
  assert.deepEqual(allWidgets(out, 'p1', 'portrait'), [
    { id: 'a', type: 'clock', x: 0, y: 0, w: 6, h: 3, config: {} }
  ]);
});

test('copyVariant replaces the target variant and keeps the source', () => {
  const layout = frozenLayout();
  const out = EditorModel.copyVariant(layout, 'p1', 'landscape', 'portrait');
  assert.deepEqual(allWidgets(out, 'p1', 'landscape'), allWidgets(layout, 'p1', 'landscape'));
  assert.equal(allWidgets(out, 'p1', 'portrait').some((w) => w.id === 'c'), false);
});

test('copyVariant moves a colliding widget to the next free spot or drops it', () => {
  // Two landscape widgets both scale to the same 3x3 cell in portrait,
  // a third one cannot fit anywhere after the first two fill the grid.
  const widgets = [
    widget('a', 0, 0, 2, 2),
    widget('b', 0, 0, 2, 2),
    widget('c', 2, 0, 10, 6)
  ];
  const layout = frozenLayout(undefined, [{ id: 'p1', title: 'Main', landscape: widgets, portrait: [] }]);
  const out = EditorModel.copyVariant(layout, 'p1', 'landscape', 'portrait');
  const placed = allWidgets(out, 'p1', 'portrait');
  assertNoOverlap(placed);
  const ids = placed.map((w) => w.id);
  assert.equal(ids.includes('a'), true);
  assert.equal(ids.includes('b'), true);
  for (const w of placed) {
    assert.ok(w.x >= 0 && w.y >= 0 && w.x + w.w <= 6 && w.y + w.h <= 12, `${w.id} inside grid`);
  }
});

test('copyVariant drops a widget when there is no free spot left', () => {
  // Portrait 6x12 is full after the first widget, so the second is dropped.
  const layout = frozenLayout(undefined, [
    {
      id: 'p1',
      title: 'Main',
      landscape: [widget('a', 0, 0, 12, 6), widget('b', 0, 0, 2, 2)],
      portrait: []
    }
  ]);
  const out = EditorModel.copyVariant(layout, 'p1', 'landscape', 'portrait');
  const placed = allWidgets(out, 'p1', 'portrait');
  assert.deepEqual(placed.map((w) => w.id), ['a']);
});

test('copyVariant with an unknown page leaves the layout unchanged', () => {
  const layout = makeLayout();
  assert.deepEqual(EditorModel.copyVariant(layout, 'nope', 'landscape', 'portrait'), layout);
});

// ---------- duplicateDoc ----------

test('duplicateDoc returns a doc without id or updated_at, version 1, with the new name', () => {
  const layout = frozenLayout();
  const before = snapshot(layout);
  const doc = EditorModel.duplicateDoc(layout, '  Desk copy  ');
  assert.deepEqual(Object.keys(doc).sort(), ['grid', 'name', 'pages', 'version']);
  assert.equal(doc.name, 'Desk copy');
  assert.equal(doc.version, 1);
  assert.deepEqual(doc.grid, layout.grid);
  assert.deepEqual(doc.pages, layout.pages);
  doc.pages[0].title = 'Changed';
  assert.equal(snapshot(layout), before);
});

test('duplicateDoc falls back to a copy name and cuts at 60', () => {
  assert.equal(EditorModel.duplicateDoc(makeLayout(), '   ').name, 'Desk copy');
  assert.equal(EditorModel.duplicateDoc(makeLayout(), 'd'.repeat(90)).name.length, 60);
});

// ---------- isDirty ----------

test('isDirty ignores updated_at', () => {
  const a = makeLayout();
  const b = JSON.parse(JSON.stringify(a));
  b.updated_at = '2030-01-01T00:00:00Z';
  assert.equal(EditorModel.isDirty(a, b), false);
});

test('isDirty is true when any real field differs', () => {
  const a = makeLayout();
  const b = JSON.parse(JSON.stringify(a));
  b.pages[0].landscape[0].x = 1;
  assert.equal(EditorModel.isDirty(a, b), true);
  const c = JSON.parse(JSON.stringify(a));
  c.name = 'Other';
  assert.equal(EditorModel.isDirty(a, c), true);
});

test('isDirty does not depend on key order and does not mutate its inputs', () => {
  const a = frozenLayout();
  const reordered = {};
  Object.keys(a).reverse().forEach((key) => { reordered[key] = a[key]; });
  assert.equal(EditorModel.isDirty(a, reordered), false);
});

// ---------- reorder ----------

test('reorder moves an item to the target index and returns a new array', () => {
  const list = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];
  deepFreeze(list);
  const out = EditorModel.reorder(list, 'c', 0);
  assert.deepEqual(out.map((x) => x.id), ['c', 'a', 'b']);
  assert.notEqual(out, list);
  assert.deepEqual(list.map((x) => x.id), ['a', 'b', 'c']);
});

test('reorder clamps the target index and ignores unknown ids', () => {
  const list = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];
  assert.deepEqual(EditorModel.reorder(list, 'a', 99).map((x) => x.id), ['b', 'c', 'a']);
  assert.deepEqual(EditorModel.reorder(list, 'a', -4).map((x) => x.id), ['a', 'b', 'c']);
  assert.deepEqual(EditorModel.reorder(list, 'zzz', 0).map((x) => x.id), ['a', 'b', 'c']);
});

// ---------- getPage / getWidget ----------

test('getPage returns a copy of the page or null', () => {
  const layout = frozenLayout();
  const page = EditorModel.getPage(layout, 'p1');
  assert.equal(page.title, 'Main');
  page.title = 'Changed';
  assert.equal(layout.pages[0].title, 'Main');
  assert.equal(EditorModel.getPage(layout, 'nope'), null);
});

test('getWidget returns a copy of the widget or null', () => {
  const layout = frozenLayout();
  const w = EditorModel.getWidget(layout, 'p1', 'landscape', 'a');
  assert.equal(w.id, 'a');
  w.x = 9;
  assert.equal(layout.pages[0].landscape[0].x, 0);
  assert.equal(EditorModel.getWidget(layout, 'p1', 'landscape', 'zzz'), null);
  assert.equal(EditorModel.getWidget(layout, 'nope', 'landscape', 'a'), null);
});

// ---------- Grid independence: same logic on 6x12 landscape and 12x6 portrait ----------

test('every grid-dependent operation works on a 6x12 landscape / 12x6 portrait layout', () => {
  const layout = frozenLayout(GRIDS.swapped, [
    { id: 'p1', title: 'Main', landscape: [widget('a', 0, 0, 3, 3)], portrait: [widget('b', 0, 0, 6, 2)] },
    { id: 'p2', title: 'Second', landscape: [], portrait: [] }
  ]);
  const added = EditorModel.addWidget(layout, 'p2', 'landscape', { id: 'clock', sizes: { default: { w: 6, h: 12 } } });
  assert.notEqual(added.widgetId, null);
  assert.deepEqual(
    [allWidgets(added.layout, 'p2', 'landscape')[0].w, allWidgets(added.layout, 'p2', 'landscape')[0].h],
    [6, 12]
  );
  const moved = EditorModel.updateWidget(layout, 'p1', 'landscape', 'a', { x: 3, y: 3 });
  assert.equal(moved.ok, true);
  const overflow = EditorModel.updateWidget(layout, 'p1', 'landscape', 'a', { x: 5 });
  assert.equal(overflow.ok, true, 'x clamps to 3 so the widget still fits 6 columns');
  assert.equal(allWidgets(overflow.layout, 'p1', 'landscape')[0].x, 3);
  // portrait 12x6 -> landscape 6x12: x,w *0.5 and y,h *2
  const copied = EditorModel.copyVariant(layout, 'p1', 'portrait', 'landscape');
  assert.deepEqual(allWidgets(copied, 'p1', 'landscape'), [
    { id: 'b', type: 'clock', x: 0, y: 0, w: 3, h: 4, config: {} }
  ]);
});

test('the same operations on the default 12x6 / 6x12 layout use those grids', () => {
  const layout = frozenLayout();
  const widthResult = EditorModel.updateWidget(layout, 'p1', 'portrait', 'c', { x: 10 });
  assert.equal(widthResult.ok, true);
  assert.equal(allWidgets(widthResult.layout, 'p1', 'portrait')[0].x, 3);
  // a is 4 wide; x=6 clamps to x=6 on 12 columns and overlaps b (x 4..8), so it is refused.
  const landscapeClamp = EditorModel.updateWidget(layout, 'p1', 'landscape', 'a', { x: 6 });
  assert.equal(landscapeClamp.ok, false);
});

// ---------- Immutability sweep ----------

test('no function mutates its frozen input layout', () => {
  const layout = frozenLayout();
  const before = snapshot(layout);
  EditorModel.renameLayout(layout, 'X');
  EditorModel.addPage(layout, 'X');
  EditorModel.renamePage(layout, 'p1', 'X');
  EditorModel.removePage(layout, 'p1');
  EditorModel.movePage(layout, 'p1', 1);
  EditorModel.addWidget(layout, 'p1', 'landscape', { id: 'clock', sizes: { default: { w: 1, h: 1 } } });
  EditorModel.updateWidget(layout, 'p1', 'landscape', 'a', { x: 8 });
  EditorModel.removeWidget(layout, 'p1', 'landscape', 'a');
  EditorModel.setWidgetConfig(layout, 'p1', 'landscape', 'a', { k: 1 });
  EditorModel.copyVariant(layout, 'p1', 'landscape', 'portrait');
  EditorModel.duplicateDoc(layout, 'Copy');
  EditorModel.isDirty(layout, layout);
  EditorModel.getPage(layout, 'p1');
  EditorModel.getWidget(layout, 'p1', 'landscape', 'a');
  assert.equal(snapshot(layout), before);
});

test('the returned layout is never the same object as the input', () => {
  const layout = frozenLayout();
  assert.notEqual(EditorModel.renameLayout(layout, 'X'), layout);
  assert.notEqual(EditorModel.removeWidget(layout, 'p1', 'landscape', 'a'), layout);
  assert.notEqual(EditorModel.removePage(layout, 'missing'), layout);
});
