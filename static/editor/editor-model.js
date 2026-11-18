(function (root) {
  'use strict';

  // Pure model for the Mac layout editor. No DOM access.
  // Every function returns new objects and never mutates its inputs.
  // The grid size always comes from layout.grid[orientation] through
  // PanelGrid.gridFor; nothing here hardcodes 12 or 6.

  var PanelGrid = (typeof module !== 'undefined' && module.exports) ? require('../panel/grid.js') : root.PanelGrid;

  var MAX_PAGES = 12;
  var MAX_WIDGETS = 36;
  var MAX_PAGE_TITLE = 40;
  var MAX_LAYOUT_NAME = 60;
  var MAX_ID = 32;
  var DEFAULT_ID_PREFIX = 'item';

  function clone(value) {
    return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
  }

  function hasOwn(object, key) {
    return Object.prototype.hasOwnProperty.call(object, key);
  }

  function intClamp(value, low, high) {
    var n = Number(value);
    if (!isFinite(n)) n = low;
    n = Math.round(n);
    return Math.min(high, Math.max(low, n));
  }

  function isPlainObject(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
  }

  function pageIndex(layout, pageId) {
    var pages = (layout && layout.pages) || [];
    for (var i = 0; i < pages.length; i++) {
      if (pages[i] && pages[i].id === pageId) return i;
    }
    return -1;
  }

  function widgetIndex(widgets, widgetId) {
    for (var i = 0; i < widgets.length; i++) {
      if (widgets[i] && widgets[i].id === widgetId) return i;
    }
    return -1;
  }

  function variantOf(page, orientation) {
    return (page && Array.isArray(page[orientation])) ? page[orientation] : [];
  }

  function sanitizePrefix(prefix) {
    return String(prefix === undefined || prefix === null ? '' : prefix).replace(/[^A-Za-z0-9_-]/g, '');
  }

  // "<prefix>-<n>" with the smallest n >= 1 that is not in existingIds.
  // The prefix is cut so the whole id fits in MAX_ID characters.
  function newId(prefix, existingIds) {
    var base = sanitizePrefix(prefix) || DEFAULT_ID_PREFIX;
    var taken = Object.create(null);
    (existingIds || []).forEach(function (id) { taken[String(id)] = true; });
    for (var n = 1; ; n++) {
      var suffix = '-' + n;
      var candidate = base.slice(0, MAX_ID - suffix.length) + suffix;
      if (!taken[candidate]) return candidate;
    }
  }

  function renameLayout(layout, name) {
    var src = clone(layout);
    var trimmed = String(name === undefined || name === null ? '' : name).trim();
    if (!trimmed) return src;
    src.name = trimmed.slice(0, MAX_LAYOUT_NAME);
    return src;
  }

  function addPage(layout, title) {
    var src = clone(layout);
    src.pages = src.pages || [];
    if (src.pages.length >= MAX_PAGES) return { layout: src, pageId: null };
    var pageId = newId('page', src.pages.map(function (p) { return p.id; }));
    var text = String(title === undefined || title === null ? '' : title).trim();
    if (!text) text = 'Page ' + (src.pages.length + 1);
    src.pages.push({
      id: pageId,
      title: text.slice(0, MAX_PAGE_TITLE),
      landscape: [],
      portrait: []
    });
    return { layout: src, pageId: pageId };
  }

  function renamePage(layout, pageId, title) {
    var src = clone(layout);
    var index = pageIndex(src, pageId);
    var text = String(title === undefined || title === null ? '' : title).trim();
    if (index < 0 || !text) return src;
    src.pages[index].title = text.slice(0, MAX_PAGE_TITLE);
    return src;
  }

  function removePage(layout, pageId) {
    var src = clone(layout);
    var index = pageIndex(src, pageId);
    if (index < 0 || src.pages.length <= 1) return src;
    src.pages.splice(index, 1);
    return src;
  }

  function movePage(layout, pageId, delta) {
    var src = clone(layout);
    var index = pageIndex(src, pageId);
    var step = Number(delta);
    if (index < 0 || !isFinite(step)) return src;
    var target = intClamp(index + step, 0, src.pages.length - 1);
    if (target === index) return src;
    var page = src.pages.splice(index, 1)[0];
    src.pages.splice(target, 0, page);
    return src;
  }

  function addWidget(layout, pageId, orientation, def) {
    var src = clone(layout);
    var index = pageIndex(src, pageId);
    if (index < 0) return { layout: src, widgetId: null };

    var page = src.pages[index];
    var widgets = variantOf(page, orientation);
    if (widgets.length >= MAX_WIDGETS) return { layout: src, widgetId: null };

    var grid = PanelGrid.gridFor(src, orientation);
    var sizeDefault = (def && def.sizes && def.sizes.default) || { w: 1, h: 1 };
    var w = intClamp(sizeDefault.w, 1, grid.cols);
    var h = intClamp(sizeDefault.h, 1, grid.rows);

    var spot = PanelGrid.findFreeSpot(widgets, w, h, grid);
    if (!spot && (w !== 1 || h !== 1)) {
      w = 1;
      h = 1;
      spot = PanelGrid.findFreeSpot(widgets, 1, 1, grid);
    }
    if (!spot) return { layout: src, widgetId: null };

    var widgetId = newId(def && def.id, widgets.map(function (x) { return x.id; }));
    page[orientation] = widgets.concat([{
      id: widgetId,
      type: def && def.id,
      x: spot.x,
      y: spot.y,
      w: w,
      h: h,
      config: {}
    }]);
    return { layout: src, widgetId: widgetId };
  }

  function updateWidget(layout, pageId, orientation, widgetId, patch) {
    var src = clone(layout);
    var index = pageIndex(src, pageId);
    if (index < 0) return { layout: src, ok: false };

    var page = src.pages[index];
    var widgets = variantOf(page, orientation);
    var at = widgetIndex(widgets, widgetId);
    if (at < 0) return { layout: src, ok: false };

    var current = widgets[at];
    var changes = isPlainObject(patch) ? patch : {};
    var candidate = clone(current);
    ['x', 'y', 'w', 'h'].forEach(function (key) {
      if (hasOwn(changes, key)) candidate[key] = changes[key];
    });

    var grid = PanelGrid.gridFor(src, orientation);
    var clamped = PanelGrid.clampWidget(candidate, grid);
    var others = widgets.filter(function (x) { return x.id !== widgetId; });
    if (PanelGrid.collides(clamped, others)) return { layout: src, ok: false };

    widgets[at] = clamped;
    return { layout: src, ok: true };
  }

  function removeWidget(layout, pageId, orientation, widgetId) {
    var src = clone(layout);
    var index = pageIndex(src, pageId);
    if (index < 0) return src;
    var widgets = variantOf(src.pages[index], orientation);
    var at = widgetIndex(widgets, widgetId);
    if (at < 0) return src;
    widgets.splice(at, 1);
    return src;
  }

  function setWidgetConfig(layout, pageId, orientation, widgetId, config) {
    var src = clone(layout);
    if (!isPlainObject(config)) return src;
    var index = pageIndex(src, pageId);
    if (index < 0) return src;
    var widgets = variantOf(src.pages[index], orientation);
    var at = widgetIndex(widgets, widgetId);
    if (at < 0) return src;
    widgets[at].config = clone(config);
    return src;
  }

  function copyVariant(layout, pageId, fromOrientation, toOrientation) {
    var src = clone(layout);
    var index = pageIndex(src, pageId);
    if (index < 0) return src;

    var page = src.pages[index];
    var fromGrid = PanelGrid.gridFor(src, fromOrientation);
    var toGrid = PanelGrid.gridFor(src, toOrientation);
    var scaleX = toGrid.cols / fromGrid.cols;
    var scaleY = toGrid.rows / fromGrid.rows;

    var source = variantOf(page, fromOrientation);
    var placed = [];
    for (var i = 0; i < source.length && placed.length < MAX_WIDGETS; i++) {
      var original = source[i];
      var scaled = clone(original);
      scaled.x = Math.round(original.x * scaleX);
      scaled.y = Math.round(original.y * scaleY);
      scaled.w = Math.round(original.w * scaleX);
      scaled.h = Math.round(original.h * scaleY);
      scaled = PanelGrid.clampWidget(scaled, toGrid);

      if (!PanelGrid.collides(scaled, placed)) {
        placed.push(scaled);
        continue;
      }
      var spot = PanelGrid.findFreeSpot(placed, scaled.w, scaled.h, toGrid);
      if (spot) {
        scaled.x = spot.x;
        scaled.y = spot.y;
        placed.push(scaled);
      }
    }

    page[toOrientation] = placed;
    return src;
  }

  function duplicateDoc(layout, name) {
    var src = clone(layout) || {};
    var text = String(name === undefined || name === null ? '' : name).trim();
    if (!text) text = String(src.name || 'Layout') + ' copy';
    return {
      name: text.slice(0, MAX_LAYOUT_NAME),
      version: 1,
      grid: clone(src.grid) || clone(PanelGrid.DEFAULT_GRID),
      pages: clone(src.pages) || []
    };
  }

  // Stable serialisation: object keys sorted so key order does not matter.
  function canonical(value) {
    if (Array.isArray(value)) {
      return '[' + value.map(canonical).join(',') + ']';
    }
    if (value !== null && typeof value === 'object') {
      return '{' + Object.keys(value).sort().filter(function (key) {
        return value[key] !== undefined;
      }).map(function (key) {
        return JSON.stringify(key) + ':' + canonical(value[key]);
      }).join(',') + '}';
    }
    return JSON.stringify(value === undefined ? null : value);
  }

  function isDirty(a, b) {
    var left = clone(a);
    var right = clone(b);
    if (isPlainObject(left)) delete left.updated_at;
    if (isPlainObject(right)) delete right.updated_at;
    return canonical(left) !== canonical(right);
  }

  function reorder(list, id, toIndex) {
    var items = clone(list) || [];
    var from = -1;
    for (var i = 0; i < items.length; i++) {
      if (items[i] && items[i].id === id) { from = i; break; }
    }
    if (from < 0) return items;
    var item = items.splice(from, 1)[0];
    var target = intClamp(toIndex, 0, items.length);
    items.splice(target, 0, item);
    return items;
  }

  function getPage(layout, pageId) {
    var index = pageIndex(layout, pageId);
    return index < 0 ? null : clone(layout.pages[index]);
  }

  function getWidget(layout, pageId, orientation, widgetId) {
    var index = pageIndex(layout, pageId);
    if (index < 0) return null;
    var widgets = variantOf(layout.pages[index], orientation);
    var at = widgetIndex(widgets, widgetId);
    return at < 0 ? null : clone(widgets[at]);
  }

  var api = {
    newId: newId,
    renameLayout: renameLayout,
    addPage: addPage,
    renamePage: renamePage,
    removePage: removePage,
    movePage: movePage,
    addWidget: addWidget,
    updateWidget: updateWidget,
    removeWidget: removeWidget,
    setWidgetConfig: setWidgetConfig,
    copyVariant: copyVariant,
    duplicateDoc: duplicateDoc,
    isDirty: isDirty,
    reorder: reorder,
    getPage: getPage,
    getWidget: getWidget
  };

  root.EditorModel = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
