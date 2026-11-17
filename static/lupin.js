/**
 * Layered Lupin face (/static/lupin.js)
 *
 * Draws the husky from the SVGs in /static/lupin/layers/ and the table in
 * /static/lupin/expressions.json (the same table the ESP32/LVGL Body uses).
 * Exposes the public API on window.LupinFace.
 */
(function (global) {
  'use strict';

  const BASE = '/static/lupin/';
  const TABLE_URL = BASE + 'expressions.json';
  const WIDTH = 480;
  const HEIGHT = 320;

  const SUPPORTED_STATES = Object.freeze(['idle', 'listening', 'thinking', 'speaking', 'error']);
  const SUPPORTED_EMOTIONS = Object.freeze([
    'neutral', 'happy', 'excited', 'curious', 'skeptical', 'surprised',
    'sad', 'wink', 'love', 'sleepy', 'angry', 'dizzy',
  ]);
  const SUPPORTED_ACCESSORIES = Object.freeze(['none', 'headphones', 'pomodoro']);

  const IDLE_SLEEP_TIMEOUT_MS = 90000;
  const MANUAL_GAZE_MS = 2500;
  const BLINK_MS = 130;

  function clamp(value, min, max) {
    if (typeof value !== 'number' || Number.isNaN(value)) return min;
    return Math.min(max, Math.max(min, value));
  }

  function lerp(current, target, factor) {
    return current + (target - current) * factor;
  }

  function nowMs() {
    return typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now();
  }

  /**
   * Resolves the variant of each layer. Pure: precedence order is
   * default < expression < state < blink < speech.
   */
  function resolveLayers(table, input) {
    const layers = Object.assign({}, table.default);
    const expression = table.expressions[input.emotion] || {};
    const state = table.states[input.state] || {};
    let tilt = 0;
    let gaze = null;
    [expression, state].forEach((source) => {
      Object.keys(source).forEach((key) => {
        if (key === 'tilt') tilt = source[key];
        else if (key === 'gaze') gaze = source[key];
        else if (key === 'speaking') return;
        else if (table.layers[key]) layers[key] = source[key];
      });
    });
    // Blink: the table says which pose replaces each one (empty until closed-eyes art exists).
    const blink = table.blink || {};
    if (input.blinking && blink[layers.pose]) {
      layers.pose = blink[layers.pose];
    }
    // Speaking: with whole poses the mouth opens by switching to the open-mouth pose.
    if (state.speaking && table.speech && input.audioLevel >= table.speech.threshold) {
      layers.pose = table.speech.pose;
    }
    return { layers, tilt, gaze };
  }

  const internal = {
    container: null,
    root: null,
    stage: null,
    breath: null,
    headGroup: null,
    body: null,
    imgs: {},
    layerEl: {},
    visivel: {},
    table: null,
    loading: false,
    state: 'idle',
    emotion: 'neutral',
    emotionTimer: null,
    audioLevel: 0,
    blinking: false,
    nextBlink: 0,
    blinkEnd: 0,
    gazeX: 0,
    gazeY: 0,
    targetX: 0,
    targetY: 0,
    manualGazeUntil: 0,
    nextGaze: 0,
    tilt: 0,
    currentTilt: 0,
    lastInteraction: 0,
    sleepy: false,
    music: false,
    accessory: 'none',
    compact: false,
    clicks: [],
    trickTimers: [],
    activeTrick: null,
    rafId: null,
    scale: 0,
    motionQuery: null,
    motionListener: null,
    reduceMotion: false,
  };

  function shouldReduceMotion() {
    return internal.reduceMotion;
  }

  function clearMotionPreference() {
    if (internal.motionQuery && internal.motionListener) {
      if (typeof internal.motionQuery.removeEventListener === 'function') {
        internal.motionQuery.removeEventListener('change', internal.motionListener);
      }
    }
    internal.motionQuery = null;
    internal.motionListener = null;
  }

  function bindMotionPreference() {
    clearMotionPreference();
    if (typeof global.matchMedia !== 'function') {
      internal.reduceMotion = false;
      return;
    }
    const query = global.matchMedia('(prefers-reduced-motion: reduce)');
    internal.reduceMotion = Boolean(query && query.matches);
    if (query && typeof query.addEventListener === 'function') {
      internal.motionListener = (event) => {
        internal.reduceMotion = Boolean(event.matches);
        if (internal.reduceMotion) settle();
        apply();
      };
      query.addEventListener('change', internal.motionListener);
      internal.motionQuery = query;
    }
  }

  // With reduced motion, everything stops on the static pose of the current expression.
  function settle() {
    internal.blinking = false;
    internal.gazeX = 0;
    internal.gazeY = 0;
    internal.targetX = 0;
    internal.targetY = 0;
    internal.currentTilt = internal.tilt;
    if (internal.breath) internal.breath.style.transform = '';
    transformGaze();
  }

  function registerInteraction(ts) {
    internal.lastInteraction = typeof ts === 'number' ? ts : nowMs();
    internal.sleepy = false;
  }

  function create(tag, className) {
    const el = global.document.createElement(tag);
    if (className) el.className = className;
    return el;
  }

  function buildDom(container) {
    container.textContent = '';
    const root = create('div', 'lupin-root');
    root.setAttribute('role', 'img');
    root.setAttribute('aria-label', 'Lupin, the pet husky');
    const stage = create('div', 'lupin-stage');
    const breath = create('div', 'lupin-breath');
    stage.appendChild(breath);
    root.appendChild(stage);
    container.appendChild(root);
    internal.container = container;
    internal.root = root;
    internal.stage = stage;
    internal.breath = breath;
    internal.headGroup = null;
    internal.body = null;
    internal.imgs = {};
    internal.layerEl = {};
    internal.visivel = {};
  }

  function buildLayers() {
    const table = internal.table;
    const breath = internal.breath;
    breath.textContent = '';
    internal.imgs = {};
    internal.layerEl = {};
    internal.visivel = {};
    const insideHead = new Set(table.headGroup);
    const group = create('div', 'lupin-head-group');
    internal.headGroup = group;
    let groupAttached = false;
    table.layerOrder.forEach((name) => {
      const layer = create('div', 'lupin-layer lupin-layer-' + name);
      layer.dataset.layer = name;
      internal.imgs[name] = {};
      internal.layerEl[name] = layer;
      table.layers[name].forEach((variant) => {
        const img = create('img', 'lupin-variant');
        img.setAttribute('src', BASE + 'layers/' + name + '/' + variant + '.svg');
        img.setAttribute('alt', '');
        img.setAttribute('draggable', 'false');
        img.hidden = true;
        layer.appendChild(img);
        internal.imgs[name][variant] = img;
      });
      if (insideHead.has(name)) {
        group.appendChild(layer);
        if (!groupAttached) {
          breath.appendChild(group);
          groupAttached = true;
        }
      } else {
        breath.appendChild(layer);
      }
    });
    const body = create('img', 'lupin-body');
    body.setAttribute('alt', '');
    body.setAttribute('draggable', 'false');
    body.hidden = true;
    internal.stage.appendChild(body);
    internal.body = body;
  }

  function loadTable() {
    if (internal.loading || internal.table || typeof global.fetch !== 'function') return;
    internal.loading = true;
    Promise.resolve(global.fetch(TABLE_URL))
      .then((response) => {
        if (!response || response.ok === false) throw new Error('HTTP ' + (response && response.status));
        return response.json();
      })
      .then((table) => {
        internal.table = table;
        internal.loading = false;
        if (internal.stage) {
          buildLayers();
          apply();
        }
      })
      .catch((error) => {
        internal.loading = false;
        if (typeof console !== 'undefined' && console.warn) {
          console.warn('[LupinFace] Could not load the expressions table:', error);
        }
      });
  }

  function effectiveEmotion() {
    if (internal.sleepy && internal.emotion === 'neutral') return 'sleepy';
    return internal.emotion;
  }

  function currentInput() {
    return {
      emotion: effectiveEmotion(),
      state: internal.state,
      blinking: internal.blinking,
      audioLevel: internal.audioLevel,
    };
  }

  function transformGaze() {
    if (!internal.table || !internal.layerEl.eyes) return;
    const dx = (internal.gazeX * 9).toFixed(2);
    const dy = (internal.gazeY * 6).toFixed(2);
    const value = 'translate(' + dx + 'px, ' + dy + 'px)';
    ['eyes', 'eyebrows'].forEach((name) => {
      const layer = internal.layerEl[name];
      if (layer) layer.style.transform = value;
    });
  }

  function transformHead() {
    if (!internal.headGroup) return;
    const degrees = internal.currentTilt.toFixed(2);
    const px = (internal.gazeX * 3).toFixed(2);
    internal.headGroup.style.transform = 'translate(' + px + 'px, 0) rotate(' + degrees + 'deg)';
  }

  function updateAttributes() {
    const root = internal.root;
    if (!root) return;
    root.dataset.state = internal.state;
    root.dataset.emotion = effectiveEmotion();
    root.dataset.compact = internal.compact ? 'true' : 'false';
    root.dataset.accessory = internal.accessory;
    root.classList.toggle('lupin-compact', internal.compact);
    root.classList.toggle('lupin-speaking', internal.state === 'speaking');
  }

  // Applies the current logical state to the visible layers.
  function apply() {
    updateAttributes();
    if (!internal.table || !internal.stage || !internal.headGroup) return;
    const resolved = resolveLayers(internal.table, currentInput());
    Object.keys(resolved.layers).forEach((name) => {
      const chosen = resolved.layers[name];
      if (internal.visivel[name] === chosen) return;
      const variants = internal.imgs[name];
      if (!variants || !variants[chosen]) return;
      if (internal.visivel[name] && variants[internal.visivel[name]]) {
        variants[internal.visivel[name]].hidden = true;
      }
      variants[chosen].hidden = false;
      internal.visivel[name] = chosen;
    });
    internal.tilt = resolved.tilt || 0;
    if (resolved.gaze && Date.now() > internal.manualGazeUntil) {
      internal.targetX = resolved.gaze.x;
      internal.targetY = resolved.gaze.y;
    }
    if (shouldReduceMotion()) {
      internal.currentTilt = internal.tilt;
      transformHead();
    }
  }

  function fitScale() {
    if (!internal.root || !internal.stage) return;
    const w = internal.root.clientWidth || WIDTH;
    const h = internal.root.clientHeight || HEIGHT;
    const k = Math.min(w / WIDTH, h / HEIGHT);
    if (Math.abs(k - internal.scale) < 0.001) return;
    internal.scale = k;
    internal.stage.style.transform = 'translate(-50%, -50%) scale(' + k.toFixed(4) + ')';
  }

  function scheduleBlink(ts) {
    internal.nextBlink = ts + 2600 + Math.random() * 3600;
  }

  function step(ts) {
    internal.rafId = null;
    if (!internal.root) return;
    fitScale();
    const reduce = shouldReduceMotion();

    if (!reduce) {
      if (ts >= internal.nextBlink && !internal.blinking) {
        internal.blinking = true;
        internal.blinkEnd = ts + BLINK_MS;
        scheduleBlink(ts);
        apply();
      } else if (internal.blinking && ts >= internal.blinkEnd) {
        internal.blinking = false;
        apply();
      }

      // Look around when nobody is steering the gaze.
      if (Date.now() > internal.manualGazeUntil && internal.state !== 'thinking') {
        if (ts >= internal.nextGaze) {
          internal.targetX = (Math.random() - 0.5) * 1.0;
          internal.targetY = (Math.random() - 0.5) * 0.5;
          internal.nextGaze = ts + 3000 + Math.random() * 4000;
        }
      }
      internal.gazeX = lerp(internal.gazeX, internal.targetX, 0.12);
      internal.gazeY = lerp(internal.gazeY, internal.targetY, 0.12);
      transformGaze();

      let targetTilt = internal.tilt;
      if (internal.music) targetTilt += Math.sin(ts / 260) * 2.2;
      internal.currentTilt = lerp(internal.currentTilt, targetTilt, 0.14);
      transformHead();

      const breathing = 1 + 0.012 * Math.sin(ts / 900);
      internal.breath.style.transform = 'scale(' + breathing.toFixed(4) + ')';

      if (internal.state === 'idle' && !internal.sleepy && ts - internal.lastInteraction > IDLE_SLEEP_TIMEOUT_MS) {
        internal.sleepy = true;
        apply();
      }
    }

    if (internal.state === 'speaking') {
      apply();
      const collar = internal.layerEl.collar;
      if (collar) {
        const glow = 3 + internal.audioLevel * 12;
        collar.style.filter = 'drop-shadow(0 0 ' + glow.toFixed(1) + 'px #22d3ee)';
      }
    }

    if (typeof global.requestAnimationFrame === 'function') {
      internal.rafId = global.requestAnimationFrame(step);
    }
  }

  function clearTrick() {
    internal.trickTimers.forEach((id) => clearTimeout(id));
    internal.trickTimers = [];
    internal.activeTrick = null;
    if (internal.body) internal.body.hidden = true;
    if (internal.root) internal.root.classList.remove('lupin-full-body');
    if (internal.stage) {
      const effects = internal.stage.effects || [];
      effects.forEach((el) => el.parentNode && el.parentNode.removeChild(el));
      internal.stage.effects = [];
    }
  }

  function schedule(fn, ms) {
    const id = setTimeout(fn, ms);
    internal.trickTimers.push(id);
    return id;
  }

  function launchEffect(kind, count) {
    if (!internal.stage || shouldReduceMotion()) return;
    internal.stage.effects = internal.stage.effects || [];
    for (let i = 0; i < count; i += 1) {
      const el = create('i', 'lupin-effect lupin-effect-' + kind);
      el.style.setProperty('--i', String(i));
      el.style.setProperty('--x', String(Math.round((i / Math.max(1, count - 1)) * 100)));
      internal.stage.appendChild(el);
      internal.stage.effects.push(el);
    }
  }

  const LupinFace = {
    init(containerEl) {
      let container = containerEl;
      if (typeof container === 'string' && global.document && global.document.querySelector) {
        container = global.document.querySelector(container);
      }
      if (!container) {
        throw new Error('LupinFace.init: containerEl is invalid or was not found.');
      }
      if (internal.rafId !== null && typeof global.cancelAnimationFrame === 'function') {
        global.cancelAnimationFrame(internal.rafId);
        internal.rafId = null;
      }
      clearTrick();
      buildDom(container);
      bindMotionPreference();
      internal.scale = 0;
      const ts = nowMs();
      registerInteraction(ts);
      scheduleBlink(ts);
      internal.nextGaze = ts + 2500;
      if (internal.table) buildLayers();
      else loadTable();
      apply();
      fitScale();
      if (typeof global.requestAnimationFrame === 'function') {
        internal.rafId = global.requestAnimationFrame(step);
      }
      return LupinFace;
    },

    setState(state) {
      if (!SUPPORTED_STATES.includes(state)) {
        if (typeof console !== 'undefined' && console.warn) {
          console.warn('[LupinFace] Unknown state ignored: ' + state);
        }
        return internal.state;
      }
      internal.state = state;
      if (state !== 'speaking') internal.audioLevel = 0;
      if (state !== 'speaking' && internal.layerEl.collar) {
        internal.layerEl.collar.style.filter = '';
      }
      registerInteraction();
      apply();
      return internal.state;
    },

    setEmotion(emotion, opts) {
      if (!SUPPORTED_EMOTIONS.includes(emotion)) {
        if (typeof console !== 'undefined' && console.warn) {
          console.warn('[LupinFace] Unknown emotion ignored: ' + emotion);
        }
        return internal.emotion;
      }
      if (internal.emotionTimer !== null) {
        clearTimeout(internal.emotionTimer);
        internal.emotionTimer = null;
      }
      internal.emotion = emotion;
      registerInteraction();
      if (opts && typeof opts.durationMs === 'number' && opts.durationMs > 0) {
        internal.emotionTimer = setTimeout(() => {
          internal.emotionTimer = null;
          internal.emotion = 'neutral';
          apply();
        }, opts.durationMs);
      }
      apply();
      return internal.emotion;
    },

    lookAt(x, y) {
      internal.targetX = clamp(Number(x), -1, 1);
      internal.targetY = clamp(Number(y), -1, 1);
      internal.manualGazeUntil = Date.now() + MANUAL_GAZE_MS;
      registerInteraction();
      if (shouldReduceMotion()) {
        internal.gazeX = 0;
        internal.gazeY = 0;
      }
    },

    blink() {
      if (shouldReduceMotion()) return;
      internal.blinking = true;
      internal.blinkEnd = nowMs() + BLINK_MS;
      apply();
    },

    setAudioLevel(level) {
      internal.audioLevel = clamp(Number(level), 0, 1);
    },

    getState() {
      return internal.state;
    },

    getEmotion() {
      return internal.emotion;
    },

    getSupportedEmotions() {
      return SUPPORTED_EMOTIONS.slice();
    },

    getSupportedStates() {
      return SUPPORTED_STATES.slice();
    },

    getTricks() {
      return internal.table ? Object.keys(internal.table.tricks) : [];
    },

    /**
     * Direct touch. 'pet' makes Lupin happy; 'poke' startles him, and
     * repeated pokes annoy him.
     */
    reactToTouch(kind, nx, ny) {
      registerInteraction();
      const audio = global.EmoAudio;
      if (kind === 'pet') {
        LupinFace.setEmotion('happy', { durationMs: 2400 });
        LupinFace.lookAt(nx, ny);
        if (audio && typeof audio.purr === 'function') audio.purr(true);
        return;
      }
      if (kind === 'poke') {
        const nowTs = Date.now();
        internal.clicks = internal.clicks.filter((t) => nowTs - t < 3000);
        internal.clicks.push(nowTs);
        const n = internal.clicks.length;
        if (n >= 3) {
          LupinFace.setEmotion('angry', { durationMs: 3600 });
          if (audio && typeof audio.chirp === 'function') audio.chirp('angry');
        } else if (n === 2) {
          LupinFace.setEmotion('skeptical', { durationMs: 3000 });
          if (audio && typeof audio.chirp === 'function') audio.chirp('skeptical');
        } else {
          LupinFace.setEmotion('surprised', { durationMs: 900 });
          if (audio && typeof audio.click === 'function') audio.click();
        }
        LupinFace.lookAt(nx, ny);
      }
    },

    // Accessories are registered; their art arrives with the final art.
    setAccessory(name) {
      if (!SUPPORTED_ACCESSORIES.includes(name)) return internal.accessory;
      internal.accessory = name;
      updateAttributes();
      return internal.accessory;
    },

    setCompactMode(active) {
      internal.compact = Boolean(active);
      updateAttributes();
    },

    setMusicPlaying(active) {
      internal.music = Boolean(active);
      if (!internal.music && !shouldReduceMotion()) internal.currentTilt = internal.tilt;
    },

    getHitboxRect() {
      if (!internal.stage || typeof internal.stage.getBoundingClientRect !== 'function') return null;
      return internal.stage.getBoundingClientRect();
    },

    /**
     * Tricks come from the table: 'body' swaps the bust for full-body
     * frames during the Trick; 'bust' stays on the bust with an expression and effect.
     */
    playTrick(trickId) {
      const id = typeof trickId === 'string' ? trickId.toLowerCase() : '';
      const trick = internal.table && internal.table.tricks[id];
      if (!trick) return false;
      registerInteraction();
      clearTrick();
      internal.activeTrick = id;

      if (trick.mode === 'bust') {
        LupinFace.setEmotion(trick.expression, { durationMs: trick.durationMs });
        const count = { notes: 6, rings: 3, confetti: 18 }[trick.effect] || 0;
        launchEffect(trick.effect, count);
        schedule(() => clearTrick(), trick.durationMs);
        return true;
      }

      if (shouldReduceMotion()) {
        LupinFace.setEmotion(id === 'nap' ? 'sleepy' : 'happy', { durationMs: trick.durationMs });
        internal.activeTrick = null;
        return true;
      }

      const frames = trick.frames;
      let index = 0;
      const show = () => {
        if (!internal.body) return;
        internal.body.setAttribute('src', BASE + 'body/' + frames[index % frames.length] + '.svg');
        internal.body.hidden = false;
        index += 1;
      };
      internal.root.classList.add('lupin-full-body');
      show();
      for (let t = trick.intervalMs; t < trick.durationMs; t += trick.intervalMs) {
        schedule(show, t);
      }
      schedule(() => clearTrick(), trick.durationMs);
      return true;
    },

    isTrickPlaying() {
      return internal.activeTrick !== null;
    },
  };

  LupinFace.resolveLayers = resolveLayers;
  global.LupinFace = LupinFace;
})(typeof window !== 'undefined' ? window : globalThis);
