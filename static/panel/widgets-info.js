(function (root) {
  'use strict';

  // Everyday Panel widgets: Weather, Now playing and Calendar.
  // Registers through registry.register(def) only. Strict ES5 for old WebViews and e-ink
  // browsers. Text is set with textContent only, never markup.

  var PanelKit = (typeof module !== 'undefined' && module.exports) ? require('./widget-kit.js') : root.PanelKit;

  var WEATHER_POLL_MS = 15 * 60 * 1000;
  var NOW_PLAYING_POLL_MS = 5000;
  var NOW_PLAYING_REPOLL_MS = 700;
  var CALENDAR_POLL_MS = 60 * 1000;
  var CALENDAR_DEFAULT_MAX = 6;
  var NO_TIME = -1;
  var LATE_TIME = 100000;
  var PREV_TEXT = '⏮';
  var PLAY_TEXT = '▶';
  var PAUSE_TEXT = '⏸';
  var NEXT_TEXT = '⏭';

  function noop() {}

  function isNumber(value) {
    return typeof value === 'number' && isFinite(value);
  }

  function isArray(value) {
    return Object.prototype.toString.call(value) === '[object Array]';
  }

  function isObject(value) {
    return value !== null && typeof value === 'object';
  }

  function textOf(value) {
    return typeof value === 'string' ? value : '';
  }

  function positiveInt(value, fallback) {
    return isNumber(value) && value >= 1 ? Math.floor(value) : fallback;
  }

  // Rounded temperature with the degree sign, e.g. 21.6 -> "22°C".
  function formatTemp(n) {
    if (!isNumber(n)) return '--°C';
    return String(Math.round(n)) + '°C';
  }

  // Builds /api/weather with the optional lat, lon and city config values.
  function weatherUrl(config) {
    var cfg = isObject(config) ? config : {};
    var params = [];
    if (isNumber(cfg.lat)) params.push('lat=' + encodeURIComponent(String(cfg.lat)));
    if (isNumber(cfg.lon)) params.push('lon=' + encodeURIComponent(String(cfg.lon)));
    if (typeof cfg.city === 'string' && cfg.city !== '') {
      params.push('city=' + encodeURIComponent(cfg.city));
    }
    return params.length ? '/api/weather?' + params.join('&') : '/api/weather';
  }

  // "HH:MM" -> minutes since midnight, or NO_TIME when the text is not a clock time.
  function parseMinutes(text) {
    if (typeof text !== 'string') return NO_TIME;
    var match = /^(\d{1,2}):(\d{2})$/.exec(text);
    if (!match) return NO_TIME;
    var hours = Number(match[1]);
    var minutes = Number(match[2]);
    if (hours > 23 || minutes > 59) return NO_TIME;
    return hours * 60 + minutes;
  }

  // Returns a new array: all-day events first, then timed events by start time.
  // Events with a bad start go last. The input array is not changed.
  function sortEvents(events) {
    if (!isArray(events)) return [];
    var items = [];
    for (var i = 0; i < events.length; i++) {
      var ev = events[i];
      if (!isObject(ev)) continue;
      var key;
      if (ev.all_day === true) {
        key = NO_TIME;
      } else {
        var minutes = parseMinutes(ev.start);
        key = minutes === NO_TIME ? LATE_TIME : minutes;
      }
      items.push({ event: ev, key: key, order: items.length });
    }
    items.sort(function (a, b) {
      if (a.key !== b.key) return a.key - b.key;
      return a.order - b.order;
    });
    var out = [];
    for (var j = 0; j < items.length; j++) out.push(items[j].event);
    return out;
  }

  // Index of the earliest timed event that has not started yet at nowMs (local time),
  // or -1. All-day events are never "next".
  function nextEventIndex(events, nowMs) {
    if (!isArray(events) || !isNumber(nowMs)) return -1;
    var now = new Date(nowMs);
    var nowMinutes = now.getHours() * 60 + now.getMinutes();
    var best = -1;
    var bestMinutes = LATE_TIME;
    for (var i = 0; i < events.length; i++) {
      var ev = events[i];
      if (!isObject(ev) || ev.all_day === true) continue;
      var minutes = parseMinutes(ev.start);
      if (minutes === NO_TIME || minutes < nowMinutes) continue;
      if (best === -1 || minutes < bestMinutes) {
        best = i;
        bestMinutes = minutes;
      }
    }
    return best;
  }

  function makeButton(doc, label, title, onPress) {
    var btn = PanelKit.el(doc, 'button', 'pn-np-btn', label);
    btn.setAttribute('type', 'button');
    btn.setAttribute('title', title);
    btn.addEventListener('click', onPress);
    return btn;
  }

  // ------------------------------------------------------------------ weather

  function paintWeather(el, data) {
    var doc = el.ownerDocument;
    PanelKit.clear(el);
    if (!isObject(data) || data.ok === false || data.offline) {
      el.appendChild(PanelKit.el(doc, 'div', 'pn-weather-status', 'Weather unavailable'));
      return;
    }
    var box = PanelKit.el(doc, 'div', 'pn-weather');
    box.appendChild(PanelKit.el(doc, 'div', 'pn-weather-temp', formatTemp(data.temperature_c)));
    if (textOf(data.condition)) {
      box.appendChild(PanelKit.el(doc, 'div', 'pn-weather-condition', data.condition));
    }
    if (textOf(data.city)) {
      box.appendChild(PanelKit.el(doc, 'div', 'pn-weather-city', data.city));
    }
    if (isNumber(data.apparent_c)) {
      box.appendChild(PanelKit.el(doc, 'div', 'pn-weather-feels', 'feels like ' + formatTemp(data.apparent_c)));
    }
    el.appendChild(box);
  }

  function renderWeather(el, ctx) {
    var doc = el.ownerDocument;
    var url = weatherUrl(ctx && ctx.config);
    var alive = true;

    el.appendChild(PanelKit.el(doc, 'div', 'pn-weather-status', 'Loading weather'));

    var stop = PanelKit.poll(function () {
      PanelKit.getJson(url, function (err, data) {
        if (!alive) return;
        paintWeather(el, err ? null : data);
      });
    }, WEATHER_POLL_MS);

    return {
      destroy: function () {
        alive = false;
        stop();
      }
    };
  }

  // -------------------------------------------------------------- now playing

  function renderNowPlaying(el, ctx) {
    var doc = el.ownerDocument;
    var alive = true;
    var repoll = null;

    var view = PanelKit.el(doc, 'div', 'pn-np');
    var status = PanelKit.el(doc, 'div', 'pn-np-status', 'Loading...');
    var info = PanelKit.el(doc, 'div', 'pn-np-info');
    var track = PanelKit.el(doc, 'div', 'pn-np-track');
    var artist = PanelKit.el(doc, 'div', 'pn-np-artist');
    var app = PanelKit.el(doc, 'div', 'pn-np-app');
    info.appendChild(track);
    info.appendChild(artist);
    info.appendChild(app);

    var controls = PanelKit.el(doc, 'div', 'pn-np-controls');
    var prevBtn = makeButton(doc, PREV_TEXT, 'Previous', function () { press('media.previous'); });
    var playBtn = makeButton(doc, PLAY_TEXT, 'Play', function () { press('media.play_pause'); });
    var nextBtn = makeButton(doc, NEXT_TEXT, 'Next', function () { press('media.next'); });
    controls.appendChild(prevBtn);
    controls.appendChild(playBtn);
    controls.appendChild(nextBtn);

    view.appendChild(status);
    view.appendChild(info);
    view.appendChild(controls);
    el.appendChild(view);

    function showMessage(message) {
      status.textContent = message;
      status.style.display = '';
      info.style.display = 'none';
    }

    function paint(data) {
      if (!isObject(data) || data.ok === false) {
        showMessage('Media unavailable');
        return;
      }
      var np = data.now_playing;
      if (!isObject(np)) {
        showMessage('Nothing playing');
        return;
      }
      status.style.display = 'none';
      info.style.display = '';
      track.textContent = textOf(np.track) || 'Unknown track';
      artist.textContent = textOf(np.artist);
      app.textContent = textOf(np.app);
      var playing = np.state === 'playing';
      playBtn.textContent = playing ? PAUSE_TEXT : PLAY_TEXT;
      playBtn.setAttribute('title', playing ? 'Pause' : 'Play');
    }

    function load() {
      PanelKit.getJson('/api/mac/status', function (err, data) {
        if (!alive) return;
        paint(err ? null : data);
      });
    }

    function press(actionId) {
      try {
        if (ctx && typeof ctx.sendAction === 'function') ctx.sendAction(actionId, {});
      } catch (e) {
        // A failed action shows up on the next status poll; the tile itself stays up.
      }
      if (repoll !== null) clearTimeout(repoll);
      repoll = setTimeout(function () {
        repoll = null;
        if (alive) load();
      }, NOW_PLAYING_REPOLL_MS);
    }

    var stop = PanelKit.poll(load, NOW_PLAYING_POLL_MS);

    return {
      destroy: function () {
        alive = false;
        stop();
        if (repoll !== null) {
          clearTimeout(repoll);
          repoll = null;
        }
      }
    };
  }

  // ----------------------------------------------------------------- calendar

  function paintCalendar(el, data, max, nowMs) {
    var doc = el.ownerDocument;
    PanelKit.clear(el);
    if (!isObject(data) || data.ok === false) {
      el.appendChild(PanelKit.el(doc, 'div', 'pn-cal-status', 'Calendar unavailable'));
      return;
    }
    var events = sortEvents(data.events);
    if (events.length === 0) {
      el.appendChild(PanelKit.el(doc, 'div', 'pn-cal-status', 'No events today'));
      return;
    }
    var next = nextEventIndex(events, nowMs);
    var list = PanelKit.el(doc, 'div', 'pn-cal-list');
    var shown = Math.min(max, events.length);
    for (var i = 0; i < shown; i++) {
      var ev = events[i];
      var row = PanelKit.el(doc, 'div', i === next ? 'pn-cal-row pn-cal-next' : 'pn-cal-row');
      var when = ev.all_day === true ? 'All day' : (textOf(ev.start) || '--:--');
      row.appendChild(PanelKit.el(doc, 'span', 'pn-cal-time', when));
      row.appendChild(PanelKit.el(doc, 'span', 'pn-cal-title', textOf(ev.title) || '(untitled)'));
      list.appendChild(row);
    }
    el.appendChild(list);
  }

  function renderCalendar(el, ctx) {
    var doc = el.ownerDocument;
    var config = isObject(ctx && ctx.config) ? ctx.config : {};
    var max = positiveInt(config.max, CALENDAR_DEFAULT_MAX);
    var nowFn = ctx && typeof ctx.now === 'function' ? ctx.now : function () { return new Date().getTime(); };
    var alive = true;

    el.appendChild(PanelKit.el(doc, 'div', 'pn-cal-status', 'Loading calendar'));

    function load() {
      PanelKit.getJson('/api/panel/calendar', function (err, data) {
        if (!alive) return;
        paintCalendar(el, err ? null : data, max, nowFn());
      });
    }

    var stop = PanelKit.poll(load, CALENDAR_POLL_MS);

    return {
      destroy: function () {
        alive = false;
        stop();
      }
    };
  }

  // ---------------------------------------------------------------- definitions

  var DEFS = [
    {
      id: 'weather',
      title: 'Weather',
      sizes: {
        min: { w: 2, h: 1 },
        default: { w: 3, h: 2 },
        max: { w: 6, h: 4 }
      },
      topics: [],
      actions: [],
      render: renderWeather
    },
    {
      id: 'now_playing',
      title: 'Now playing',
      sizes: {
        min: { w: 2, h: 1 },
        default: { w: 3, h: 2 },
        max: { w: 6, h: 3 }
      },
      topics: [],
      actions: ['media.play_pause', 'media.next', 'media.previous'],
      render: renderNowPlaying
    },
    {
      id: 'calendar',
      title: 'Calendar',
      sizes: {
        min: { w: 2, h: 2 },
        default: { w: 3, h: 3 },
        max: { w: 6, h: 6 }
      },
      topics: [],
      actions: [],
      render: renderCalendar
    }
  ];

  var api = {
    registerAll: function (registry) {
      PanelKit.registerAll(registry, DEFS);
    },
    DEFS: DEFS,
    formatTemp: formatTemp,
    nextEventIndex: nextEventIndex,
    sortEvents: sortEvents,
    weatherUrl: weatherUrl
  };

  root.PanelWidgetsInfo = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;

  PanelKit.autoRegister(root, DEFS);
})(typeof window !== 'undefined' ? window : this);
