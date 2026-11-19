/**
 * Control Deck Panel widgets (P10): volume, microphone, media keys, macros, Dock and a webhook value.
 * Every control sends an action ID; no command text ever leaves a Panel. Shortcut titles, app
 * names, macro names and webhook values are data: text is only set with textContent.
 * Registers through PanelKit.autoRegister. Strict ES5 for old WebViews.
 */
(function (root) {
  'use strict';

  var kit = (typeof module !== 'undefined' && module.exports)
    ? require('./widget-kit.js')
    : root.PanelKit;

  var AUDIO_URL = '/api/control/audio';
  var MACROS_URL = '/api/control/macros';
  var HOOKS_URL = '/api/control/webhooks';
  var SHORTCUTS_URL = '/api/shortcuts';
  var APPS_URL = '/api/mac/apps';
  var AUDIO_POLL_MS = 5000;
  var LIST_POLL_MS = 10000;
  var REPOLL_AFTER_PRESS_MS = 600;
  var MAX_NAME = 40;

  function send(ctx, id, args) {
    if (ctx && typeof ctx.sendAction === 'function') ctx.sendAction(id, args || {});
  }

  function isRecord(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
  }

  function shortText(value) {
    var text = typeof value === 'string' ? value : '';
    return text.length > MAX_NAME ? text.substring(0, MAX_NAME) : text;
  }

  // Volume label from /api/control/audio: '42%', 'Muted' or '--' when unknown.
  function volumeLabel(status) {
    if (!isRecord(status)) return '--';
    if (status.muted === true) return 'Muted';
    var v = Number(status.volume);
    if (status.volume === null || status.volume === undefined || !isFinite(v)) return '--';
    return Math.round(v) + '%';
  }

  function micLabel(status) {
    if (!isRecord(status) || typeof status.mic_muted !== 'boolean') return 'Mic --';
    return status.mic_muted ? 'Mic off' : 'Mic on';
  }

  // Shortcuts pinned on the Deck that a Panel may run (no confirmation gate, no agent prompts).
  function pinnedShortcuts(data) {
    var list = isRecord(data) && Array.isArray(data.shortcuts) ? data.shortcuts : [];
    var out = [];
    for (var i = 0; i < list.length; i++) {
      var s = list[i];
      if (!isRecord(s) || typeof s.slug !== 'string' || !s.pinned_on_deck) continue;
      if (s.requires_confirmation || s.action_type === 'agent_prompt') continue;
      out.push({ slug: s.slug, title: shortText(s.title) || s.slug });
    }
    return out;
  }

  // Open apps first (front app first, as the Brain orders them), then the favourites.
  function appList(data) {
    var list = isRecord(data) && Array.isArray(data.apps) ? data.apps : [];
    var out = [];
    for (var i = 0; i < list.length; i++) {
      var a = list[i];
      if (!isRecord(a) || typeof a.name !== 'string' || !a.name) continue;
      out.push({ name: shortText(a.name), running: !!a.running, frontmost: !!a.frontmost });
    }
    return out;
  }

  function macroList(data) {
    var list = isRecord(data) && Array.isArray(data.macros) ? data.macros : [];
    var out = [];
    for (var i = 0; i < list.length; i++) {
      var m = list[i];
      if (!isRecord(m) || typeof m.id !== 'number' || !isFinite(m.id)) continue;
      out.push({ id: m.id, name: shortText(m.name) || ('Macro ' + m.id) });
    }
    return out;
  }

  function makeButton(doc, label, onClick) {
    var btn = kit.el(doc, 'button', 'pn-ctl-btn', label);
    btn.type = 'button';
    btn.addEventListener('click', onClick);
    return btn;
  }

  // Shared base: a polled audio status plus a re-poll shortly after a press.
  function audioWidget(el, ctx, build) {
    var doc = el.ownerDocument;
    var destroyed = false;
    var timer = null;
    var wrap = kit.el(doc, 'div', 'pn-ctl');
    el.appendChild(wrap);
    var view = build(doc, wrap, function press(id) {
      if (destroyed) return;
      send(ctx, id, {});
      if (timer !== null) clearTimeout(timer);
      timer = setTimeout(function () {
        timer = null;
        refresh();
      }, REPOLL_AFTER_PRESS_MS);
    });

    function refresh() {
      if (destroyed) return;
      kit.getJson(AUDIO_URL, function (error, data) {
        if (destroyed || error) return;
        view.paint(data);
      });
    }

    var stop = kit.poll(refresh, AUDIO_POLL_MS);
    return {
      destroy: function () {
        destroyed = true;
        stop();
        if (timer !== null) clearTimeout(timer);
        timer = null;
      }
    };
  }

  function renderVolume(el, ctx) {
    return audioWidget(el, ctx, function (doc, wrap, press) {
      var level = kit.el(doc, 'div', 'pn-ctl-level', '--');
      var row = kit.el(doc, 'div', 'pn-ctl-row');
      row.appendChild(makeButton(doc, '-', function () { press('volume.down'); }));
      row.appendChild(makeButton(doc, 'Mute', function () { press('volume.mute'); }));
      row.appendChild(makeButton(doc, '+', function () { press('volume.up'); }));
      wrap.appendChild(level);
      wrap.appendChild(row);
      return { paint: function (data) { level.textContent = volumeLabel(data); } };
    });
  }

  function renderMic(el, ctx) {
    return audioWidget(el, ctx, function (doc, wrap, press) {
      var btn = makeButton(doc, 'Mic --', function () { press('mic.toggle'); });
      btn.className += ' pn-ctl-big';
      wrap.appendChild(btn);
      return { paint: function (data) { btn.textContent = micLabel(data); } };
    });
  }

  function renderMedia(el, ctx) {
    var doc = el.ownerDocument;
    var wrap = kit.el(doc, 'div', 'pn-ctl');
    var row = kit.el(doc, 'div', 'pn-ctl-row');
    row.appendChild(makeButton(doc, 'Prev', function () { send(ctx, 'media.previous', {}); }));
    row.appendChild(makeButton(doc, 'Play/Pause', function () { send(ctx, 'media.play_pause', {}); }));
    row.appendChild(makeButton(doc, 'Next', function () { send(ctx, 'media.next', {}); }));
    wrap.appendChild(row);
    el.appendChild(wrap);
    return {};
  }

  // A polled list of buttons: the shared shape of the Macros and Dock widgets.
  function listWidget(el, urls, paintAll) {
    var doc = el.ownerDocument;
    var destroyed = false;
    var wrap = kit.el(doc, 'div', 'pn-ctl pn-ctl-list');
    el.appendChild(wrap);
    var latest = {};

    function refresh() {
      if (destroyed) return;
      for (var i = 0; i < urls.length; i++) {
        (function (key, url) {
          kit.getJson(url, function (error, data) {
            if (destroyed || error) return;
            latest[key] = data;
            kit.clear(wrap);
            paintAll(doc, wrap, latest);
          });
        })(urls[i][0], urls[i][1]);
      }
    }

    var stop = kit.poll(refresh, LIST_POLL_MS);
    return {
      destroy: function () {
        destroyed = true;
        stop();
      }
    };
  }

  function renderMacros(el, ctx) {
    return listWidget(el, [['macros', MACROS_URL]], function (doc, wrap, latest) {
      var macros = macroList(latest.macros);
      if (!macros.length) {
        wrap.appendChild(kit.el(doc, 'div', 'pn-ctl-empty', 'No macros yet'));
        return;
      }
      for (var i = 0; i < macros.length; i++) {
        (function (macro) {
          wrap.appendChild(makeButton(doc, macro.name, function () {
            send(ctx, 'macro.run', { id: macro.id });
          }));
        })(macros[i]);
      }
    });
  }

  function renderDock(el, ctx) {
    return listWidget(el, [['shortcuts', SHORTCUTS_URL], ['apps', APPS_URL]], function (doc, wrap, latest) {
      var pinned = pinnedShortcuts(latest.shortcuts);
      var apps = appList(latest.apps);
      var i;
      for (i = 0; i < pinned.length; i++) {
        (function (item) {
          wrap.appendChild(makeButton(doc, item.title, function () {
            send(ctx, 'shortcut.run', { slug: item.slug });
          }));
        })(pinned[i]);
      }
      for (i = 0; i < apps.length; i++) {
        (function (item) {
          var btn = makeButton(doc, item.name, function () {
            send(ctx, 'app.activate', { name: item.name });
          });
          btn.className += item.frontmost ? ' pn-ctl-front' : (item.running ? ' pn-ctl-open' : ' pn-ctl-closed');
          wrap.appendChild(btn);
        })(apps[i]);
      }
    });
  }

  // One webhook value. config.hook is the webhook id; without it the first webhook is shown.
  function renderWebhook(el, ctx) {
    var doc = el.ownerDocument;
    var destroyed = false;
    var wanted = ctx && ctx.config && typeof ctx.config.hook === 'number' ? ctx.config.hook : null;
    var wrap = kit.el(doc, 'div', 'pn-ctl');
    var nameEl = kit.el(doc, 'div', 'pn-ctl-sub', '');
    var valueEl = kit.el(doc, 'div', 'pn-ctl-level', '--');
    wrap.appendChild(nameEl);
    wrap.appendChild(valueEl);
    el.appendChild(wrap);

    function show(hook) {
      if (!isRecord(hook)) return;
      if (wanted !== null && hook.id !== wanted) return;
      nameEl.textContent = shortText(hook.name);
      valueEl.textContent = hook.value === null || hook.value === undefined ? '--' : String(hook.value);
    }

    function load() {
      kit.getJson(HOOKS_URL, function (error, data) {
        if (destroyed || error || !isRecord(data) || !Array.isArray(data.webhooks)) return;
        for (var i = 0; i < data.webhooks.length; i++) {
          if (isRecord(data.webhooks[i]) && (wanted === null || data.webhooks[i].id === wanted)) {
            show(data.webhooks[i]);
            return;
          }
        }
      });
    }

    load();
    return {
      onTopic: function (topic, data) {
        if (topic === 'webhooks') show(data);
      },
      destroy: function () { destroyed = true; }
    };
  }

  var DEFS = [
    {
      id: 'control.volume', title: 'Volume',
      sizes: { min: { w: 2, h: 1 }, max: { w: 4, h: 3 }, default: { w: 3, h: 2 } },
      topics: [], actions: ['volume.up', 'volume.down', 'volume.mute'], render: renderVolume
    },
    {
      id: 'control.mic', title: 'Microphone',
      sizes: { min: { w: 1, h: 1 }, max: { w: 4, h: 3 }, default: { w: 2, h: 1 } },
      topics: [], actions: ['mic.toggle'], render: renderMic
    },
    {
      id: 'control.media', title: 'Media keys',
      sizes: { min: { w: 2, h: 1 }, max: { w: 6, h: 2 }, default: { w: 3, h: 1 } },
      topics: [], actions: ['media.previous', 'media.play_pause', 'media.next'], render: renderMedia
    },
    {
      id: 'control.macros', title: 'Macros',
      sizes: { min: { w: 2, h: 2 }, max: { w: 6, h: 6 }, default: { w: 3, h: 3 } },
      topics: [], actions: ['macro.run'], render: renderMacros
    },
    {
      id: 'control.dock', title: 'Dock',
      sizes: { min: { w: 3, h: 2 }, max: { w: 12, h: 6 }, default: { w: 6, h: 3 } },
      topics: [], actions: ['shortcut.run', 'app.activate'], render: renderDock
    },
    {
      id: 'control.webhook', title: 'Webhook value',
      sizes: { min: { w: 2, h: 1 }, max: { w: 6, h: 3 }, default: { w: 2, h: 2 } },
      topics: ['webhooks'], actions: [], render: renderWebhook
    }
  ];

  function registerAll(registry) {
    kit.registerAll(registry, DEFS);
  }

  var api = {
    registerAll: registerAll,
    DEFS: DEFS,
    volumeLabel: volumeLabel,
    micLabel: micLabel,
    pinnedShortcuts: pinnedShortcuts,
    appList: appList,
    macroList: macroList
  };

  root.PanelWidgetsControl = api;
  kit.autoRegister(root, DEFS);
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
