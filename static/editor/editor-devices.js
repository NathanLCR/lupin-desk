(function (root) {
  'use strict';

  // Devices list and Credentials form for the Mac layout editor.
  // The DOM is built with createElement and textContent only.
  // A credential value lives only in the password input being typed in: it is
  // cleared after a successful save, and it is never rendered, stored or logged.

  var REFRESH_MS = 5000;
  var CREDENTIALS_NOTE = 'Stored in .env on this Mac. Never sent to devices.';
  var ROLE_ERROR = 'A device needs at least one role: Body or Panel.';

  function pad(n) {
    return n < 10 ? '0' + n : String(n);
  }

  // Local date and time of last_seen. Same local day as `now` shows "Today HH:MM".
  function formatLastSeen(iso, now) {
    if (typeof iso !== 'string' || iso.trim() === '') return 'never';
    var seen = new Date(iso);
    if (isNaN(seen.getTime())) return 'unknown';
    var current = (now === undefined || now === null) ? new Date() : new Date(now);
    var time = pad(seen.getHours()) + ':' + pad(seen.getMinutes());
    var sameDay = seen.getFullYear() === current.getFullYear() &&
      seen.getMonth() === current.getMonth() &&
      seen.getDate() === current.getDate();
    if (sameDay) return 'Today ' + time;
    return seen.getFullYear() + '-' + pad(seen.getMonth() + 1) + '-' + pad(seen.getDate()) + ' ' + time;
  }

  function hasRole(device, role) {
    return !!device && Array.isArray(device.roles) && device.roles.indexOf(role) !== -1;
  }

  function priorityOf(device) {
    var value = device && device.body_priority;
    return typeof value === 'number' && isFinite(value) ? value : Infinity;
  }

  // Body devices, highest priority first (body_priority ascending). Nulls go last.
  // Ties keep their input order. Never mutates the input.
  function orderBodyDevices(devices) {
    if (!Array.isArray(devices)) return [];
    return devices
      .map(function (device, index) { return { device: device, index: index }; })
      .filter(function (entry) { return hasRole(entry.device, 'body'); })
      .sort(function (a, b) {
        var pa = priorityOf(a.device);
        var pb = priorityOf(b.device);
        if (pa !== pb) return pa < pb ? -1 : 1;
        return a.index - b.index;
      })
      .map(function (entry) { return entry.device; });
  }

  // New array with `id` moved by `delta` places, clamped to the list. Unknown id: copy.
  function moveId(ids, id, delta) {
    var list = Array.isArray(ids) ? ids.slice() : [];
    var from = list.indexOf(id);
    if (from === -1 || !delta) return list;
    var to = Math.max(0, Math.min(list.length - 1, from + delta));
    list.splice(from, 1);
    list.splice(to, 0, id);
    return list;
  }

  function make(doc, tag, options, children) {
    var node = doc.createElement(tag);
    var opts = options || {};
    if (opts.className) node.className = opts.className;
    if (opts.text !== undefined) node.textContent = String(opts.text);
    if (opts.attrs) {
      Object.keys(opts.attrs).forEach(function (name) {
        node.setAttribute(name, opts.attrs[name]);
      });
    }
    if (opts.props) {
      Object.keys(opts.props).forEach(function (name) {
        node[name] = opts.props[name];
      });
    }
    if (opts.on) {
      Object.keys(opts.on).forEach(function (type) {
        node.addEventListener(type, opts.on[type]);
      });
    }
    (children || []).forEach(function (child) {
      if (child) node.appendChild(child);
    });
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function isWithin(container, node) {
    var current = node;
    while (current) {
      if (current === container) return true;
      current = current.parentNode;
    }
    return false;
  }

  function errorText(err) {
    return err && typeof err.message === 'string' && err.message ? err.message : 'Something went wrong.';
  }

  function mount(containerEl, options) {
    var opts = options || {};
    var api = opts.api;
    if (!api) throw new Error('EditorDevices.mount needs an api.');
    var onLayoutsChanged = typeof opts.onLayoutsChanged === 'function' ? opts.onLayoutsChanged : function () {};
    var doc = containerEl.ownerDocument || document;

    var state = { devices: [], layouts: [], credentials: [], destroyed: false, pending: {} };
    var credInputs = {};
    var dragId = null;

    // Devices section

    var deviceError = make(doc, 'p', { className: 'editor-error', attrs: { role: 'alert' } });
    var deviceList = make(doc, 'ul', { className: 'device-list' });
    var priorityList = make(doc, 'ol', { className: 'body-priority' });
    var deviceSection = make(doc, 'section', { className: 'editor-section devices', attrs: { 'aria-label': 'Devices' } }, [
      make(doc, 'h2', { text: 'Devices' }),
      deviceError,
      deviceList,
      make(doc, 'h3', { text: 'Body priority' }),
      make(doc, 'p', { className: 'editor-hint', text: 'The first Body has the highest priority. Drag to reorder, or use the buttons.' }),
      priorityList
    ]);

    // Credentials section

    var credError = make(doc, 'p', { className: 'editor-error', attrs: { role: 'alert' } });
    var credList = make(doc, 'ul', { className: 'credential-list' });
    var credSection = make(doc, 'section', { className: 'editor-section credentials', attrs: { 'aria-label': 'Credentials' } }, [
      make(doc, 'h2', { text: 'Credentials' }),
      credError,
      credList,
      make(doc, 'p', { className: 'editor-hint', text: CREDENTIALS_NOTE })
    ]);

    containerEl.appendChild(deviceSection);
    containerEl.appendChild(credSection);

    function setError(node, err) {
      node.textContent = errorText(err);
    }

    function clearError(node) {
      node.textContent = '';
    }

    function visibleDevices() {
      return state.devices.filter(function (device) {
        return device && device.kind !== 'editor';
      });
    }

    function findDevice(id) {
      for (var i = 0; i < state.devices.length; i += 1) {
        if (state.devices[i] && state.devices[i].id === id) return state.devices[i];
      }
      return null;
    }

    function replaceDevice(updated) {
      if (!updated || typeof updated !== 'object' || !updated.id) return;
      state.devices = state.devices.map(function (device) {
        return device && device.id === updated.id ? Object.assign({}, device, updated) : device;
      });
    }

    function bodyIds() {
      return orderBodyDevices(visibleDevices()).map(function (device) { return device.id; });
    }

    function appendOption(select, value, label) {
      select.appendChild(make(doc, 'option', { text: label, props: { value: value } }));
    }

    function layoutSelect(device, onChange) {
      var select = make(doc, 'select', {
        attrs: { 'aria-label': 'Layout for ' + (device.name || device.id) },
        on: { change: onChange }
      });
      appendOption(select, '', '(none)');
      var current = device.layout_id || '';
      var known = false;
      state.layouts.forEach(function (layout) {
        if (!layout || !layout.id) return;
        if (layout.id === current) known = true;
        appendOption(select, layout.id, layout.name || layout.id);
      });
      if (current && !known) appendOption(select, current, 'Missing layout (' + current + ')');
      select.value = current;
      return select;
    }

    function deviceRow(device) {
      var nameInput = make(doc, 'input', {
        className: 'device-name',
        attrs: { type: 'text', 'aria-label': 'Device name' },
        props: { value: device.name || '' },
        on: { change: commitName, blur: commitName }
      });

      function commitName() {
        var current = findDevice(device.id) || device;
        var next = nameInput.value.trim();
        if (next === (current.name || '')) return;
        if (next === '') {
          setError(deviceError, new Error('Name cannot be empty.'));
          nameInput.value = current.name || '';
          return;
        }
        sendUpdate(current.id, { name: next });
      }

      function onRoleChange() {
        var current = findDevice(device.id) || device;
        var roles = [];
        if (bodyBox.checked) roles.push('body');
        if (panelBox.checked) roles.push('panel');
        if (roles.length === 0) {
          setError(deviceError, new Error(ROLE_ERROR));
          renderDevices(true);
          return;
        }
        sendUpdate(current.id, { roles: roles });
      }

      var bodyBox = make(doc, 'input', {
        attrs: { type: 'checkbox' },
        props: { checked: hasRole(device, 'body') },
        on: { change: onRoleChange }
      });
      var panelBox = make(doc, 'input', {
        attrs: { type: 'checkbox' },
        props: { checked: hasRole(device, 'panel') },
        on: { change: onRoleChange }
      });

      var select = layoutSelect(device, function () {
        var current = findDevice(device.id) || device;
        sendUpdate(current.id, { layout_id: select.value === '' ? null : select.value }, onLayoutsChanged);
      });

      var head = make(doc, 'div', { className: 'device-head' }, [
        nameInput,
        make(doc, 'span', { className: 'dot ' + (device.connected ? 'connected' : 'offline'), attrs: { 'aria-hidden': 'true' } }),
        make(doc, 'span', { className: 'device-status', text: device.connected ? 'Connected' : 'Offline' })
      ]);
      if (device.active) head.appendChild(make(doc, 'span', { className: 'badge', text: 'Active Body' }));

      var meta = make(doc, 'div', { className: 'device-meta' }, [
        make(doc, 'span', { className: 'device-seen', text: 'Last seen: ' + formatLastSeen(device.last_seen) })
      ]);
      if (device.screen && device.screen.width && device.screen.height) {
        meta.appendChild(make(doc, 'span', { className: 'device-screen', text: device.screen.width + 'x' + device.screen.height }));
      }

      var roles = make(doc, 'div', { className: 'device-roles' }, [
        make(doc, 'label', null, [bodyBox, make(doc, 'span', { text: 'Body' })]),
        make(doc, 'label', null, [panelBox, make(doc, 'span', { text: 'Panel' })])
      ]);

      var layout = make(doc, 'label', { className: 'device-layout' }, [
        make(doc, 'span', { text: 'Layout' }),
        select
      ]);

      return make(doc, 'li', { className: 'device-row' }, [head, meta, roles, layout]);
    }

    function priorityRow(device, index, count) {
      var name = device.name || device.id;

      function reorderFrom(fromIndex, toIndex) {
        var ids = bodyIds();
        return reorderBody(ids[fromIndex], toIndex - fromIndex);
      }

      var up = make(doc, 'button', {
        text: 'Up',
        attrs: { type: 'button', 'aria-label': 'Move ' + name + ' up' },
        props: { disabled: index === 0 },
        on: { click: function () { reorderFrom(index, index - 1); } }
      });
      var down = make(doc, 'button', {
        text: 'Down',
        attrs: { type: 'button', 'aria-label': 'Move ' + name + ' down' },
        props: { disabled: index === count - 1 },
        on: { click: function () { reorderFrom(index, index + 1); } }
      });

      return make(doc, 'li', {
        className: 'priority-row',
        props: { draggable: true },
        on: {
          dragstart: function (ev) {
            dragId = device.id;
            if (ev && ev.dataTransfer) {
              ev.dataTransfer.effectAllowed = 'move';
              ev.dataTransfer.setData('text/plain', device.id);
            }
          },
          dragover: function (ev) {
            if (dragId === null) return;
            if (ev.preventDefault) ev.preventDefault();
            if (ev.dataTransfer) ev.dataTransfer.dropEffect = 'move';
          },
          drop: function (ev) {
            if (ev.preventDefault) ev.preventDefault();
            var fromId = dragId;
            dragId = null;
            if (fromId === null || fromId === device.id) return;
            var ids = bodyIds();
            reorderBody(fromId, ids.indexOf(device.id) - ids.indexOf(fromId));
          },
          dragend: function () { dragId = null; }
        }
      }, [
        make(doc, 'span', { className: 'grip', text: '::', attrs: { 'aria-hidden': 'true' } }),
        make(doc, 'span', { className: 'priority-name', text: name }),
        up,
        down
      ]);
    }

    function renderPriority() {
      clear(priorityList);
      var ordered = orderBodyDevices(visibleDevices());
      if (ordered.length === 0) {
        priorityList.appendChild(make(doc, 'li', { className: 'empty', text: 'No Body devices.' }));
        return;
      }
      ordered.forEach(function (device, index) {
        priorityList.appendChild(priorityRow(device, index, ordered.length));
      });
    }

    // Skips the redraw while focus is inside the section, unless `force` is set.
    function renderDevices(force) {
      if (state.destroyed) return;
      if (!force && isWithin(deviceSection, doc.activeElement)) return;
      clear(deviceList);
      visibleDevices().forEach(function (device) {
        deviceList.appendChild(deviceRow(device));
      });
      if (deviceList.firstChild === null) {
        deviceList.appendChild(make(doc, 'li', { className: 'empty', text: 'No devices yet.' }));
      }
      renderPriority();
    }

    function sendUpdate(id, fields, onDone) {
      var key = id + ':' + Object.keys(fields).join(',');
      if (state.pending[key]) return Promise.resolve();
      state.pending[key] = true;
      return api.updateDevice(id, fields).then(function (updated) {
        delete state.pending[key];
        if (state.destroyed) return;
        replaceDevice(updated);
        clearError(deviceError);
        renderDevices(true);
        if (onDone) onDone();
      }, function (err) {
        delete state.pending[key];
        if (state.destroyed) return;
        setError(deviceError, err);
        renderDevices(true);
      });
    }

    function reorderBody(id, delta) {
      if (!id) return Promise.resolve();
      var ids = bodyIds();
      var next = moveId(ids, id, delta);
      if (JSON.stringify(next) === JSON.stringify(ids)) return Promise.resolve();
      if (state.pending.priority) return Promise.resolve();
      state.pending.priority = true;
      return api.setPriority(next).then(function (response) {
        delete state.pending.priority;
        if (state.destroyed) return;
        if (response && Array.isArray(response.devices)) state.devices = response.devices;
        clearError(deviceError);
        renderDevices(true);
      }, function (err) {
        delete state.pending.priority;
        if (state.destroyed) return;
        setError(deviceError, err);
        renderDevices(true);
      });
    }

    function loadDevices(fromTimer) {
      if (state.destroyed) return Promise.resolve();
      if (fromTimer && state.pending.load) return Promise.resolve();
      state.pending.load = true;
      return api.listDevices().then(function (response) {
        delete state.pending.load;
        if (state.destroyed) return;
        state.devices = response && Array.isArray(response.devices) ? response.devices : [];
        if (!fromTimer) clearError(deviceError);
        renderDevices(!fromTimer);
      }, function (err) {
        delete state.pending.load;
        if (state.destroyed) return;
        setError(deviceError, err);
      });
    }

    // Credentials section

    function credentialRow(cred, draft) {
      var label = cred.label || cred.key;
      var status = cred.set ? (cred.preview ? 'Set (' + cred.preview + ')' : 'Set') : 'Not set';

      var input = make(doc, 'input', {
        className: 'credential-input',
        attrs: {
          type: 'password',
          placeholder: 'Enter new value',
          autocomplete: 'off',
          'aria-label': 'New value for ' + label
        },
        props: { value: draft }
      });
      credInputs[cred.key] = input;

      var save = make(doc, 'button', {
        text: 'Save',
        attrs: { type: 'button' },
        on: { click: function () { saveCredential(cred, input); } }
      });
      var clearButton = make(doc, 'button', {
        text: 'Clear',
        attrs: { type: 'button' },
        on: { click: function () { sendCredentials(cred.key, '', input); } }
      });

      return make(doc, 'li', { className: 'credential-row' }, [
        make(doc, 'span', { className: 'credential-label', text: label }),
        make(doc, 'span', { className: 'credential-status', text: status }),
        input,
        save,
        clearButton
      ]);
    }

    function renderCredentials() {
      if (state.destroyed) return;
      // Carry typed drafts of the other rows across the redraw (they stay in inputs only).
      var drafts = {};
      Object.keys(credInputs).forEach(function (key) { drafts[key] = credInputs[key].value; });
      credInputs = {};
      clear(credList);
      state.credentials.forEach(function (cred) {
        credList.appendChild(credentialRow(cred, drafts[cred.key] || ''));
      });
      if (credList.firstChild === null) {
        credList.appendChild(make(doc, 'li', { className: 'empty', text: 'No credentials.' }));
      }
    }

    function saveCredential(cred, input) {
      if (String(input.value || '').trim() === '') {
        setError(credError, new Error('Type a new value first, or use Clear to remove the stored one.'));
        return Promise.resolve();
      }
      return sendCredentials(cred.key, input.value, input);
    }

    function sendCredentials(key, value, input) {
      var pendingKey = 'credential:' + key;
      if (state.pending[pendingKey]) return Promise.resolve();
      state.pending[pendingKey] = true;
      var values = {};
      values[key] = value;
      return api.saveCredentials(values).then(function (response) {
        delete state.pending[pendingKey];
        input.value = '';
        if (state.destroyed) return;
        state.credentials = response && Array.isArray(response.credentials) ? response.credentials : [];
        clearError(credError);
        renderCredentials();
      }, function (err) {
        delete state.pending[pendingKey];
        if (state.destroyed) return;
        setError(credError, err);
      });
    }

    function loadCredentials() {
      return api.getCredentials().then(function (response) {
        if (state.destroyed) return;
        state.credentials = response && Array.isArray(response.credentials) ? response.credentials : [];
        clearError(credError);
        renderCredentials();
      }, function (err) {
        if (state.destroyed) return;
        setError(credError, err);
      });
    }

    // Public handle

    function refresh(layouts) {
      var list = Array.isArray(layouts) ? layouts : (layouts && Array.isArray(layouts.layouts) ? layouts.layouts : null);
      if (list) state.layouts = list;
      return loadDevices(false);
    }

    function destroy() {
      if (state.destroyed) return;
      state.destroyed = true;
      clearInterval(timer);
      credInputs = {};
      clear(containerEl);
    }

    var timer = setInterval(function () { loadDevices(true); }, REFRESH_MS);

    loadDevices(false);
    loadCredentials();

    return { refresh: refresh, destroy: destroy };
  }

  var api = {
    mount: mount,
    formatLastSeen: formatLastSeen,
    orderBodyDevices: orderBodyDevices,
    moveId: moveId
  };

  root.EditorDevices = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
