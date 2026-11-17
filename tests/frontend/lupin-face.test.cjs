const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const sourcePath = path.join(__dirname, '../../static/lupin.js');
const source = fs.readFileSync(sourcePath, 'utf8');
const tabela = JSON.parse(
  fs.readFileSync(path.join(__dirname, '../../static/lupin/expressoes.json'), 'utf8'),
);

class FakeElement {
  constructor(tag) {
    this.tag = tag;
    this.attributes = new Map();
    this.style = { setProperty() {} };
    this.dataset = {};
    this.children = [];
    this.parentNode = null;
    this.hidden = false;
    this.className = '';
    this.classes = new Set();
    this.classList = {
      add: (n) => this.classes.add(n),
      remove: (n) => this.classes.delete(n),
      contains: (n) => this.classes.has(n),
      toggle: (n, force) => {
        const on = force === undefined ? !this.classes.has(n) : Boolean(force);
        if (on) this.classes.add(n);
        else this.classes.delete(n);
        return on;
      },
    };
  }
  setAttribute(n, v) { this.attributes.set(n, String(v)); }
  getAttribute(n) { return this.attributes.get(n) ?? null; }
  appendChild(el) { el.parentNode = this; this.children.push(el); return el; }
  removeChild(el) { this.children = this.children.filter((c) => c !== el); el.parentNode = null; }
  set textContent(_) { this.children = []; }
  getBoundingClientRect() { return { left: 0, top: 0, width: 480, height: 320 }; }
}

