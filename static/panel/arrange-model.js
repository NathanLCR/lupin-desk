(function (root) {
  'use strict';

  // Pure model for arranging the widgets of one page and orientation.
  // No DOM access. The UI calls these methods and redraws from widgets().
  // Strict ES5 for old WebViews and e-ink browsers.

  var PanelGrid = (typeof module !== 'undefined' && module.exports) ? require('./grid.js') : root.PanelGrid;

  var ID_CHARS = 'abcdefghijklmnopqrstuvwxyz0123456789';
  var MAX_ID_TRIES = 20;

  function hasOwn(object, key) {
    return Object.prototype.hasOwnProperty.call(object, key);
  }

  function copyWidget(source) {
    var out = {};
    for (var key in source) {
      if (hasOwn(source, key)) out[key] = source[key];
    }
    return out;
  }

  function defaultIdFn() {
    var id = 'w';
    for (var i = 0; i < 6; i++) {
      id += ID_CHARS.charAt(Math.floor(Math.random() * ID_CHARS.length));
    }
    return id;
  }

  function between(value, low, high) {
    return Math.max(low, Math.min(high, value));
  }

  function indexOfId(widgets, id) {
    for (var i = 0; i < widgets.length; i++) {
      if (widgets[i].id === id) return i;
    }
    return -1;
  }

  function cloneAll(widgets) {
    var out = [];
    for (var i = 0; i < widgets.length; i++) out.push(copyWidget(widgets[i]));
    return out;
  }

  function sameLayoutFields(a, b) {
    return a.type === b.type && a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h;
  }

  function create(options) {
    var opts = options || {};
    var grid = opts.grid || PanelGrid.DEFAULT_GRID.landscape;
    var registry = opts.registry || null;
    var idFn = typeof opts.idFn === 'function' ? opts.idFn : defaultIdFn;
    var initial = [];
    var current = [];
    var source = opts.widgets || [];

    for (var i = 0; i < source.length; i++) {
      initial.push(PanelGrid.clampWidget(source[i], grid));
    }
    current = cloneAll(initial);

    function typeDef(typeId) {
      return registry && typeof registry.get === 'function' ? registry.get(typeId) : null;
    }

    // Allowed size range for a widget at column x, row y, given its type.
    function limits(widget) {
      var def = typeDef(widget.type);
      var minW = 1;
      var minH = 1;
      var maxW = grid.cols;
      var maxH = grid.rows;
      if (def && def.sizes) {
        if (def.sizes.min) {
          minW = Math.max(1, def.sizes.min.w);
          minH = Math.max(1, def.sizes.min.h);
        }
        if (def.sizes.max) {
          maxW = Math.min(grid.cols, def.sizes.max.w);
          maxH = Math.min(grid.rows, def.sizes.max.h);
        }
      }
      // Resizing keeps the top-left corner, so the size is bounded by the grid edge.
      var roomW = grid.cols - widget.x;
      var roomH = grid.rows - widget.y;
      return {
        minW: Math.min(minW, roomW),
        maxW: Math.min(maxW, roomW),
        minH: Math.min(minH, roomH),
        maxH: Math.min(maxH, roomH)
      };
    }

    function planAdd(typeId) {
      var def = typeDef(typeId);
      if (!def) return null;
      var size = def.sizes && def.sizes.default ? def.sizes.default : { w: 2, h: 2 };
      var w = Math.max(1, Math.min(size.w, grid.cols));
      var h = Math.max(1, Math.min(size.h, grid.rows));
      var spot = PanelGrid.findFreeSpot(current, w, h, grid);
      if (!spot) return null;
      return { type: typeId, x: spot.x, y: spot.y, w: w, h: h };
    }

    function uniqueId() {
      for (var tries = 0; tries < MAX_ID_TRIES; tries++) {
        var id = idFn();
        if (typeof id === 'string' && id && indexOfId(current, id) < 0) return id;
      }
      return null;
    }

    function widgets() {
      return cloneAll(current);
    }

    function isDirty() {
      if (current.length !== initial.length) return true;
      for (var i = 0; i < current.length; i++) {
        var before = initial[indexOfId(initial, current[i].id)];
        if (!before || !sameLayoutFields(before, current[i])) return true;
      }
      return false;
    }

    function move(id, x, y) {
      var index = indexOfId(current, id);
      if (index < 0) return false;
      var base = current[index];
      var candidate = PanelGrid.clampWidget({
        id: base.id, type: base.type, x: x, y: y, w: base.w, h: base.h, config: base.config
      }, grid);
      if (PanelGrid.collides(candidate, current)) return false;
      current[index] = candidate;
      return true;
    }

    function resize(id, w, h) {
      var index = indexOfId(current, id);
      if (index < 0) return false;
      var base = current[index];
      var bounds = limits(base);
      var nextW = between(Math.round(Number(w)) || 1, bounds.minW, bounds.maxW);
      var nextH = between(Math.round(Number(h)) || 1, bounds.minH, bounds.maxH);
      var candidate = {
        id: base.id, type: base.type, x: base.x, y: base.y, w: nextW, h: nextH, config: base.config
      };
      if (PanelGrid.collides(candidate, current)) return false;
      current[index] = candidate;
      return true;
    }

    function remove(id) {
      var index = indexOfId(current, id);
      if (index < 0) return false;
      current.splice(index, 1);
      return true;
    }

    function canAdd(typeId) {
      return planAdd(typeId) !== null;
    }

    function add(typeId) {
      var plan = planAdd(typeId);
      if (!plan) return null;
      var id = uniqueId();
      if (!id) return null;
      var widget = {
        id: id, type: plan.type, x: plan.x, y: plan.y, w: plan.w, h: plan.h, config: {}
      };
      current.push(widget);
      return copyWidget(widget);
    }

    function cancel() {
      current = cloneAll(initial);
    }

    function toPayload(pageId, orientation) {
      var out = [];
      for (var i = 0; i < current.length; i++) {
        var w = current[i];
        out.push({ id: w.id, type: w.type, x: w.x, y: w.y, w: w.w, h: w.h });
      }
      return { page_id: pageId, orientation: orientation, widgets: out };
    }

    return {
      widgets: widgets,
      isDirty: isDirty,
      move: move,
      resize: resize,
      remove: remove,
      add: add,
      cancel: cancel,
      toPayload: toPayload,
      canAdd: canAdd
    };
  }

  var api = { create: create };

  root.PanelArrangeModel = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
