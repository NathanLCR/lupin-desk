const { app, BrowserWindow, Menu, Tray, dialog, globalShortcut, ipcMain, nativeImage, screen } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '..');
const VENV_UVICORN = path.join(REPO_ROOT, '.venv', 'bin', 'uvicorn');
const BASE_URL = 'http://127.0.0.1:8000';
const MINI_PET_POSITION_FILE = 'minipet-position.json';
const MINI_PET_WIDTH = 420;
const MINI_PET_HEIGHT = 300;
const MAX_NUDGE_DELTA = 50;

let sidecarProc = null;
let ownsSidecar = false;
let tray = null;
let dashboardWin = null;
let miniPetWin = null;
let miniPetDrag = null;
let miniPetDragTimer = null;
let petIgnoreMouse = true;
let isQuitting = false;
let trayState = { syncStatus: 'yellow', pomodoro: '' };

function syncEmoji(status) {
  if (status === 'green') return '🟢';
  if (status === 'red') return '🔴';
  return '🟡';
}

function updateTrayTitle() {
  if (!tray) return;
  const dot = syncEmoji(trayState.syncStatus);
  const pomo = trayState.pomodoro ? ` ${trayState.pomodoro}` : '';
  tray.setTitle(`${dot}${pomo}`);
}

function isServerHealthy() {
  return new Promise((resolve) => {
    const req = http.get(`${BASE_URL}/health`, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on('error', () => resolve(false));
    req.setTimeout(1000, () => {
      req.destroy();
      resolve(false);
    });
  });
}

function waitForHealth(timeoutMs = 15000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const probe = async () => {
      if (await isServerHealthy()) return resolve();
      if (Date.now() - started > timeoutMs) {
        return reject(new Error('FastAPI sidecar timeout'));
      }
      setTimeout(probe, 300);
    };
    probe();
  });
}

function startSidecar() {
  if (sidecarProc) return;
  ownsSidecar = true;
  sidecarProc = spawn(
    VENV_UVICORN,
    ['app.main:app', '--host', '0.0.0.0', '--port', '8000'],
    { cwd: REPO_ROOT, stdio: ['ignore', 'pipe', 'pipe'] }
  );
  sidecarProc.stdout.on('data', (chunk) => process.stdout.write(`[sidecar] ${chunk}`));
  sidecarProc.stderr.on('data', (chunk) => process.stderr.write(`[sidecar] ${chunk}`));
  sidecarProc.on('exit', (code) => {
    sidecarProc = null;
    if (!isQuitting && ownsSidecar) {
      console.error(`[sidecar] exited unexpectedly (code=${code}); restarting...`);
      setTimeout(startSidecar, 1500);
    }
  });
}

function stopSidecar() {
  if (ownsSidecar && sidecarProc) {
    sidecarProc.kill('SIGTERM');
    sidecarProc = null;
  }
}

