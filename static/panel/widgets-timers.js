/**
 * Everyday Panel widgets: Pomodoro and Timers.
 * Registers through PanelKit.registerAll / autoRegister. Strict ES5, no innerHTML.
 */
(function (root) {
  'use strict';

  var kit = (typeof module !== 'undefined' && module.exports)
    ? require('./widget-kit.js')
    : root.PanelKit;

  var STATUS_URL = '/api/mac/status';
  var TIMERS_URL = '/api/panel/timers';
  var POMO_POLL_MS = 5000;
  var TICK_MS = 1000;
  var REPOLL_AFTER_PRESS_MS = 700;
  var POMO_EMPTY = '--:--';
  var POMO_DONE = 'Done';
  var DEFAULT_PRESETS = [1, 5, 10, 25];
  var MAX_PRESETS = 6;
  var MAX_PRESET_MINUTES = 1440;

  function pad2(n) {
    return (n < 10 ? '0' : '') + n;
  }

  // Non-numbers, NaN and negatives count as zero. Fractions are floored.
  function toWholeSeconds(value) {
    var n = Number(value);
    if (!isFinite(n) || n < 0) return 0;
    return Math.floor(n);
  }

  // 'MM:SS', or 'H:MM:SS' from one hour on.
  function formatDuration(totalSeconds) {
    var total = toWholeSeconds(totalSeconds);
    var hours = Math.floor(total / 3600);
    var minutes = Math.floor((total % 3600) / 60);
    var seconds = total % 60;
    if (hours > 0) return hours + ':' + pad2(minutes) + ':' + pad2(seconds);
    return pad2(minutes) + ':' + pad2(seconds);
  }

  // Seconds left in a pomodoro state at nowMs, or null when not running or unreadable.
  function pomodoroRemaining(state, nowMs) {
    if (!state || !state.active) return null;
    if (typeof state.started_at !== 'string') return null;
    var startMs = Date.parse(state.started_at);
    var minutes = Number(state.duration_minutes);
    var now = Number(nowMs);
    if (isNaN(startMs) || !isFinite(minutes) || !isFinite(now)) return null;
    var endMs = startMs + minutes * 60000;
    var left = Math.ceil((endMs - now) / 1000);
    return left > 0 ? left : 0;
  }

  // Counts each timer down by the whole seconds elapsed since the message was received.
  // Entries without an id are skipped.
  function timersWithRemaining(list, receivedAtMs, nowMs) {
    var out = [];
    if (!list || typeof list !== 'object' || typeof list.length !== 'number') return out;
    var elapsed = Number(nowMs) - Number(receivedAtMs);
    var elapsedSeconds = isFinite(elapsed) && elapsed > 0 ? Math.floor(elapsed / 1000) : 0;
    for (var i = 0; i < list.length; i++) {
      var t = list[i];
      if (!t || typeof t !== 'object') continue;
      if (t.id === undefined || t.id === null || t.id === '') continue;
      var remaining = toWholeSeconds(t.remaining) - elapsedSeconds;
      out.push({
        id: String(t.id),
        label: typeof t.label === 'string' ? t.label.trim() : '',
        seconds: toWholeSeconds(t.seconds),
        remaining: remaining > 0 ? remaining : 0
      });
    }
    return out;
  }

  // Preset minutes from config: integers 1..1440, at most six. Falls back to the defaults.
  function sanitizePresets(raw) {
    if (!raw || typeof raw !== 'object' || typeof raw.length !== 'number') {
      return DEFAULT_PRESETS.slice();
    }
    var out = [];
    for (var i = 0; i < raw.length && out.length < MAX_PRESETS; i++) {
      var v = raw[i];
      if (typeof v === 'number' && v === Math.floor(v) && v >= 1 && v <= MAX_PRESET_MINUTES) {
        out.push(v);
      }
    }
    return out.length ? out : DEFAULT_PRESETS.slice();
  }

  function clearChildren(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function nowFunction(ctx) {
    if (ctx && typeof ctx.now === 'function') return ctx.now;
    return function () { return new Date().getTime(); };
  }

  function send(ctx, id, args) {
    if (ctx && typeof ctx.sendAction === 'function') ctx.sendAction(id, args);
  }

  function renderPomodoro(el, ctx) {
    var doc = el.ownerDocument;
    var nowFn = nowFunction(ctx);
    var status = null;        // last pomodoro object from /api/mac/status
    var destroyed = false;
    var stopPoll = null;
    var tickTimer = null;
    var repollTimer = null;

    var wrap = kit.el(doc, 'div', 'pn-pomo');
    var timeEl = kit.el(doc, 'div', 'pn-pomo-time', POMO_EMPTY);
    var btn = kit.el(doc, 'button', 'pn-pomo-btn', 'Start');
    btn.type = 'button';
    wrap.appendChild(timeEl);
    wrap.appendChild(btn);
    el.appendChild(wrap);

    function isActive() {
      return !!(status && status.active);
    }

    function paint() {
      if (destroyed) return;
      var text = POMO_EMPTY;
      if (isActive()) {
        var left = pomodoroRemaining(status, nowFn());
        if (left === null) text = POMO_EMPTY;
        else if (left === 0) text = POMO_DONE;
        else text = formatDuration(left);
      } else if (status) {
        var minutes = Number(status.duration_minutes);
        if (isFinite(minutes) && minutes > 0) text = formatDuration(minutes * 60);
      }
      timeEl.textContent = text;
      btn.textContent = isActive() ? 'Stop' : 'Start';
    }

    function applyStatus(data) {
      if (destroyed) return;
      var pomo = data && typeof data === 'object' ? data.pomodoro : null;
      status = pomo && typeof pomo === 'object' ? pomo : { active: false };
      paint();
    }

    function refresh() {
      if (destroyed) return;
      kit.getJson(STATUS_URL, function (error, data) {
        if (error) return;
        applyStatus(data);
      });
    }

    function clearRepoll() {
      if (repollTimer !== null) {
        clearTimeout(repollTimer);
        repollTimer = null;
      }
    }

    btn.addEventListener('click', function () {
      if (destroyed) return;
      send(ctx, isActive() ? 'pomodoro.stop' : 'pomodoro.start', {});
      clearRepoll();
      repollTimer = setTimeout(function () {
        repollTimer = null;
        refresh();
      }, REPOLL_AFTER_PRESS_MS);
    });

    paint();
    stopPoll = kit.poll(refresh, POMO_POLL_MS);
    tickTimer = setInterval(paint, TICK_MS);

    return {
      onTopic: function (topic) {
        if (topic === 'signal:timer_done') refresh();
      },
      destroy: function () {
        if (destroyed) return;
        destroyed = true;
        if (stopPoll) stopPoll();
        stopPoll = null;
        if (tickTimer !== null) {
          clearInterval(tickTimer);
          tickTimer = null;
        }
        clearRepoll();
      }
    };
  }

  function presetLabel(minutes) {
    return minutes + ' min';
  }

  function renderTimers(el, ctx) {
    var doc = el.ownerDocument;
    var nowFn = nowFunction(ctx);
    var presets = sanitizePresets(ctx && ctx.config ? ctx.config.presets : null);
    var timers = [];          // last list received from the Panel
    var receivedAt = 0;       // local ms when that list arrived
    var rows = [];            // countdown element for each rendered timer, same order
    var destroyed = false;
    var tickTimer = null;

    var wrap = kit.el(doc, 'div', 'pn-timers');
    var presetRow = kit.el(doc, 'div', 'pn-timer-presets');
    var listEl = kit.el(doc, 'div', 'pn-timer-list');
    wrap.appendChild(presetRow);
    wrap.appendChild(listEl);
    el.appendChild(wrap);

    presets.forEach(function (minutes) {
      var btn = kit.el(doc, 'button', 'pn-timer-preset', presetLabel(minutes));
      btn.type = 'button';
      btn.addEventListener('click', function () {
        if (destroyed) return;
        send(ctx, 'timers.start', { seconds: minutes * 60 });
      });
      presetRow.appendChild(btn);
    });

    function buildRow(item) {
      var row = kit.el(doc, 'div', 'pn-timer-row');
      var label = item.label || formatDuration(item.seconds);
      var countdown = kit.el(doc, 'span', 'pn-timer-countdown', formatDuration(item.remaining));
      var cancel = kit.el(doc, 'button', 'pn-remove', '×');
      cancel.type = 'button';
      cancel.addEventListener('click', function () {
        if (destroyed) return;
        send(ctx, 'timers.cancel', { id: item.id });
      });
      row.appendChild(kit.el(doc, 'span', 'pn-timer-label', label));
      row.appendChild(countdown);
      row.appendChild(cancel);
      listEl.appendChild(row);
      return countdown;
    }

    function rebuild() {
      clearChildren(listEl);
      rows = [];
      var items = timersWithRemaining(timers, receivedAt, nowFn());
      if (!items.length) {
        listEl.appendChild(kit.el(doc, 'div', 'pn-timer-empty', 'No timers'));
        return;
      }
      for (var i = 0; i < items.length; i++) {
        rows.push(buildRow(items[i]));
      }
    }

    function tick() {
      if (destroyed || !rows.length) return;
      var items = timersWithRemaining(timers, receivedAt, nowFn());
      for (var i = 0; i < rows.length && i < items.length; i++) {
        rows[i].textContent = formatDuration(items[i].remaining);
      }
    }

    function applyList(data) {
      if (destroyed) return;
      var list = data && typeof data === 'object' ? data.timers : null;
      timers = list && typeof list === 'object' && typeof list.length === 'number' ? list : [];
      receivedAt = nowFn();
      rebuild();
    }

    function refresh() {
      if (destroyed) return;
      kit.getJson(TIMERS_URL, function (error, data) {
        if (error) return;
        applyList(data);
      });
    }

    rebuild();
    refresh();
    tickTimer = setInterval(tick, TICK_MS);

    return {
      onTopic: function (topic, data) {
        if (topic === 'timers') applyList(data);
      },
      destroy: function () {
        if (destroyed) return;
        destroyed = true;
        if (tickTimer !== null) {
          clearInterval(tickTimer);
          tickTimer = null;
        }
      }
    };
  }

  var DEFS = [
    {
      id: 'pomodoro',
      title: 'Pomodoro',
      sizes: {
        min: { w: 2, h: 1 },
        max: { w: 6, h: 4 },
        default: { w: 3, h: 2 }
      },
      topics: ['signal:timer_done'],
      actions: ['pomodoro.start', 'pomodoro.stop'],
      render: renderPomodoro
    },
    {
      id: 'timers',
      title: 'Timers',
      sizes: {
        min: { w: 2, h: 2 },
        max: { w: 6, h: 6 },
        default: { w: 3, h: 3 }
      },
      topics: ['timers'],
      actions: ['timers.start', 'timers.cancel'],
      render: renderTimers
    }
  ];

  function registerAll(registry) {
    kit.registerAll(registry, DEFS);
  }

  var api = {
    registerAll: registerAll,
    DEFS: DEFS,
    formatDuration: formatDuration,
    pomodoroRemaining: pomodoroRemaining,
    timersWithRemaining: timersWithRemaining,
    sanitizePresets: sanitizePresets
  };

  root.PanelWidgetsTimers = api;
  kit.autoRegister(root, DEFS);
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
