/**
 * Controlador de Gamepad para Anbernic RG406H (/static/gamepad.js)
 * Mapeia analógico esquerdo, gatilhos L2/R2 (Push-to-Talk, ou página anterior/próxima
 * quando `triggersAsPage()` devolve true, como no Dock), L1/R1 (modos),
 * D-Pad + A/B/X/Y (Y segurado = falar, se `onYPress` existir)/Start/Select e expõe snapshot ao vivo para Diagnóstico.
 */
(function (global) {
  'use strict';

  const ANALOG_DEADZONE = 0.15;
  const TRIGGER_THRESHOLD = 0.35;
  const DPAD_INITIAL_REPEAT_MS = 340;
  const DPAD_REPEAT_INTERVAL_MS = 140;

  const BUTTON_NAMES = {
    0: 'A',
    1: 'B',
    2: 'X',
    3: 'Y',
    4: 'L1',
    5: 'R1',
    6: 'L2',
    7: 'R2',
    8: 'Select',
    9: 'Start',
    10: 'L3',
    11: 'R3',
    12: 'D-Up',
    13: 'D-Down',
    14: 'D-Left',
    15: 'D-Right',
    16: 'Home',
  };

  let rafId = null;
  let running = false;
  let handlers = {};
  let prevButtons = {};
  let dpadTimers = {};
  let pttActive = false;
  let analogWasActive = false;
  const triggerWasDown = { l2: false, r2: false };
  let lastSnapshot = {
    connected: false,
    id: null,
    index: null,
    mapping: null,
    axes: [],
    buttons: [],
    pttActive: false,
    lastAction: '',
    timestamp: 0,
  };

  function safeVibrate(durationMs) {
    try {
      if (typeof navigator !== 'undefined' && typeof navigator.vibrate === 'function') {
        navigator.vibrate(durationMs);
      }
    } catch {
      // Ignora caso o navegador bloqueie vibração antes de gesto
    }
  }

  function applyDeadzone(value, deadzone) {
    if (typeof value !== 'number' || Number.isNaN(value)) return 0;
    const abs = Math.abs(value);
    if (abs <= deadzone) return 0;
    const normalized = (abs - deadzone) / (1 - deadzone);
    return Math.sign(value) * Math.min(1, Math.max(0, normalized));
  }

  function readActiveGamepad() {
    if (typeof navigator === 'undefined' || typeof navigator.getGamepads !== 'function') {
      return null;
    }
    const pads = navigator.getGamepads();
    if (!pads) return null;
    for (let i = 0; i < pads.length; i += 1) {
      if (pads[i] && pads[i].connected) {
        return pads[i];
      }
    }
    return null;
  }

  function isButtonPressed(pad, index, threshold) {
    const btn = pad.buttons && pad.buttons[index];
    if (!btn) return false;
    if (typeof threshold === 'number') {
      return Boolean(btn.pressed) || (typeof btn.value === 'number' && btn.value > threshold);
    }
    return Boolean(btn.pressed) || (typeof btn.value === 'number' && btn.value > 0.5);
  }

  function emitLastAction(label) {
    lastSnapshot.lastAction = label;
    if (typeof handlers.onAction === 'function') {
      handlers.onAction(label);
    }
  }

  function handleDpadDirection(pad, btnIndex, direction, now) {
    const pressed = isButtonPressed(pad, btnIndex);
    const wasPressed = Boolean(prevButtons[btnIndex]);

    if (pressed && !wasPressed) {
      dpadTimers[btnIndex] = now + DPAD_INITIAL_REPEAT_MS;
      emitLastAction(`D-Pad ${direction}`);
      if (typeof handlers.onDpad === 'function') {
        handlers.onDpad(direction);
      }
    } else if (pressed && wasPressed && now >= (dpadTimers[btnIndex] || Infinity)) {
      dpadTimers[btnIndex] = now + DPAD_REPEAT_INTERVAL_MS;
      if (typeof handlers.onDpad === 'function') {
        handlers.onDpad(direction);
      }
    } else if (!pressed) {
      delete dpadTimers[btnIndex];
    }

    prevButtons[btnIndex] = pressed;
  }

  function handleEdgeButton(pad, btnIndex, label, callback) {
    const pressed = isButtonPressed(pad, btnIndex);
    const wasPressed = Boolean(prevButtons[btnIndex]);
    if (pressed && !wasPressed) {
      emitLastAction(label);
      safeVibrate(10);
      if (typeof callback === 'function') {
        callback();
      }
    }
    prevButtons[btnIndex] = pressed;
  }

  function pollFrame(now) {
    if (!running) return;

    const pad = readActiveGamepad();
    if (!pad) {
      if (pttActive) {
        pttActive = false;
        if (typeof handlers.onPttEnd === 'function') {
          handlers.onPttEnd();
        }
      }
      if (analogWasActive) {
        analogWasActive = false;
        if (typeof handlers.onLook === 'function') {
          handlers.onLook(0, 0);
        }
      }
      prevButtons = {};
      dpadTimers = {};
      lastSnapshot = {
        connected: false,
        id: null,
        index: null,
        mapping: null,
        axes: [],
        buttons: [],
        pttActive: false,
        lastAction: lastSnapshot.lastAction || '',
        timestamp: now,
      };
      rafId = global.requestAnimationFrame(pollFrame);
      return;
    }

    // 1. Analógico esquerdo -> olhar do rosto
    const lx = applyDeadzone(pad.axes[0] || 0, ANALOG_DEADZONE);
    const ly = applyDeadzone(pad.axes[1] || 0, ANALOG_DEADZONE);
    if (lx !== 0 || ly !== 0) {
      analogWasActive = true;
      if (typeof handlers.onLook === 'function') {
        handlers.onLook(lx, ly);
      }
    } else if (analogWasActive) {
      analogWasActive = false;
      if (typeof handlers.onLook === 'function') {
        handlers.onLook(0, 0);
      }
    }

    // 2. Gatilhos L2 (6) ou R2 (7) -> Push-to-Talk
    const l2Val = pad.buttons[6] ? pad.buttons[6].value || (pad.buttons[6].pressed ? 1 : 0) : 0;
    const r2Val = pad.buttons[7] ? pad.buttons[7].value || (pad.buttons[7].pressed ? 1 : 0) : 0;
    const l2Down = l2Val > TRIGGER_THRESHOLD;
    const r2Down = r2Val > TRIGGER_THRESHOLD;
    const triggerPressed = l2Down || r2Down;
    const pageMode = typeof handlers.triggersAsPage === 'function' && handlers.triggersAsPage();

    if (pageMode) {
      // Nesse contexto os gatilhos não gravam: L2 volta uma página, R2 avança uma.
      if (pttActive) {
        pttActive = false;
        if (typeof handlers.onPttEnd === 'function') handlers.onPttEnd();
      }
      if (l2Down && !triggerWasDown.l2) {
        emitLastAction('L2 (Página anterior)');
        safeVibrate(10);
        if (typeof handlers.onPage === 'function') handlers.onPage(-1);
      }
      if (r2Down && !triggerWasDown.r2) {
        emitLastAction('R2 (Próxima página)');
        safeVibrate(10);
        if (typeof handlers.onPage === 'function') handlers.onPage(1);
      }
    } else if (triggerPressed && !pttActive) {
      pttActive = true;
      emitLastAction('L2/R2 Push-to-Talk (início)');
      safeVibrate(18);
      if (typeof handlers.onPttStart === 'function') {
        handlers.onPttStart();
      }
    } else if (!triggerPressed && pttActive) {
      pttActive = false;
      emitLastAction('L2/R2 Push-to-Talk (enviar)');
      safeVibrate(12);
      if (typeof handlers.onPttEnd === 'function') {
        handlers.onPttEnd();
      }
    }
    triggerWasDown.l2 = l2Down;
    triggerWasDown.r2 = r2Down;

    // 3. L1 (4) / R1 (5) -> alternar entre os 4 modos de tela
    handleEdgeButton(pad, 4, 'L1 (Modo anterior)', () => {
      if (typeof handlers.onModeCycle === 'function') handlers.onModeCycle(-1);
    });
    handleEdgeButton(pad, 5, 'R1 (Próximo modo)', () => {
      if (typeof handlers.onModeCycle === 'function') handlers.onModeCycle(1);
    });

    // 4. D-Pad (12..15)
    handleDpadDirection(pad, 12, 'up', now);
    handleDpadDirection(pad, 13, 'down', now);
    handleDpadDirection(pad, 14, 'left', now);
    handleDpadDirection(pad, 15, 'right', now);

    // 5. Botões A (0), B (1), X (2), Y (3), Select (8), Start (9)
    handleEdgeButton(pad, 0, 'A (Confirmar/Executar)', handlers.onConfirm);
    handleEdgeButton(pad, 1, 'B (Barge-in/Voltar)', handlers.onBackOrInterrupt);
    handleEdgeButton(pad, 2, 'X (Legenda)', handlers.onToggleCaption);
    if (typeof handlers.onYPress === 'function') {
      // Y segurado: onYPress ao apertar e onYRelease ao soltar (ex.: falar no Dock).
      const yDown = isButtonPressed(pad, 3);
      const yWas = Boolean(prevButtons[3]);
      if (yDown && !yWas) {
        emitLastAction('Y (Falar)');
        safeVibrate(12);
        handlers.onYPress();
      } else if (!yDown && yWas && typeof handlers.onYRelease === 'function') {
        handlers.onYRelease();
      }
      prevButtons[3] = yDown;
    } else {
      handleEdgeButton(pad, 3, 'Y (Modo TTS)', handlers.onToggleTtsMode);
    }
    handleEdgeButton(pad, 8, 'Select (Tela Cheia)', handlers.onSelect);
    handleEdgeButton(pad, 9, 'Start (Memória / Config)', handlers.onStart);

    // 6. Snapshot ao vivo para Diagnóstico
    const buttonsList = [];
    for (let i = 0; i < Math.min(pad.buttons.length, 17); i += 1) {
      const b = pad.buttons[i];
      buttonsList.push({
        index: i,
        name: BUTTON_NAMES[i] || `B${i}`,
        pressed: Boolean(b && b.pressed),
        value: b && typeof b.value === 'number' ? Number(b.value.toFixed(2)) : 0,
      });
    }

    lastSnapshot = {
      connected: true,
      id: pad.id || 'Gamepad genérico',
      index: pad.index,
      mapping: pad.mapping || 'standard',
      axes: Array.from(pad.axes || []).slice(0, 6).map((v) => Number((v || 0).toFixed(2))),
      buttons: buttonsList,
      pttActive,
      lastAction: lastSnapshot.lastAction || '',
      timestamp: now,
    };

    rafId = global.requestAnimationFrame(pollFrame);
  }

  function onGamepadConnected(event) {
    const pad = event && event.gamepad;
    if (pad) {
      emitLastAction(`Conectado: ${pad.id}`);
      if (typeof handlers.onConnectionChange === 'function') {
        handlers.onConnectionChange(true, pad);
      }
    }
  }

  function onGamepadDisconnected(event) {
    const pad = event && event.gamepad;
    if (typeof handlers.onConnectionChange === 'function') {
      handlers.onConnectionChange(false, pad || null);
    }
  }

  const DeskGamepad = {
    init(nextHandlers = {}) {
      handlers = nextHandlers || {};
      if (running) return;
      running = true;

      if (typeof global.addEventListener === 'function') {
        global.addEventListener('gamepadconnected', onGamepadConnected);
        global.addEventListener('gamepaddisconnected', onGamepadDisconnected);
      }
      if (typeof global.requestAnimationFrame === 'function') {
        rafId = global.requestAnimationFrame(pollFrame);
      }
    },

    destroy() {
      running = false;
      if (rafId !== null && typeof global.cancelAnimationFrame === 'function') {
        global.cancelAnimationFrame(rafId);
        rafId = null;
      }
      if (typeof global.removeEventListener === 'function') {
        global.removeEventListener('gamepadconnected', onGamepadConnected);
        global.removeEventListener('gamepaddisconnected', onGamepadDisconnected);
      }
    },

    setHandlers(nextHandlers = {}) {
      handlers = { ...handlers, ...nextHandlers };
    },

    getSnapshot() {
      return {
        ...lastSnapshot,
        axes: [...(lastSnapshot.axes || [])],
        buttons: (lastSnapshot.buttons || []).map((b) => ({ ...b })),
      };
    },

    isPttActive() {
      return pttActive;
    },

    vibrate: safeVibrate,
  };

  global.DeskGamepad = DeskGamepad;
})(typeof window !== 'undefined' ? window : globalThis);
