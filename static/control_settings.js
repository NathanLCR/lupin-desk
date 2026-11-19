/**
 * Control Deck settings (/static/control_settings.js -> window.DeskControlSettings)
 * Mac-only section for macros, webhooks and rules. Talks to /api/control/*.
 * Everything from the server (names, apps, paths) is shown with textContent, never innerHTML.
 */
(function (global) {
  'use strict';

  var MAX_STEPS = 10;
  var MAX_DELAY_MS = 2000;
  var MAX_TOTAL_DELAY_MS = 10000;

  // The only actions a macro step may use (mirrors MACRO_ACTIONS on the Brain, which re-checks).
  var STEP_ACTIONS = [
    { id: 'volume.up', label: 'Volume up' },
    { id: 'volume.down', label: 'Volume down' },
    { id: 'volume.mute', label: 'Mute / unmute sound' },
    { id: 'mic.toggle', label: 'Mute / unmute microphone' },
    { id: 'media.play_pause', label: 'Play / pause' },
    { id: 'media.next', label: 'Next track' },
    { id: 'media.previous', label: 'Previous track' },
    { id: 'shortcut.run', label: 'Run a Shortcut' }
  ];

  function actionLabel(id) {
    for (var i = 0; i < STEP_ACTIONS.length; i++) {
      if (STEP_ACTIONS[i].id === id) return STEP_ACTIONS[i].label;
    }
    return String(id);
  }

  // Clean steps for the API, or throws an Error with a plain message. rows: [{action, slug, delay}]
  function buildSteps(rows) {
    if (!rows.length) throw new Error('Add at least one step.');
    if (rows.length > MAX_STEPS) throw new Error('A macro has at most ' + MAX_STEPS + ' steps.');
    var total = 0;
    var steps = [];
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var step = { action: row.action, delay_ms: 0 };
      if (row.action === 'shortcut.run') {
        if (!row.slug) throw new Error('Step ' + (i + 1) + ': pick a Shortcut.');
        step.args = { slug: row.slug };
      }
      var delay = Number(row.delay === '' || row.delay === undefined ? 0 : row.delay);
      if (!isFinite(delay) || delay < 0 || delay > MAX_DELAY_MS || Math.floor(delay) !== delay) {
        throw new Error('Step ' + (i + 1) + ': delay must be 0 to ' + MAX_DELAY_MS + ' ms.');
      }
      step.delay_ms = delay;
      total += delay;
      steps.push(step);
    }
    if (total > MAX_TOTAL_DELAY_MS) throw new Error('Delays add up to at most 10 seconds.');
    return steps;
  }

  function stepsSummary(steps) {
    return (steps || []).map(function (s) {
      var text = actionLabel(s.action);
      if (s.args && s.args.slug) text += ' (' + s.args.slug + ')';
      if (s.delay_ms) text += ' +' + s.delay_ms + ' ms';
      return text;
    }).join(' > ');
  }

  function ruleSummary(rule, pageTitle) {
    var when = rule.trigger === 'app_front' ? 'When ' + rule.match + ' is in front' : 'When Signal ' + rule.match + ' arrives';
    return when + ', show ' + (pageTitle || rule.page_id) + (rule.enabled ? '' : ' (off)');
  }

  function hookUrl(origin, path) {
    return typeof path === 'string' && path ? String(origin || '') + path : '';
  }

  function defaultFetchJson(url, options) {
    var opts = options || {};
    var init = { method: opts.method || 'GET', headers: {} };
    if (init.method !== 'GET') init.headers['Content-Type'] = 'application/json';
    if (opts.body !== undefined) init.body = JSON.stringify(opts.body);
    return global.fetch(url, init).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok) {
          throw new Error(data && typeof data.detail === 'string' ? data.detail : 'Request failed.');
        }
        return data;
      });
    });
  }

  function mount(root, options) {
    var opts = options || {};
    var doc = opts.doc || global.document;
    var fetchJson = opts.fetchJson || defaultFetchJson;
    var confirmFn = opts.confirm || function (text) { return global.confirm(text); };
    var origin = opts.origin !== undefined ? opts.origin : (global.location ? global.location.origin : '');

    var data = { isMac: false, macros: [], hooks: [], rules: [], pages: [], shortcuts: [] };
    var draft = null;       // macro being edited: {id|null, name, rows}
    var ruleDraft = null;   // rule being edited: {id|null}
    var message = '';

    function el(tag, className, text) {
      var node = doc.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined && text !== null) node.textContent = String(text);
      return node;
    }

    function button(label, onClick) {
      var b = el('button', '', label);
      b.type = 'button';
      b.addEventListener('click', onClick);
      return b;
    }

    function option(value, label) {
      var o = el('option', '', label);
      o.value = value;
      return o;
    }

    function field(label, control) {
      var wrap = el('label', 'control-field');
      wrap.appendChild(el('span', '', label + ' '));
      wrap.appendChild(control);
      return wrap;
    }

    function fail(error) {
      message = error && error.message ? error.message : 'Something went wrong.';
      render();
    }

    function call(url, method, body) {
      return fetchJson(url, { method: method, body: body });
    }

    function pageTitle(id) {
      for (var i = 0; i < data.pages.length; i++) if (data.pages[i].id === id) return data.pages[i].title || id;
      return id;
    }

    // ------------------------------------------------------------ macros

    function syncRows() {
      if (!draft) return;
      draft.name = draft.nameInput ? draft.nameInput.value : draft.name;
      draft.rows.forEach(function (row) {
        if (row.actionSel) row.action = row.actionSel.value;
        if (row.slugSel) row.slug = row.slugSel.value;
        if (row.delayInput) row.delay = row.delayInput.value;
      });
    }

    function startMacro(macro) {
      message = '';
      draft = { id: macro ? macro.id : null, name: macro ? macro.name : '', rows: [] };
      if (macro) {
        macro.steps.forEach(function (s) {
          draft.rows.push({ action: s.action, slug: s.args && s.args.slug || '', delay: String(s.delay_ms || 0) });
        });
      } else {
        draft.rows.push({ action: STEP_ACTIONS[0].id, slug: '', delay: '0' });
      }
      render();
    }

    function saveMacro() {
      syncRows();
      var name = String(draft.name || '').trim();
      var steps;
      try {
        if (!name) throw new Error('Give the macro a name.');
        steps = buildSteps(draft.rows);
      } catch (e) { fail(e); return; }
      var id = draft.id;
      var req = id === null ? call('/api/control/macros', 'POST', { name: name, steps: steps })
        : call('/api/control/macros/' + id, 'PATCH', { name: name, steps: steps });
      req.then(function () { draft = null; message = 'Macro saved.'; return load(); }).catch(fail);
    }

    function renderMacroEditor(parent) {
      var box = el('div', 'control-editor');
      draft.nameInput = el('input');
      draft.nameInput.value = draft.name;
      draft.nameInput.setAttribute('placeholder', 'Macro name');
      box.appendChild(field('Name', draft.nameInput));
      box.appendChild(el('p', 'diag-hint', 'Up to ' + MAX_STEPS + ' steps. Each delay is 0 to ' + MAX_DELAY_MS +
        ' ms, and delays add up to at most 10 seconds. It runs with one tap and never asks first.'));
      draft.rows.forEach(function (row, index) {
        var line = el('div', 'control-step');
        line.appendChild(el('span', '', (index + 1) + '.'));
        row.actionSel = el('select');
        STEP_ACTIONS.forEach(function (a) { row.actionSel.appendChild(option(a.id, a.label)); });
        row.actionSel.value = row.action;
        row.actionSel.addEventListener('change', function () { syncRows(); render(); });
        line.appendChild(row.actionSel);
        row.slugSel = null;
        if (row.action === 'shortcut.run') {
          row.slugSel = el('select');
          row.slugSel.appendChild(option('', 'Pick a Shortcut'));
          data.shortcuts.forEach(function (s) { row.slugSel.appendChild(option(s.slug, s.title || s.slug)); });
          row.slugSel.value = row.slug;
          line.appendChild(row.slugSel);
        }
        row.delayInput = el('input');
        row.delayInput.setAttribute('type', 'number');
        row.delayInput.setAttribute('min', '0');
        row.delayInput.setAttribute('max', String(MAX_DELAY_MS));
        row.delayInput.value = row.delay;
        line.appendChild(field('Delay after (ms)', row.delayInput));
        line.appendChild(button('Remove step', function () {
          syncRows();
          draft.rows.splice(index, 1);
          render();
        }));
        box.appendChild(line);
      });
      var add = button('Add step', function () {
        syncRows();
        draft.rows.push({ action: STEP_ACTIONS[0].id, slug: '', delay: '0' });
        render();
      });
      if (draft.rows.length >= MAX_STEPS) add.disabled = true;
      box.appendChild(add);
      box.appendChild(button('Save macro', saveMacro));
      box.appendChild(button('Cancel', function () { draft = null; message = ''; render(); }));
      parent.appendChild(box);
    }

    function renderMacros(parent) {
      var sec = el('section', 'control-section');
      sec.appendChild(el('h3', '', 'Macros'));
      if (!data.macros.length) sec.appendChild(el('p', 'diag-hint', 'No macros yet.'));
      data.macros.forEach(function (macro) {
        var row = el('div', 'control-row');
        row.appendChild(el('strong', '', macro.name));
        row.appendChild(el('span', 'diag-hint', ' ' + stepsSummary(macro.steps)));
        row.appendChild(button('Edit', function () { startMacro(macro); }));
        row.appendChild(button('Delete', function () {
          if (!confirmFn('Delete the macro "' + macro.name + '"?')) return;
          call('/api/control/macros/' + macro.id, 'DELETE').then(function () { message = 'Macro deleted.'; return load(); }).catch(fail);
        }));
        sec.appendChild(row);
      });
      if (draft) renderMacroEditor(sec);
      else sec.appendChild(button('New macro', function () { startMacro(null); }));
      parent.appendChild(sec);
    }

    // ---------------------------------------------------------- webhooks

    var hookName = null;
    var hookSignal = null;

    function renderHooks(parent) {
      var sec = el('section', 'control-section');
      sec.appendChild(el('h3', '', 'Webhooks'));
      sec.appendChild(el('p', 'diag-hint',
        'A device on your network can POST JSON {"value": ...} to the URL. Anyone with the URL can post, so keep it private.'));
      if (!data.hooks.length) sec.appendChild(el('p', 'diag-hint', 'No webhooks yet.'));
      data.hooks.forEach(function (hook) {
        var row = el('div', 'control-row');
        row.appendChild(el('strong', '', hook.name));
        if (hook.emit_signal) row.appendChild(el('span', 'diag-hint', ' Signal: webhook.' + hook.id));
        var url = hookUrl(origin, hook.path);
        if (url) row.appendChild(el('code', 'control-url', url));
        row.appendChild(button('Rotate secret', function () {
          if (!confirmFn('Rotate the secret of "' + hook.name + '"? The old URL stops working.')) return;
          call('/api/control/webhooks/' + hook.id + '/rotate', 'POST').then(function () { message = 'Secret rotated.'; return load(); }).catch(fail);
        }));
        row.appendChild(button('Delete', function () {
          if (!confirmFn('Delete the webhook "' + hook.name + '"?')) return;
          call('/api/control/webhooks/' + hook.id, 'DELETE').then(function () { message = 'Webhook deleted.'; return load(); }).catch(fail);
        }));
        sec.appendChild(row);
      });
      hookName = el('input');
      hookName.setAttribute('placeholder', 'Webhook name');
      hookSignal = el('input');
      hookSignal.setAttribute('type', 'checkbox');
      hookSignal.checked = true;
      var form = el('div', 'control-editor');
      form.appendChild(field('Name', hookName));
      form.appendChild(field('Also emit a Signal', hookSignal));
      form.appendChild(button('Create webhook', function () {
        var name = String(hookName.value || '').trim();
        if (!name) { fail(new Error('Give the webhook a name.')); return; }
        call('/api/control/webhooks', 'POST', { name: name, emit_signal: !!hookSignal.checked })
          .then(function () { message = 'Webhook created.'; return load(); }).catch(fail);
      }));
      sec.appendChild(form);
      parent.appendChild(sec);
    }

    // ------------------------------------------------------------- rules

    function renderRuleEditor(parent) {
      var existing = null;
      data.rules.forEach(function (r) { if (r.id === ruleDraft.id) existing = r; });
      var trigger = el('select');
      trigger.appendChild(option('app_front', 'App in front'));
      trigger.appendChild(option('signal', 'Signal received'));
      trigger.value = existing ? existing.trigger : 'app_front';
      var match = el('input');
      match.setAttribute('placeholder', 'App name, or Signal kind such as timer_done');
      match.value = existing ? existing.match : '';
      var page = data.pages.length ? el('select') : el('input');
      if (data.pages.length) {
        data.pages.forEach(function (p) { page.appendChild(option(p.id, p.title || p.id)); });
      } else {
        page.setAttribute('placeholder', 'Page id');
      }
      page.value = existing ? existing.page_id : (data.pages.length ? data.pages[0].id : '');
      var box = el('div', 'control-editor');
      box.appendChild(field('When', trigger));
      box.appendChild(field('Match', match));
      box.appendChild(field('Show page', page));
      box.appendChild(el('p', 'diag-hint', 'Only the name of the front app is compared. It is not saved or logged and nothing is sent to the AI.'));
      box.appendChild(button('Save rule', function () {
        var body = { trigger: trigger.value, match: String(match.value || '').trim(), page_id: String(page.value || '').trim() };
        if (!body.match || !body.page_id) { fail(new Error('Fill in the match and the page.')); return; }
        var req = ruleDraft.id === null ? call('/api/control/rules', 'POST', body)
          : call('/api/control/rules/' + ruleDraft.id, 'PATCH', body);
        req.then(function () { ruleDraft = null; message = 'Rule saved.'; return load(); }).catch(fail);
      }));
      box.appendChild(button('Cancel', function () { ruleDraft = null; render(); }));
      parent.appendChild(box);
    }

    function renderRules(parent) {
      var sec = el('section', 'control-section');
      sec.appendChild(el('h3', '', 'Rules'));
      if (!data.rules.length) sec.appendChild(el('p', 'diag-hint', 'No rules yet.'));
      data.rules.forEach(function (rule) {
        var row = el('div', 'control-row');
        row.appendChild(el('span', '', ruleSummary(rule, pageTitle(rule.page_id))));
        row.appendChild(button(rule.enabled ? 'Turn off' : 'Turn on', function () {
          call('/api/control/rules/' + rule.id, 'PATCH', { enabled: !rule.enabled }).then(load).catch(fail);
        }));
        row.appendChild(button('Edit', function () { ruleDraft = { id: rule.id }; render(); }));
        row.appendChild(button('Delete', function () {
          if (!confirmFn('Delete this rule?')) return;
          call('/api/control/rules/' + rule.id, 'DELETE').then(function () { message = 'Rule deleted.'; return load(); }).catch(fail);
        }));
        sec.appendChild(row);
      });
      if (ruleDraft) renderRuleEditor(sec);
      else sec.appendChild(button('New rule', function () { ruleDraft = { id: null }; render(); }));
      parent.appendChild(sec);
    }

    // ------------------------------------------------------------ render

    function render() {
      root.textContent = '';
      var wrap = el('div', 'control-settings');
      wrap.appendChild(el('h2', '', 'Control Deck'));
      if (!data.isMac) {
        wrap.appendChild(el('p', 'diag-hint', 'Control Deck settings can only be changed on the Mac.'));
      } else {
        renderMacros(wrap);
        renderHooks(wrap);
        renderRules(wrap);
      }
      if (message) wrap.appendChild(el('p', 'diag-hint control-message', message));
      root.appendChild(wrap);
    }

    function load() {
      return call('/api/client-info', 'GET').then(function (info) {
        data.isMac = !!(info && info.is_mac);
        if (!data.isMac) { render(); return null; }
        return Promise.all([
          call('/api/control/macros', 'GET'),
          call('/api/control/webhooks', 'GET'),
          call('/api/control/rules', 'GET'),
          call('/api/layouts/default', 'GET').catch(function () { return {}; }),
          call('/api/shortcuts', 'GET').catch(function () { return {}; })
        ]).then(function (r) {
          data.macros = r[0].macros || [];
          data.hooks = r[1].webhooks || [];
          data.rules = r[2].rules || [];
          data.pages = (r[3].pages || []).map(function (p) { return { id: p.id, title: p.title }; });
          data.shortcuts = (r[4].shortcuts || []).filter(function (s) {
            return s && typeof s.slug === 'string' && !s.requires_confirmation && s.action_type !== 'agent_prompt';
          });
          render();
        });
      }).catch(fail);
    }

    render();
    load();
    return { reload: load };
  }

  var api = {
    STEP_ACTIONS: STEP_ACTIONS,
    MAX_STEPS: MAX_STEPS,
    buildSteps: buildSteps,
    stepsSummary: stepsSummary,
    ruleSummary: ruleSummary,
    hookUrl: hookUrl,
    mount: mount
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.DeskControlSettings = api;
})(typeof window !== 'undefined' ? window : globalThis);
