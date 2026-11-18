/**
 * Everyday Panel widgets: Checklist, Notes and Habits.
 * Registers through PanelKit.registerAll on the shared registry. ES5 for old WebViews.
 * Titles and notes are user data: text is only ever set with textContent, never innerHTML.
 */
(function (root) {
  'use strict';

  var PanelKit = typeof module !== 'undefined' && module.exports
    ? require('./widget-kit.js')
    : root.PanelKit;

  function isRecord(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
  }

  function hasId(item) {
    if (!isRecord(item)) return false;
    if (typeof item.id === 'string') return item.id !== '';
    return typeof item.id === 'number' && isFinite(item.id);
  }

  // Returns the list of items under key (or the array itself) as an array of records with an id.
  // Whatever comes in, the result is an array.
  function normalizeList(data, key) {
    var list = [];
    if (Array.isArray(data)) {
      list = data;
    } else if (isRecord(data) && Array.isArray(data[key])) {
      list = data[key];
    }
    var out = [];
    for (var i = 0; i < list.length; i++) {
      if (hasId(list[i])) out.push(list[i]);
    }
    return out;
  }

  function isDone(item) {
    return !!item.done;
  }

  // Open tasks first, done tasks after. Each group keeps the order it arrived in.
  function orderTasks(tasks) {
    var list = normalizeList(tasks, 'tasks');
    var open = [];
    var done = [];
    for (var i = 0; i < list.length; i++) {
      if (isDone(list[i])) done.push(list[i]);
      else open.push(list[i]);
    }
    return open.concat(done);
  }

  function timeOf(value) {
    if (typeof value === 'number') return isFinite(value) ? value : 0;
    if (typeof value === 'string') {
      var parsed = Date.parse(value);
      return isNaN(parsed) ? 0 : parsed;
    }
    return 0;
  }

  // Newest first. Notes without a usable created_at keep their order at the end.
  function orderNotes(notes) {
    var list = normalizeList(notes, 'notes');
    var decorated = [];
    for (var i = 0; i < list.length; i++) {
      decorated.push({ note: list[i], time: timeOf(list[i].created_at), index: i });
    }
    decorated.sort(function (a, b) {
      if (a.time !== b.time) return b.time - a.time;
      return a.index - b.index;
    });
    return decorated.map(function (entry) { return entry.note; });
  }

  function make(doc, tag, className, text) {
    return PanelKit.el(doc, tag, className, text);
  }

  function emptyNode(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function sendTo(ctx, actionId, args) {
    if (ctx && typeof ctx.sendAction === 'function') ctx.sendAction(actionId, args);
  }

  function removeButton(doc, label, onClick) {
    var button = make(doc, 'button', 'pn-remove', '×');
    button.type = 'button';
    button.setAttribute('aria-label', label);
    button.addEventListener('click', onClick);
    return button;
  }

  // Text input plus an Add button. Enter and the button both submit trimmed, non-empty text.
  function addForm(doc, add, submit) {
    var wrap = make(doc, 'div', 'pn-add');
    var input = make(doc, 'input', 'pn-input');
    input.type = 'text';
    input.setAttribute('placeholder', add.placeholder);
    var button = make(doc, 'button', 'pn-add-btn', add.label);
    button.type = 'button';

    function go() {
      var raw = input.value === undefined || input.value === null ? '' : String(input.value);
      input.value = '';
      var text = raw.trim();
      if (text) submit(text);
    }

    button.addEventListener('click', go);
    input.addEventListener('keydown', function (event) {
      if (event && (event.key === 'Enter' || event.keyCode === 13)) go();
    });
    wrap.appendChild(input);
    wrap.appendChild(button);
    return wrap;
  }

  function renderTask(doc, task, send) {
    var done = isDone(task);
    var item = make(doc, 'li', done ? 'pn-task pn-done' : 'pn-task');
    var row = make(doc, 'button', 'pn-check-row');
    row.type = 'button';
    row.setAttribute('role', 'button');
    row.appendChild(make(doc, 'span', 'pn-box', done ? '[x]' : '[ ]'));
    row.appendChild(make(doc, 'span', 'pn-task-title', task.title));
    row.addEventListener('click', function () {
      send('tasks.toggle', { id: task.id });
    });
    item.appendChild(row);
    item.appendChild(removeButton(doc, 'Remove task', function () {
      send('tasks.remove', { id: task.id });
    }));
    return item;
  }

  function renderNote(doc, note, send) {
    var item = make(doc, 'li', 'pn-note');
    item.appendChild(make(doc, 'span', 'pn-note-text', note.text));
    item.appendChild(removeButton(doc, 'Remove note', function () {
      send('notes.remove', { id: note.id });
    }));
    return item;
  }

  function renderHabit(doc, habit, send) {
    var done = !!habit.done_today;
    var item = make(doc, 'li', done ? 'pn-habit pn-done' : 'pn-habit');
    var info = make(doc, 'div', 'pn-habit-info');
    info.appendChild(make(doc, 'span', 'pn-habit-name', habit.name));
    var streak = typeof habit.streak === 'number' && isFinite(habit.streak)
      ? Math.floor(habit.streak)
      : 0;
    if (streak > 0) {
      info.appendChild(make(doc, 'span', 'pn-habit-streak', streak + ' day streak'));
    }
    if (habit.time !== undefined && habit.time !== null && habit.time !== '') {
      info.appendChild(make(doc, 'span', 'pn-habit-time', habit.time));
    }
    item.appendChild(info);
    var check = make(doc, 'button', 'pn-check', done ? 'Done' : 'Check in');
    check.type = 'button';
    check.addEventListener('click', function () {
      send('habits.checkin', { id: habit.id, done: !done });
    });
    item.appendChild(check);
    return item;
  }

  // Shared tile body: GET once on mount, then follow the topic. The topic payload is the full truth,
  // so a GET answer that arrives after a topic update is ignored.
  function mountList(el, ctx, spec) {
    var doc = el.ownerDocument;
    var send = function (actionId, args) { sendTo(ctx, actionId, args); };
    var root = make(doc, 'div', 'pn-productivity ' + spec.className);
    var status = make(doc, 'div', 'pn-status');
    var list = make(doc, 'ul', 'pn-list');
    root.appendChild(status);
    root.appendChild(list);
    if (spec.add) {
      root.appendChild(addForm(doc, spec.add, function (text) {
        send(spec.add.action, spec.add.args(text));
      }));
    }
    el.appendChild(root);

    var live = true;
    var hasData = false;

    function paint(items) {
      emptyNode(list);
      status.textContent = items.length ? '' : spec.emptyText;
      for (var i = 0; i < items.length; i++) {
        list.appendChild(spec.renderItem(doc, items[i], send));
      }
    }

    function apply(data) {
      hasData = true;
      paint(spec.order(data));
    }

    PanelKit.getJson(spec.url, function (error, data) {
      if (!live || hasData) return;
      if (error) {
        status.textContent = spec.errorText;
        return;
      }
      apply(data);
    });

    return {
      onTopic: function (topic, data) {
        if (!live || topic !== spec.topic) return;
        apply(data);
      },
      destroy: function () {
        live = false;
      }
    };
  }

  function normalizeHabits(data) {
    return normalizeList(data, 'habits');
  }

  var CHECKLIST = {
    url: '/api/tasks?include_done=true',
    key: 'tasks',
    topic: 'tasks',
    className: 'pn-checklist',
    emptyText: 'No tasks yet.',
    errorText: 'Could not load tasks.',
    order: orderTasks,
    renderItem: renderTask,
    add: {
      placeholder: 'Add a task',
      label: 'Add',
      action: 'tasks.add',
      args: function (text) { return { title: text }; }
    }
  };

  var NOTES = {
    url: '/api/notes',
    key: 'notes',
    topic: 'notes',
    className: 'pn-notes',
    emptyText: 'No notes yet.',
    errorText: 'Could not load notes.',
    order: orderNotes,
    renderItem: renderNote,
    add: {
      placeholder: 'Write a note',
      label: 'Add',
      action: 'notes.add',
      args: function (text) { return { text: text }; }
    }
  };

  var HABITS = {
    url: '/api/habits',
    key: 'habits',
    topic: 'habits',
    className: 'pn-habits',
    emptyText: 'No habits yet.',
    errorText: 'Could not load habits.',
    order: normalizeHabits,
    renderItem: renderHabit,
    add: null
  };

  var DEFS = [
    {
      id: 'checklist',
      title: 'Checklist',
      sizes: {
        min: { w: 2, h: 2 },
        max: { w: 6, h: 8 },
        default: { w: 3, h: 4 }
      },
      topics: ['tasks'],
      actions: ['tasks.add', 'tasks.toggle', 'tasks.remove'],
      render: function (el, ctx) { return mountList(el, ctx, CHECKLIST); }
    },
    {
      id: 'notes',
      title: 'Notes',
      sizes: {
        min: { w: 2, h: 2 },
        max: { w: 6, h: 8 },
        default: { w: 3, h: 3 }
      },
      topics: ['notes'],
      actions: ['notes.add', 'notes.remove'],
      render: function (el, ctx) { return mountList(el, ctx, NOTES); }
    },
    {
      id: 'habits',
      title: 'Habits',
      sizes: {
        min: { w: 2, h: 2 },
        max: { w: 6, h: 8 },
        default: { w: 3, h: 3 }
      },
      topics: ['habits'],
      actions: ['habits.checkin'],
      render: function (el, ctx) { return mountList(el, ctx, HABITS); }
    }
  ];

  function registerAll(registry) {
    PanelKit.registerAll(registry, DEFS);
  }

  var api = {
    registerAll: registerAll,
    DEFS: DEFS,
    orderTasks: orderTasks,
    orderNotes: orderNotes,
    normalizeList: normalizeList
  };

  root.PanelWidgetsProductivity = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;

  PanelKit.autoRegister(root, DEFS);
})(typeof window !== 'undefined' ? window : this);