function createDashboardWindow() {
  if (dashboardWin && !dashboardWin.isDestroyed()) {
    dashboardWin.show();
    dashboardWin.focus();
    return dashboardWin;
  }
  dashboardWin = new BrowserWindow({
    width: 1200,
    height: 820,
    minWidth: 960,
    minHeight: 680,
    backgroundColor: '#000000',
    title: 'Desk Assistant — Nathan OS',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  dashboardWin.loadURL(`${BASE_URL}/?shell=electron`);
  dashboardWin.on('close', (e) => {
    if (!isQuitting) {
      e.preventDefault();
      dashboardWin.hide();
    }
  });
  return dashboardWin;
}

function readMiniPetPosition() {
  try {
    const saved = JSON.parse(fs.readFileSync(path.join(app.getPath('userData'), MINI_PET_POSITION_FILE), 'utf8'));
    if (Number.isFinite(saved?.x) && Number.isFinite(saved?.y)) return { x: saved.x, y: saved.y };
  } catch (_err) {
    // First run and invalid files fall back to the default position.
  }
  return null;
}

function saveMiniPetPosition() {
  if (!miniPetWin || miniPetWin.isDestroyed()) return;
  try {
    const { x, y } = miniPetWin.getBounds();
    fs.writeFileSync(
      path.join(app.getPath('userData'), MINI_PET_POSITION_FILE),
      JSON.stringify({ x, y }),
      'utf8'
    );
  } catch (err) {
    console.error(`[mini-pet] Could not save the position: ${err.message}`);
  }
}

function displayForRect(rect) {
  const displays = typeof screen.getAllDisplays === 'function' ? screen.getAllDisplays() : [];
  let bestDisplay = null;
  let bestOverlap = 0;
  for (const display of displays) {
    const area = display.workArea;
    const overlapWidth = Math.max(0, Math.min(rect.x + rect.width, area.x + area.width) - Math.max(rect.x, area.x));
    const overlapHeight = Math.max(0, Math.min(rect.y + rect.height, area.y + area.height) - Math.max(rect.y, area.y));
    const overlap = overlapWidth * overlapHeight;
    if (overlap > bestOverlap) {
      bestDisplay = display;
      bestOverlap = overlap;
    }
  }
  // No overlap means the saved display was disconnected; fall back to the primary one.
  return bestDisplay || screen.getPrimaryDisplay();
}

function clampMiniPetBounds(x, y, display = displayForRect({ x, y, width: MINI_PET_WIDTH, height: MINI_PET_HEIGHT })) {
  const area = display.workArea;
  const width = Math.max(1, Math.min(MINI_PET_WIDTH, area.width));
  const height = Math.max(1, Math.min(MINI_PET_HEIGHT, area.height));
  return {
    x: Math.round(Math.max(area.x, Math.min(x, area.x + area.width - width))),
    y: Math.round(Math.max(area.y, Math.min(y, area.y + area.height - height))),
    width,
    height,
  };
}

function setMiniPetPosition(x, y) {
  if (!miniPetWin || miniPetWin.isDestroyed()) return;
  const bounds = clampMiniPetBounds(x, y);
  const current = miniPetWin.getBounds();
  if (current.x !== bounds.x || current.y !== bounds.y || current.width !== bounds.width || current.height !== bounds.height) {
    miniPetWin.setBounds(bounds);
  }
}

function stopMiniPetDrag(savePosition = true) {
  if (!miniPetDrag) return;
  if (miniPetDragTimer) clearInterval(miniPetDragTimer);
  miniPetDragTimer = null;
  miniPetDrag = null;
  if (miniPetWin && !miniPetWin.isDestroyed()) {
    miniPetWin.setIgnoreMouseEvents(petIgnoreMouse, { forward: true });
    if (savePosition) saveMiniPetPosition();
  }
}

function beginMiniPetDrag() {
  if (!miniPetWin || miniPetWin.isDestroyed() || !miniPetWin.isVisible() || miniPetDrag) return;
  const bounds = miniPetWin.getBounds();
  const cursor = screen.getCursorScreenPoint();
  miniPetDrag = { x: bounds.x, y: bounds.y, cursorX: cursor.x, cursorY: cursor.y };
  miniPetWin.setIgnoreMouseEvents(false, { forward: true });
  miniPetDragTimer = setInterval(() => {
    if (!miniPetWin || miniPetWin.isDestroyed() || !miniPetWin.isVisible()) {
      stopMiniPetDrag();
      return;
    }
    try {
      const point = screen.getCursorScreenPoint();
      setMiniPetPosition(
        miniPetDrag.x + point.x - miniPetDrag.cursorX,
        miniPetDrag.y + point.y - miniPetDrag.cursorY
      );
    } catch (err) {
      console.error(`[mini-pet] Drag interrupted: ${err.message}`);
      stopMiniPetDrag();
    }
  }, 16);
}

function createMiniPetWindow() {
  if (miniPetWin && !miniPetWin.isDestroyed()) {
    if (miniPetWin.isVisible()) hideMiniPetWindow();
    else miniPetWin.showInactive();
    return miniPetWin;
  }
  const saved = readMiniPetPosition();
  const primary = screen.getPrimaryDisplay();
  const area = primary.workArea;
  const initialX = saved ? saved.x : area.x + Math.round((area.width - MINI_PET_WIDTH) / 2);
  const initialY = saved ? saved.y : area.y + area.height - MINI_PET_HEIGHT;
  const initialBounds = clampMiniPetBounds(initialX, initialY, saved ? displayForRect({
    x: saved.x, y: saved.y, width: MINI_PET_WIDTH, height: MINI_PET_HEIGHT,
  }) : primary);
  miniPetWin = new BrowserWindow({
    ...initialBounds,
    frame: false,
    transparent: true,
    hasShadow: false,
    alwaysOnTop: true,
    resizable: false,
    skipTaskbar: true,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  miniPetWin.setIgnoreMouseEvents(true, { forward: true });
  miniPetWin.loadURL(`${BASE_URL}/?widget=minipet`);
  miniPetWin.on('blur', () => stopMiniPetDrag());
  miniPetWin.on('close', () => stopMiniPetDrag());
  miniPetWin.on('closed', () => {
    stopMiniPetDrag(false);
    miniPetWin = null;
  });
  return miniPetWin;
}

function hideMiniPetWindow() {
  if (!miniPetWin || miniPetWin.isDestroyed()) return;
  stopMiniPetDrag();
  if (miniPetWin.isVisible()) miniPetWin.hide();
}

function showMiniPetWindow() {
  const win = miniPetWin && !miniPetWin.isDestroyed() ? miniPetWin : createMiniPetWindow();
  if (!win || win.isDestroyed()) return;
  win.show();
  win.focus();
}

function createTray() {
  const icon = nativeImage.createEmpty();
  tray = new Tray(icon);
  updateTrayTitle();
  const contextMenu = Menu.buildFromTemplate([
    { label: 'Open Dashboard (Cmd+Shift+Space)', click: () => createDashboardWindow() },
    { label: 'Show Mini-Pet (Cmd+Shift+L)', accelerator: 'CommandOrControl+Shift+L', click: () => showMiniPetWindow() },
    { label: 'Toggle Floating Mini-Pet', click: () => createMiniPetWindow() },
    {
      label: 'Look at Screen (Jarvis On Demand)',
      click: () => {
        const win = createDashboardWindow();
        win.webContents.send('shortcut-trigger', 'vision');
      },
    },
    { type: 'separator' },
    {
      label: 'Quit',
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]);
  tray.setToolTip('Desk Assistant + Nathan OS');
  tray.setContextMenu(contextMenu);
  tray.on('click', () => createDashboardWindow());
}

ipcMain.handle('confirm-write', async (_event, payload) => {
  const win = dashboardWin && !dashboardWin.isDestroyed() ? dashboardWin : null;
  const result = await dialog.showMessageBox(win, {
    type: 'question',
    buttons: ['Cancel', 'Authorize Write'],
    defaultId: 1,
    cancelId: 0,
    title: payload?.title || 'Confirm write to Cowork',
    message: payload?.message || 'Confirm change?',
    detail: payload?.diff ? String(payload.diff).slice(0, 1500) : '',
  });
  return result.response === 1;
});

function isTrustedMiniPetEvent(event) {
  const frame = event?.senderFrame;
  return Boolean(
    miniPetWin && !miniPetWin.isDestroyed() &&
    event.sender === miniPetWin.webContents &&
    frame && frame === event.sender.mainFrame &&
    frame.url === `${BASE_URL}/?widget=minipet`
  );
}

ipcMain.on('open-dashboard', () => createDashboardWindow());
ipcMain.on('toggle-minipet', () => createMiniPetWindow());
ipcMain.on('begin-pet-drag', (event) => {
  if (isTrustedMiniPetEvent(event)) beginMiniPetDrag();
});
ipcMain.on('end-pet-drag', (event) => {
  if (isTrustedMiniPetEvent(event)) stopMiniPetDrag();
});
ipcMain.on('nudge-pet', (event, delta) => {
  if (!isTrustedMiniPetEvent(event) || !delta || typeof delta !== 'object') return;
  if (!Number.isFinite(delta.x) || !Number.isFinite(delta.y)) return;
  const x = Math.max(-MAX_NUDGE_DELTA, Math.min(MAX_NUDGE_DELTA, Math.round(delta.x)));
  const y = Math.max(-MAX_NUDGE_DELTA, Math.min(MAX_NUDGE_DELTA, Math.round(delta.y)));
  const bounds = miniPetWin.getBounds();
  setMiniPetPosition(bounds.x + x, bounds.y + y);
  saveMiniPetPosition();
});
ipcMain.on('hide-minipet', (event) => {
  if (isTrustedMiniPetEvent(event)) hideMiniPetWindow();
});
ipcMain.on('pet-ignore-mouse', (event, ignore) => {
  if (!isTrustedMiniPetEvent(event)) return;
  petIgnoreMouse = Boolean(ignore);
  if (!miniPetDrag) miniPetWin.setIgnoreMouseEvents(petIgnoreMouse, { forward: true });
});
ipcMain.on('tray-update', (_event, status) => {
  if (status && typeof status === 'object') {
    if (status.syncStatus) trayState.syncStatus = status.syncStatus;
    if (typeof status.pomodoro === 'string') trayState.pomodoro = status.pomodoro;
    updateTrayTitle();
  }
});

app.whenReady().then(async () => {
  const alreadyUp = await isServerHealthy();
  if (alreadyUp) {
    console.log('[sidecar] Server already running at 127.0.0.1:8000; reusing the existing instance.');
  } else {
    startSidecar();
    try {
      await waitForHealth();
    } catch (err) {
      console.error(err);
    }
  }
  createTray();
  createDashboardWindow();
  createMiniPetWindow();

  globalShortcut.register('CommandOrControl+Shift+Space', () => {
    if (dashboardWin && !dashboardWin.isDestroyed() && dashboardWin.isVisible()) {
      dashboardWin.hide();
    } else {
      createDashboardWindow();
    }
  });
});

app.on('before-quit', () => {
  isQuitting = true;
  globalShortcut.unregisterAll();
  stopSidecar();
});
