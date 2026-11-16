const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const rootDir = path.resolve(__dirname, '../..');
const mainSource = fs.readFileSync(path.join(rootDir, 'electron/main.js'), 'utf8');
const preloadSource = fs.readFileSync(path.join(rootDir, 'electron/preload.js'), 'utf8');

function makeHarness({ displays, position, readError, writeError } = {}) {
  const windows = [];
  const ipcListeners = new Map();
  const ipcHandlers = new Map();
  const fsFiles = new Map();
  const writes = [];
  const intervals = [];
  const shortcuts = new Map();
  const appListeners = new Map();
  let trayTemplate = [];
  const activeDisplays = displays || [{ workArea: { x: 0, y: 0, width: 1000, height: 800 } }];
  const positionPath = path.join('/mock-user-data', 'minipet-position.json');
  if (position !== undefined) fsFiles.set(positionPath, JSON.stringify(position));

  class FakeWindow {
    constructor(options) {
      this.bounds = { x: options.x, y: options.y, width: options.width, height: options.height };
      this.visible = true;
      this.destroyed = false;
      this.listeners = new Map();
      this.ignoreMouseCalls = [];
      this.hideCalls = 0;
      this.focusCalls = 0;
      this.webContents = {
        send() {},
        mainFrame: null,
      };
      windows.push(this);
    }
    loadURL(url) {
      this.url = url;
      this.webContents.mainFrame = { url };
    }
    on(name, callback) {
      const listeners = this.listeners.get(name) || [];
      listeners.push(callback);
      this.listeners.set(name, listeners);
    }
    emit(name, ...args) {
      for (const callback of this.listeners.get(name) || []) callback(...args);
    }
    isDestroyed() { return this.destroyed; }
    isVisible() { return this.visible; }
    getBounds() { return { ...this.bounds }; }
    setBounds(bounds) { this.bounds = { ...bounds }; }
    setIgnoreMouseEvents(ignore, options) { this.ignoreMouseCalls.push({ ignore, options }); }
    showInactive() { this.visible = true; }
    show() { this.visible = true; }
    focus() { this.focusCalls += 1; }
    hide() { this.hideCalls += 1; this.visible = false; }
    destroy() {
      this.emit('close');
      this.destroyed = true;
      this.emit('closed');
    }
  }

  class FakeTray {
    setTitle() {}
    setToolTip() {}
    setContextMenu(menu) { this.menu = menu; }
    on() {}
  }

  const electron = {
    app: {
      whenReady: () => Promise.resolve(),
      getPath: () => '/mock-user-data',
      on: (name, callback) => appListeners.set(name, callback),
      quit() {},
    },
    BrowserWindow: FakeWindow,
    Menu: { buildFromTemplate: (template) => { trayTemplate = template; return template; } },
    Tray: FakeTray,
    dialog: { showMessageBox: async () => ({ response: 0 }) },
    globalShortcut: {
      register: (accelerator, callback) => shortcuts.set(accelerator, callback),
      unregisterAll() {},
    },
    ipcMain: {
      on: (channel, callback) => ipcListeners.set(channel, callback),
      handle: (channel, callback) => ipcHandlers.set(channel, callback),
    },
    nativeImage: { createEmpty: () => ({}) },
    screen: {
      getAllDisplays: () => activeDisplays,
      getPrimaryDisplay: () => activeDisplays[0],
      getCursorScreenPoint: () => ({ ...cursor }),
    },
  };
  const cursor = { x: 400, y: 300 };
  const fsMock = {
    readFileSync(filePath) {
      if (readError) throw readError;
      if (!fsFiles.has(filePath)) throw new Error('Arquivo ausente');
      return fsFiles.get(filePath);
    },
    writeFileSync(filePath, content) {
      writes.push({ filePath, content });
      if (writeError) throw writeError;
      fsFiles.set(filePath, content);
    },
  };
  const http = {
    get(_url, callback) {
      callback({ statusCode: 200, resume() {} });
      return { on() {}, setTimeout() {}, destroy() {} };
    },
  };
  const timers = {
    setInterval(callback, delay) {
      const timer = { callback, delay, cleared: false };
      intervals.push(timer);
      return timer;
    },
    clearInterval(timer) { timer.cleared = true; },
  };
  const mockRequire = (name) => {
    if (name === 'electron') return electron;
    if (name === 'child_process') return { spawn() { throw new Error('sidecar não deve ser iniciado'); } };
    if (name === 'fs') return fsMock;
    if (name === 'http') return http;
    if (name === 'path') return path;
    throw new Error(`Módulo inesperado: ${name}`);
  };
  const context = {
    require: mockRequire,
    __dirname: '/mock-project/electron',
    console: { log() {}, error() {} },
    process: { stdout: { write() {} }, stderr: { write() {} } },
    setTimeout() { return 1; },
    clearTimeout() {},
    setInterval: timers.setInterval,
    clearInterval: timers.clearInterval,
  };
  vm.runInNewContext(mainSource, context, { filename: 'electron/main.js' });

  async function ready() {
    for (let i = 0; i < 8; i += 1) await Promise.resolve();
  }
  function miniPet() {
    return windows.find((win) => win.url === 'http://127.0.0.1:8000/?widget=minipet');
  }
  function send(channel, sender, frame = sender?.mainFrame, payload) {
    ipcListeners.get(channel)?.({ sender, senderFrame: frame }, payload);
  }
  function trustedEvent(win) {
    return { sender: win.webContents, senderFrame: win.webContents.mainFrame };
  }
  return {
    ready, windows, miniPet, send, trustedEvent, fsFiles, writes, intervals, shortcuts,
    trayTemplate: () => trayTemplate, ipcListeners, ipcHandlers, cursor,
  };
}

