(function (root) {
  'use strict';

  // Live preview of one Layout page variant for the Mac Layout editor.
  // Mounts the same widgets the Panel would show, in a scaled device frame.
  // Previews never send actions. Live data uses a 'editor' WebSocket client
  // that only subscribes and receives topics.

  var PanelGridModule = (typeof module !== 'undefined' && module.exports) ? require('../panel/grid.js') : null;
  var PanelRegistryModule = (typeof module !== 'undefined' && module.exports) ? require('../panel/registry.js') : null;

  var RECONNECT_MS = 3000;
  var HELLO_BODY = 'editor';
  var HELLO_NAME = 'Layout editor';

  function noop() {}

  function pick(win, name, fallback) {
    if (win && win[name]) return win[name];
    if (fallback) return fallback;
    return root[name] || null;
  }

  function clearChildren(el) {
    while (el.lastChild) el.removeChild(el.lastChild);
  }

  function makeEl(doc, tag, className) {
    var el = doc.createElement(tag);
    if (className) el.className = className;
    return el;
  }

  function placeTile(tileEl, rect) {
    tileEl.style.left = rect.left + '%';
    tileEl.style.top = rect.top + '%';
    tileEl.style.width = rect.width + '%';
    tileEl.style.height = rect.height + '%';
  }

  function positiveOr(value, fallback) {
    var n = Number(value);
    return isFinite(n) && n > 0 ? n : fallback;
  }

  function create(containerEl, options) {
    var opts = options || {};
    var win = opts.win || root;
    var doc = win.document;
    var G = pick(win, 'PanelGrid', PanelGridModule);
    var Reg = pick(win, 'PanelRegistry', PanelRegistryModule);
    var registry = opts.registry;
    var wsUrl = opts.wsUrl;

    var mounted = [];      // [{handle}] for the page currently shown
    var widgetsShown = []; // widget defs currently shown (for subscribe)
    var live = false;
    var socket = null;
    var socketReady = false;
    var reconnectTimer = null;
    var destroyed = false;

    // ------------------------------------------------------------ handles

    function destroyHandles() {
      for (var i = 0; i < mounted.length; i++) {
        var handle = mounted[i].handle;
        try {
          if (handle && typeof handle.destroy === 'function') handle.destroy();
        } catch (e) {
          // a broken widget must not break the editor
        }
      }
      mounted = [];
    }

    function resizeHandles() {
      for (var i = 0; i < mounted.length; i++) {
        var handle = mounted[i].handle;
        try {
          if (handle && typeof handle.resize === 'function') handle.resize();
        } catch (e) {
          // ignored on purpose
        }
      }
    }

    function mountTile(stageEl, widget, grid) {
      var tileEl = makeEl(doc, 'div', 'pn-tile');
      placeTile(tileEl, G.cellRect(widget, grid));
      var innerEl = makeEl(doc, 'div', 'pn-tile-inner');
      tileEl.appendChild(innerEl);
      stageEl.appendChild(tileEl);
      var handle = null;
      try {
        handle = Reg.mount(registry, innerEl, widget, {
          sendAction: function () { return false; }
        });
      } catch (e) {
        handle = null;
      }
      mounted.push({ handle: handle });
    }

    // ------------------------------------------------------------ show

    function show(layout, pageId, orientation, size) {
      destroyHandles();
      clearChildren(containerEl);
      widgetsShown = [];
      if (destroyed) return;

      var page = null;
      var pages = layout && Array.isArray(layout.pages) ? layout.pages : [];
      for (var p = 0; p < pages.length; p++) {
        if (pages[p] && pages[p].id === pageId) {
          page = pages[p];
          break;
        }
      }
      var variant = page && Array.isArray(page[orientation]) ? page[orientation] : [];
      var grid = G.gridFor(layout, orientation);
      var width = positiveOr(size && size.width, 1);
      var height = positiveOr(size && size.height, 1);

      var available = containerEl.clientWidth || 0;
      var scale = available > 0 ? Math.min(1, available / width) : 1;

      var wrapEl = makeEl(doc, 'div', 'ed-pv');
      wrapEl.style.width = '100%';
      wrapEl.style.height = height * scale + 'px';
      wrapEl.style.position = 'relative';
      wrapEl.style.overflow = 'hidden';

      var frameEl = makeEl(doc, 'div', 'ed-pv-frame');
      frameEl.style.position = 'absolute';
      frameEl.style.top = '0';
      frameEl.style.left = '0';
      frameEl.style.width = width + 'px';
      frameEl.style.height = height + 'px';
      frameEl.style.overflow = 'hidden';
      frameEl.style.transformOrigin = '0 0';
      frameEl.style.transform = 'scale(' + scale + ')';
      frameEl.style.webkitTransformOrigin = '0 0';
      frameEl.style.webkitTransform = 'scale(' + scale + ')';

      var stageEl = makeEl(doc, 'div', 'pn-stage');
      frameEl.appendChild(stageEl);
      wrapEl.appendChild(frameEl);
      containerEl.appendChild(wrapEl);

      for (var i = 0; i < variant.length; i++) {
        var widget = variant[i];
        if (!widget) continue;
        widgetsShown.push(widget);
        try {
          mountTile(stageEl, widget, grid);
        } catch (e) {
          // one bad widget never breaks the preview
        }
      }

      // Tiles now have a layout box: let the widgets measure themselves.
      resizeHandles();
      sendSubscribe();
    }

    // ------------------------------------------------------------ live

    function currentTopics() {
      if (!registry || typeof registry.topicsFor !== 'function') return [];
      try {
        return registry.topicsFor(widgetsShown) || [];
      } catch (e) {
        return [];
      }
    }

    function send(msg) {
      if (!socket || !socketReady) return false;
      try {
        socket.send(JSON.stringify(msg));
        return true;
      } catch (e) {
        return false;
      }
    }

    function sendSubscribe() {
      send({ type: 'subscribe', topics: currentTopics() });
    }

    function sendHello() {
      send({ type: 'hello', body: HELLO_BODY, name: HELLO_NAME });
    }

    function onTopic(topic, data) {
      for (var i = 0; i < mounted.length; i++) {
        var handle = mounted[i].handle;
        try {
          if (handle && typeof handle.onTopic === 'function') handle.onTopic(topic, data);
        } catch (e) {
          // ignored on purpose
        }
      }
    }

    function clearReconnect() {
      if (reconnectTimer !== null) {
        win.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    }

    function scheduleReconnect() {
      if (!live || destroyed || reconnectTimer !== null) return;
      reconnectTimer = win.setTimeout(function () {
        reconnectTimer = null;
        openSocket();
      }, RECONNECT_MS);
    }

    function closeSocket() {
      var sock = socket;
      socket = null;
      socketReady = false;
      if (sock) {
        sock.onopen = null;
        sock.onmessage = null;
        sock.onclose = null;
        sock.onerror = noop;
        try {
          sock.close();
        } catch (e) {
          // already closed
        }
      }
    }

    function openSocket() {
      clearReconnect();
      closeSocket();
      var sock;
      try {
        sock = new win.WebSocket(wsUrl);
      } catch (e) {
        scheduleReconnect();
        return;
      }
      socket = sock;
      sock.onopen = function () {
        if (socket !== sock) return;
        socketReady = true;
        sendHello();
        sendSubscribe();
      };
      sock.onmessage = function (ev) {
        if (socket !== sock) return;
        var msg = null;
        try {
          msg = JSON.parse(ev && ev.data);
        } catch (e) {
          msg = null;
        }
        if (msg && msg.type === 'topic') onTopic(msg.topic, msg.data);
      };
      sock.onclose = function () {
        if (socket !== sock) return;
        socket = null;
        socketReady = false;
        scheduleReconnect();
      };
      sock.onerror = noop;
    }

    function setLive(on) {
      if (destroyed) return;
      var want = !!on;
      if (want === live) return;
      live = want;
      if (live) {
        openSocket();
      } else {
        clearReconnect();
        closeSocket();
      }
    }

    function destroy() {
      if (destroyed) return;
      live = false;
      clearReconnect();
      closeSocket();
      destroyHandles();
      clearChildren(containerEl);
      widgetsShown = [];
      destroyed = true;
    }

    return {
      show: show,
      setLive: setLive,
      destroy: destroy
    };
  }

  var api = {
    create: create
  };

  root.EditorPreview = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
