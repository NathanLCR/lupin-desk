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
  var SVG_NS = 'http://www.w3.org/2000/svg';
  var ZONE_LIMIT = 4;
  var NO_TIME = '--:--';

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

  // 'HH:MM' for an instant in an IANA time zone, or '--:--' if the engine cannot do it.
  function zoneTime(date, tz) {
    var text;
    try {
      text = date.toLocaleTimeString('en-GB', {
        timeZone: tz,
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
      });
    } catch (err) {
      return NO_TIME;
    }
    var match = /(\d{1,2}):(\d{2})/.exec(String(text));
    if (!match) return NO_TIME;
    var hour = parseInt(match[1], 10);
    if (hour === 24) hour = 0; // some engines print midnight as 24:00
    if (hour > 23) return NO_TIME;
    return pad2(hour) + ':' + match[2];
  }

  // Hand angles in degrees, measured clockwise from 12 o'clock.
  function analogAngles(date) {
    var h = date.getHours();
    var m = date.getMinutes();
    var s = date.getSeconds();
    return {
      hour: (h % 12) * 30 + m * 0.5,
      minute: m * 6 + s * 0.1,
      second: s * 6
    };
  }

  // Keeps up to ZONE_LIMIT valid {label, tz} entries; anything else is dropped.
  function normalizeZones(list) {
    var out = [];
    if (!Array.isArray(list)) return out;
    for (var i = 0; i < list.length && out.length < ZONE_LIMIT; i++) {
      var entry = list[i];
      if (entry && typeof entry === 'object' &&
          typeof entry.label === 'string' && typeof entry.tz === 'string') {
        out.push({ label: entry.label, tz: entry.tz });
      }
    }
    return out;
  }

  function svgNode(doc, tag, attrs) {
    var node = doc.createElementNS(SVG_NS, tag);
    Object.keys(attrs).forEach(function (name) {
      node.setAttribute(name, String(attrs[name]));
    });
    return node;
  }

  function setRotation(node, degrees) {
    var rounded = Math.round(degrees * 1000) / 1000;
    node.setAttribute('transform', 'rotate(' + rounded + ' 50 50)');
  }

  // Square side in px for the analog face, or 0 to fill the container.
  function faceSide(size) {
    var width = size && size.width > 0 ? size.width : 0;
    var height = size && size.height > 0 ? size.height : 0;
    if (!width || !height) return 0;
    return Math.max(40, Math.floor(Math.min(width * 0.9, height * 0.7)));
  }

  // Builds the SVG face (ticks, hands) inside a wrapper div.
  function buildAnalogFace(doc) {
    var face = doc.createElement('div');
    face.className = 'pn-clock-face';
    var svg = svgNode(doc, 'svg', { viewBox: '0 0 100 100', width: '100%', height: '100%' });
    svg.appendChild(svgNode(doc, 'circle', {
      cx: 50, cy: 50, r: 47, fill: 'none', stroke: 'currentColor', 'stroke-width': 2
    }));
    for (var i = 0; i < 12; i++) {
      var major = i % 3 === 0;
      svg.appendChild(svgNode(doc, 'line', {
        x1: 50, y1: 5, x2: 50, y2: major ? 14 : 10,
        stroke: 'currentColor', 'stroke-width': major ? 2.5 : 1,
        transform: 'rotate(' + (i * 30) + ' 50 50)',
        'data-role': 'tick'
      }));
    }
    var hands = {
      hour: svgNode(doc, 'line', {
        x1: 50, y1: 56, x2: 50, y2: 28, stroke: 'currentColor', 'stroke-width': 4,
        'stroke-linecap': 'round', 'data-hand': 'hour'
      }),
      minute: svgNode(doc, 'line', {
        x1: 50, y1: 58, x2: 50, y2: 16, stroke: 'currentColor', 'stroke-width': 2.5,
        'stroke-linecap': 'round', 'data-hand': 'minute'
      }),
      second: svgNode(doc, 'line', {
        x1: 50, y1: 64, x2: 50, y2: 10, stroke: 'currentColor', 'stroke-width': 1,
        'data-hand': 'second'
      })
    };
    svg.appendChild(hands.hour);
    svg.appendChild(hands.minute);
    svg.appendChild(hands.second);
    svg.appendChild(svgNode(doc, 'circle', { cx: 50, cy: 50, r: 2.5, fill: 'currentColor' }));
    face.appendChild(svg);
    return { face: face, hands: hands };
  }

  function renderClock(el, ctx) {
    var doc = el.ownerDocument;
    var cfg = (ctx && ctx.config) || {};
    var zones = normalizeZones(cfg.zones);
    var showSeconds = cfg.seconds === true;
    // Analog needs SVG namespace support; otherwise show the digital face.
    var analog = cfg.style === 'analog' && typeof doc.createElementNS === 'function';

    var wrap = doc.createElement('div');
    wrap.className = analog ? 'pn-clock pn-clock-analog' : 'pn-clock';
    var timeEl = null;
    var face = null;
    var hands = null;
    if (analog) {
      var built = buildAnalogFace(doc);
      face = built.face;
      hands = built.hands;
      wrap.appendChild(face);
    } else {
      timeEl = doc.createElement('div');
      timeEl.className = 'pn-clock-time';
      wrap.appendChild(timeEl);
    }
    var dateEl = doc.createElement('div');
    dateEl.className = 'pn-clock-date';
    wrap.appendChild(dateEl);

    var zonesEl = null;
    var zoneRows = [];
    if (zones.length) {
      zonesEl = doc.createElement('div');
      zonesEl.className = 'pn-clock-zones';
      zones.forEach(function (zone) {
        var row = doc.createElement('div');
        row.className = 'pn-clock-zone';
        var label = doc.createElement('span');
        label.className = 'pn-clock-zone-label';
        label.textContent = zone.label;
        var value = doc.createElement('span');
        value.className = 'pn-clock-zone-time';
        row.appendChild(label);
        row.appendChild(value);
        zonesEl.appendChild(row);
        zoneRows.push({ tz: zone.tz, value: value });
      });
      wrap.appendChild(zonesEl);
    }
    el.appendChild(wrap);

    function scale(size) {
      var sizes = clockFontSizes(size);
      if (timeEl) timeEl.style.fontSize = sizes.time + 'px';
      dateEl.style.fontSize = sizes.date + 'px';
      if (zonesEl) zonesEl.style.fontSize = sizes.date + 'px';
      if (face) {
        var side = faceSide(size);
        face.style.width = side ? side + 'px' : '100%';
        face.style.height = side ? side + 'px' : '100%';
      }
    }

    function tick() {
      var now = new Date();
      if (timeEl) {
        timeEl.textContent = formatTime(now) +
          (showSeconds ? ':' + pad2(now.getSeconds()) : '');
      }
      if (hands) {
        var angles = analogAngles(now);
        setRotation(hands.hour, angles.hour);
        setRotation(hands.minute, angles.minute);
        setRotation(hands.second, angles.second);
      }
      dateEl.textContent = formatDate(now);
      zoneRows.forEach(function (row) {
        row.value.textContent = zoneTime(now, row.tz);
      });
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
    clockFontSizes: clockFontSizes,
    zoneTime: zoneTime,
    analogAngles: analogAngles,
    normalizeZones: normalizeZones
  };

  root.PanelWidgets = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
