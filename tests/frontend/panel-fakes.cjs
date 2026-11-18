// Fake DOM, clock and network shared by Panel integration tests.

function findAll(node, pred, out) {
  const acc = out || [];
  if (pred(node)) acc.push(node);
  for (const child of node.children) findAll(child, pred, acc);
  return acc;
}

class FakeElement {
  constructor(tag, doc) {
    this.tagName = String(tag).toUpperCase();
    this.ownerDocument = doc;
    this.children = [];
    this.parentNode = null;
    this.style = {};
    this.id = '';
    this.textContent = '';
    this.clientWidth = 0;
    this.clientHeight = 0;
    this.attributes = {};
    this.listeners = {};
    this._classes = [];
    this.classList = {
      add: (...names) => {
        for (const name of names) if (!this._classes.includes(name)) this._classes.push(name);
      },
      remove: (...names) => {
        this._classes = this._classes.filter((c) => !names.includes(c));
      },
      contains: (name) => this._classes.includes(name),
    };
  }

  get className() {
    return this._classes.join(' ');
  }

  set className(value) {
    this._classes = String(value).split(/\s+/).filter(Boolean);
  }

  get firstChild() {
    return this.children[0] || null;
  }

  get lastChild() {
    return this.children[this.children.length - 1] || null;
  }

  appendChild(child) {
    if (child.parentNode) child.parentNode.removeChild(child);
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index < 0) throw new Error('not a child');
    this.children.splice(index, 1);
    child.parentNode = null;
    return child;
  }

  addEventListener(type, fn) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(fn);
  }

  fire(type, event) {
    for (const fn of this.listeners[type] || []) fn(event || {});
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  getBoundingClientRect() {
    return { left: 0, top: 0, width: this.clientWidth, height: this.clientHeight };
  }
}

function makeDocument() {
  const listeners = {};
  const doc = {
    visibilityState: 'visible',
    body: null,
    createElement(tag) {
      return new FakeElement(tag, doc);
    },
    getElementById(id) {
      return findAll(doc.body, (el) => el.id === id)[0] || null;
    },
    addEventListener(type, fn) {
      if (!listeners[type]) listeners[type] = [];
      listeners[type].push(fn);
    },
    fire(type, event) {
      for (const fn of listeners[type] || []) fn(event || {});
    },
  };
  doc.body = new FakeElement('body', doc);
  return doc;
}

// ---------------------------------------------------------------- fake clock (win.setTimeout & co.)

function makeClock() {
  let now = 0;
  let nextId = 1;
  let timers = [];

  function add(fn, ms, repeat) {
    const id = nextId++;
    timers.push({ id, fn, ms: ms || 0, at: now + (ms || 0), repeat: !!repeat });
    return id;
  }

  function remove(id) {
    timers = timers.filter((t) => t.id !== id);
  }

  return {
    setTimeout: (fn, ms) => add(fn, ms, false),
    setInterval: (fn, ms) => add(fn, ms, true),
    clearTimeout: remove,
    clearInterval: remove,
    pending: () => timers.map((t) => t.ms),
    tick(ms) {
      const end = now + ms;
      for (;;) {
        timers.sort((a, b) => a.at - b.at || a.id - b.id);
        const t = timers[0];
        if (!t || t.at > end) break;
        now = t.at;
        if (t.repeat) t.at += t.ms;
        else timers.shift();
        t.fn();
      }
      now = end;
    },
  };
}

// ---------------------------------------------------------------- fake WebSocket and XMLHttpRequest

function makeNetwork() {
  const net = { sockets: [], xhrs: [] };

  class FakeWebSocket {
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.sent = [];
      this.onopen = null;
      this.onmessage = null;
      this.onclose = null;
      net.sockets.push(this);
    }

    send(data) {
      this.sent.push(JSON.parse(data));
    }

    open() {
      this.readyState = 1;
      if (this.onopen) this.onopen({});
    }

    message(obj) {
      if (this.onmessage) this.onmessage({ data: JSON.stringify(obj) });
    }

    close() {
      this.readyState = 3;
      if (this.onclose) this.onclose({});
    }
  }

  class FakeXHR {
    constructor() {
      this.readyState = 0;
      this.status = 0;
      this.responseText = '';
      this.method = null;
      this.url = null;
      this.body = undefined;
      this.headers = {};
      this.onreadystatechange = null;
      net.xhrs.push(this);
    }

    open(method, url) {
      this.method = method;
      this.url = url;
      this.readyState = 1;
    }

    setRequestHeader(name, value) {
      this.headers[name] = value;
    }

    send(body) {
      this.body = body === null ? null : JSON.parse(body);
    }

    respond(status, data) {
      this.status = status;
      this.responseText = data === undefined ? '' : JSON.stringify(data);
      this.readyState = 4;
      if (this.onreadystatechange) this.onreadystatechange();
    }
  }

  net.WebSocket = FakeWebSocket;
  net.XMLHttpRequest = FakeXHR;
  return net;
}
module.exports = { findAll, FakeElement, makeDocument, makeClock, makeNetwork };