test('mini-pet usa 420×300 e se ajusta a uma área de trabalho pequena', async () => {
  const harness = makeHarness({ displays: [{ workArea: { x: -200, y: 60, width: 360, height: 240 } }] });
  await harness.ready();

  assert.deepEqual(harness.miniPet().getBounds(), { x: -200, y: 60, width: 360, height: 240 });
  assert.equal(harness.miniPet().url, 'http://127.0.0.1:8000/?widget=minipet');
  const showItem = harness.trayTemplate().find((item) => item.label.startsWith('Mostrar Mini-Pet'));
  assert.equal(showItem.accelerator, 'CommandOrControl+Shift+L');
  assert.equal(harness.shortcuts.has('CommandOrControl+Shift+Space'), true);
  showItem.click();
  assert.equal(harness.miniPet().focusCalls, 1);
});

test('posição salva é restaurada na tela conectada e limitada quando o monitor foi removido', async (t) => {
  await t.test('restaura a posição na tela secundária conectada', async () => {
    const harness = makeHarness({
      displays: [
        { workArea: { x: 0, y: 0, width: 1000, height: 800 } },
        { workArea: { x: 1000, y: 0, width: 800, height: 600 } },
      ],
      position: { x: 1200, y: 250 },
    });
    await harness.ready();
    assert.deepEqual(harness.miniPet().getBounds(), { x: 1200, y: 250, width: 420, height: 300 });
  });

  await t.test('usa a tela principal quando a coordenada salva não intersecta nenhuma tela', async () => {
    const harness = makeHarness({ position: { x: 5000, y: 5000 } });
    await harness.ready();
    assert.deepEqual(harness.miniPet().getBounds(), { x: 580, y: 500, width: 420, height: 300 });
  });
});

test('arraste nativo acompanha o cursor do sistema, encerra e persiste somente x/y', async () => {
  const harness = makeHarness({ position: { x: 200, y: 150 } });
  await harness.ready();
  const win = harness.miniPet();
  const event = harness.trustedEvent(win);
  const initialBounds = win.getBounds();

  harness.send('begin-pet-drag', event.sender, event.senderFrame);
  assert.equal(harness.intervals.length, 1);
  assert.equal(win.ignoreMouseCalls.at(-1).ignore, false);
  harness.cursor.x -= 80;
  harness.cursor.y -= 70;
  harness.intervals[0].callback();
  assert.equal(win.getBounds().x, initialBounds.x - 80);
  assert.equal(win.getBounds().y, initialBounds.y - 70);

  harness.send('end-pet-drag', event.sender, event.senderFrame);
  assert.equal(harness.intervals[0].cleared, true);
  assert.equal(win.ignoreMouseCalls.at(-1).ignore, true);
  assert.deepEqual(JSON.parse(harness.writes.at(-1).content), { x: 120, y: 80 });
  assert.equal(harness.writes.at(-1).filePath, '/mock-user-data/minipet-position.json');
});

test('nudge aceita apenas deltas finitos limitados e respeita os limites da tela', async () => {
  const harness = makeHarness({ position: { x: 20, y: 30 } });
  await harness.ready();
  const win = harness.miniPet();
  const event = harness.trustedEvent(win);

  harness.send('nudge-pet', event.sender, event.senderFrame, { x: 100000, y: -100000 });
  assert.deepEqual(win.getBounds(), { x: 70, y: 0, width: 420, height: 300 });
  assert.deepEqual(JSON.parse(harness.writes.at(-1).content), { x: 70, y: 0 });
  const writeCount = harness.writes.length;
  harness.send('nudge-pet', event.sender, event.senderFrame, { x: '50', y: 1 });
  assert.equal(harness.writes.length, writeCount);
});

