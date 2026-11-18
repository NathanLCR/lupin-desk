(function (root) {
  'use strict';

  // Pure grid math for the Panel runtime. No DOM access.
  // Every function returns new objects and never mutates its inputs.

  var DEFAULT_GRID = {
    landscape: { cols: 12, rows: 6 },
    portrait: { cols: 6, rows: 12 }
  };

  function copyObject(source) {
    var out = {};
    for (var key in source) {
      if (Object.prototype.hasOwnProperty.call(source, key)) out[key] = source[key];
    }
    return out;
  }

  function intClamp(value, low, high) {
    var n = Number(value);
    if (!isFinite(n)) n = low;
    n = Math.round(n);
    return Math.min(high, Math.max(low, n));
  }

  function orientationFor(width, height) {
    return width >= height ? 'landscape' : 'portrait';
  }

  function gridFor(layout, orientation) {
    var fromLayout = layout && layout.grid ? layout.grid[orientation] : null;
    var source = fromLayout || DEFAULT_GRID[orientation] || DEFAULT_GRID.landscape;
    return { cols: source.cols, rows: source.rows };
  }

  function pickVariant(page, orientation) {
    var other = orientation === 'landscape' ? 'portrait' : 'landscape';
    var requested = page && page[orientation] ? page[orientation] : [];
    var alternate = page && page[other] ? page[other] : [];
    if (requested.length) return { orientation: orientation, widgets: requested.slice() };
    if (alternate.length) return { orientation: other, widgets: alternate.slice() };
    return { orientation: orientation, widgets: [] };
  }

  function cellRect(widget, grid) {
    return {
      left: (widget.x / grid.cols) * 100,
      top: (widget.y / grid.rows) * 100,
      width: (widget.w / grid.cols) * 100,
      height: (widget.h / grid.rows) * 100
    };
  }

  function clampWidget(widget, grid) {
    var out = copyObject(widget);
    out.w = intClamp(widget.w, 1, grid.cols);
    out.h = intClamp(widget.h, 1, grid.rows);
    out.x = intClamp(widget.x, 0, grid.cols - out.w);
    out.y = intClamp(widget.y, 0, grid.rows - out.h);
    return out;
  }

  // Rectangles that only share an edge do not overlap.
  function overlaps(a, b) {
    return a.x < b.x + b.w &&
      b.x < a.x + a.w &&
      a.y < b.y + b.h &&
      b.y < a.y + a.h;
  }

  function collides(widget, others) {
    for (var i = 0; i < others.length; i++) {
      if (others[i].id !== widget.id && overlaps(widget, others[i])) return true;
    }
    return false;
  }

  function findFreeSpot(widgets, w, h, grid) {
    if (w < 1 || h < 1 || w > grid.cols || h > grid.rows) return null;
    for (var y = 0; y <= grid.rows - h; y++) {
      for (var x = 0; x <= grid.cols - w; x++) {
        var candidate = { x: x, y: y, w: w, h: h };
        if (!collides(candidate, widgets)) return { x: x, y: y };
      }
    }
    return null;
  }

  function snap(px, py, boxWidth, boxHeight, grid) {
    var col = boxWidth > 0 ? Math.floor((px / boxWidth) * grid.cols) : 0;
    var row = boxHeight > 0 ? Math.floor((py / boxHeight) * grid.rows) : 0;
    if (!isFinite(col)) col = 0;
    if (!isFinite(row)) row = 0;
    return {
      x: Math.min(grid.cols - 1, Math.max(0, col)),
      y: Math.min(grid.rows - 1, Math.max(0, row))
    };
  }

  var api = {
    DEFAULT_GRID: DEFAULT_GRID,
    orientationFor: orientationFor,
    gridFor: gridFor,
    pickVariant: pickVariant,
    cellRect: cellRect,
    clampWidget: clampWidget,
    overlaps: overlaps,
    collides: collides,
    findFreeSpot: findFreeSpot,
    snap: snap
  };

  root.PanelGrid = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
