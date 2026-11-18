const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const sourcePath = path.join(__dirname, '../../static/panel/pet.js');
const petSource = fs.readFileSync(sourcePath, 'utf8');

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = {};
    this.rel = '';
    this.href = '';
    this.src = '';
    this.onload = null;
    this.onerror = null;
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }
}

// Loads pet.js in a fresh vm context with a fake window and document.
// Each call gets its own module state (shared loader state lives in the context).
function loadPet(options) {
  const opts = options || {};
  const head = new FakeElement('head');
  const body = new FakeElement('body');
  const created = [];
  const doc = {
    head,
    body,
    defaultView: undefined,
    createElement(tag) {
      if (opts.throwOnCreate) throw new Error('no DOM here');
      const el = new FakeElement(tag);
      created.push(el);
      return el;
    },
    getElementsByTagName() {
      return [head];
    }
  };

  const face = {
    calls: [],
    init(container) {
      this.calls.push(['init', container]);
      if (opts.initThrows) throw new Error('init boom');
    },
    setState(state) {
      this.calls.push(['setState', state]);
      if (opts.stateThrows) throw new Error('setState boom');
    },
    setEmotion(emotion) {
      this.calls.push(['setEmotion', emotion]);
    }
  };

  const win = { console };
  if (opts.withFace) win.LupinFace = face;

  const sandbox = { window: win, document: doc, console };
  vm.createContext(sandbox);
  vm.runInContext(petSource, sandbox, { filename: sourcePath });

  return {
    api: win.PanelPet,
    win,
    doc,
    head,
    face,
    created,
    scripts: () => head.children.filter((c) => c.tagName === 'SCRIPT'),
    links: () => head.children.filter((c) => c.tagName === 'LINK'),
    loadFace(target) {
      win.LupinFace = target || face;
    }
  };
}

test('pet injects lupin.css and lupin.js when LupinFace is missing', () => {
  const env = loadPet();
  const pageEl = new FakeElement('div');
  env.api.create(env.doc, pageEl);

  assert.equal(env.links().length, 1);
  assert.equal(env.links()[0].rel, 'stylesheet');
  assert.equal(env.links()[0].href, '/static/lupin.css');
  assert.equal(env.scripts().length, 1);
  assert.equal(env.scripts()[0].src, '/static/lupin.js');
});

test('pet does not inject assets when LupinFace already exists, and inits at once', () => {
  const env = loadPet({ withFace: true });
  const pageEl = new FakeElement('div');
  const pet = env.api.create(env.doc, pageEl);
  pet.setState('listening');

  assert.equal(env.scripts().length, 0);
  assert.equal(env.links().length, 0);
  assert.deepEqual(env.face.calls, [['init', pageEl], ['setState', 'listening']]);
});

test('pet queues setState and setEmotion until lupin.js loads, then inits once and forwards in order', () => {
  const env = loadPet();
  const pageEl = new FakeElement('div');
  const pet = env.api.create(env.doc, pageEl);

  pet.setState('listening');
  pet.setEmotion('happy');
  pet.setState('thinking');
  assert.deepEqual(env.face.calls, [], 'nothing reaches the face before load');

  env.loadFace();
  env.scripts()[0].onload();

  assert.deepEqual(env.face.calls, [
    ['init', pageEl],
    ['setState', 'listening'],
    ['setEmotion', 'happy'],
    ['setState', 'thinking']
  ]);

  pet.setState('idle');
  assert.deepEqual(env.face.calls[env.face.calls.length - 1], ['setState', 'idle']);
});

test('pet loads lupin.js once for several instances and inits each container once', () => {
  const env = loadPet();
  const pageA = new FakeElement('div');
  const pageB = new FakeElement('div');
  env.api.create(env.doc, pageA);
  env.api.create(env.doc, pageB);

  assert.equal(env.scripts().length, 1, 'one script element');
  env.loadFace();
  env.scripts()[0].onload();

  const inits = env.face.calls.filter((c) => c[0] === 'init').map((c) => c[1]);
  assert.deepEqual(inits, [pageA, pageB]);
});

test('pet errors thrown by LupinFace never propagate', () => {
  const env = loadPet({ withFace: true, initThrows: true, stateThrows: true });
  const pet = env.api.create(env.doc, new FakeElement('div'));

  assert.doesNotThrow(() => pet.setState('listening'));
  assert.doesNotThrow(() => pet.setEmotion('happy'));
  assert.doesNotThrow(() => pet.destroy());
});

test('pet errors thrown while loading never propagate', () => {
  const env = loadPet({ throwOnCreate: true });
  let pet = null;
  assert.doesNotThrow(() => {
    pet = env.api.create(env.doc, new FakeElement('div'));
  });
  assert.doesNotThrow(() => pet.setState('listening'));
  assert.doesNotThrow(() => pet.destroy());
});

test('pet drops queued calls when lupin.js fails to load and does not reinject', () => {
  const env = loadPet();
  const pet = env.api.create(env.doc, new FakeElement('div'));
  pet.setState('listening');

  env.scripts()[0].onerror();
  assert.doesNotThrow(() => pet.setEmotion('happy'));
  assert.deepEqual(env.face.calls, []);

  env.api.create(env.doc, new FakeElement('div'));
  assert.equal(env.scripts().length, 1, 'no second injection after a failed load');
});

test('pet ignores calls and loads after destroy', () => {
  const env = loadPet();
  const pageEl = new FakeElement('div');
  const pet = env.api.create(env.doc, pageEl);
  pet.setState('listening');
  pet.destroy();

  env.loadFace();
  env.scripts()[0].onload();
  pet.setEmotion('happy');

  assert.deepEqual(env.face.calls, [], 'queued and later calls are dropped after destroy');
});

test('pet.js stays ES5 (no arrow functions, let/const, classes or template literals)', () => {
  const code = petSource.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
  assert.equal(/=>/.test(code), false, 'arrow function');
  assert.equal(/\b(let|const)\s+[A-Za-z_$]/.test(code), false, 'let/const');
  assert.equal(/\bclass\s+[A-Za-z_$]/.test(code), false, 'class');
  assert.equal(/`/.test(code), false, 'template literal');
  assert.equal(/\bPromise\b|\bnew\s+(Map|Set)\b/.test(code), false, 'Promise/Map/Set');
});