function makeHarness({ reducedMotion = false } = {}) {
  const timers = new Map();
  let nextTimer = 0;
  let nextRaf = 0;
  const rafs = new Map();
  let now = 0;
  const listeners = new Set();
  const motionQuery = {
    matches: reducedMotion,
    addEventListener(type, cb) { listeners.add(cb); },
    removeEventListener(type, cb) { listeners.delete(cb); },
    change(matches) { this.matches = matches; for (const cb of [...listeners]) cb({ matches }); },
  };
  const window = {
    matchMedia: () => motionQuery,
    requestAnimationFrame(cb) { const id = ++nextRaf; rafs.set(id, cb); return id; },
    cancelAnimationFrame(id) { rafs.delete(id); },
    fetch: async () => ({ ok: true, json: async () => tabela }),
    EmoAudio: null,
    document: { createElement: (tag) => new FakeElement(tag), body: new FakeElement('body') },
  };
  const context = {
    window,
    document: window.document,
    performance: { now: () => now },
    Math, Date, console, Promise,
    setTimeout(cb, delay) { const id = ++nextTimer; timers.set(id, { cb, delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
  };
  vm.runInNewContext(source, context, { filename: sourcePath });
  const container = new FakeElement('div');
  return {
    api: window.LupinFace,
    container,
    motionQuery,
    timers,
    get listenerCount() { return listeners.size; },
    tick(ts) {
      now = ts;
      const frame = rafs.entries().next().value;
      assert.ok(frame, 'um quadro de animação deve estar agendado');
      rafs.delete(frame[0]);
      frame[1](ts);
    },
    runTimers() {
      const pendentes = [...timers.entries()];
      timers.clear();
      pendentes.forEach(([, t]) => t.cb());
    },
  };
}

async function iniciar(opts) {
  const h = makeHarness(opts);
  h.api.init(h.container);
  await new Promise((resolve) => setImmediate(resolve));
  return h;
}

function visiveis(h) {
  const root = h.container.children[0];
  const camadas = {};
  const achar = (el) => {
    if (el.dataset && el.dataset.camada) {
      const ativa = el.children.filter((img) => !img.hidden);
      camadas[el.dataset.camada] = ativa.map((img) => img.getAttribute('src').split('/').pop().replace('.svg', ''));
    }
    el.children.forEach(achar);
  };
  achar(root);
  return camadas;
}

test('a tabela cobre as 12 expressões e os 5 estados com variantes que existem', () => {
  const { api } = makeHarness();
  assert.equal(api.getSupportedEmotions().length, 12);
  for (const emocao of api.getSupportedEmotions()) {
    assert.ok(tabela.expressoes[emocao], `expressão ${emocao} sem linha na tabela`);
    const r = api.resolverCamadas(tabela, { emocao, estado: 'idle', piscando: false, nivelAudio: 0 });
    for (const [camada, variante] of Object.entries(r.camadas)) {
      assert.ok(tabela.camadas[camada].includes(variante), `${emocao}: ${camada}/${variante} não existe`);
    }
  }
  for (const estado of api.getSupportedStates()) {
    assert.ok(tabela.estados[estado], `estado ${estado} sem linha na tabela`);
  }
});

test('cada camada mostra uma única variante e a expressão troca as camadas', async () => {
  const h = await iniciar();
  let v = visiveis(h);
  assert.deepEqual(v.olhos, ['aberto']);
  assert.deepEqual(v.boca, ['fechada']);
  h.api.setEmotion('love');
  v = visiveis(h);
  assert.deepEqual(v.olhos, ['coracao']);
  assert.deepEqual(v.boca, ['lingua']);
  h.api.setEmotion('angry');
  v = visiveis(h);
  assert.deepEqual(v.olhos, ['bravo']);
  assert.deepEqual(v.orelhas, ['atras']);
  for (const lista of Object.values(v)) assert.equal(lista.length, 1);
});

test('emoção temporária volta ao neutro depois do tempo', async () => {
  const h = await iniciar();
  h.api.setEmotion('surprised', { durationMs: 900 });
  assert.equal(h.api.getEmotion(), 'surprised');
  h.runTimers();
  assert.equal(h.api.getEmotion(), 'neutral');
  assert.deepEqual(visiveis(h).olhos, ['aberto']);
});

test('valores desconhecidos de estado e emoção são ignorados', async () => {
  const h = await iniciar();
  const aviso = console.warn;
  console.warn = () => {};
  try {
    h.api.setEmotion('feliz-demais');
    h.api.setState('voando');
  } finally {
    console.warn = aviso;
  }
  assert.equal(h.api.getEmotion(), 'neutral');
  assert.equal(h.api.getState(), 'idle');
});

test('falando acende a onda da coleira e a boca acompanha o nível de áudio', async () => {
  const h = await iniciar();
  assert.deepEqual(visiveis(h).colar, ['apagado']);
  h.api.setState('speaking');
  assert.deepEqual(visiveis(h).colar, ['aceso']);
  h.api.setAudioLevel(0.8);
  h.tick(100);
  assert.deepEqual(visiveis(h).boca, ['aberta']);
  h.api.setAudioLevel(0.25);
  h.tick(200);
  assert.deepEqual(visiveis(h).boca, ['meio-aberta']);
  h.api.setAudioLevel(0.02);
  h.tick(300);
  assert.deepEqual(visiveis(h).boca, ['fechada']);
  h.api.setState('idle');
  assert.deepEqual(visiveis(h).colar, ['apagado']);
});

test('piscar fecha os olhos abertos e reabre depois', async () => {
  const h = await iniciar();
  h.api.blink();
  assert.deepEqual(visiveis(h).olhos, ['fechado']);
  h.tick(10000);
  assert.ok(['aberto', 'fechado'].includes(visiveis(h).olhos[0]));
  h.tick(20000);
  h.tick(20200);
  assert.deepEqual(visiveis(h).olhos, ['aberto']);
});

test('Truque de corpo inteiro troca o busto pelos quadros e volta no fim', async () => {
  const h = await iniciar();
  const root = h.container.children[0];
  assert.equal(h.api.playTrick('dance'), true);
  assert.ok(root.classes.has('lupin-corpo-inteiro'));
  assert.ok(h.api.isTrickPlaying());
  const stage = root.children[0];
  const corpo = stage.children.find((c) => c.className === 'lupin-corpo');
  assert.equal(corpo.hidden, false);
  assert.match(corpo.getAttribute('src'), /corpo\/danca-1\.svg$/);
  h.runTimers();
  assert.equal(corpo.hidden, true);
  assert.ok(!root.classes.has('lupin-corpo-inteiro'));
  assert.equal(h.api.isTrickPlaying(), false);
});

test('Truques de busto não usam corpo inteiro', async () => {
  const h = await iniciar();
  const root = h.container.children[0];
  for (const id of ['sing', 'meditate', 'celebrate']) {
    assert.equal(h.api.playTrick(id), true);
    assert.ok(!root.classes.has('lupin-corpo-inteiro'), id);
  }
  assert.equal(h.api.playTrick('voar'), false);
});

test('movimento reduzido assenta o rosto e pula a coreografia de corpo', async () => {
  const h = await iniciar({ reducedMotion: true });
  const root = h.container.children[0];
  h.api.blink();
  assert.deepEqual(visiveis(h).olhos, ['aberto']);
  assert.equal(h.api.playTrick('nap'), true);
  assert.ok(!root.classes.has('lupin-corpo-inteiro'));
  assert.equal(h.api.getEmotion(), 'sleepy');
});

test('reinit mantém só um listener de preferência de movimento', async () => {
  const h = makeHarness();
  h.api.init(h.container);
  assert.equal(h.listenerCount, 1);
  h.api.init(h.container);
  assert.equal(h.listenerCount, 1);
});
