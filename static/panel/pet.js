/**
 * Panel Pet page: hosts the Lupin face (static/lupin.js) lazily.
 * Calls made before lupin.js loads are queued and forwarded after init().
 * Nothing thrown by the face ever reaches the Panel. ES5 for old WebViews.
 */
(function (root) {
  'use strict';

  var LUPIN_CSS = '/static/lupin.css';
  var LUPIN_JS = '/static/lupin.js';
  var MAX_QUEUE = 100;

  // Shared loader state: 'idle' | 'loading' | 'ready' | 'failed'.
  var loadState = 'idle';
  var waiters = [];

  function getFace(win) {
    return win && win.LupinFace ? win.LupinFace : null;
  }

  function headOf(doc) {
    return doc.head || doc.getElementsByTagName('head')[0] || doc.body;
  }

  function finishLoad(win, ok) {
    var pending = waiters;
    waiters = [];
    loadState = ok && getFace(win) ? 'ready' : 'failed';
    pending.forEach(function (callback) {
      callback(loadState === 'ready');
    });
  }

  // Calls callback(true|false) once lupin.js is usable, injecting the assets once.
  function whenFaceReady(win, doc, callback) {
    if (getFace(win)) {
      callback(true);
      return;
    }
    if (loadState === 'failed') {
      callback(false);
      return;
    }
    if (loadState === 'ready') {
      // lupin.js was loaded before but the global is gone now: load it again.
      loadState = 'idle';
    }
    waiters.push(callback);
    if (loadState === 'loading') {
      return;
    }
    loadState = 'loading';
    try {
      var head = headOf(doc);
      var link = doc.createElement('link');
      link.rel = 'stylesheet';
      link.href = LUPIN_CSS;
      head.appendChild(link);

      var script = doc.createElement('script');
      script.src = LUPIN_JS;
      script.onload = function () {
        finishLoad(win, true);
      };
      script.onerror = function () {
        finishLoad(win, false);
      };
      head.appendChild(script);
    } catch (error) {
      finishLoad(win, false);
    }
  }

  function create(doc, pageEl) {
    var win = (doc && doc.defaultView) || root;
    var queue = [];
    var ready = false;
    var failed = false;
    var destroyed = false;

    function callFace(method, args) {
      try {
        var face = getFace(win);
        if (face && typeof face[method] === 'function') {
          face[method].apply(face, args);
        }
      } catch (error) {
        // A Pet failure must not break the Panel.
      }
    }

    function forward(method, args) {
      if (destroyed || failed) return;
      if (!ready) {
        if (queue.length < MAX_QUEUE) {
          queue.push({ method: method, args: args });
        }
        return;
      }
      callFace(method, args);
    }

    function onFaceReady(ok) {
      if (destroyed) return;
      if (!ok) {
        failed = true;
        queue = [];
        return;
      }
      ready = true;
      callFace('init', [pageEl]);
      var pending = queue;
      queue = [];
      pending.forEach(function (item) {
        callFace(item.method, item.args);
      });
    }

    try {
      whenFaceReady(win, doc, onFaceReady);
    } catch (error) {
      failed = true;
      queue = [];
    }

    return {
      setState: function (state) {
        forward('setState', [state]);
      },
      setEmotion: function (emotion) {
        forward('setEmotion', [emotion]);
      },
      destroy: function () {
        if (ready) callFace('destroy', []);
        destroyed = true;
        queue = [];
      }
    };
  }

  var api = { create: create };

  root.PanelPet = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
