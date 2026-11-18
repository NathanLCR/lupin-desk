(function (root) {
  'use strict';

  // Widget registry and the mount wrapper that makes widgets fail alone.
  // Strict ES5: runs on old Android WebViews, old Safari and e-ink browsers.

  var ID_PATTERN = /^[a-z][a-z0-9_.-]{0,63}$/;
  var DEFAULT_MIN = { w: 1, h: 1 };
  var DEFAULT_MAX = { w: 12, h: 12 };
  var DEFAULT_SIZE = { w: 2, h: 2 };

  function noop() {}

  function hasOwn(object, key) {
    return Object.prototype.hasOwnProperty.call(object, key);
  }

  function copyObject(source) {
    var out = {};
    for (var key in source) {
      if (hasOwn(source, key)) out[key] = source[key];
    }
    return out;
  }

  function copyStrings(list) {
    var out = [];
    if (!list) return out;
    for (var i = 0; i < list.length; i++) {
      if (typeof list[i] === 'string') out.push(list[i]);
    }
    return out;
  }

  function sizeOf(value, fallback) {
    var source = value || fallback;
    var w = typeof source.w === 'number' && isFinite(source.w) ? Math.floor(source.w) : fallback.w;
    var h = typeof source.h === 'number' && isFinite(source.h) ? Math.floor(source.h) : fallback.h;
    return { w: Math.max(1, w), h: Math.max(1, h) };
  }

  function normalizeSizes(sizes) {
    var source = sizes || {};
    return {
      min: sizeOf(source.min, DEFAULT_MIN),
      max: sizeOf(source.max, DEFAULT_MAX),
      default: sizeOf(source.default, DEFAULT_SIZE)
    };
  }

  function errorMessage(error) {
    if (error && typeof error.message === 'string' && error.message) return error.message;
    return String(error);
  }

  function validate(def) {
    if (!def || typeof def !== 'object') {
      throw new Error('Panel widget definition must be an object');
    }
    if (typeof def.id !== 'string' || !ID_PATTERN.test(def.id)) {
      throw new Error('Invalid panel widget id: ' + String(def.id));
    }
    if (typeof def.title !== 'string') {
      throw new Error('Panel widget ' + def.id + ' needs a string title');
    }
    if (typeof def.render !== 'function') {
      throw new Error('Panel widget ' + def.id + ' needs a render function');
    }
  }

  // Replaces the tile content with the error tile. Never throws.
  function showError(handle, el, title, message) {
    handle.failed = true;
    handle.error = message;
    handle.instance = null;
    el.textContent = '';
    var doc = el.ownerDocument;
    var box = doc.createElement('div');
    box.className = 'pn-error';
    var strong = doc.createElement('strong');
    strong.textContent = title;
    var span = doc.createElement('span');
    span.textContent = message;
    box.appendChild(strong);
    box.appendChild(span);
    el.appendChild(box);
  }

  function create() {
    var defs = {};

    function get(id) {
      return hasOwn(defs, id) ? defs[id] : null;
    }

    function register(def) {
      validate(def);
      if (hasOwn(defs, def.id)) {
        throw new Error('Panel widget already registered: ' + def.id);
      }
      var stored = copyObject(def);
      stored.sizes = normalizeSizes(def.sizes);
      stored.topics = copyStrings(def.topics);
      stored.actions = copyStrings(def.actions);
      defs[def.id] = stored;
      return stored;
    }

    function list() {
      var out = [];
      for (var id in defs) {
        if (hasOwn(defs, id)) out.push(defs[id]);
      }
      out.sort(function (a, b) {
        if (a.title !== b.title) return a.title < b.title ? -1 : 1;
        if (a.id !== b.id) return a.id < b.id ? -1 : 1;
        return 0;
      });
      return out;
    }

    function topicsFor(widgets) {
      var seen = {};
      var out = [];
      for (var i = 0; i < (widgets || []).length; i++) {
        var def = get(widgets[i].type);
        if (!def) continue;
        for (var j = 0; j < def.topics.length; j++) {
          var topic = def.topics[j];
          if (!hasOwn(seen, topic)) {
            seen[topic] = true;
            out.push(topic);
          }
        }
      }
      return out.sort();
    }

    return {
      register: register,
      get: get,
      list: list,
      topicsFor: topicsFor
    };
  }

  function mount(registry, el, widget, env) {
    var options = env || {};
    var sendAction = typeof options.sendAction === 'function' ? options.sendAction : noop;
    var now = typeof options.now === 'function' ? options.now : function () { return new Date().getTime(); };
    var def = registry ? registry.get(widget.type) : null;
    var title = def ? (def.title || def.id) : widget.type;

    var handle = {
      widget: widget,
      failed: false,
      error: null,
      instance: null,
      destroyed: false,
      onTopic: noop,
      resize: noop,
      destroy: noop
    };

    el.textContent = '';

    if (!def) {
      showError(handle, el, title, 'Unknown widget type: ' + String(widget.type));
      return handle;
    }

    var ctx = {
      widget: widget,
      config: widget.config || {},
      size: { width: el.clientWidth || 0, height: el.clientHeight || 0 },
      sendAction: sendAction,
      now: now,
      el: el
    };

    try {
      handle.instance = def.render(el, ctx) || null;
    } catch (error) {
      showError(handle, el, title, errorMessage(error));
      return handle;
    }

    var instance = handle.instance;

    function guard(fn) {
      if (handle.failed) return;
      try {
        fn();
      } catch (error) {
        showError(handle, el, title, errorMessage(error));
      }
    }

    handle.onTopic = function (topic, data) {
      if (!instance || typeof instance.onTopic !== 'function') return;
      if (def.topics.indexOf(topic) < 0) return;
      guard(function () { instance.onTopic(topic, data); });
    };

    handle.resize = function () {
      if (!instance || typeof instance.onResize !== 'function') return;
      var size = { width: el.clientWidth || 0, height: el.clientHeight || 0 };
      guard(function () { instance.onResize(size); });
    };

    handle.destroy = function () {
      // A tile that failed after mount still owns a live instance (timers): tear it down.
      if (handle.destroyed) return;
      handle.destroyed = true;
      if (!instance || typeof instance.destroy !== 'function') return;
      try {
        instance.destroy();
      } catch (error) {
        // A widget that fails while tearing down must not break the Panel.
      }
    };

    return handle;
  }

  var api = {
    create: create,
    mount: mount
  };
  api.shared = create();

  root.PanelRegistry = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
