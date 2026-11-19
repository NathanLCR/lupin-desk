/**
 * Mac monitoring Panel widgets: CPU, memory, disks, network and top processes.
 * They follow the `monitor` topic (about one message per second while a Panel is subscribed).
 * Registers through PanelKit.registerAll on the shared registry. ES5 for old WebViews.
 * Process names come from the Mac: text is only ever set with textContent, never innerHTML.
 */
(function (root) {
  'use strict';

  var PanelKit = typeof module !== 'undefined' && module.exports
    ? require('./widget-kit.js')
    : root.PanelKit;

  var TOPIC = 'monitor';
  var HISTORY = 30;

  function isRecord(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
  }

  function num(value) {
    return typeof value === 'number' && isFinite(value) ? value : null;
  }

  function clampPercent(value) {
    var n = num(value);
    if (n === null) return 0;
    return Math.max(0, Math.min(100, n));
  }

  function formatPercent(value) {
    var n = num(value);
    return n === null ? '--' : Math.round(n) + '%';
  }

  function formatBytes(value) {
    var n = num(value);
    if (n === null || n < 0) return '--';
    var units = ['B', 'KB', 'MB', 'GB', 'TB'];
    var i = 0;
    while (n >= 1024 && i < units.length - 1) {
      n = n / 1024;
      i += 1;
    }
    var text = i === 0 || n >= 100 ? String(Math.round(n)) : String(Math.round(n * 10) / 10);
    return text + ' ' + units[i];
  }

  function formatRate(value) {
    var n = num(value);
    return n === null ? '--' : formatBytes(n) + '/s';
  }

  function formatPing(value) {
    var n = num(value);
    return n === null ? 'offline' : Math.round(n) + ' ms';
  }

  // Appends value to a history array and keeps the newest HISTORY entries.
  function pushHistory(history, value) {
    history.push(clampPercent(value));
    while (history.length > HISTORY) history.shift();
    return history;
  }

  function make(doc, tag, className, text) {
    return PanelKit.el(doc, tag, className, text);
  }

  function emptyNode(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function bar(doc, percent) {
    var track = make(doc, 'div', 'pn-mon-bar');
    var fill = make(doc, 'div', 'pn-mon-fill');
    fill.style.width = clampPercent(percent) + '%';
    track.appendChild(fill);
    return track;
  }

  function spark(doc, history) {
    var wrap = make(doc, 'div', 'pn-mon-spark');
    for (var i = 0; i < history.length; i++) {
      var col = make(doc, 'div', 'pn-mon-col');
      col.style.height = Math.max(2, history[i]) + '%';
      wrap.appendChild(col);
    }
    return wrap;
  }

  function line(doc, label, value) {
    var row = make(doc, 'div', 'pn-mon-line');
    row.appendChild(make(doc, 'span', 'pn-mon-label', label));
    row.appendChild(make(doc, 'span', 'pn-mon-value', value));
    return row;
  }

  // Shared tile body. paint(box, data, state) fills the body from one `monitor` message.
  function mount(el, spec) {
    var doc = el.ownerDocument;
    var box = make(doc, 'div', 'pn-monitor ' + spec.className);
    var body = make(doc, 'div', 'pn-mon-body');
    var status = make(doc, 'div', 'pn-mon-status', 'Waiting for the Mac...');
    box.appendChild(status);
    box.appendChild(body);
    el.appendChild(box);

    var live = true;
    var state = { history: [] };

    return {
      onTopic: function (topic, data) {
        if (!live || topic !== TOPIC || !isRecord(data)) return;
        status.textContent = '';
        emptyNode(body);
        spec.paint(doc, body, data, state);
      },
      destroy: function () {
        live = false;
      }
    };
  }

  function paintCpu(doc, body, data, state) {
    var cpu = isRecord(data.cpu) ? data.cpu : {};
    pushHistory(state.history, cpu.percent);
    body.appendChild(make(doc, 'div', 'pn-mon-big', formatPercent(cpu.percent)));
    body.appendChild(bar(doc, cpu.percent));
    body.appendChild(spark(doc, state.history));
    if (num(cpu.cores) !== null && cpu.cores > 0) {
      body.appendChild(line(doc, 'Cores', String(cpu.cores)));
    }
  }

  function paintRam(doc, body, data, state) {
    var ram = isRecord(data.ram) ? data.ram : {};
    pushHistory(state.history, ram.percent);
    body.appendChild(make(doc, 'div', 'pn-mon-big', formatPercent(ram.percent)));
    body.appendChild(bar(doc, ram.percent));
    body.appendChild(spark(doc, state.history));
    body.appendChild(line(doc, 'Used', formatBytes(ram.used) + ' of ' + formatBytes(ram.total)));
  }

  function paintDisks(doc, body, data) {
    var disks = Array.isArray(data.disks) ? data.disks : [];
    if (!disks.length) {
      body.appendChild(make(doc, 'div', 'pn-mon-status', 'No disks found.'));
      return;
    }
    for (var i = 0; i < disks.length; i++) {
      var disk = disks[i];
      if (!isRecord(disk)) continue;
      var item = make(doc, 'div', 'pn-mon-disk');
      item.appendChild(line(doc, String(disk.mount || '?'), formatPercent(disk.percent)));
      item.appendChild(bar(doc, disk.percent));
      item.appendChild(make(doc, 'div', 'pn-mon-sub', formatBytes(disk.used) + ' of ' + formatBytes(disk.total)));
      body.appendChild(item);
    }
  }

  function paintNet(doc, body, data) {
    var net = isRecord(data.net) ? data.net : {};
    var ping = isRecord(data.ping) ? data.ping : {};
    body.appendChild(line(doc, 'Down', formatRate(net.down_bps)));
    body.appendChild(line(doc, 'Up', formatRate(net.up_bps)));
    body.appendChild(line(doc, 'Ping', formatPing(ping.ms)));
  }

  function paintProcesses(doc, body, data) {
    var rows = Array.isArray(data.processes) ? data.processes : [];
    if (!rows.length) {
      body.appendChild(make(doc, 'div', 'pn-mon-status', 'No processes yet.'));
      return;
    }
    var list = make(doc, 'ul', 'pn-mon-procs');
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      if (!isRecord(row)) continue;
      var item = make(doc, 'li', 'pn-mon-proc');
      item.appendChild(make(doc, 'span', 'pn-mon-proc-name', String(row.name || '?')));
      item.appendChild(make(doc, 'span', 'pn-mon-proc-cpu', formatPercent(row.cpu)));
      item.appendChild(make(doc, 'span', 'pn-mon-proc-mem', formatPercent(row.mem)));
      list.appendChild(item);
    }
    body.appendChild(list);
  }

  function def(id, title, className, sizes, paint) {
    var spec = { className: className, paint: paint };
    return {
      id: id,
      title: title,
      sizes: sizes,
      topics: [TOPIC],
      actions: [],
      render: function (el) { return mount(el, spec); }
    };
  }

  var DEFS = [
    def('mac-cpu', 'Mac CPU', 'pn-mon-cpu',
      { min: { w: 2, h: 2 }, max: { w: 6, h: 4 }, default: { w: 3, h: 2 } }, paintCpu),
    def('mac-memory', 'Mac memory', 'pn-mon-ram',
      { min: { w: 2, h: 2 }, max: { w: 6, h: 4 }, default: { w: 3, h: 2 } }, paintRam),
    def('mac-disks', 'Mac disks', 'pn-mon-disks',
      { min: { w: 2, h: 2 }, max: { w: 6, h: 6 }, default: { w: 3, h: 3 } }, paintDisks),
    def('mac-network', 'Mac network', 'pn-mon-net',
      { min: { w: 2, h: 2 }, max: { w: 6, h: 4 }, default: { w: 3, h: 2 } }, paintNet),
    def('mac-processes', 'Top processes', 'pn-mon-processes',
      { min: { w: 3, h: 3 }, max: { w: 6, h: 8 }, default: { w: 4, h: 4 } }, paintProcesses)
  ];

  function registerAll(registry) {
    PanelKit.registerAll(registry, DEFS);
  }

  var api = {
    registerAll: registerAll,
    DEFS: DEFS,
    TOPIC: TOPIC,
    HISTORY: HISTORY,
    formatBytes: formatBytes,
    formatRate: formatRate,
    formatPing: formatPing,
    formatPercent: formatPercent,
    pushHistory: pushHistory
  };

  root.PanelWidgetsMonitoring = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;

  PanelKit.autoRegister(root, DEFS);
})(typeof window !== 'undefined' ? window : this);
