/**
 * Claude Code hooks settings (/static/claude_hooks_settings.js -> window.DeskClaudeHooksSettings)
 * The Mac-only Settings section that adds or removes the three Claude Code hooks (permission
 * request, notification, stop) which let a Panel answer permission prompts. It shows exactly what
 * it adds before installing, and Remove restores Claude Code's settings. Every string is escaped.
 */
(function (global) {
  'use strict';

  var EVENT_LABELS = {
    PermissionRequest: 'Permission request: ask on a Panel before Claude Code asks you',
    Notification: 'Notification: Lupin tells you when a session waits for you',
    Stop: 'Stop: Lupin tells you when a session stops',
  };

  function escapeHtml(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // The commands Install would add, one block per event, as plain text.
  function describeAdds(adds) {
    var lines = [];
    Object.keys(adds || {}).forEach(function (event) {
      (adds[event] || []).forEach(function (entry) {
        (entry.hooks || []).forEach(function (hook) {
          lines.push(event + ' -> ' + hook.command);
        });
      });
    });
    return lines.join('\n');
  }

  function render(status, canEdit) {
    var installed = Boolean(status && status.installed);
    var events = Object.keys((status && status.adds) || {}).map(function (event) {
      return '<li>' + escapeHtml(EVENT_LABELS[event] || event) + '</li>';
    }).join('');
    var actions = canEdit
      ? '<button type="button" data-hooks-install' + (installed ? ' disabled' : '') + '>Install hooks</button> ' +
        '<button type="button" data-hooks-remove' + (installed ? '' : ' disabled') + '>Remove hooks</button>'
      : '<p class="diag-hint">Set this up on the Mac.</p>';
    return '<section class="panel-card claude-hooks-settings">' +
      '<div class="panel-head"><h2>Claude Code permission prompts</h2></div>' +
      '<p class="diag-hint">Opt in to answer Claude Code permission prompts from a Panel. ' +
      'This edits ' + escapeHtml(status && status.settings_file) + '. If nobody answers in 2 minutes, ' +
      'Claude Code asks you itself. Remove puts the file back as it was.</p>' +
      '<p data-hooks-state>' + (installed ? 'Installed.' : 'Not installed.') + '</p>' +
      '<ul>' + events + '</ul>' +
      '<details><summary>Show exactly what is added</summary><pre data-hooks-adds>' +
      escapeHtml(describeAdds(status && status.adds)) + '</pre></details>' +
      actions +
      '<p data-hooks-status class="diag-hint" role="status"></p>' +
      '</section>';
  }

  function defaultFetchJson(url, options) {
    var opts = options || {};
    var init = { method: opts.method || 'GET', headers: {} };
    if (init.method !== 'GET') init.headers['Content-Type'] = 'application/json';
    return global.fetch(url, init).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok) {
          throw new Error(data && typeof data.detail === 'string' ? data.detail : 'Request failed.');
        }
        return data;
      });
    });
  }

  function mount(containerEl, options) {
    if (!containerEl) return null;
    var opts = options || {};
    var fetchJson = typeof opts.fetchJson === 'function' ? opts.fetchJson : defaultFetchJson;
    var canEdit = true;

    function setStatus(message, isError) {
      var node = containerEl.querySelector('[data-hooks-status]');
      if (node) {
        node.textContent = message || '';
        node.className = 'diag-hint' + (isError ? ' mcp-error' : '');
      }
    }

    function load() {
      return fetchJson('/api/claude-hooks').then(function (status) {
        canEdit = true;
        containerEl.innerHTML = render(status, canEdit);
      }).catch(function (err) {
        // Off the Mac the route answers 403: show the section as read-only guidance.
        canEdit = false;
        containerEl.innerHTML = render({ installed: false, adds: {}, settings_file: '' }, canEdit);
        setStatus(err && err.message ? err.message : 'Could not load.', true);
      });
    }

    function change(route, okMessage) {
      return fetchJson('/api/claude-hooks/' + route, { method: 'POST' }).then(function () {
        return load().then(function () { setStatus(okMessage, false); });
      }).catch(function (err) {
        setStatus(err && err.message ? err.message : 'Something went wrong.', true);
      });
    }

    containerEl.addEventListener('click', function (event) {
      var target = event && event.target;
      if (!target || !target.hasAttribute) return;
      if (target.hasAttribute('data-hooks-install')) change('install', 'Hooks installed.');
      if (target.hasAttribute('data-hooks-remove')) change('remove', 'Hooks removed.');
    });

    return load();
  }

  var api = {
    escapeHtml: escapeHtml,
    describeAdds: describeAdds,
    render: render,
    mount: mount,
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  if (typeof window !== 'undefined') {
    window.DeskClaudeHooksSettings = api;
  }
})(typeof window !== 'undefined' ? window : globalThis);
