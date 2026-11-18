(function (root) {
  'use strict';

  // A press stops being a long press once the pointer moves further than this (px).
  var SLOP_PX = 10;
  var CROSS = '×';

  // PanelGrid is resolved lazily so a missing grid.js only fails when a drag needs it.
  function gridApi() {
    if (typeof module !== 'undefined' && module.exports) return require('./grid.js');
    return root.PanelGrid;
  }

  function isTouchEvent(e) {
    return String(e.type).indexOf('touch') === 0;
  }

  function isSecondaryButton(e) {
    return !isTouchEvent(e) && e.button !== undefined && e.button !== 0;
  }

  // Touch events carry the moving finger in changedTouches; mouse events carry clientX/Y.
  function pointOf(e) {
    var list = null;
    if (e.changedTouches && e.changedTouches.length) list = e.changedTouches;
    else if (e.touches && e.touches.length) list = e.touches;
    var src = list ? list[0] : e;
    return { x: src.clientX || 0, y: src.clientY || 0 };
  }

  function stopProp(e) {
    if (e && e.stopPropagation) e.stopPropagation();
  }

  // Adds a listener and records how to remove it, so teardown is exact.
  function listen(bag, target, type, fn) {
    target.addEventListener(type, fn);
    bag.push(function () {
      target.removeEventListener(type, fn);
    });
  }

  function runAll(bag) {
    while (bag.length) bag.pop()();
  }

  function longPress(el, ms, callback) {
    var doc = el.ownerDocument || null;
    var unbind = [];
    var timer = null;
    var start = null;

    function cancel() {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
      start = null;
    }

    function down(e) {
      if (isSecondaryButton(e)) return;
      cancel();
      if (e.touches && e.touches.length > 1) return;
      start = pointOf(e);
      timer = setTimeout(function () {
        timer = null;
        start = null;
        callback();
      }, ms);
    }

    function move(e) {
      if (timer === null || start === null) return;
      var p = pointOf(e);
      var dx = p.x - start.x;
      var dy = p.y - start.y;
      if (Math.sqrt(dx * dx + dy * dy) > SLOP_PX) cancel();
    }

    listen(unbind, el, 'touchstart', down);
    listen(unbind, el, 'touchmove', move);
    listen(unbind, el, 'touchend', cancel);
    listen(unbind, el, 'touchcancel', cancel);
    listen(unbind, el, 'mousedown', down);
    listen(unbind, el, 'mouseleave', cancel);
    if (doc) {
      listen(unbind, doc, 'mousemove', move);
      listen(unbind, doc, 'mouseup', cancel);
    }

    return function detach() {
      cancel();
      runAll(unbind);
    };
  }

  function create(opts) {
    var stageEl = opts.stageEl;
    var doc = opts.doc || stageEl.ownerDocument;
    var model = opts.model;
    var registry = opts.registry;
    var grid = opts.grid;

    var active = false;
    var toolbar = null;
    var toolbarUnbind = [];
    var saveBtn = null;
    var typeSelect = null;
    var statusEl = null;
    var tileRecs = [];
    var drag = null;
    var docUnbind = null;

    function notify() {
      if (opts.onChange) opts.onChange();
    }

    function refresh() {
      if (saveBtn) saveBtn.disabled = !model.isDirty();
    }

    function changed() {
      refresh();
      notify();
    }

    function mk(tag, cls) {
      var el = doc.createElement(tag);
      if (cls) el.classList.add(cls);
      return el;
    }

    function button(label, cls) {
      var b = mk('button', cls);
      b.type = 'button';
      b.textContent = label;
      return b;
    }

    function findWidget(id) {
      var ws = model.widgets();
      for (var i = 0; i < ws.length; i++) {
        if (ws[i].id === id) return ws[i];
      }
      return null;
    }

    // Cell under a viewport point, relative to the stage box.
    function cellAt(pt) {
      var rect = stageEl.getBoundingClientRect();
      return gridApi().snap(pt.x - rect.left, pt.y - rect.top, rect.width, rect.height, grid);
    }

    function endDrag() {
      drag = null;
      if (docUnbind) {
        var undo = docUnbind;
        docUnbind = null;
        undo();
      }
    }

    // mode 'move': keep the grab offset (in cells) so the tile follows the finger.
    // mode 'resize': the tile's origin is fixed and the pointer cell sets the far corner.
    function startDrag(e, mode, rec) {
      if (drag || isSecondaryButton(e)) return;
      var w = findWidget(rec.id);
      if (!w) return;
      var touch = isTouchEvent(e);
      var cell = cellAt(pointOf(e));
      drag = {
        mode: mode,
        id: rec.id,
        el: rec.el,
        touch: touch,
        offX: cell.x - w.x,
        offY: cell.y - w.y,
        ox: w.x,
        oy: w.y,
        tx: null,
        ty: null,
        tw: null,
        th: null
      };
      if (!touch) {
        doc.addEventListener('mousemove', onMouseMove);
        doc.addEventListener('mouseup', onMouseUp);
        docUnbind = function () {
          doc.removeEventListener('mousemove', onMouseMove);
          doc.removeEventListener('mouseup', onMouseUp);
        };
        if (e.preventDefault) e.preventDefault();
      }
    }

    function updateDrag(e) {
      if (!drag) return;
      var cell = cellAt(pointOf(e));
      if (drag.mode === 'move') {
        var tx = cell.x - drag.offX;
        var ty = cell.y - drag.offY;
        if (tx === drag.tx && ty === drag.ty) return;
        drag.tx = tx;
        drag.ty = ty;
        if (model.move(drag.id, tx, ty)) changed();
      } else {
        var tw = Math.max(1, cell.x - drag.ox + 1);
        var th = Math.max(1, cell.y - drag.oy + 1);
        if (tw === drag.tw && th === drag.th) return;
        drag.tw = tw;
        drag.th = th;
        if (model.resize(drag.id, tw, th)) changed();
      }
    }

    function onMouseMove(e) {
      updateDrag(e);
    }

    function onMouseUp() {
      endDrag();
    }

    // Touch listeners live on the tile itself (touch events target the element
    // where the touch started), so no document-level touch listener is needed.
    function onTouchMove(e) {
      if (!drag || !drag.touch) return;
      if (e.preventDefault) e.preventDefault();
      updateDrag(e);
    }

    function onTouchEnd() {
      if (drag && drag.touch) endDrag();
    }

    function detachRec(rec) {
      runAll(rec.unbind);
      rec.nodes.forEach(function (n) {
        if (n.parentNode) n.parentNode.removeChild(n);
      });
    }

    function detachTile(el) {
      for (var i = 0; i < tileRecs.length; i++) {
        if (tileRecs[i].el === el) {
          if (drag && drag.el === el) endDrag();
          detachRec(tileRecs[i]);
          tileRecs.splice(i, 1);
          return;
        }
      }
    }

    function attachTile(tileEl, widgetId) {
      if (!active) return;
      detachTile(tileEl);

      var rec = { el: tileEl, id: widgetId, unbind: [], nodes: [] };
      var remove = mk('button', 'pn-arrange-remove');
      remove.type = 'button';
      remove.textContent = CROSS;
      var resize = mk('div', 'pn-arrange-resize');
      tileEl.appendChild(remove);
      tileEl.appendChild(resize);
      rec.nodes.push(remove, resize);
      tileRecs.push(rec);

      // Handles stop propagation so the runtime's swipe and the tile drag never see them.
      listen(rec.unbind, remove, 'mousedown', stopProp);
      listen(rec.unbind, remove, 'touchstart', stopProp);
      listen(rec.unbind, remove, 'click', function (e) {
        stopProp(e);
        if (model.remove(widgetId)) {
          detachTile(tileEl);
          changed();
        }
      });

      listen(rec.unbind, resize, 'mousedown', function (e) {
        stopProp(e);
        startDrag(e, 'resize', rec);
      });
      listen(rec.unbind, resize, 'touchstart', function (e) {
        stopProp(e);
        startDrag(e, 'resize', rec);
      });

      listen(rec.unbind, tileEl, 'mousedown', function (e) {
        startDrag(e, 'move', rec);
      });
      listen(rec.unbind, tileEl, 'touchstart', function (e) {
        startDrag(e, 'move', rec);
      });
      listen(rec.unbind, tileEl, 'touchmove', onTouchMove);
      listen(rec.unbind, tileEl, 'touchend', onTouchEnd);
      listen(rec.unbind, tileEl, 'touchcancel', onTouchEnd);
    }

    function onAdd() {
      var widget = model.add(typeSelect.value);
      if (!widget) {
        statusEl.textContent = 'No space';
        return;
      }
      statusEl.textContent = '';
      changed();
    }

    function onSave() {
      if (!model.isDirty()) return;
      if (opts.onSave) opts.onSave();
    }

    function onCancel() {
      if (opts.onCancel) opts.onCancel();
    }

    function enter() {
      if (active) return;
      active = true;
      stageEl.classList.add('pn-arranging');

      toolbar = mk('div', 'pn-toolbar');
      typeSelect = mk('select', 'pn-arrange-type');
      var defs = registry ? registry.list() : [];
      defs.forEach(function (def) {
        var opt = mk('option');
        opt.value = def.id;
        opt.textContent = def.title || def.id;
        typeSelect.appendChild(opt);
      });
      var addBtn = button('Add', 'pn-arrange-add');
      statusEl = mk('span', 'pn-arrange-status');
      saveBtn = button('Save', 'pn-arrange-save');
      var cancelBtn = button('Cancel', 'pn-arrange-cancel');

      listen(toolbarUnbind, addBtn, 'click', onAdd);
      listen(toolbarUnbind, saveBtn, 'click', onSave);
      listen(toolbarUnbind, cancelBtn, 'click', onCancel);

      toolbar.appendChild(typeSelect);
      toolbar.appendChild(addBtn);
      toolbar.appendChild(statusEl);
      toolbar.appendChild(saveBtn);
      toolbar.appendChild(cancelBtn);
      stageEl.appendChild(toolbar);
      refresh();
    }

    function exit() {
      if (!active) return;
      endDrag();
      while (tileRecs.length) detachRec(tileRecs.pop());
      runAll(toolbarUnbind);
      if (toolbar && toolbar.parentNode) toolbar.parentNode.removeChild(toolbar);
      stageEl.classList.remove('pn-arranging');
      toolbar = null;
      saveBtn = null;
      typeSelect = null;
      statusEl = null;
      active = false;
    }

    return {
      enter: enter,
      exit: exit,
      attachTile: attachTile,
      isActive: function () {
        return active;
      }
    };
  }

  var api = {
    longPress: longPress,
    create: create
  };

  root.PanelArrangeUI = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
