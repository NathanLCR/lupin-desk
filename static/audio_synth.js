/**
 * Procedural audio synthesizer via the Web Audio API (/static/audio_synth.js)
 * Generates the pet's emotional sound vocabulary (Vector/Cozmo style) 100% in real time,
 * with no external MP3/WAV files, exposing the public API on window.EmoAudio.
 */
(function (global) {
  'use strict';

  const internal = {
    ctx: null,
    masterGain: null,
    compressor: null,
    muted: false,
    initialized: false,
    unlocked: false,

    // Active envelopes, used to sync micro-pulses in the eyes with AudioContext.currentTime
    envelopes: [],

    // Nodes of the continuous purr (~60Hz with LFO)
    purr: {
      active: false,
      osc: null,
      subOsc: null,
      lfo: null,
      lfoGain: null,
      breathLfo: null,
      breathGain: null,
      filter: null,
      baseGain: null,
      lfoScaleGain: null,
      cleanupTimer: null,
      startedAt: 0,
    },
  };

  function nowSec() {
    if (internal.ctx && typeof internal.ctx.currentTime === 'number') {
      return internal.ctx.currentTime;
    }
    if (typeof performance !== 'undefined' && performance.now) {
      return performance.now() / 1000;
    }
    return Date.now() / 1000;
  }

  function clamp(value, min, max) {
    if (typeof value !== 'number' || Number.isNaN(value)) {
      return min;
    }
    return Math.min(max, Math.max(min, value));
  }

  function getAudioContextCtor() {
    if (!global) return null;
    return global.AudioContext || global.webkitAudioContext || null;
  }

  function ensureContext() {
    if (internal.ctx && internal.ctx.state !== 'closed') {
      return internal.ctx;
    }
    const Ctor = getAudioContextCtor();
    if (!Ctor) {
      return null;
    }
    try {
      const ctx = new Ctor();
      const masterGain = ctx.createGain();
      masterGain.gain.setValueAtTime(internal.muted ? 0 : 0.72, ctx.currentTime);

      const compressor = ctx.createDynamicsCompressor();
      compressor.threshold.setValueAtTime(-16, ctx.currentTime);
      compressor.knee.setValueAtTime(18, ctx.currentTime);
      compressor.ratio.setValueAtTime(6, ctx.currentTime);
      compressor.attack.setValueAtTime(0.005, ctx.currentTime);
      compressor.release.setValueAtTime(0.12, ctx.currentTime);

      masterGain.connect(compressor);
      compressor.connect(ctx.destination);

      internal.ctx = ctx;
      internal.masterGain = masterGain;
      internal.compressor = compressor;
      if (ctx.state === 'running') {
        internal.unlocked = true;
      }
      return ctx;
    } catch {
      return null;
    }
  }

  function canScheduleAudio() {
    const ctx = ensureContext();
    if (!ctx || internal.muted) {
      return false;
    }
    if (ctx.state === 'running') {
      internal.unlocked = true;
      return true;
    }
    // Avoid queueing stale beeps before the first unlock gesture
    if (internal.unlocked && typeof ctx.resume === 'function') {
      ctx.resume().catch(() => {});
      return true;
    }
    return false;
  }

  function registerEnvelope(delaySec, attackSec, holdSec, releaseSec, peak) {
    const start = nowSec() + Math.max(0, delaySec || 0);
    const att = Math.max(0.005, attackSec || 0.01);
    const hold = Math.max(0, holdSec || 0);
    const rel = Math.max(0.02, releaseSec || 0.08);
    const amp = clamp(peak || 0.5, 0, 1);

    // Drop finished envelopes to keep the list small
    const cur = nowSec();
    internal.envelopes = internal.envelopes.filter(
      (env) => cur <= env.start + env.attack + env.hold + env.release + 0.05
    );
    internal.envelopes.push({
      start,
      attack: att,
      hold,
      release: rel,
      peak: amp,
    });
  }

  /**
   * Schedules a procedural tone with frequency glide, optional filter and FM modulation.
   */
  function playTone(opts) {
    if (!canScheduleAudio()) {
      return;
    }
    const ctx = internal.ctx;
    const baseTime = ctx.currentTime;
    const delay = Math.max(0, opts.delay || 0);
    const startTime = baseTime + delay;
    const duration = Math.max(0.025, opts.duration || 0.1);
    const attack = Math.min(duration * 0.35, Math.max(0.005, opts.attack || 0.012));
    const release = Math.max(0.015, opts.release || duration * 0.45);
    const hold = Math.max(0, duration - attack - release * 0.4);
    const peakGain = clamp(opts.gain != null ? opts.gain : 0.22, 0.001, 0.9);

    const startFreq = Math.max(30, opts.startFreq || 440);
    const endFreq = Math.max(30, opts.endFreq != null ? opts.endFreq : startFreq);

    const osc = ctx.createOscillator();
    osc.type = opts.type || 'sine';
    osc.frequency.setValueAtTime(startFreq, startTime);

    if (endFreq !== startFreq) {
      if (opts.linearGlide) {
        osc.frequency.linearRampToValueAtTime(endFreq, startTime + duration);
      } else {
        osc.frequency.exponentialRampToValueAtTime(endFreq, startTime + duration);
      }
    }

    // Optional FM modulation for a robotic Vector/Cozmo-style timbre
    let fmOsc = null;
    let fmGain = null;
    if (opts.fmFreq && opts.fmDepth) {
      fmOsc = ctx.createOscillator();
      fmGain = ctx.createGain();
      fmOsc.type = opts.fmType || 'sine';
      fmOsc.frequency.setValueAtTime(opts.fmFreq, startTime);
      fmGain.gain.setValueAtTime(opts.fmDepth, startTime);
      if (opts.fmEndDepth != null) {
        fmGain.gain.linearRampToValueAtTime(opts.fmEndDepth, startTime + duration);
      }
      fmOsc.connect(fmGain);
      fmGain.connect(osc.frequency);
    }

    const envGain = ctx.createGain();
    envGain.gain.setValueAtTime(0.0001, startTime);
    envGain.gain.linearRampToValueAtTime(peakGain, startTime + attack);
    envGain.gain.setValueAtTime(peakGain, startTime + attack + hold);
    envGain.gain.exponentialRampToValueAtTime(0.0001, startTime + duration + release * 0.6);

    let outputNode = osc;
    let filter = null;
    if (opts.filterFreq) {
      filter = ctx.createBiquadFilter();
      filter.type = opts.filterType || 'lowpass';
      filter.frequency.setValueAtTime(opts.filterFreq, startTime);
      if (opts.filterEndFreq) {
        filter.frequency.exponentialRampToValueAtTime(
          Math.max(40, opts.filterEndFreq),
          startTime + duration
        );
      }
      filter.Q.setValueAtTime(opts.filterQ || 1.4, startTime);
      osc.connect(filter);
      outputNode = filter;
    }

    outputNode.connect(envGain);
    envGain.connect(internal.masterGain);

    const stopAt = startTime + duration + release * 0.65 + 0.02;
    osc.start(startTime);
    osc.stop(stopAt);
    if (fmOsc) {
      fmOsc.start(startTime);
      fmOsc.stop(stopAt);
    }

    osc.onended = () => {
      try {
        osc.disconnect();
        envGain.disconnect();
        if (filter) filter.disconnect();
        if (fmOsc) fmOsc.disconnect();
        if (fmGain) fmGain.disconnect();
      } catch {
        // Ignore redundant disconnect
      }
    };

    registerEnvelope(delay, attack, hold, release, clamp(peakGain * 2.4, 0.12, 1));
  }

  function cleanupPurrNodes() {
    const p = internal.purr;
    const nodes = [
      p.osc,
      p.subOsc,
      p.lfo,
      p.lfoGain,
      p.breathLfo,
      p.breathGain,
      p.filter,
      p.baseGain,
      p.lfoScaleGain,
    ];
    nodes.forEach((node) => {
      if (!node) return;
      try {
        if (typeof node.stop === 'function') {
          node.stop();
        }
      } catch {
        // Node already stopped
      }
      try {
        node.disconnect();
      } catch {
        // Node already disconnected
      }
    });
    p.osc = null;
    p.subOsc = null;
    p.lfo = null;
    p.lfoGain = null;
    p.breathLfo = null;
    p.breathGain = null;
    p.filter = null;
    p.baseGain = null;
    p.lfoScaleGain = null;
  }

  function startPurr() {
    const p = internal.purr;
    if (p.cleanupTimer) {
      clearTimeout(p.cleanupTimer);
      p.cleanupTimer = null;
    }
    if (!canScheduleAudio()) {
      return;
    }
    const ctx = internal.ctx;
    const t = ctx.currentTime;

    if (p.active && p.baseGain) {
      p.baseGain.gain.cancelScheduledValues(t);
      p.baseGain.gain.setTargetAtTime(0.14, t, 0.08);
      return;
    }

    cleanupPurrNodes();

    // Main oscillator ~60Hz with a soft harmonic
    const osc = ctx.createOscillator();
    osc.type = 'sawtooth';
    osc.frequency.setValueAtTime(60, t);

    const subOsc = ctx.createOscillator();
    subOsc.type = 'sine';
    subOsc.frequency.setValueAtTime(120, t);

    const subGain = ctx.createGain();
    subGain.gain.setValueAtTime(0.28, t);

    const filter = ctx.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.setValueAtTime(185, t);
    filter.Q.setValueAtTime(2.4, t);

    const baseGain = ctx.createGain();
    baseGain.gain.setValueAtTime(0.0001, t);
    baseGain.gain.linearRampToValueAtTime(0.14, t + 0.22);

    // Purr vibration LFO (~22Hz) + slow breathing LFO (~1.3Hz)
    const lfo = ctx.createOscillator();
    lfo.type = 'sine';
    lfo.frequency.setValueAtTime(22, t);

    const lfoGain = ctx.createGain();
    lfoGain.gain.setValueAtTime(0.055, t);

    const breathLfo = ctx.createOscillator();
    breathLfo.type = 'sine';
    breathLfo.frequency.setValueAtTime(1.3, t);

    const breathGain = ctx.createGain();
    breathGain.gain.setValueAtTime(0.035, t);

    osc.connect(filter);
    subOsc.connect(subGain);
    subGain.connect(filter);
    filter.connect(baseGain);

    lfo.connect(lfoGain);
    lfoGain.connect(baseGain.gain);

    breathLfo.connect(breathGain);
    breathGain.connect(baseGain.gain);

    baseGain.connect(internal.masterGain);

    osc.start(t);
    subOsc.start(t);
    lfo.start(t);
    breathLfo.start(t);

    p.active = true;
    p.startedAt = t;
    p.osc = osc;
    p.subOsc = subOsc;
    p.lfo = lfo;
    p.lfoGain = lfoGain;
    p.breathLfo = breathLfo;
    p.breathGain = breathGain;
    p.filter = filter;
    p.baseGain = baseGain;
    p.lfoScaleGain = subGain;
  }

  function stopPurr() {
    const p = internal.purr;
    if (!p.active && !p.baseGain) {
      return;
    }
    p.active = false;
    if (p.cleanupTimer) {
      clearTimeout(p.cleanupTimer);
      p.cleanupTimer = null;
    }

    if (internal.ctx && p.baseGain) {
      const t = internal.ctx.currentTime;
      try {
        p.baseGain.gain.cancelScheduledValues(t);
        p.baseGain.gain.setValueAtTime(Math.max(0.0001, p.baseGain.gain.value), t);
        p.baseGain.gain.exponentialRampToValueAtTime(0.0001, t + 0.22);
      } catch {
        // Ignore error when ending the ramp
      }
      p.cleanupTimer = setTimeout(() => {
        p.cleanupTimer = null;
        if (!p.active) {
          cleanupPurrNodes();
        }
      }, 260);
    } else {
      cleanupPurrNodes();
    }
  }

  // Public API window.EmoAudio
  const EmoAudio = {
    init() {
      ensureContext();
      internal.initialized = true;
      return EmoAudio;
    },

    unlock() {
      internal.unlocked = true;
      const ctx = ensureContext();
      if (!ctx) {
        return Promise.resolve(false);
      }
      if (ctx.state === 'running') {
        return Promise.resolve(true);
      }
      if (typeof ctx.resume === 'function') {
        return ctx
          .resume()
          .then(() => ctx.state === 'running')
          .catch(() => false);
      }
      return Promise.resolve(false);
    },

    setMuted(muted) {
      internal.muted = Boolean(muted);
      if (internal.muted) {
        stopPurr();
      }
      if (internal.ctx && internal.masterGain) {
        const t = internal.ctx.currentTime;
        internal.masterGain.gain.cancelScheduledValues(t);
        internal.masterGain.gain.setTargetAtTime(internal.muted ? 0 : 0.72, t, 0.02);
      }
      return internal.muted;
    },

    isMuted() {
      return internal.muted;
    },

    /**
     * Emits a procedural emotional chirp in the Vector/Cozmo style.
     */
    chirp(emotion) {
      const key = typeof emotion === 'string' ? emotion.toLowerCase() : 'neutral';
      switch (key) {
        case 'happy':
          // Short, cheerful rising arpeggio
          playTone({ type: 'triangle', startFreq: 523, endFreq: 587, duration: 0.065, delay: 0, gain: 0.16, fmFreq: 18, fmDepth: 12 });
          playTone({ type: 'triangle', startFreq: 659, endFreq: 720, duration: 0.065, delay: 0.065, gain: 0.18, fmFreq: 20, fmDepth: 14 });
          playTone({ type: 'sine', startFreq: 784, endFreq: 932, duration: 0.11, delay: 0.13, gain: 0.2, fmFreq: 24, fmDepth: 16 });
          break;

        case 'excited':
          // Fast, bright 4-note arpeggio
          playTone({ type: 'triangle', startFreq: 587, endFreq: 640, duration: 0.055, delay: 0, gain: 0.17, fmFreq: 32, fmDepth: 18 });
          playTone({ type: 'triangle', startFreq: 740, endFreq: 790, duration: 0.055, delay: 0.052, gain: 0.19, fmFreq: 36, fmDepth: 22 });
          playTone({ type: 'sine', startFreq: 880, endFreq: 960, duration: 0.06, delay: 0.104, gain: 0.2, fmFreq: 42, fmDepth: 24 });
          playTone({ type: 'sine', startFreq: 1046, endFreq: 1280, duration: 0.12, delay: 0.16, gain: 0.22, fmFreq: 48, fmDepth: 28 });
          break;

        case 'curious':
          // Characteristic rising chirp 450Hz -> 950Hz
          playTone({
            type: 'triangle',
            startFreq: 450,
            endFreq: 950,
            duration: 0.17,
            gain: 0.2,
            fmFreq: 34,
            fmDepth: 26,
            filterFreq: 2400,
          });
          playTone({
            type: 'sine',
            startFreq: 920,
            endFreq: 1020,
            duration: 0.055,
            delay: 0.145,
            gain: 0.12,
          });
          break;

        case 'sad':
          // Soft falling glide
          playTone({
            type: 'triangle',
            startFreq: 520,
            endFreq: 230,
            duration: 0.3,
            gain: 0.18,
            filterFreq: 1300,
            filterEndFreq: 520,
          });
          break;

        case 'sleepy':
          // Low, filtered, falling sigh
          playTone({
            type: 'sine',
            startFreq: 310,
            endFreq: 145,
            duration: 0.36,
            gain: 0.15,
            filterFreq: 720,
            filterEndFreq: 260,
          });
          break;

        case 'angry':
          // Angry low metallic double beep
          playTone({
            type: 'sawtooth',
            startFreq: 230,
            endFreq: 165,
            duration: 0.095,
            delay: 0,
            gain: 0.2,
            fmFreq: 92,
            fmDepth: 115,
            filterFreq: 1050,
          });
          playTone({
            type: 'sawtooth',
            startFreq: 215,
            endFreq: 140,
            duration: 0.12,
            delay: 0.12,
            gain: 0.22,
            fmFreq: 98,
            fmDepth: 130,
            filterFreq: 980,
          });
          break;

        case 'error':
          // Two short metallic alert/error beeps
          playTone({
            type: 'square',
            startFreq: 340,
            endFreq: 290,
            duration: 0.08,
            delay: 0,
            gain: 0.15,
            fmFreq: 135,
            fmDepth: 95,
            filterFreq: 1500,
          });
          playTone({
            type: 'square',
            startFreq: 250,
            endFreq: 185,
            duration: 0.11,
            delay: 0.11,
            gain: 0.17,
            fmFreq: 120,
            fmDepth: 105,
            filterFreq: 1300,
          });
          break;

        case 'love':
          // Soft, welcoming tone with a warm harmonic
          playTone({
            type: 'sine',
            startFreq: 440,
            endFreq: 554,
            duration: 0.22,
            gain: 0.16,
            attack: 0.035,
            release: 0.14,
          });
          playTone({
            type: 'sine',
            startFreq: 659,
            endFreq: 880,
            duration: 0.24,
            delay: 0.05,
            gain: 0.1,
            attack: 0.04,
            release: 0.15,
          });
          break;

        case 'surprised':
          // Quick high pop
          playTone({
            type: 'sine',
            startFreq: 510,
            endFreq: 1320,
            duration: 0.105,
            gain: 0.2,
            fmFreq: 46,
            fmDepth: 32,
          });
          break;

        case 'wink':
          // Playful two-tap quick blip
          playTone({ type: 'sine', startFreq: 660, endFreq: 740, duration: 0.048, delay: 0, gain: 0.15 });
          playTone({ type: 'sine', startFreq: 880, endFreq: 980, duration: 0.065, delay: 0.055, gain: 0.17 });
          break;

        case 'dizzy':
          // Wobbling dizzy glide
          playTone({
            type: 'triangle',
            startFreq: 620,
            endFreq: 350,
            duration: 0.24,
            gain: 0.17,
            fmFreq: 15,
            fmDepth: 95,
            filterFreq: 1800,
          });
          playTone({
            type: 'sine',
            startFreq: 380,
            endFreq: 510,
            duration: 0.12,
            delay: 0.19,
            gain: 0.12,
            fmFreq: 14,
            fmDepth: 65,
          });
          break;

        case 'skeptical':
          // Short questioning/skeptical inflection
          playTone({
            type: 'triangle',
            startFreq: 480,
            endFreq: 410,
            duration: 0.08,
            delay: 0,
            gain: 0.15,
            filterFreq: 1500,
          });
          playTone({
            type: 'triangle',
            startFreq: 430,
            endFreq: 520,
            duration: 0.1,
            delay: 0.085,
            gain: 0.16,
            filterFreq: 1700,
          });
          break;

        case 'neutral':
        default:
          playTone({
            type: 'sine',
            startFreq: 540,
            endFreq: 600,
            duration: 0.055,
            gain: 0.09,
          });
          break;
      }
    },

    /**
     * Starts or gently stops the purr (~60Hz with LFO) while being petted.
     */
    purr(active) {
      if (active) {
        startPurr();
      } else {
        stopPurr();
      }
    },

    /**
     * Short tactile click for touches and UI.
     */
    click() {
      playTone({
        type: 'triangle',
        startFreq: 960,
        endFreq: 420,
        duration: 0.032,
        attack: 0.004,
        release: 0.02,
        gain: 0.13,
      });
    },

    /**
     * Short, clean attention/alert sound.
     */
    alert() {
      playTone({
        type: 'triangle',
        startFreq: 784,
        endFreq: 784,
        duration: 0.075,
        delay: 0,
        gain: 0.18,
        fmFreq: 110,
        fmDepth: 35,
      });
      playTone({
        type: 'sine',
        startFreq: 1046,
        endFreq: 1120,
        duration: 0.125,
        delay: 0.09,
        gain: 0.2,
      });
    },

    /**
     * Friendly wake-up sound for the assistant.
     */
    wake() {
      playTone({ type: 'sine', startFreq: 440, endFreq: 494, duration: 0.07, delay: 0, gain: 0.14 });
      playTone({ type: 'triangle', startFreq: 587, endFreq: 659, duration: 0.08, delay: 0.075, gain: 0.16, fmFreq: 24, fmDepth: 14 });
      playTone({ type: 'sine', startFreq: 880, endFreq: 988, duration: 0.14, delay: 0.16, gain: 0.19, fmFreq: 32, fmDepth: 16 });
    },

    /**
     * Procedural sound sequences for the pet's interactive tricks.
     */
    playTrick(trickId) {
      const id = typeof trickId === 'string' ? trickId.toLowerCase() : '';
      switch (id) {
        case 'dance':
          [523, 659, 784, 659, 880, 1046].forEach((freq, idx) => {
            playTone({ type: 'triangle', startFreq: freq, endFreq: freq * 1.04, duration: 0.11, delay: idx * 0.14, gain: 0.15 });
          });
          break;
        case 'sing':
          [523, 587, 659, 784, 880, 784, 1046].forEach((freq, idx) => {
            playTone({ type: 'sine', startFreq: freq, endFreq: freq, duration: 0.18, delay: idx * 0.2, gain: 0.16, fmFreq: 6, fmDepth: 14 });
          });
          break;
        case 'meditate':
          playTone({ type: 'sine', startFreq: 261, endFreq: 261, duration: 0.7, delay: 0, gain: 0.11, attack: 0.15, release: 0.4 });
          playTone({ type: 'sine', startFreq: 392, endFreq: 392, duration: 0.7, delay: 0.75, gain: 0.1, attack: 0.15, release: 0.4 });
          break;
        case 'nap':
          playTone({ type: 'sine', startFreq: 330, endFreq: 247, duration: 0.35, delay: 0, gain: 0.09, attack: 0.08, release: 0.2 });
          playTone({ type: 'sine', startFreq: 262, endFreq: 196, duration: 0.45, delay: 0.45, gain: 0.08, attack: 0.1, release: 0.25 });
          break;
        case 'celebrate':
          [523, 659, 784, 1046, 1318].forEach((freq, idx) => {
            playTone({ type: 'sine', startFreq: freq, endFreq: freq * 1.08, duration: 0.13, delay: idx * 0.085, gain: 0.18, fmFreq: 28, fmDepth: 18 });
          });
          break;
        case 'stretch':
          playTone({ type: 'triangle', startFreq: 320, endFreq: 620, duration: 0.32, delay: 0, gain: 0.13, attack: 0.06, release: 0.16 });
          playTone({ type: 'sine', startFreq: 640, endFreq: 520, duration: 0.22, delay: 0.36, gain: 0.11 });
          break;
        default:
          EmoAudio.wake();
          break;
      }
    },

    /**
     * Returns the current level (0..1) of the sound envelope, synced with AudioContext.currentTime.
     */
    getPulseLevel() {
      if (internal.muted) {
        return 0;
      }
      const cur = nowSec();
      let level = 0;

      for (let i = 0; i < internal.envelopes.length; i += 1) {
        const env = internal.envelopes[i];
        if (cur < env.start) continue;
        const elapsed = cur - env.start;
        const total = env.attack + env.hold + env.release;
        if (elapsed > total) continue;

        let factor = 0;
        if (elapsed < env.attack) {
          factor = elapsed / env.attack;
        } else if (elapsed < env.attack + env.hold) {
          factor = 1;
        } else {
          const relElapsed = elapsed - env.attack - env.hold;
          factor = Math.max(0, 1 - relElapsed / env.release);
        }
        level = Math.max(level, env.peak * factor);
      }

      if (internal.purr.active) {
        const purrMod = 0.22 + 0.16 * (0.5 + 0.5 * Math.sin(cur * Math.PI * 2 * 1.3));
        level = Math.max(level, purrMod);
      }

      return clamp(level, 0, 1);
    },
  };

  global.EmoAudio = EmoAudio;
})(typeof window !== 'undefined' ? window : globalThis);