test('para o arraste em blur, ocultação idempotente e fechamento da janela', async () => {
  const harness = makeHarness({ position: { x: 100, y: 100 } });
  await harness.ready();
  const win = harness.miniPet();
  const event = harness.trustedEvent(win);

  harness.send('begin-pet-drag', event.sender, event.senderFrame);
  const blurTimer = harness.intervals.at(-1);
  win.emit('blur');
  assert.equal(blurTimer.cleared, true);

  harness.send('begin-pet-drag', event.sender, event.senderFrame);
  const hideTimer = harness.intervals.at(-1);
  harness.send('hide-minipet', event.sender, event.senderFrame);
  harness.send('hide-minipet', event.sender, event.senderFrame);
  assert.equal(hideTimer.cleared, true);
  assert.equal(win.visible, false);
  assert.equal(win.hideCalls, 1);

  harness.send('toggle-minipet', null);
  harness.send('begin-pet-drag', event.sender, event.senderFrame);
  const closeTimer = harness.intervals.at(-1);
  win.destroy();
  assert.equal(closeTimer.cleared, true);
});

test('remetentes dashboard, iframe e remoto não podem mover nem ocultar o mini-pet', async () => {
  const harness = makeHarness({ position: { x: 200, y: 200 } });
  await harness.ready();
  const win = harness.miniPet();
  const original = win.getBounds();
  const dashboard = harness.windows.find((candidate) => candidate.url === 'http://127.0.0.1:8000/?shell=electron');
  const remoteSender = { mainFrame: { url: 'https://example.invalid/?widget=minipet' } };
  const iframe = { url: 'http://127.0.0.1:8000/?widget=minipet' };
  const ignoreCalls = win.ignoreMouseCalls.length;

  for (const [sender, frame] of [
    [dashboard.webContents, dashboard.webContents.mainFrame],
    [win.webContents, iframe],
    [remoteSender, remoteSender.mainFrame],
  ]) {
    harness.send('begin-pet-drag', sender, frame);
    harness.send('nudge-pet', sender, frame, { x: 40, y: 40 });
    harness.send('hide-minipet', sender, frame);
    harness.send('pet-ignore-mouse', sender, frame, false);
  }

  assert.deepEqual(win.getBounds(), original);
  assert.equal(win.visible, true);
  assert.equal(harness.intervals.length, 0);
  assert.equal(win.ignoreMouseCalls.length, ignoreCalls);
  assert.equal(harness.writes.length, 0);
});

test('falhas ao carregar ou gravar a posição não impedem abrir nem arrastar', async (t) => {
  await t.test('arquivo inválido usa posição padrão', async () => {
    const harness = makeHarness({ readError: new Error('leitura negada') });
    await harness.ready();
    assert.deepEqual(harness.miniPet().getBounds(), { x: 290, y: 500, width: 420, height: 300 });
  });

  await t.test('falha de gravação é absorvida com segurança', async () => {
    const harness = makeHarness({ position: { x: 200, y: 150 }, writeError: new Error('disco cheio') });
    await harness.ready();
    const win = harness.miniPet();
    const event = harness.trustedEvent(win);
    harness.send('nudge-pet', event.sender, event.senderFrame, { x: 10, y: 0 });
    assert.equal(win.getBounds().x, 210);
    assert.equal(harness.writes.length, 1);
  });
});

test('preload mantém a API existente e expõe os controles nativos do mini-pet', () => {
  let exposed;
  const sent = [];
  const listeners = [];
  const context = {
    require: () => ({
      contextBridge: { exposeInMainWorld: (_name, api) => { exposed = api; } },
      ipcRenderer: {
        send: (...args) => sent.push(args),
        invoke: (...args) => sent.push(args),
        on: (...args) => listeners.push(args),
      },
    }),
  };
  vm.runInNewContext(preloadSource, context, { filename: 'electron/preload.js' });

  for (const method of ['openDashboard', 'beginPetDrag', 'endPetDrag', 'nudgePet', 'hideMiniPet', 'setPetIgnoreMouse']) {
    assert.equal(typeof exposed[method], 'function', `${method} deve estar exposto`);
  }
  exposed.openDashboard();
  exposed.beginPetDrag();
  exposed.endPetDrag();
  exposed.nudgePet({ x: 1, y: -1 });
  exposed.hideMiniPet();
  exposed.setPetIgnoreMouse(false);
  assert.deepEqual(sent, [
    ['open-dashboard'], ['begin-pet-drag'], ['end-pet-drag'], ['nudge-pet', { x: 1, y: -1 }],
    ['hide-minipet'], ['pet-ignore-mouse', false],
  ]);
});
