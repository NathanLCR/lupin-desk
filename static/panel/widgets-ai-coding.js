/**
 * AI coding Panel widgets: Claude Code / Codex sessions, quotas, GitHub and permission prompts.
 * Sessions, quotas and GitHub follow the `ai-coding` topic (and load /api/ai-coding/snapshot once).
 * Prompts follow `ai-coding-prompts` and answer with the `ai_coding_answer` action.
 * Registers through PanelKit.registerAll on the shared registry. ES5 for old WebViews.
 * Everything shown comes from the Mac: text is only ever set with textContent, never innerHTML.
 */
(function (root) {
  'use strict';

  var PanelKit = typeof module !== 'undefined' && module.exports
    ? require('./widget-kit.js')
    : root.PanelKit;

  var TOPIC = 'ai-coding';
  var PROMPTS_TOPIC = 'ai-coding-prompts';
  var SNAPSHOT_URL = '/api/ai-coding/snapshot';
  var ANSWER_ACTION = 'ai_coding_answer';
  var SHOWN_ACTION = 'ai_coding_prompt_shown';

  function isRecord(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
  }

  function num(value) {
    return typeof value === 'number' && isFinite(value) ? value : null;
  }

  function list(value) {
    return Array.isArray(value) ? value : [];
  }

  function make(doc, tag, className, text) {
    return PanelKit.el(doc, tag, className, text);
  }

  function emptyNode(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function formatTokens(value) {
    var n = num(value);
    if (n === null || n < 0) return '--';
    if (n >= 1000000) return (Math.round(n / 100000) / 10) + 'M';
    if (n >= 1000) return (Math.round(n / 100) / 10) + 'k';
    return String(Math.round(n));
  }

  function formatDuration(seconds) {
    var s = num(seconds);
    if (s === null || s < 0) return '--';
    var minutes = Math.floor(s / 60);
    if (minutes < 60) return minutes + ' min';
    return Math.floor(minutes / 60) + ' h ' + (minutes % 60) + ' min';
  }

  // "in 2 h 5 min" for a reset time given as epoch seconds.
  function formatReset(resetsAt, nowMs) {
    var at = num(resetsAt);
    if (at === null) return '--';
    var seconds = at - nowMs / 1000;
    if (seconds <= 0) return 'now';
    return 'in ' + formatDuration(seconds);
  }

  function clampPercent(value) {
    var n = num(value);
    return n === null ? 0 : Math.max(0, Math.min(100, n));
  }

  function bar(doc, percent) {
    var track = make(doc, 'div', 'pn-ai-bar');
    var fill = make(doc, 'div', 'pn-ai-fill');
    fill.style.width = clampPercent(percent) + '%';
    track.appendChild(fill);
    return track;
  }

  // Shared tile for the three snapshot widgets. paint(doc, body, snapshot, ctx).
  function mountSnapshot(el, ctx, className, paint) {
    var doc = el.ownerDocument;
    var box = make(doc, 'div', 'pn-ai ' + className);
    var status = make(doc, 'div', 'pn-ai-status', 'Waiting for the Mac...');
    var body = make(doc, 'div', 'pn-ai-body');
    box.appendChild(status);
    box.appendChild(body);
    el.appendChild(box);
    var live = true;
    var got = false;

    function show(data) {
      if (!live || !isRecord(data)) return;
      got = true;
      status.textContent = '';
      emptyNode(body);
      paint(doc, body, data, ctx);
    }

    PanelKit.getJson(SNAPSHOT_URL, function (error, data) {
      if (error) {
        if (live && !got) status.textContent = 'Could not reach the Mac.';
        return;
      }
      if (!got) show(data);
    });

    return {
      onTopic: function (topic, data) {
        if (topic === TOPIC) show(data);
      },
      destroy: function () { live = false; }
    };
  }

  function paintSessions(doc, body, data) {
    var sessions = list(data.sessions);
    if (!sessions.length) {
      body.appendChild(make(doc, 'div', 'pn-ai-status', 'No sessions in the last 7 days.'));
      return;
    }
    var ul = make(doc, 'ul', 'pn-ai-list');
    for (var i = 0; i < sessions.length; i++) {
      var s = sessions[i];
      if (!isRecord(s)) continue;
      var item = make(doc, 'li', 'pn-ai-session pn-ai-' + String(s.status || 'ended'));
      var head = make(doc, 'div', 'pn-ai-row');
      head.appendChild(make(doc, 'span', 'pn-ai-project', String(s.project || '?')));
      head.appendChild(make(doc, 'span', 'pn-ai-state', String(s.status || '')));
      item.appendChild(head);
      var tool = s.tool === 'codex' ? 'Codex' : 'Claude';
      item.appendChild(make(doc, 'div', 'pn-ai-sub',
        tool + ' ' + String(s.model || '') + ' - ' + formatDuration(s.duration_seconds) +
        ' - ' + formatTokens(s.tokens) + ' tokens'));
      ul.appendChild(item);
    }
    body.appendChild(ul);
  }

  function paintDaily(doc, body, label, days) {
    var rows = list(days);
    var max = 0;
    var i;
    for (i = 0; i < rows.length; i++) {
      if (isRecord(rows[i]) && num(rows[i].tokens) > max) max = rows[i].tokens;
    }
    body.appendChild(make(doc, 'div', 'pn-ai-sub', label + ': tokens per day'));
    for (i = 0; i < rows.length; i++) {
      if (!isRecord(rows[i])) continue;
      var line = make(doc, 'div', 'pn-ai-row');
      line.appendChild(make(doc, 'span', 'pn-ai-label', String(rows[i].day || '').slice(5)));
      line.appendChild(bar(doc, max ? (num(rows[i].tokens) || 0) * 100 / max : 0));
      line.appendChild(make(doc, 'span', 'pn-ai-value', formatTokens(rows[i].tokens)));
      body.appendChild(line);
    }
  }

  function paintQuotas(doc, body, data, ctx) {
    var quotas = isRecord(data.quotas) ? data.quotas : {};
    var nowMs = ctx && typeof ctx.now === 'function' ? ctx.now() : new Date().getTime();
    var codex = isRecord(quotas.codex) ? quotas.codex : {};
    var limits = list(codex.limits);
    var i;
    for (i = 0; i < limits.length; i++) {
      var limit = limits[i];
      if (!isRecord(limit)) continue;
      var hours = num(limit.window_minutes) ? Math.round(limit.window_minutes / 60) : null;
      var title = 'Codex ' + (hours === null ? '' : (hours >= 48 ? Math.round(hours / 24) + ' day' : hours + ' h') + ' ') + 'limit';
      body.appendChild(make(doc, 'div', 'pn-ai-sub', title));
      body.appendChild(make(doc, 'div', 'pn-ai-big', Math.round(clampPercent(limit.used_percent)) + '% used'));
      body.appendChild(bar(doc, limit.used_percent));
      body.appendChild(make(doc, 'div', 'pn-ai-sub', 'Resets ' + formatReset(limit.resets_at, nowMs)));
      var f = isRecord(limit.forecast) ? limit.forecast : null;
      if (f) {
        var text = 'At this pace: ' + Math.round(num(f.projected_percent_at_reset) || 0) + '% at reset';
        if (num(f.exhausted_in_minutes) !== null) text += ', runs out in ' + formatDuration(f.exhausted_in_minutes * 60);
        body.appendChild(make(doc, 'div', 'pn-ai-forecast', text));
      }
    }
    var claude = isRecord(quotas.claude) ? quotas.claude : {};
    paintDaily(doc, body, 'Claude Code', claude.daily_tokens);
    if (!limits.length) {
      paintDaily(doc, body, 'Codex', codex.daily_tokens);
      body.appendChild(make(doc, 'div', 'pn-ai-sub', 'No limits shown: the CLIs do not expose them here.'));
    }
  }

  function paintGithub(doc, body, data) {
    var gh = isRecord(data.github) ? data.github : {};
    if (gh.available === false) {
      body.appendChild(make(doc, 'div', 'pn-ai-status', 'GitHub: run "gh auth login" on the Mac.'));
      return;
    }
    var repos = list(gh.repos);
    if (!repos.length) {
      body.appendChild(make(doc, 'div', 'pn-ai-status', 'No repos from recent sessions.'));
      return;
    }
    for (var i = 0; i < repos.length; i++) {
      var repo = repos[i];
      if (!isRecord(repo)) continue;
      var card = make(doc, 'div', 'pn-ai-repo');
      card.appendChild(make(doc, 'div', 'pn-ai-project', String(repo.repo || '?')));
      var ci = isRecord(repo.ci) ? repo.ci : null;
      if (ci) {
        var verdict = ci.conclusion || ci.status || 'unknown';
        card.appendChild(make(doc, 'div', 'pn-ai-sub pn-ai-ci-' + String(verdict),
          'CI ' + String(verdict) + ' on ' + String(ci.branch || '?')));
      }
      var reviews = list(repo.reviews);
      for (var j = 0; j < reviews.length; j++) {
        if (isRecord(reviews[j])) {
          card.appendChild(make(doc, 'div', 'pn-ai-review', 'Review #' + String(reviews[j].number) + ' ' + String(reviews[j].title || '')));
        }
      }
      if (!reviews.length) card.appendChild(make(doc, 'div', 'pn-ai-sub', 'No review requests.'));
      body.appendChild(card);
    }
  }

  // Permission prompts. The tool and its full command are shown on screen only.
  function mountPrompts(el, ctx) {
    var doc = el.ownerDocument;
    var box = make(doc, 'div', 'pn-ai pn-ai-prompts');
    var status = make(doc, 'div', 'pn-ai-status', 'No permission prompts waiting.');
    var body = make(doc, 'div', 'pn-ai-body');
    box.appendChild(status);
    box.appendChild(body);
    el.appendChild(box);
    var live = true;
    var shown = {}; // prompt ids this tile has told the Brain it shows

    function pageVisible() {
      return doc.visibilityState !== 'hidden';
    }

    function tell(id, visible) {
      if (ctx && typeof ctx.sendAction === 'function') ctx.sendAction(SHOWN_ACTION, { id: id, visible: visible });
    }

    // The Brain accepts Allow only from a tile that acked the prompt while its page is visible.
    function syncAcks(ids) {
      var id;
      for (id in shown) {
        if (Object.prototype.hasOwnProperty.call(shown, id) && (!pageVisible() || ids.indexOf(id) < 0)) {
          tell(id, false);
          delete shown[id];
        }
      }
      if (!pageVisible()) return;
      // Ack on every update: a reconnect starts a new server-side connection with no acks.
      for (var i = 0; i < ids.length; i++) {
        shown[ids[i]] = true;
        tell(ids[i], true);
      }
    }

    var lastIds = [];
    function onVisibility() {
      if (live) syncAcks(lastIds);
    }
    if (typeof doc.addEventListener === 'function') doc.addEventListener('visibilitychange', onVisibility);

    function answer(id, decision) {
      if (ctx && typeof ctx.sendAction === 'function') ctx.sendAction(ANSWER_ACTION, { id: id, decision: decision });
    }

    function button(label, className, id, decision) {
      var b = make(doc, 'button', 'pn-ai-btn ' + className, label);
      b.type = 'button';
      b.addEventListener('click', function () { answer(id, decision); });
      return b;
    }

    return {
      onTopic: function (topic, data) {
        if (!live || topic !== PROMPTS_TOPIC || !isRecord(data)) return;
        var prompts = list(data.prompts);
        var ids = [];
        emptyNode(body);
        status.textContent = prompts.length ? 'Claude needs you' : 'No permission prompts waiting.';
        for (var i = 0; i < prompts.length; i++) {
          var p = prompts[i];
          if (!isRecord(p) || typeof p.id !== 'string') continue;
          var card = make(doc, 'div', 'pn-ai-prompt');
          card.appendChild(make(doc, 'div', 'pn-ai-sub', String(p.project || '') + ' wants to use'));
          card.appendChild(make(doc, 'div', 'pn-ai-tool', String(p.tool || 'tool') + ': ' + String(p.args || '')));
          var actions = make(doc, 'div', 'pn-ai-actions');
          actions.appendChild(button('Allow', 'pn-ai-allow', p.id, 'allow'));
          actions.appendChild(button('Deny', 'pn-ai-deny', p.id, 'deny'));
          card.appendChild(actions);
          body.appendChild(card);
          ids.push(p.id);
        }
        lastIds = ids;
        syncAcks(ids);
      },
      destroy: function () {
        if (live) {
          for (var id in shown) {
            if (Object.prototype.hasOwnProperty.call(shown, id)) tell(id, false);
          }
          shown = {};
          if (typeof doc.removeEventListener === 'function') doc.removeEventListener('visibilitychange', onVisibility);
        }
        live = false;
      }
    };
  }

  function snapshotDef(id, title, className, sizes, paint) {
    return {
      id: id,
      title: title,
      sizes: sizes,
      topics: [TOPIC],
      actions: [],
      render: function (el, ctx) { return mountSnapshot(el, ctx, className, paint); }
    };
  }

  var DEFS = [
    snapshotDef('ai-sessions', 'AI coding sessions', 'pn-ai-sessions',
      { min: { w: 3, h: 2 }, max: { w: 8, h: 8 }, default: { w: 4, h: 4 } }, paintSessions),
    snapshotDef('ai-quotas', 'AI quotas', 'pn-ai-quotas',
      { min: { w: 3, h: 3 }, max: { w: 6, h: 8 }, default: { w: 3, h: 4 } }, paintQuotas),
    snapshotDef('ai-github', 'GitHub reviews and CI', 'pn-ai-github',
      { min: { w: 3, h: 2 }, max: { w: 8, h: 8 }, default: { w: 4, h: 3 } }, paintGithub),
    {
      id: 'ai-permissions',
      title: 'Claude permission prompts',
      sizes: { min: { w: 3, h: 2 }, max: { w: 8, h: 6 }, default: { w: 4, h: 3 } },
      topics: [PROMPTS_TOPIC],
      actions: [ANSWER_ACTION, SHOWN_ACTION],
      render: mountPrompts
    }
  ];

  function registerAll(registry) {
    PanelKit.registerAll(registry, DEFS);
  }

  var api = {
    registerAll: registerAll,
    DEFS: DEFS,
    TOPIC: TOPIC,
    PROMPTS_TOPIC: PROMPTS_TOPIC,
    formatTokens: formatTokens,
    formatDuration: formatDuration,
    formatReset: formatReset
  };

  root.PanelWidgetsAiCoding = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;

  PanelKit.autoRegister(root, DEFS);
})(typeof window !== 'undefined' ? window : this);
