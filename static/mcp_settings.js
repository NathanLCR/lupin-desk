/**
 * External MCP servers settings (/static/mcp_settings.js -> window.DeskMcpSettings)
 * Pure helpers plus mount(), which renders the Settings section for external tool servers.
 * Plain ES5 style so it runs on old WebViews. Every server-supplied string is escaped.
 */
(function (global) {
  'use strict';

  var RISK_OPTIONS = ['read', 'write', 'external'];
  var RISK_TEXT = {
    read: 'Read: runs without asking',
    write: 'Write: asks first',
    external: 'External: asks first',
  };

  function escapeHtml(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Split on whitespace into argv. Used for stdio commands; never passed to a shell.
  function parseCommand(text) {
    return String(text || '')
      .split(/\s+/)
      .filter(function (part) { return part.length > 0; });
  }

  // KEY=VALUE per line. Blank lines are skipped. The value keeps any further '='.
  function parseEnvLines(text) {
    var env = {};
    String(text || '').split(/\r?\n/).forEach(function (raw) {
      var line = raw.trim();
      if (!line) return;
      var at = line.indexOf('=');
      var key = at > 0 ? line.slice(0, at).trim() : '';
      if (!key) throw new Error('Each environment line must look like KEY=VALUE.');
      env[key] = line.slice(at + 1).trim();
    });
    return env;
  }

  // "Name: value" per line, for HTTP headers.
  function parseHeaderLines(text) {
    var headers = {};
    String(text || '').split(/\r?\n/).forEach(function (raw) {
      var line = raw.trim();
      if (!line) return;
      var colon = line.indexOf(':');
      var name = colon > 0 ? line.slice(0, colon).trim() : '';
      if (!name) throw new Error('Each header line must look like Name: value.');
      headers[name] = line.slice(colon + 1).trim();
    });
    return headers;
  }

  function riskLabel(risk) {
    return Object.prototype.hasOwnProperty.call(RISK_TEXT, risk) ? RISK_TEXT[risk] : RISK_TEXT.external;
  }

  // Builds the POST body for a new server from plain form values. Only the fields
  // that apply to the chosen transport are included.
  function buildAddPayload(form) {
    var f = form || {};
    var payload = {
      id: String(f.id || '').trim(),
      name: String(f.name || '').trim(),
      transport: f.transport === 'http' ? 'http' : 'stdio',
    };
    if (payload.transport === 'http') {
      payload.url = String(f.url || '').trim();
      payload.headers = parseHeaderLines(f.headers);
    } else {
      payload.command = parseCommand(f.command);
      payload.env = parseEnvLines(f.env);
    }
    return payload;
  }

  function defaultFetchJson(url, options) {
    var opts = options || {};
    var init = { method: opts.method || 'GET', headers: {} };
    if (init.method !== 'GET') init.headers['Content-Type'] = 'application/json';
    if (opts.body !== undefined) init.body = JSON.stringify(opts.body);
    return global.fetch(url, init).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok) {
          var detail = data && typeof data.detail === 'string' ? data.detail : 'Request failed.';
          throw new Error(detail);
        }
        return data;
      });
    });
  }

  function renderServer(server, canEdit) {
    var target = server.transport === 'http'
      ? 'URL: ' + escapeHtml(server.url)
      : 'Command: ' + escapeHtml((server.command || []).join(' '));
    var envKeys = (server.env_keys || []).length
      ? '<p class="diag-hint">Environment keys: ' + escapeHtml(server.env_keys.join(', ')) + '</p>'
      : '';
    var headerNames = (server.header_names || []).length
      ? '<p class="diag-hint">Header names: ' + escapeHtml(server.header_names.join(', ')) + '</p>'
      : '';
    var id = escapeHtml(server.id);

    var toolRows = (server.tools || []).map(function (tool) {
      var risk = RISK_OPTIONS.indexOf(tool.risk) >= 0 ? tool.risk : 'external';
      var options = RISK_OPTIONS.map(function (level) {
        return '<option value="' + level + '"' + (level === risk ? ' selected' : '') + '>' +
          escapeHtml(level) + '</option>';
      }).join('');
      var riskControl = canEdit
        ? '<select data-mcp-risk data-server="' + id + '" data-tool="' + escapeHtml(tool.name) + '">' +
          options + '</select>'
        : '<span class="diag-pill">' + escapeHtml(risk) + '</span>';
      return '<li class="mcp-tool">' +
        '<strong>' + escapeHtml(tool.name) + '</strong> ' +
        '<small>' + escapeHtml(riskLabel(risk)) + '</small> ' + riskControl +
        (tool.description ? '<p class="diag-hint">' + escapeHtml(tool.description) + '</p>' : '') +
        '</li>';
    }).join('');

    var actions = '';
    if (canEdit) {
      actions =
        '<label><input type="checkbox" data-mcp-enabled data-server="' + id + '"' +
        (server.enabled ? ' checked' : '') + '> Enabled</label> ' +
        '<button type="button" data-mcp-refresh data-server="' + id + '">Refresh tools</button> ' +
        '<button type="button" data-mcp-remove data-server="' + id + '">Remove</button>';
    }

    return '<article class="mcp-server" data-server-card="' + id + '">' +
      '<h3>' + escapeHtml(server.name) + ' <small>(' + id + ', ' + escapeHtml(server.transport) + ')</small></h3>' +
      '<p class="diag-hint">' + target + '</p>' + envKeys + headerNames +
      '<div class="mcp-actions">' + actions + '</div>' +
      (toolRows ? '<ul class="mcp-tools">' + toolRows + '</ul>' :
        '<p class="diag-hint">No tools yet. Refresh to discover them.</p>') +
      '</article>';
  }

  function renderAddForm() {
    return '<form class="mcp-add" data-mcp-add>' +
      '<label>Id <input name="id" autocomplete="off" placeholder="github"></label>' +
      '<label>Name <input name="name" autocomplete="off" placeholder="GitHub"></label>' +
      '<label>Transport <select name="transport" data-mcp-transport>' +
      '<option value="stdio">Local command (stdio)</option>' +
      '<option value="http">Remote URL (http)</option></select></label>' +
      '<div data-mcp-stdio-fields>' +
      '<label>Command <input name="command" autocomplete="off" placeholder="npx -y some-mcp-server"></label>' +
      '<label>Environment (KEY=VALUE per line) <textarea name="env" rows="3" autocomplete="off"></textarea></label>' +
      '</div>' +
      '<div data-mcp-http-fields hidden>' +
      '<label>URL <input name="url" autocomplete="off" placeholder="https://example.com/mcp"></label>' +
      '<label>Headers (Name: value per line) <textarea name="headers" rows="3" autocomplete="off"></textarea></label>' +
      '</div>' +
      '<button type="submit">Add server</button>' +
      '</form>';
  }

  function mount(containerEl, options) {
    if (!containerEl) return null;
    var opts = options || {};
    var fetchJson = typeof opts.fetchJson === 'function' ? opts.fetchJson : defaultFetchJson;
    var state = { servers: [], canEdit: false };
    var status = null;

    function setStatus(message, isError) {
      if (!status) return;
      status.textContent = message || '';
      status.className = 'diag-hint' + (isError ? ' mcp-error' : '');
    }

    function render() {
      var body = state.servers.length
        ? state.servers.map(function (s) { return renderServer(s, state.canEdit); }).join('')
        : '<p class="diag-hint">No external servers yet.</p>';
      var note = state.canEdit
        ? ''
        : '<p class="diag-hint">Configure external servers on the Mac.</p>';
      containerEl.innerHTML =
        '<section class="panel-card mcp-settings">' +
        '<div class="panel-head"><h2>External tools (MCP)</h2></div>' +
        '<p class="diag-hint">Tools from external servers run only when you allow them. ' +
        'Read tools run without asking; write and external tools ask first.</p>' +
        note +
        '<div data-mcp-list>' + body + '</div>' +
        (state.canEdit ? renderAddForm() : '') +
        '<p data-mcp-status class="diag-hint" role="status"></p>' +
        '</section>';
      status = containerEl.querySelector('[data-mcp-status]');
      syncTransport();
    }

    function syncTransport() {
      var form = containerEl.querySelector('[data-mcp-add]');
      if (!form) return;
      var isHttp = form.elements.transport.value === 'http';
      containerEl.querySelector('[data-mcp-stdio-fields]').hidden = isHttp;
      containerEl.querySelector('[data-mcp-http-fields]').hidden = !isHttp;
    }

    function load() {
      return fetchJson('/api/mcp/servers').then(function (data) {
        state.servers = Array.isArray(data.servers) ? data.servers : [];
        state.canEdit = Boolean(data.can_edit);
        render();
      }).catch(function (err) {
        setStatus(err && err.message ? err.message : 'Could not load external servers.', true);
      });
    }

    function run(promise, okMessage) {
      return promise.then(function () {
        setStatus(okMessage, false);
        return load();
      }).catch(function (err) {
        setStatus(err && err.message ? err.message : 'Something went wrong.', true);
      });
    }

    containerEl.addEventListener('click', function (event) {
      var target = event.target;
      var refreshBtn = target.closest ? target.closest('[data-mcp-refresh]') : null;
      var removeBtn = target.closest ? target.closest('[data-mcp-remove]') : null;
      if (refreshBtn) {
        var id = refreshBtn.getAttribute('data-server');
        run(fetchJson('/api/mcp/servers/' + encodeURIComponent(id) + '/refresh', { method: 'POST' }),
          'Tools refreshed.');
      } else if (removeBtn) {
        var removeId = removeBtn.getAttribute('data-server');
        if (global.confirm('Remove the server ' + removeId + '?')) {
          run(fetchJson('/api/mcp/servers/' + encodeURIComponent(removeId), { method: 'DELETE' }),
            'Server removed.');
        }
      }
    });

    containerEl.addEventListener('change', function (event) {
      var target = event.target;
      if (target.hasAttribute('data-mcp-enabled')) {
        var id = target.getAttribute('data-server');
        run(fetchJson('/api/mcp/servers/' + encodeURIComponent(id), {
          method: 'PATCH',
          body: { enabled: target.checked },
        }), 'Saved.');
      } else if (target.hasAttribute('data-mcp-risk')) {
        var serverId = target.getAttribute('data-server');
        var tool = target.getAttribute('data-tool');
        run(fetchJson('/api/mcp/servers/' + encodeURIComponent(serverId) + '/tools/' +
          encodeURIComponent(tool) + '/risk', { method: 'PUT', body: { risk: target.value } }),
          'Risk saved.');
      } else if (target.name === 'transport') {
        syncTransport();
      }
    });

    containerEl.addEventListener('submit', function (event) {
      var form = event.target;
      if (!form.hasAttribute || !form.hasAttribute('data-mcp-add')) return;
      event.preventDefault();
      var values = {};
      Array.prototype.forEach.call(form.elements, function (el) {
        if (el.name) values[el.name] = el.value;
      });
      var payload;
      try {
        payload = buildAddPayload(values);
      } catch (err) {
        setStatus(err.message, true);
        return;
      }
      // Credentials were sent in the payload: clear the fields so they are not left in the DOM.
      if (form.elements.env) form.elements.env.value = '';
      if (form.elements.headers) form.elements.headers.value = '';
      run(fetchJson('/api/mcp/servers', { method: 'POST', body: payload }), 'Server added.');
    });

    render();
    load();
    return { reload: load };
  }

  var api = {
    escapeHtml: escapeHtml,
    parseCommand: parseCommand,
    parseEnvLines: parseEnvLines,
    parseHeaderLines: parseHeaderLines,
    riskLabel: riskLabel,
    buildAddPayload: buildAddPayload,
    mount: mount,
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  if (typeof window !== 'undefined') {
    window.DeskMcpSettings = api;
  }
})(typeof window !== 'undefined' ? window : globalThis);
