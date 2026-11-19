/**
 * Presence settings (/static/presence.js -> window.LupinPresence)
 * Break reminders (on/off, interval) and the "front app" Data Consent switch. Mac only to edit.
 * Pure helpers are separate from the DOM part so they can be tested. Plain ES5.
 */
(function () {
  'use strict';

  var MIN_DEFAULT = 20;
  var MAX_DEFAULT = 240;

  function clampMinutes(value, min, max) {
    var n = Math.round(Number(value));
    if (!isFinite(n)) return null;
    return Math.max(min || MIN_DEFAULT, Math.min(max || MAX_DEFAULT, n));
  }

  // Normalise a GET /api/presence response.
  function normalize(data) {
    var d = data || {};
    return {
      breakEnabled: d.break_enabled !== false,
      breakMinutes: clampMinutes(d.break_minutes, d.break_min, d.break_max) || 50,
      breakMin: Number(d.break_min) || MIN_DEFAULT,
      breakMax: Number(d.break_max) || MAX_DEFAULT,
      frontApp: d.front_app === true,
      frontAppLocal: d.front_app_local === true,
    };
  }

  // The PUT body for one change; null when the change is not valid.
  function buildChange(key, value, settings) {
    var s = settings || normalize({});
    if (key === 'break_enabled') return { break_enabled: Boolean(value) };
    if (key === 'front_app') return { front_app: Boolean(value) };
    if (key === 'break_minutes') {
      var minutes = clampMinutes(value, s.breakMin, s.breakMax);
      return minutes === null ? null : { break_minutes: minutes };
    }
    return null;
  }

  function receiverLabel(receiver) {
    return 'Let ' + (receiver || 'the provider') + ' see the name and window title of your front app';
  }

  var api = { clampMinutes: clampMinutes, normalize: normalize, buildChange: buildChange, receiverLabel: receiverLabel };

  function mount(doc) {
    var anchor = doc.getElementById('consent-note');
    if (!anchor || !anchor.parentNode || doc.getElementById('presence-settings')) return;
    var box = doc.createElement('div');
    box.id = 'presence-settings';
    box.innerHTML =
      '<div class="settings-row"><strong id="presence-front-label">Let the provider see your front app</strong>' +
      '<button id="btn-presence-front" type="button" class="hud-btn" role="switch" aria-checked="false" aria-labelledby="presence-front-label" disabled>Off</button></div>' +
      '<div class="settings-row"><strong id="presence-break-label">Break reminders</strong>' +
      '<button id="btn-presence-break" type="button" class="hud-btn" role="switch" aria-checked="false" aria-labelledby="presence-break-label" disabled>On</button></div>' +
      '<div class="settings-row"><label for="presence-minutes">Remind me after (minutes of work)</label>' +
      '<input id="presence-minutes" type="number" min="20" max="240" step="5" disabled></div>';
    anchor.parentNode.insertBefore(box, anchor.nextSibling);

    var settings = normalize({});
    var canEdit = false;
    var front = doc.getElementById('btn-presence-front');
    var brk = doc.getElementById('btn-presence-break');
    var minutes = doc.getElementById('presence-minutes');

    function render() {
      front.textContent = settings.frontApp ? 'On' : 'Off';
      front.setAttribute('aria-checked', String(settings.frontApp));
      front.disabled = !canEdit || settings.frontAppLocal;
      brk.textContent = settings.breakEnabled ? 'On' : 'Off';
      brk.setAttribute('aria-checked', String(settings.breakEnabled));
      brk.disabled = !canEdit;
      minutes.value = String(settings.breakMinutes);
      minutes.min = String(settings.breakMin);
      minutes.max = String(settings.breakMax);
      minutes.disabled = !canEdit;
    }

    function load() {
      fetch('/api/presence').then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
        if (d) { settings = normalize(d); render(); }
      }).catch(function () {});
    }

    function send(change) {
      if (!change || !canEdit) return;
      fetch('/api/presence', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(change),
      }).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
        if (d) { settings = normalize(d); render(); }
      }).catch(function () {});
    }

    front.addEventListener('click', function () { send(buildChange('front_app', !settings.frontApp, settings)); });
    brk.addEventListener('click', function () { send(buildChange('break_enabled', !settings.breakEnabled, settings)); });
    minutes.addEventListener('change', function () { send(buildChange('break_minutes', minutes.value, settings)); });

    fetch('/api/client-info').then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
      canEdit = Boolean(d && d.is_mac);
      render();
    }).catch(function () {});
    render();
    load();
  }

  api.mount = mount;

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  if (typeof window !== 'undefined') {
    window.LupinPresence = api;
    if (window.document) {
      if (window.document.readyState === 'loading') {
        window.document.addEventListener('DOMContentLoaded', function () { mount(window.document); });
      } else {
        mount(window.document);
      }
    }
  }
})();
