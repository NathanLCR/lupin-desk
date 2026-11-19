/*
 * Desk Panel runtime (PanelRuntime). Plain ES5 for the Android 7 WebView, old Safari and Kindle.
 *
 * Pages: the Pet page first when the device also has the 'body' role, then one page per Layout page.
 * Each widget page holds absolutely positioned tiles; widgets are mounted with PanelRegistry.mount.
 * A WebSocket keeps the Panel connected (hello, welcome, role, topic, emotion, state), with backoff reconnects.
 * Navigation: swipe, keys, volume keys and gamepad L1/R1. Arrange mode edits one page + orientation.
 *
 * Injection points (all read from start() options, falling back to the window globals):
 *   options.win        window-like object: document, innerWidth/innerHeight, navigator, location,
 *                      addEventListener, setTimeout/clearTimeout/setInterval, WebSocket, XMLHttpRequest,
 *                      PanelGrid, PanelRegistry, PanelArrangeModel, PanelArrangeUI, PanelPet, PanelWidgets, DeskDevice
 *   options.doc        document-like object (defaults to win.document)
 *   options.registry   registry to use (defaults to PanelRegistry.shared)
 *   options.wsUrl      WebSocket URL (defaults to ws(s)://location.host/ws)
 */
(function (root) {
  'use strict';

  var PROTOCOL = 1;
  var RECONNECT_MIN_MS = 1000;
  var RECONNECT_MAX_MS = 10000;
  var LAYOUT_RETRY_MS = 5000;
  var ORIENTATION_DEBOUNCE_MS = 150;
  var GAMEPAD_POLL_MS = 100;
  var LONG_PRESS_MS = 600;
  var SWIPE_MIN_PX = 50;
  var SWIPE_RATIO = 1.5;

  // ---------------------------------------------------------------- pager

  function normalizeCount(n) {
    var value = Math.floor(Number(n));
    return value > 0 ? value : 0;
  }

  // Clamped page index (no wrap). onChange listeners fire only when the index really changes.
  function createPager(count) {
    var current = 0;
    var total = normalizeCount(count);
    var listeners = [];

    function clamp(index) {
      if (total === 0 || index < 0) return 0;
      if (index > total - 1) return total - 1;
      return index;
    }

    function notify() {
      for (var i = 0; i < listeners.length; i++) listeners[i](current);
    }

    function goTo(index) {
      var target = Math.floor(index);
      if (target !== target) return; // NaN
      target = clamp(target);
      if (target === current) return;
      current = target;
      notify();
    }

    return {
      index: function () { return current; },
      count: function () { return total; },
      next: function () { goTo(current + 1); },
      prev: function () { goTo(current - 1); },
      goTo: goTo,
      setCount: function (n) {
        total = normalizeCount(n);
        var clamped = clamp(current);
        if (clamped !== current) {
          current = clamped;
          notify();
        }
      },
      onChange: function (fn) {
        if (typeof fn === 'function') listeners.push(fn);
      }
    };
  }

  // ---------------------------------------------------------------- HTTP

  function httpError(status) {
    var err = new Error('HTTP ' + status);
    err.status = status;
    return err;
  }

  // cb(err, data). XhrCtor is optional (defaults to root.XMLHttpRequest) so tests can inject a stub.
  function sendJSON(method, url, body, cb, XhrCtor) {
    var Xhr = XhrCtor || root.XMLHttpRequest;
    var hasBody = body !== undefined && body !== null;
    var xhr = new Xhr();
    var finished = false;
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4 || finished) return;
      finished = true;
      if (xhr.status < 200 || xhr.status >= 300) {
        cb(httpError(xhr.status), null);
        return;
      }
      var data = null;
      try {
        data = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch (e) {
        cb(e, null);
        return;
      }
      cb(null, data);
    };
    xhr.open(method, url, true);
    if (hasBody) xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.send(hasBody ? JSON.stringify(body) : null);
  }

  function getJSON(url, cb, XhrCtor) {
    sendJSON('GET', url, null, cb, XhrCtor);
  }

  // ---------------------------------------------------------------- small helpers

  function makeEl(doc, tag, className) {
    var el = doc.createElement(tag);
    if (className) el.className = className;
    return el;
  }

  function addClass(el, name) {
    if (el && el.classList) el.classList.add(name);
  }

  function removeClass(el, name) {
    if (el && el.classList) el.classList.remove(name);
  }

  // A failing widget or Pet must never break the Panel: errors are swallowed here.
  function callMethod(obj, name, args) {
    if (!obj || typeof obj[name] !== 'function') return;
    try {
      obj[name].apply(obj, args || []);
    } catch (e) {
      // ignored on purpose
    }
  }

  function hasRole(app, role) {
    return app.roles.indexOf(role) !== -1;
  }

  function defaultWsUrl(win) {
    var loc = win.location || {};
    var scheme = loc.protocol === 'https:' ? 'wss://' : 'ws://';
    return scheme + (loc.host || '') + '/ws';
  }

  function parseMessage(data) {
    try {
      return JSON.parse(data);
    } catch (e) {
      return null;
    }
  }

  function setStatus(app, text) {
    app.statusEl.textContent = text || '';
    app.statusEl.style.display = text ? '' : 'none';
  }

  // ---------------------------------------------------------------- messages out

  function sendMsg(app, msg) {
    if (!app.socket || !app.connected) return false;
    try {
      app.socket.send(JSON.stringify(msg));
      return true;
    } catch (e) {
      return false;
    }
  }

  function sendAction(app, id, args) {
    return sendMsg(app, { type: 'action', id: id, args: args || {} });
  }

  // 'layout' is always subscribed; the widget topics are added after each render.
  function sendSubscribe(app, topics) {
    var list = ['layout', 'panel:goto'];
    for (var i = 0; i < topics.length; i++) {
      if (list.indexOf(topics[i]) === -1) list.push(topics[i]);
    }
    sendMsg(app, { type: 'subscribe', topics: list });
  }

  function sendHello(app) {
    var hello = {};
    var device = app.win.DeskDevice;
    var fields = device && typeof device.helloFields === 'function' ? device.helloFields() : null;
    var key;
    if (fields) {
      for (key in fields) {
        if (Object.prototype.hasOwnProperty.call(fields, key)) hello[key] = fields[key];
      }
    }
    hello.type = 'hello';
    hello.body = 'panel';
    hello.protocol = PROTOCOL;
    sendMsg(app, hello);
  }

  // ---------------------------------------------------------------- connection

  function connect(app) {
    app.reconnectTimer = null;
    var sock;
    try {
      sock = new app.win.WebSocket(app.wsUrl);
    } catch (e) {
      scheduleReconnect(app);
      return;
    }
    app.socket = sock;
    sock.onopen = function () {
      if (app.socket !== sock) return;
      app.connected = true;
      app.reconnectDelay = RECONNECT_MIN_MS;
      sendHello(app);
    };
    sock.onmessage = function (ev) {
      if (app.socket !== sock) return;
      var msg = parseMessage(ev.data);
      if (msg) handleMessage(app, msg);
    };
    sock.onclose = function () {
      if (app.socket !== sock) return;
      app.socket = null;
      app.connected = false;
      setStatus(app, 'Reconnecting...');
      scheduleReconnect(app);
    };
  }

  // Backoff: 1s, 2s, 4s, 8s, then 10s. The delay resets on the next successful open.
  function scheduleReconnect(app) {
    if (app.reconnectTimer !== null) return;
    var delay = app.reconnectDelay;
    app.reconnectDelay = Math.min(delay * 2, RECONNECT_MAX_MS);
    app.reconnectTimer = app.win.setTimeout(function () {
      connect(app);
    }, delay);
  }

  function handleMessage(app, msg) {
    switch (msg.type) {
      case 'welcome':
        onRolesMessage(app, msg, true);
        break;
      case 'role':
        onRolesMessage(app, msg, false);
        break;
      case 'topic':
        onTopicMessage(app, msg.topic, msg.data);
        break;
      case 'emotion':
        callMethod(app.pet, 'setEmotion', [msg.emotion]);
        break;
      case 'state':
        callMethod(app.pet, 'setState', [msg.state]);
        break;
      default:
        break;
    }
  }

  function onRolesMessage(app, msg, isWelcome) {
    app.roles = Array.isArray(msg.roles) ? msg.roles.slice() : [];
    var layoutId = msg.layout_id || null;
    var layoutChanged = layoutId !== app.layoutId;
    app.layoutId = layoutId;
    sendSubscribe(app, []);
    if (isWelcome || layoutChanged || !app.layout) {
      loadLayout(app);
    } else {
      render(app);
    }
  }

  function layoutTopicIsOurs(app, data) {
    var id = data && data.layout_id;
    if (!id) return false;
    return id === app.layoutId || (!!app.layout && id === app.layout.id);
  }

  // Control Deck rules publish panel:goto {page_id}: show that Layout page if this Panel has it.
  function gotoPageById(app, data) {
    var id = data && data.page_id;
    if (typeof id !== 'string' || app.arranging) return;
    var layoutPages = app.layout && app.layout.pages ? app.layout.pages : [];
    for (var i = 0; i < layoutPages.length; i++) {
      if (layoutPages[i].id !== id) continue;
      for (var j = 0; j < app.pages.length; j++) {
        if (app.pages[j].id === id) {
          goPage(app, j);
          return;
        }
      }
    }
  }

  function onTopicMessage(app, topic, data) {
    if (topic === 'panel:goto') {
      gotoPageById(app, data);
      return;
    }
    if (topic === 'layout') {
      if (!app.arranging && layoutTopicIsOurs(app, data)) loadLayout(app);
      return;
    }
    forEachTile(app, function (tile) {
      callMethod(tile.handle, 'onTopic', [topic, data]);
    });
  }

  // ---------------------------------------------------------------- layout loading

  function clearLayoutRetry(app) {
    if (app.layoutRetryTimer !== null) {
      app.win.clearTimeout(app.layoutRetryTimer);
      app.layoutRetryTimer = null;
    }
  }

  function scheduleLayoutRetry(app) {
    if (app.layoutRetryTimer !== null) return;
    app.layoutRetryTimer = app.win.setTimeout(function () {
      app.layoutRetryTimer = null;
      loadLayout(app);
    }, LAYOUT_RETRY_MS);
  }

  function loadLayout(app) {
    clearLayoutRetry(app);
    app.loadSeq += 1;
    var seq = app.loadSeq;
    var id = app.layoutId || 'default';
    app.http.getJSON('/api/layouts/' + encodeURIComponent(id), function (err, layout) {
      if (seq !== app.loadSeq) return;
      if (err || !layout || typeof layout !== 'object') {
        setStatus(app, 'Could not load layout');
        scheduleLayoutRetry(app);
        return;
      }
      app.layout = layout;
      setStatus(app, '');
      render(app);
    });
  }

  // ---------------------------------------------------------------- rendering

  function forEachTile(app, fn) {
    for (var i = 0; i < app.pages.length; i++) {
      var page = app.pages[i];
      if (page.kind !== 'widgets') continue;
      for (var j = 0; j < page.tiles.length; j++) fn(page.tiles[j]);
    }
  }

  function ensurePet(app) {
    if (!app.Pet || typeof app.Pet.create !== 'function') return null;
    if (!app.pet) {
      var pageEl = makeEl(app.doc, 'div', 'pn-page pn-pet');
      var pet = null;
      try {
        pet = app.Pet.create(app.doc, pageEl);
      } catch (e) {
        pet = null;
      }
      if (!pet) return null;
      app.pet = pet;
      app.petPage = { kind: 'pet', pageEl: pageEl };
    }
    return app.petPage;
  }

  function dropPet(app) {
    if (!app.pet) return;
    callMethod(app.pet, 'destroy', []);
    app.pet = null;
    app.petPage = null;
  }

  function mountWidget(app, el, widget) {
    try {
      return app.Reg.mount(app.registry, el, widget, {
        sendAction: function (id, args) {
          return sendAction(app, id, args);
        }
      });
    } catch (e) {
      return null;
    }
  }

  function placeTile(app, tileEl, widget, grid) {
    var rect = app.G.cellRect(widget, grid);
    tileEl.style.left = rect.left + '%';
    tileEl.style.top = rect.top + '%';
    tileEl.style.width = rect.width + '%';
    tileEl.style.height = rect.height + '%';
  }

  function createTile(app, page, widget) {
    var tileEl = makeEl(app.doc, 'div', 'pn-tile');
    placeTile(app, tileEl, widget, page.grid);
    var innerEl = makeEl(app.doc, 'div', 'pn-tile-inner');
    tileEl.appendChild(innerEl);
    page.stageEl.appendChild(tileEl);
    return {
      id: widget.id,
      widget: widget,
      tileEl: tileEl,
      handle: mountWidget(app, innerEl, widget),
      detachLongPress: null
    };
  }

  function destroyTile(tile) {
    if (typeof tile.detachLongPress === 'function') tile.detachLongPress();
    tile.detachLongPress = null;
    callMethod(tile.handle, 'destroy', []);
    tile.handle = null;
  }

  function attachLongPress(app, page, tile) {
    if (!app.ArrangeUI || typeof app.ArrangeUI.longPress !== 'function') return;
    tile.detachLongPress = app.ArrangeUI.longPress(tile.tileEl, LONG_PRESS_MS, function () {
      enterArrange(app, page);
    });
  }

  function buildWidgetPage(app, pageDef, variant) {
    var pageEl = makeEl(app.doc, 'div', 'pn-page');
    var stageEl = makeEl(app.doc, 'div', 'pn-stage');
    pageEl.appendChild(stageEl);
    var page = {
      kind: 'widgets',
      id: pageDef.id,
      orientation: variant.orientation,
      grid: app.G.gridFor(app.layout, variant.orientation),
      pageEl: pageEl,
      stageEl: stageEl,
      tiles: []
    };
    var widgets = variant.widgets || [];
    for (var i = 0; i < widgets.length; i++) {
      var tile = createTile(app, page, widgets[i]);
      page.tiles.push(tile);
      attachLongPress(app, page, tile);
    }
    return page;
  }

  function teardownPages(app) {
    forEachTile(app, destroyTile);
    app.pages = [];
    while (app.viewport.lastChild) {
      app.viewport.removeChild(app.viewport.lastChild);
    }
  }

  function positionPages(app) {
    var current = app.pager.index();
    for (var i = 0; i < app.pages.length; i++) {
      app.pages[i].pageEl.style.left = (i - current) * 100 + '%';
    }
  }

  function updateDots(app) {
    var dots = app.dotsEl;
    while (dots.lastChild) dots.removeChild(dots.lastChild);
    if (app.pages.length <= 1) {
      dots.style.display = 'none';
      return;
    }
    dots.style.display = '';
    var current = app.pager.index();
    for (var i = 0; i < app.pages.length; i++) {
      var dot = makeEl(app.doc, 'span', 'pn-dot');
      if (i === current) addClass(dot, 'on');
      bindDot(app, dot, i);
      dots.appendChild(dot);
    }
  }

  function bindDot(app, dot, index) {
    dot.addEventListener('click', function () {
      goPage(app, index);
    });
  }

  function collectTopics(app) {
    var widgets = [];
    var pages = app.layout && app.layout.pages ? app.layout.pages : [];
    for (var i = 0; i < pages.length; i++) {
      if (Array.isArray(pages[i].landscape)) widgets = widgets.concat(pages[i].landscape);
      if (Array.isArray(pages[i].portrait)) widgets = widgets.concat(pages[i].portrait);
    }
    return app.registry.topicsFor(widgets) || [];
  }

  // Rebuilds every page from the loaded Layout, the current orientation and the device roles.
  function render(app) {
    if (app.arranging) exitArrange(app);
    teardownPages(app);
    var pages = [];
    if (hasRole(app, 'body')) {
      var petPage = ensurePet(app);
      if (petPage) pages.push(petPage);
    } else {
      dropPet(app);
    }
    var layoutPages = app.layout && app.layout.pages ? app.layout.pages : [];
    for (var i = 0; i < layoutPages.length; i++) {
      var variant = app.G.pickVariant(layoutPages[i], app.orientation);
      pages.push(buildWidgetPage(app, layoutPages[i], variant));
    }
    app.pages = pages;
    addClass(app.viewport, 'pn-noanim');
    for (var j = 0; j < pages.length; j++) {
      app.viewport.appendChild(pages[j].pageEl);
    }
    app.pager.setCount(pages.length);
    positionPages(app);
    updateDots(app);
    sendSubscribe(app, collectTopics(app));
  }

  // ---------------------------------------------------------------- navigation

  function goPage(app, index) {
    if (app.arranging) return;
    app.pager.goTo(index);
  }

  function navigate(app, direction) {
    if (app.arranging) return;
    if (direction < 0) app.pager.prev();
    else app.pager.next();
  }

  function keyDirection(e) {
    var key = e.key;
    var code = e.keyCode;
    if (key === 'ArrowLeft' || key === 'PageUp' || key === 'AudioVolumeUp' || key === 'VolumeUp' || code === 175) {
      return -1;
    }
    if (key === 'ArrowRight' || key === 'PageDown' || key === 'AudioVolumeDown' || key === 'VolumeDown' || code === 174) {
      return 1;
    }
    return 0;
  }

  function isEditableTarget(target) {
    if (!target || !target.tagName) return false;
    var tag = String(target.tagName).toUpperCase();
    return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || !!target.isContentEditable;
  }

  function onKeyDown(app, e) {
    if (isEditableTarget(e && e.target)) return;
    var direction = keyDirection(e);
    if (!direction) return;
    if (e.preventDefault) e.preventDefault();
    navigate(app, direction);
  }

  function isPressed(button) {
    return !!(button && button.pressed);
  }

  // L1 (button 4) goes to the previous page, R1 (button 5) to the next one. Edge-triggered.
  function pollGamepads(app) {
    var pads;
    try {
      pads = app.win.navigator.getGamepads();
    } catch (e) {
      return;
    }
    if (!pads) return;
    for (var i = 0; i < pads.length; i++) {
      var pad = pads[i];
      if (!pad || !pad.buttons) {
        app.gamepadPrev[i] = null;
        continue;
      }
      var l1 = isPressed(pad.buttons[4]);
      var r1 = isPressed(pad.buttons[5]);
      var before = app.gamepadPrev[i] || { l1: false, r1: false };
      if (l1 && !before.l1) navigate(app, -1);
      if (r1 && !before.r1) navigate(app, 1);
      app.gamepadPrev[i] = { l1: l1, r1: r1 };
    }
  }

  // Swipe: dx > 50px and |dx| > 1.5 * |dy|. Touch and mouse drag both count.
  function attachSwipe(app) {
    var start = null;

    function begin(x, y) {
      start = app.arranging ? null : { x: x, y: y };
    }

    function end(x, y) {
      var from = start;
      start = null;
      if (!from || app.arranging) return;
      var dx = x - from.x;
      var dy = y - from.y;
      if (Math.abs(dx) > SWIPE_MIN_PX && Math.abs(dx) > SWIPE_RATIO * Math.abs(dy)) {
        navigate(app, dx < 0 ? 1 : -1);
      }
    }

    var vp = app.viewport;
    vp.addEventListener('touchstart', function (e) {
      var t = e.touches && e.touches.length ? e.touches[0] : null;
      if (t) begin(t.clientX, t.clientY);
    });
    vp.addEventListener('touchend', function (e) {
      var t = e.changedTouches && e.changedTouches.length ? e.changedTouches[0] : null;
      if (t) end(t.clientX, t.clientY);
      else start = null;
    });
    vp.addEventListener('touchcancel', function () {
      start = null;
    });
    vp.addEventListener('mousedown', function (e) {
      begin(e.clientX, e.clientY);
    });
    vp.addEventListener('mouseup', function (e) {
      end(e.clientX, e.clientY);
    });
  }

  function attachKeys(app) {
    app.doc.addEventListener('keydown', function (e) {
      onKeyDown(app, e);
    });
  }

  function startGamepadPolling(app) {
    var nav = app.win.navigator;
    if (nav && typeof nav.getGamepads === 'function') {
      app.win.setInterval(function () {
        pollGamepads(app);
      }, GAMEPAD_POLL_MS);
    }
  }

  // ---------------------------------------------------------------- orientation

  function checkOrientation(app) {
    var next = app.G.orientationFor(app.win.innerWidth, app.win.innerHeight);
    if (next === app.orientation) return;
    app.orientation = next;
    render(app);
  }

  function attachOrientation(app) {
    var onResize = function () {
      if (app.orientTimer !== null) app.win.clearTimeout(app.orientTimer);
      app.orientTimer = app.win.setTimeout(function () {
        app.orientTimer = null;
        checkOrientation(app);
      }, ORIENTATION_DEBOUNCE_MS);
    };
    app.win.addEventListener('resize', onResize);
    app.win.addEventListener('orientationchange', onResize);
  }

  // ---------------------------------------------------------------- wake lock

  function requestWakeLock(app) {
    var nav = app.win.navigator;
    if (!nav || !nav.wakeLock || typeof nav.wakeLock.request !== 'function') return;
    try {
      var pending = nav.wakeLock.request('screen');
      if (pending && typeof pending.then === 'function') {
        pending.then(function (lock) {
          app.wakeLock = lock;
        }, function () {
          // refused or unsupported: the Panel still works
        });
      }
    } catch (e) {
      // ignored on purpose
    }
  }

  function attachWakeLock(app) {
    app.doc.addEventListener('visibilitychange', function () {
      if (app.doc.visibilityState !== 'hidden') requestWakeLock(app);
    });
    requestWakeLock(app);
  }

  // ---------------------------------------------------------------- arrange mode

  function exitArrange(app) {
    var arr = app.arranging;
    if (!arr) return;
    app.arranging = null;
    arr.controller.exit();
  }

  function cancelArrange(app) {
    var arr = app.arranging;
    if (!arr) return;
    arr.model.cancel();
    exitArrange(app);
    render(app);
  }

  function sameRect(a, b) {
    return a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h;
  }

  function findTileById(tiles, id) {
    for (var i = 0; i < tiles.length; i++) {
      if (tiles[i].id === id) return tiles[i];
    }
    return null;
  }

  function findWidgetById(widgets, id) {
    for (var i = 0; i < widgets.length; i++) {
      if (widgets[i].id === id) return widgets[i];
    }
    return null;
  }

  // Diffs the model against the mounted tiles: moves/resizes in place, mounts new ones, destroys removed ones.
  function syncTiles(app, arr) {
    if (app.arranging !== arr) return;
    var page = arr.page;
    var next = arr.model.widgets();
    var kept = [];
    var i;
    for (i = 0; i < page.tiles.length; i++) {
      var tile = page.tiles[i];
      if (findWidgetById(next, tile.id)) {
        kept.push(tile);
      } else {
        destroyTile(tile);
        if (tile.tileEl.parentNode) tile.tileEl.parentNode.removeChild(tile.tileEl);
      }
    }
    var result = [];
    for (i = 0; i < next.length; i++) {
      var widget = next[i];
      var existing = findTileById(kept, widget.id);
      if (existing) {
        var moved = !sameRect(existing.widget, widget);
        existing.widget = widget;
        placeTile(app, existing.tileEl, widget, page.grid);
        if (moved) callMethod(existing.handle, 'resize', []);
        result.push(existing);
      } else {
        var created = createTile(app, page, widget);
        arr.controller.attachTile(created.tileEl, created.id);
        result.push(created);
      }
    }
    page.tiles = result;
  }

  function saveArrange(app) {
    var arr = app.arranging;
    if (!arr) return;
    var layoutId = app.layout ? app.layout.id : (app.layoutId || 'default');
    var payload = arr.model.toPayload(arr.pageId, arr.orientation);
    var url = '/api/layouts/' + encodeURIComponent(layoutId) + '/arrange';
    app.http.sendJSON('PUT', url, payload, function (err, layout) {
      if (app.arranging !== arr) return;
      if (err || !layout || typeof layout !== 'object') {
        setStatus(app, 'Could not save');
        return;
      }
      exitArrange(app);
      app.layout = layout;
      setStatus(app, '');
      render(app);
    });
  }

  function enterArrange(app, page) {
    if (app.arranging || !page || page.kind !== 'widgets') return;
    if (app.pages.indexOf(page) === -1) return;
    if (!app.Model || !app.ArrangeUI) return;
    var widgets = [];
    for (var i = 0; i < page.tiles.length; i++) widgets.push(page.tiles[i].widget);
    var model = app.Model.create({ widgets: widgets, grid: page.grid, registry: app.registry });
    var arr = { page: page, model: model, controller: null, pageId: page.id, orientation: page.orientation };
    app.arranging = arr;
    arr.controller = app.ArrangeUI.create({
      doc: app.doc,
      stageEl: page.stageEl,
      model: model,
      registry: app.registry,
      grid: page.grid,
      onChange: function () {
        syncTiles(app, arr);
      },
      onSave: function () {
        saveArrange(app);
      },
      onCancel: function () {
        cancelArrange(app);
      }
    });
    arr.controller.enter();
    for (var j = 0; j < page.tiles.length; j++) {
      arr.controller.attachTile(page.tiles[j].tileEl, page.tiles[j].id);
    }
  }

  // ---------------------------------------------------------------- start

  function registerBuiltins(app) {
    var Widgets = app.win.PanelWidgets;
    if (!Widgets || typeof Widgets.registerBuiltins !== 'function') return;
    try {
      Widgets.registerBuiltins(app.registry);
    } catch (e) {
      // already registered (for example a second start on the same registry)
    }
  }

  function buildChrome(app) {
    var doc = app.doc;
    var rootEl = doc.getElementById('panel-root');
    if (!rootEl) {
      rootEl = doc.createElement('div');
      rootEl.id = 'panel-root';
      doc.body.appendChild(rootEl);
    }
    app.root = rootEl;
    app.viewport = makeEl(doc, 'div', 'pn-viewport');
    app.dotsEl = makeEl(doc, 'div', 'pn-dots');
    app.statusEl = makeEl(doc, 'div', 'pn-status');
    rootEl.appendChild(app.viewport);
    rootEl.appendChild(app.dotsEl);
    rootEl.appendChild(app.statusEl);
    setStatus(app, 'Connecting...');
  }

  function start(options) {
    var opts = options || {};
    var win = opts.win || root;
    var doc = opts.doc || win.document;
    var app = {
      win: win,
      doc: doc,
      G: win.PanelGrid,
      Reg: win.PanelRegistry,
      Model: win.PanelArrangeModel,
      ArrangeUI: win.PanelArrangeUI,
      Pet: win.PanelPet,
      registry: opts.registry || win.PanelRegistry.shared,
      wsUrl: opts.wsUrl || defaultWsUrl(win),
      http: {
        getJSON: function (url, cb) {
          getJSON(url, cb, win.XMLHttpRequest);
        },
        sendJSON: function (method, url, body, cb) {
          sendJSON(method, url, body, cb, win.XMLHttpRequest);
        }
      },
      pager: createPager(0),
      pages: [],
      pet: null,
      petPage: null,
      roles: [],
      layoutId: null,
      layout: null,
      orientation: 'landscape',
      socket: null,
      connected: false,
      reconnectDelay: RECONNECT_MIN_MS,
      reconnectTimer: null,
      layoutRetryTimer: null,
      orientTimer: null,
      loadSeq: 0,
      arranging: null,
      gamepadPrev: [],
      wakeLock: null
    };

    app.orientation = app.G.orientationFor(win.innerWidth, win.innerHeight);
    registerBuiltins(app);
    buildChrome(app);

    app.pager.onChange(function () {
      removeClass(app.viewport, 'pn-noanim');
      positionPages(app);
      updateDots(app);
    });

    attachSwipe(app);
    attachKeys(app);
    attachOrientation(app);
    attachWakeLock(app);
    startGamepadPolling(app);
    connect(app);

    return {
      pager: app.pager,
      render: function () {
        render(app);
      },
      reload: function () {
        loadLayout(app);
      },
      sendAction: function (id, args) {
        return sendAction(app, id, args);
      },
      arrange: function (pageIndex) {
        enterArrange(app, app.pages[pageIndex]);
      },
      isArranging: function () {
        return !!app.arranging;
      },
      orientation: function () {
        return app.orientation;
      },
      layout: function () {
        return app.layout;
      },
      pages: function () {
        return app.pages;
      },
      socket: function () {
        return app.socket;
      }
    };
  }

  var api = {
    createPager: createPager,
    getJSON: getJSON,
    sendJSON: sendJSON,
    start: start
  };

  root.PanelRuntime = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
