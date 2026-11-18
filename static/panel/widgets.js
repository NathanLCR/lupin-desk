/**
 * Built-in Panel widgets: Clock and Placeholder.
 * Registers through registry.register(def) only. ES5 for old WebViews.
 */
(function (root) {
  'use strict';

  var DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  var MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var PLACEHOLDER_TEXT = 'Widget coming soon';

  function pad2(n) {
    return (n < 10 ? '0' : '') + n;
  }

  function formatTime(date) {
    return pad2(date.getHours()) + ':' + pad2(date.getMinutes());
  }

  function formatDate(date) {
    return DAY_NAMES[date.getDay()] + ' ' + date.getDate() + ' ' +
      MONTH_NAMES[date.getMonth()];
  }

  // Font sizes (px) for the clock, derived from the tile size.
  function clockFontSizes(size) {
    var width = size && size.width > 0 ? size.width : 0;
    var height = size && size.height > 0 ? size.height : 0;
    if (!width || !height) {
      return { time: 48, date: 14 };
    }
    var time = Math.floor(Math.min(height * 0.5, width * 0.2));
    if (time < 12) time = 12;
    var date = Math.max(10, Math.round(time * 0.28));
    return { time: time, date: date };
  }

  function renderClock(el, ctx) {
    var doc = el.ownerDocument;
    var wrap = doc.createElement('div');
    wrap.className = 'pn-clock';
    var timeEl = doc.createElement('div');
    timeEl.className = 'pn-clock-time';
    var dateEl = doc.createElement('div');
    dateEl.className = 'pn-clock-date';
    wrap.appendChild(timeEl);
    wrap.appendChild(dateEl);
    el.appendChild(wrap);

    function scale(size) {
      var sizes = clockFontSizes(size);
      timeEl.style.fontSize = sizes.time + 'px';
      dateEl.style.fontSize = sizes.date + 'px';
    }

    function tick() {
      var now = new Date();
      timeEl.textContent = formatTime(now);
      dateEl.textContent = formatDate(now);
    }

    var timer = null;

    scale(ctx && ctx.size);
    tick();
    timer = setInterval(tick, 1000);

    return {
      onResize: function (size) {
        scale(size);
      },
      destroy: function () {
        if (timer !== null) {
          clearInterval(timer);
          timer = null;
        }
      }
    };
  }

  function renderPlaceholder(el, ctx) {
    var doc = el.ownerDocument;
    var raw = ctx && ctx.config ? ctx.config.text : undefined;
    var text = (raw === undefined || raw === null || raw === '')
      ? PLACEHOLDER_TEXT
      : String(raw);
    var box = doc.createElement('div');
    box.className = 'pn-placeholder';
    box.textContent = text;
    el.appendChild(box);
    return null;
  }

  var BUILTINS = [
    {
      id: 'clock',
      title: 'Clock',
      sizes: {
        min: { w: 2, h: 1 },
        max: { w: 12, h: 6 },
        default: { w: 4, h: 2 }
      },
      topics: [],
      actions: [],
      render: renderClock
    },
    {
      id: 'placeholder',
      title: 'Placeholder',
      sizes: {
        min: { w: 1, h: 1 },
        max: { w: 12, h: 6 },
        default: { w: 4, h: 2 }
      },
      topics: [],
      actions: [],
      render: renderPlaceholder
    }
  ];

  function registerBuiltins(registry) {
    BUILTINS.forEach(function (def) {
      // Skip types already present, so a second start() on the shared registry is harmless.
      if (typeof registry.get === 'function' && registry.get(def.id)) {
        return;
      }
      registry.register(def);
    });
  }

  var api = {
    registerBuiltins: registerBuiltins,
    formatTime: formatTime,
    formatDate: formatDate,
    clockFontSizes: clockFontSizes
  };

  root.PanelWidgets = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
