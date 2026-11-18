(function (root) {
  'use strict';

  // Small helpers shared by the everyday Panel widgets. Strict ES5, no innerHTML.

  function hasOwn(object, key) {
    return Object.prototype.hasOwnProperty.call(object, key);
  }

  // Creates an element; text is set with textContent only (never markup).
  function el(doc, tag, className, text) {
    var node = doc.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function clear(node) {
    node.textContent = '';
  }

  // GET a JSON document. cb(error, data); error is null on success. Never throws.
  function getJson(url, cb) {
    var Xhr = typeof XMLHttpRequest !== 'undefined' ? XMLHttpRequest : null;
    if (!Xhr) {
      cb(new Error('No XMLHttpRequest'), null);
      return;
    }
    var done = false;
    function finish(error, data) {
      if (done) return;
      done = true;
      cb(error, data);
    }
    try {
      var xhr = new Xhr();
      xhr.open('GET', url, true);
      xhr.timeout = 8000;
      xhr.onload = function () {
        if (xhr.status < 200 || xhr.status >= 300) {
          finish(new Error('HTTP ' + xhr.status), null);
          return;
        }
        try {
          finish(null, JSON.parse(xhr.responseText));
        } catch (e) {
          finish(new Error('Bad JSON'), null);
        }
      };
      xhr.onerror = function () { finish(new Error('Network error'), null); };
      xhr.ontimeout = function () { finish(new Error('Timeout'), null); };
      xhr.send();
    } catch (e) {
      finish(e, null);
    }
  }

  // Calls fn now and then every ms. Returns stop(). A throwing fn does not stop the polling.
  function poll(fn, ms) {
    var timer = null;
    var stopped = false;
    function run() {
      if (stopped) return;
      try { fn(); } catch (e) { /* the widget shows its own error state */ }
    }
    run();
    timer = setInterval(run, ms);
    return function stop() {
      stopped = true;
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    };
  }

  // Registers every def on the registry, skipping ids that already exist.
  function registerAll(registry, defs) {
    for (var i = 0; i < defs.length; i++) {
      if (!registry.get(defs[i].id)) registry.register(defs[i]);
    }
  }

  // In a browser, a widget file registers itself on the shared registry when it loads.
  function autoRegister(root, defs) {
    if (typeof window === 'undefined' || !root.PanelRegistry || !root.PanelRegistry.shared) return;
    registerAll(root.PanelRegistry.shared, defs);
  }

  var api = {
    hasOwn: hasOwn,
    el: el,
    clear: clear,
    getJson: getJson,
    poll: poll,
    registerAll: registerAll,
    autoRegister: autoRegister
  };

  root.PanelKit = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
