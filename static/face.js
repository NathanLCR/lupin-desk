/**
 * Rosto animado estilo EMO (/static/face.js)
 * Renderiza os olhos e expressões em SVG puro com animações a 60fps via
 * requestAnimationFrame, expondo a API pública em window.EmoFace.
 */
(function (global) {
  'use strict';

  // Estados operacionais suportados
  const SUPPORTED_STATES = Object.freeze([
    'idle',
    'listening',
    'thinking',
    'speaking',
    'error',
  ]);

  // Expressões faciais suportadas
  const SUPPORTED_EMOTIONS = Object.freeze([
    'neutral',
    'happy',
    'excited',
    'curious',
    'skeptical',
    'surprised',
    'sad',
    'wink',
    'love',
    'sleepy',
  ]);

  // Dimensões base dos olhos no viewBox 800x480
  const EYE_WIDTH = 148;
  const EYE_HEIGHT = 176;
  const EYE_HALF_W = EYE_WIDTH / 2;
  const EYE_HALF_H = EYE_HEIGHT / 2;
  const EYE_BASE_RX = 46;
  const LEFT_EYE_X = 260;
  const RIGHT_EYE_X = 540;
  const EYE_CENTER_Y = 226;

  // Tempo de inatividade em idle para entrar no modo sonolento visual (90s)
  const IDLE_SLEEP_TIMEOUT_MS = 90000;

  // Helpers numéricos
  function clamp(value, min, max) {
    if (typeof value !== 'number' || Number.isNaN(value)) {
      return min;
    }
    return Math.min(max, Math.max(min, value));
  }

  function lerp(current, target, factor) {
    return current + (target - current) * factor;
  }

  function createDefaultEyePose() {
    return {
      upperOuter: -98,
      upperMid: -98,
      upperInner: -98,
      lowerOuter: 98,
      lowerMid: 98,
      lowerInner: 98,
      scaleX: 1,
      scaleY: 1,
      rx: EYE_BASE_RX,
      capsuleOpacity: 1,
      heartOpacity: 0,
      errorOpacity: 0,
      highlightOpacity: 1,
    };
  }

  // Calcula os alvos geométricos de cada olho conforme emoção + estado
  function resolveEyeTargets(emotion, state, autoSleepy) {
    const left = createDefaultEyePose();
    const right = createDefaultEyePose();
    const effectiveEmotion = autoSleepy && emotion === 'neutral' ? 'sleepy' : emotion;

    let headTiltDeg = 0;
    let gazeBiasX = 0;
    let gazeBiasY = 0;

    // 1. Aplica expressão facial
    switch (effectiveEmotion) {
      case 'happy':
        left.lowerOuter = 54;
        left.lowerMid = -28;
        left.lowerInner = 54;
        left.scaleX = 1.03;
        left.scaleY = 1.02;

        right.lowerOuter = 54;
        right.lowerMid = -28;
        right.lowerInner = 54;
        right.scaleX = 1.03;
        right.scaleY = 1.02;
        break;

      case 'excited':
        left.scaleX = 1.08;
        left.scaleY = 1.09;
        left.rx = 52;
        left.lowerMid = 66;

        right.scaleX = 1.08;
        right.scaleY = 1.09;
        right.rx = 52;
        right.lowerMid = 66;
        break;

      case 'curious':
        left.scaleX = 0.88;
        left.scaleY = 0.88;
        left.rx = 42;

        right.scaleX = 1.15;
        right.scaleY = 1.16;
        right.rx = 60;

        headTiltDeg = -5;
        gazeBiasX = 0.14;
        gazeBiasY = -0.08;
        break;

      case 'skeptical':
        // Olho esquerdo semicerrado reto (-_-) e direito levantado (o_O)
        left.upperOuter = -12;
        left.upperMid = -12;
        left.upperInner = -12;
        left.lowerOuter = 34;
        left.lowerMid = 34;
        left.lowerInner = 34;
        left.scaleX = 1.04;
        left.scaleY = 0.96;

        right.scaleX = 1.08;
        right.scaleY = 1.12;
        right.rx = 56;
        headTiltDeg = 2.5;
        break;

      case 'surprised':
        left.scaleX = 1.12;
        left.scaleY = 1.14;
        left.rx = 74;

        right.scaleX = 1.12;
        right.scaleY = 1.14;
        right.rx = 74;
        break;

      case 'sad':
        // Cantos externos das pálpebras superiores caídos para baixo (/ \)
        left.upperOuter = 18;
        left.upperMid = -26;
        left.upperInner = -66;
        left.scaleY = 0.94;

        right.upperOuter = 18;
        right.upperMid = -26;
        right.upperInner = -66;
        right.scaleY = 0.94;

        gazeBiasY = 0.36;
        break;

      case 'wink':
        // Olho esquerdo aberto amigável; olho direito fechado em arco alegre
        left.lowerMid = 72;
        left.scaleX = 1.04;
        left.scaleY = 1.04;

        right.upperOuter = -54;
        right.upperMid = -72;
        right.upperInner = -54;
        right.lowerOuter = 44;
        right.lowerMid = -38;
        right.lowerInner = 44;
        right.highlightOpacity = 0;
        break;

      case 'love':
        left.capsuleOpacity = 0;
        left.heartOpacity = 1;
        left.highlightOpacity = 0;

        right.capsuleOpacity = 0;
        right.heartOpacity = 1;
        right.highlightOpacity = 0;
        break;

      case 'sleepy':
        left.upperOuter = -4;
        left.upperMid = 8;
        left.upperInner = -4;
        left.lowerOuter = 80;
        left.lowerMid = 74;
        left.lowerInner = 80;
        left.scaleY = 0.94;

        right.upperOuter = -4;
        right.upperMid = 8;
        right.upperInner = -4;
        right.lowerOuter = 80;
        right.lowerMid = 74;
        right.lowerInner = 80;
        right.scaleY = 0.94;
        break;

      case 'neutral':
      default:
        break;
    }

    // 2. Aplica modificadores do estado operacional
    if (state === 'listening') {
      left.scaleX *= 1.05;
      left.scaleY *= 1.06;
      right.scaleX *= 1.05;
      right.scaleY *= 1.06;
    } else if (state === 'thinking') {
      // Semicerrar pensativo discreto sem destruir expressões fechadas
      left.upperOuter = Math.max(left.upperOuter, -50);
      left.upperMid = Math.max(left.upperMid, -44);
      left.upperInner = Math.max(left.upperInner, -50);

      right.upperOuter = Math.max(right.upperOuter, -50);
      right.upperMid = Math.max(right.upperMid, -44);
      right.upperInner = Math.max(right.upperInner, -50);
    } else if (state === 'error') {
      // Olhos em X no estado de erro
      left.capsuleOpacity = 0;
      left.heartOpacity = 0;
      left.errorOpacity = 1;
      left.highlightOpacity = 0;

      right.capsuleOpacity = 0;
      right.heartOpacity = 0;
      right.errorOpacity = 1;
      right.highlightOpacity = 0;
    }

    return {
      left,
      right,
      headTiltDeg,
      gazeBiasX,
      gazeBiasY,
    };
  }

  // Constrói o caminho SVG da pálpebra superior respeitando lado esquerdo/direito
  function buildUpperLidPath(pose, isLeft, blinkAmount) {
    const outerY = lerp(pose.upperOuter, 10, blinkAmount);
    const midY = lerp(pose.upperMid, 16, blinkAmount);
    const innerY = lerp(pose.upperInner, 10, blinkAmount);
    const leftEdgeY = isLeft ? outerY : innerY;
    const rightEdgeY = isLeft ? innerY : outerY;
    return `M -92 -140 L 92 -140 L 92 ${rightEdgeY.toFixed(2)} Q 0 ${midY.toFixed(2)} -92 ${leftEdgeY.toFixed(2)} Z`;
  }

  // Constrói o caminho SVG da pálpebra inferior respeitando lado esquerdo/direito
  function buildLowerLidPath(pose, isLeft, blinkAmount) {
    const outerY = lerp(pose.lowerOuter, 4, blinkAmount);
    const midY = lerp(pose.lowerMid, 8, blinkAmount);
    const innerY = lerp(pose.lowerInner, 4, blinkAmount);
    const leftEdgeY = isLeft ? outerY : innerY;
    const rightEdgeY = isLeft ? innerY : outerY;
    return `M -92 140 L 92 140 L 92 ${rightEdgeY.toFixed(2)} Q 0 ${midY.toFixed(2)} -92 ${leftEdgeY.toFixed(2)} Z`;
  }

  // Cria a estrutura HTML/SVG interna do rosto
  function buildFaceMarkup() {
    const xPos = -EYE_HALF_W;
    const yPos = -EYE_HALF_H;

    // Gera 7 barras para o indicador sutil de voz
    const barCount = 7;
    const barSpacing = 18;
    const startX = 400 - ((barCount - 1) * barSpacing) / 2;
    let voiceBarsMarkup = '';
    for (let i = 0; i < barCount; i += 1) {
      const bx = startX + i * barSpacing - 3;
      voiceBarsMarkup += `<rect class="emo-voice-bar" data-bar-index="${i}" x="${bx}" y="392" width="6" height="8" rx="3" ry="3"></rect>`;
    }

    const eyeInnerMarkup = (side) => `
      <g class="emo-eye-look" data-eye-look="${side}">
        <g class="emo-eye-motion" data-eye-motion="${side}">
          <g clip-path="url(#emo-clip-${side})">
            <rect
              class="emo-eye-shape"
              data-eye-shape="${side}"
              x="${xPos}"
              y="${yPos}"
              width="${EYE_WIDTH}"
              height="${EYE_HEIGHT}"
              rx="${EYE_BASE_RX}"
              ry="${EYE_BASE_RX}"
            ></rect>
            <g class="emo-eye-highlights" data-eye-highlights="${side}">
              <ellipse class="emo-eye-highlight-1" cx="-34" cy="-46" rx="16" ry="11" transform="rotate(-24 -34 -46)"></ellipse>
              <circle class="emo-eye-highlight-2" cx="-14" cy="-26" r="5.5"></circle>
            </g>
            <path class="emo-lid-upper" data-lid-upper="${side}" d="M -92 -140 L 92 -140 L 92 -98 Q 0 -98 -92 -98 Z"></path>
            <path class="emo-lid-lower" data-lid-lower="${side}" d="M -92 140 L 92 140 L 92 98 Q 0 98 -92 98 Z"></path>
          </g>

          <g class="emo-heart-group" data-heart-group="${side}" style="opacity: 0;">
            <path
              class="emo-heart-shape"
              d="M 0 64 C -14 52, -78 10, -78 -30 C -78 -64, -48 -82, -20 -82 C -6 -82, 0 -68, 0 -56 C 0 -68, 6 -82, 20 -82 C 48 -82, 78 -64, 78 -30 C 78 10, 14 52, 0 64 Z"
            ></path>
            <ellipse class="emo-heart-highlight" cx="-34" cy="-40" rx="14" ry="8" transform="rotate(-28 -34 -40)"></ellipse>
          </g>

          <g class="emo-error-x" data-error-x="${side}" style="opacity: 0;">
            <rect class="emo-error-x-bar" x="-64" y="-12" width="128" height="24" rx="12" transform="rotate(45)"></rect>
            <rect class="emo-error-x-bar" x="-64" y="-12" width="128" height="24" rx="12" transform="rotate(-45)"></rect>
          </g>
        </g>
      </g>
    `;

    return `
      <div class="emo-face-root emo-state-idle emo-emotion-neutral" data-state="idle" data-emotion="neutral" data-auto-sleepy="false">
        <svg id="emo-face-svg" class="emo-face-svg" viewBox="0 0 800 480" role="img" aria-label="Rosto animado do assistente">
          <defs>
            <clipPath id="emo-clip-left">
              <rect data-clip-rect="left" x="${xPos}" y="${yPos}" width="${EYE_WIDTH}" height="${EYE_HEIGHT}" rx="${EYE_BASE_RX}" ry="${EYE_BASE_RX}"></rect>
            </clipPath>
            <clipPath id="emo-clip-right">
              <rect data-clip-rect="right" x="${xPos}" y="${yPos}" width="${EYE_WIDTH}" height="${EYE_HEIGHT}" rx="${EYE_BASE_RX}" ry="${EYE_BASE_RX}"></rect>
            </clipPath>
          </defs>

          <!-- Halo sutil para estado listening -->
          <ellipse id="emo-listening-halo" class="emo-listening-halo" cx="400" cy="226" rx="305" ry="152"></ellipse>

          <!-- Grupo principal da cabeça (respiração, bounce e inclinação) -->
          <g id="emo-face-head" class="emo-face-head">
            <g id="emo-eye-left" class="emo-eye-group emo-eye-left" transform="translate(${LEFT_EYE_X}, ${EYE_CENTER_Y})">
              ${eyeInnerMarkup('left')}
            </g>
            <g id="emo-eye-right" class="emo-eye-group emo-eye-right" transform="translate(${RIGHT_EYE_X}, ${EYE_CENTER_Y})">
              ${eyeInnerMarkup('right')}
            </g>

            <!-- Estrelinhas para emoção excited -->
            <g id="emo-sparkles" class="emo-sparkles">
              <path class="emo-sparkle emo-sparkle-1" d="M 142 128 L 146 140 L 158 144 L 146 148 L 142 160 L 138 148 L 126 144 L 138 140 Z"></path>
              <path class="emo-sparkle emo-sparkle-2" d="M 658 118 L 663 132 L 677 137 L 663 142 L 658 156 L 653 142 L 639 137 L 653 132 Z"></path>
              <path class="emo-sparkle emo-sparkle-3" d="M 400 108 L 403 117 L 412 120 L 403 123 L 400 132 L 397 123 L 388 120 L 397 117 Z"></path>
              <path class="emo-sparkle emo-sparkle-4" d="M 672 292 L 675 301 L 684 304 L 675 307 L 672 316 L 669 307 L 660 304 L 669 301 Z"></path>
            </g>

            <!-- Indicador Zzz para sleepy e modo sonolento após 90s -->
            <g id="emo-zzz" class="emo-zzz">
              <text class="emo-zzz-char emo-zzz-1" x="628" y="138" font-size="24">z</text>
              <text class="emo-zzz-char emo-zzz-2" x="656" y="114" font-size="30">Z</text>
              <text class="emo-zzz-char emo-zzz-3" x="688" y="88" font-size="36">Z</text>
            </g>

            <!-- Indicador discreto de pensamento -->
            <g id="emo-thinking-dots" class="emo-thinking-dots">
              <circle class="emo-thinking-dot emo-thinking-dot-1" cx="378" cy="108" r="5"></circle>
              <circle class="emo-thinking-dot emo-thinking-dot-2" cx="400" cy="108" r="5"></circle>
              <circle class="emo-thinking-dot emo-thinking-dot-3" cx="422" cy="108" r="5"></circle>
            </g>
          </g>

          <!-- Onda de áudio sutil abaixo dos olhos -->
          <g id="emo-voice-wave" class="emo-voice-wave">
            ${voiceBarsMarkup}
          </g>
        </svg>
      </div>
    `;
  }

  // Estado interno do módulo
  const internal = {
    container: null,
    rootEl: null,
    els: null,
    rafId: null,
    lastFrameTime: 0,

    state: 'idle',
    emotion: 'neutral',
    emotionTimer: null,
    autoSleepy: false,
    lastInteractionAt: 0,

    // Olhar (gaze) e micro-sacadas
    manualLookX: 0,
    manualLookY: 0,
    manualLookUntil: 0,
    autoLookX: 0,
    autoLookY: 0,
    saccadeX: 0,
    saccadeY: 0,
    currentLookX: 0,
    currentLookY: 0,
    nextIdleGlanceAt: 0,
    nextSaccadeAt: 0,
    nextThinkingFlipAt: 0,
    thinkingSide: -1,

    // Piscadas
    blinkActive: false,
    blinkStartAt: 0,
    blinkDuration: 155,
    blinkPendingDouble: false,
    nextAutoBlinkAt: 0,

    // Áudio e pop de expressão
    targetAudioLevel: 0,
    smoothAudioLevel: 0,
    popBoost: 0,
    currentTiltDeg: 0,

    // Poses interpoladas de cada olho
    leftPose: createDefaultEyePose(),
    rightPose: createDefaultEyePose(),
  };

  function nowMs() {
    return typeof performance !== 'undefined' && performance.now
      ? performance.now()
      : Date.now();
  }

  function registerInteraction(ts) {
    const t = ts || nowMs();
    internal.lastInteractionAt = t;
    if (internal.autoSleepy) {
      internal.autoSleepy = false;
      syncDomAttributes();
    }
  }

  function syncDomAttributes() {
    if (!internal.rootEl) {
      return;
    }
    const root = internal.rootEl;
    root.dataset.state = internal.state;
    root.dataset.emotion = internal.emotion;
    root.dataset.autoSleepy = internal.autoSleepy ? 'true' : 'false';

    // Atualiza classes de estado e emoção para seletores CSS
    SUPPORTED_STATES.forEach((s) => {
      root.classList.toggle(`emo-state-${s}`, s === internal.state);
    });
    SUPPORTED_EMOTIONS.forEach((e) => {
      root.classList.toggle(`emo-emotion-${e}`, e === internal.emotion);
    });
    root.classList.toggle('emo-auto-sleepy', internal.autoSleepy);
  }

  function startBlink(ts) {
    internal.blinkActive = true;
    internal.blinkStartAt = ts;
  }

  function scheduleNextBlink(ts) {
    const isSlow = internal.emotion === 'sleepy' || internal.autoSleepy;
    const minDelay = isSlow ? 4200 : 2500;
    const span = isSlow ? 3200 : 3000;
    internal.nextAutoBlinkAt = ts + minDelay + Math.random() * span;
  }

  function cacheElements(rootEl) {
    const q = (sel) => rootEl.querySelector(sel);
    const voiceBars = Array.from(rootEl.querySelectorAll('.emo-voice-bar'));
    return {
      head: q('#emo-face-head'),
      voiceWave: q('#emo-voice-wave'),
      voiceBars,
      left: {
        look: q('[data-eye-look="left"]'),
        motion: q('[data-eye-motion="left"]'),
        shape: q('[data-eye-shape="left"]'),
        clipRect: q('[data-clip-rect="left"]'),
        highlights: q('[data-eye-highlights="left"]'),
        lidUpper: q('[data-lid-upper="left"]'),
        lidLower: q('[data-lid-lower="left"]'),
        heartGroup: q('[data-heart-group="left"]'),
        errorX: q('[data-error-x="left"]'),
      },
      right: {
        look: q('[data-eye-look="right"]'),
        motion: q('[data-eye-motion="right"]'),
        shape: q('[data-eye-shape="right"]'),
        clipRect: q('[data-clip-rect="right"]'),
        highlights: q('[data-eye-highlights="right"]'),
        lidUpper: q('[data-lid-upper="right"]'),
        lidLower: q('[data-lid-lower="right"]'),
        heartGroup: q('[data-heart-group="right"]'),
        errorX: q('[data-error-x="right"]'),
      },
    };
  }

  function applyEyePoseToDom(pose, els, isLeft, blinkAmount, popBoost, speakingPulse) {
    const sx = pose.scaleX * (1 + popBoost) * (1 + speakingPulse * 0.4);
    const blinkScaleY = 1 - blinkAmount * (pose.heartOpacity > 0.3 ? 0.9 : 0.06);
    const sy = pose.scaleY * (1 + popBoost) * (1 + speakingPulse) * blinkScaleY;

    els.motion.setAttribute('transform', `scale(${sx.toFixed(4)} ${sy.toFixed(4)})`);

    const rxVal = pose.rx.toFixed(2);
    els.shape.setAttribute('rx', rxVal);
    els.shape.setAttribute('ry', rxVal);
    els.clipRect.setAttribute('rx', rxVal);
    els.clipRect.setAttribute('ry', rxVal);

    els.shape.style.opacity = pose.capsuleOpacity.toFixed(3);
    els.highlights.style.opacity = pose.highlightOpacity.toFixed(3);
    els.heartGroup.style.opacity = pose.heartOpacity.toFixed(3);
    els.errorX.style.opacity = pose.errorOpacity.toFixed(3);

    els.lidUpper.setAttribute('d', buildUpperLidPath(pose, isLeft, blinkAmount));
    els.lidLower.setAttribute('d', buildLowerLidPath(pose, isLeft, blinkAmount));
  }

  // Loop principal de animação (60fps)
  function step(ts) {
    if (!internal.rootEl || !internal.els) {
      return;
    }

    const dt = internal.lastFrameTime
      ? Math.min(0.05, Math.max(0.001, (ts - internal.lastFrameTime) / 1000))
      : 0.016;
    internal.lastFrameTime = ts;
    const tSec = ts / 1000;

    // 1. Verifica entrada automática no modo sonolento após 90s em idle
    if (
      internal.state === 'idle' &&
      !internal.autoSleepy &&
      ts - internal.lastInteractionAt >= IDLE_SLEEP_TIMEOUT_MS
    ) {
      internal.autoSleepy = true;
      syncDomAttributes();
    }

    // 2. Atualiza piscada natural e ocasional piscada dupla
    let blinkAmount = 0;
    if (internal.blinkActive) {
      const elapsed = ts - internal.blinkStartAt;
      if (elapsed >= internal.blinkDuration) {
        internal.blinkActive = false;
        if (internal.blinkPendingDouble) {
          internal.blinkPendingDouble = false;
          internal.blinkStartAt = ts + 110;
          internal.blinkActive = true;
        } else {
          scheduleNextBlink(ts);
        }
      } else if (elapsed >= 0) {
        const p = elapsed / internal.blinkDuration;
        // Fechamento rápido e abertura suave
        blinkAmount = p < 0.42 ? Math.sin((p / 0.42) * (Math.PI / 2)) : Math.cos(((p - 0.42) / 0.58) * (Math.PI / 2));
      }
    } else if (ts >= internal.nextAutoBlinkAt && internal.state !== 'error') {
      internal.blinkPendingDouble = Math.random() < 0.18;
      startBlink(ts);
    }

    // 3. Atualiza alvos de expressão/estado e interpola poses dos olhos
    const targets = resolveEyeTargets(internal.emotion, internal.state, internal.autoSleepy);
    const poseRate = 1 - Math.exp(-dt * 12);
    const keys = [
      'upperOuter',
      'upperMid',
      'upperInner',
      'lowerOuter',
      'lowerMid',
      'lowerInner',
      'scaleX',
      'scaleY',
      'rx',
      'capsuleOpacity',
      'heartOpacity',
      'errorOpacity',
      'highlightOpacity',
    ];
    for (let i = 0; i < keys.length; i += 1) {
      const k = keys[i];
      internal.leftPose[k] = lerp(internal.leftPose[k], targets.left[k], poseRate);
      internal.rightPose[k] = lerp(internal.rightPose[k], targets.right[k], poseRate);
    }

    // 4. Atualiza olhar 2D (estado + manual + olhares curiosos em idle + micro-sacadas)
    let desiredX = targets.gazeBiasX;
    let desiredY = targets.gazeBiasY;

    if (ts < internal.manualLookUntil) {
      desiredX = internal.manualLookX;
      desiredY = internal.manualLookY;
    } else if (internal.state === 'thinking') {
      if (ts >= internal.nextThinkingFlipAt) {
        internal.thinkingSide *= -1;
        internal.nextThinkingFlipAt = ts + 1350;
      }
      desiredX = internal.thinkingSide * 0.48;
      desiredY = -0.54;
    } else if (internal.state === 'listening') {
      desiredX = 0;
      desiredY = 0;
    } else if (internal.state === 'idle' && !internal.autoSleepy) {
      if (ts >= internal.nextIdleGlanceAt) {
        // Olhares curiosos aleatórios a cada 2-4s, retornando ao centro com frequência
        if (Math.random() < 0.45) {
          internal.autoLookX = 0;
          internal.autoLookY = 0;
        } else {
          internal.autoLookX = (Math.random() * 2 - 1) * 0.58;
          internal.autoLookY = (Math.random() * 2 - 1) * 0.36;
        }
        internal.nextIdleGlanceAt = ts + 2000 + Math.random() * 2000;
      }
      if (ts >= internal.nextSaccadeAt) {
        internal.saccadeX = (Math.random() * 2 - 1) * 0.045;
        internal.saccadeY = (Math.random() * 2 - 1) * 0.035;
        internal.nextSaccadeAt = ts + 750 + Math.random() * 1100;
      }
      desiredX = clamp(internal.autoLookX + internal.saccadeX + targets.gazeBiasX, -1, 1);
      desiredY = clamp(internal.autoLookY + internal.saccadeY + targets.gazeBiasY, -1, 1);
    } else if (internal.autoSleepy || internal.emotion === 'sleepy') {
      desiredX = 0;
      desiredY = 0.16;
    }

    const gazeRate = 1 - Math.exp(-dt * 9.5);
    internal.currentLookX = lerp(internal.currentLookX, desiredX, gazeRate);
    internal.currentLookY = lerp(internal.currentLookY, desiredY, gazeRate);

    const lookPxX = internal.currentLookX * 32;
    const lookPxY = internal.currentLookY * 22;
    internal.els.left.look.setAttribute('transform', `translate(${lookPxX.toFixed(2)} ${lookPxY.toFixed(2)})`);
    internal.els.right.look.setAttribute('transform', `translate(${lookPxX.toFixed(2)} ${lookPxY.toFixed(2)})`);

    // Paralaxe sutil dos brilhos internos
    const hlX = (internal.currentLookX * 6).toFixed(2);
    const hlY = (internal.currentLookY * 4).toFixed(2);
    internal.els.left.highlights.setAttribute('transform', `translate(${hlX} ${hlY})`);
    internal.els.right.highlights.setAttribute('transform', `translate(${hlX} ${hlY})`);

    // 5. Atualiza nível de áudio suavizado, bounce rítmico e respiração
    const audioFactor = internal.targetAudioLevel > internal.smoothAudioLevel ? 0.3 : 0.16;
    internal.smoothAudioLevel = lerp(internal.smoothAudioLevel, internal.targetAudioLevel, audioFactor);

    const isSpeaking = internal.state === 'speaking' || internal.smoothAudioLevel > 0.02;
    const breathAmp = internal.autoSleepy || internal.emotion === 'sleepy' ? 2.8 : 4.5;
    const breathFreq = internal.autoSleepy || internal.emotion === 'sleepy' ? 1.1 : 1.65;
    let headOffsetY = Math.sin(tSec * breathFreq) * breathAmp;
    let headOffsetX = 0;

    if (internal.emotion === 'excited') {
      headOffsetY += Math.abs(Math.sin(tSec * 5.5)) * -7;
    }
    if (isSpeaking) {
      const energy = internal.state === 'speaking'
        ? Math.max(0.18, internal.smoothAudioLevel)
        : internal.smoothAudioLevel;
      headOffsetY += Math.sin(tSec * 15.5) * (2.5 + energy * 8.5) - energy * 3.5;
    }
    if (internal.state === 'error') {
      headOffsetX = Math.sin(tSec * 11) * 1.8;
    }

    internal.currentTiltDeg = lerp(internal.currentTiltDeg, targets.headTiltDeg, 1 - Math.exp(-dt * 10));
    internal.els.head.setAttribute(
      'transform',
      `translate(${headOffsetX.toFixed(2)} ${headOffsetY.toFixed(2)}) rotate(${internal.currentTiltDeg.toFixed(2)} 400 ${EYE_CENTER_Y})`
    );

    // 6. Pop de escala (ex.: surprised) e pulso na fala
    internal.popBoost *= Math.exp(-dt * 11);
    if (internal.popBoost < 0.001) {
      internal.popBoost = 0;
    }
    const speakingPulse = isSpeaking ? internal.smoothAudioLevel * 0.068 : 0;

    applyEyePoseToDom(
      internal.leftPose,
      internal.els.left,
      true,
      blinkAmount,
      internal.popBoost,
      speakingPulse
    );
    applyEyePoseToDom(
      internal.rightPose,
      internal.els.right,
      false,
      blinkAmount,
      internal.popBoost,
      speakingPulse
    );

    // 7. Atualiza barras da onda de voz abaixo dos olhos
    const showWave = internal.state === 'speaking' || internal.smoothAudioLevel > 0.02;
    internal.els.voiceWave.classList.toggle('is-active', showWave);
    if (showWave) {
      const baseLevel = internal.state === 'speaking'
        ? Math.max(0.14, internal.smoothAudioLevel)
        : internal.smoothAudioLevel;
      const bars = internal.els.voiceBars;
      const centerIdx = (bars.length - 1) / 2;
      for (let i = 0; i < bars.length; i += 1) {
        const distWeight = 1 - Math.abs(i - centerIdx) / (centerIdx + 1.1);
        const wave = 0.45 + 0.55 * Math.abs(Math.sin(tSec * 13 + i * 0.9));
        const h = 6 + baseLevel * 28 * distWeight * wave;
        const y = 396 - h / 2;
        bars[i].setAttribute('height', h.toFixed(2));
        bars[i].setAttribute('y', y.toFixed(2));
      }
    }

    internal.rafId = global.requestAnimationFrame(step);
  }

  // API pública window.EmoFace
  const EmoFace = {
    init(containerEl) {
      let targetEl = containerEl;
      if (typeof containerEl === 'string' && typeof document !== 'undefined') {
        targetEl = document.querySelector(containerEl);
      }
      if (!targetEl) {
        throw new Error('EmoFace.init: containerEl inválido ou não encontrado.');
      }

      // Limpa loop anterior se init for chamado novamente
      if (internal.rafId !== null && typeof global.cancelAnimationFrame === 'function') {
        global.cancelAnimationFrame(internal.rafId);
        internal.rafId = null;
      }

      internal.container = targetEl;
      targetEl.innerHTML = buildFaceMarkup();
      internal.rootEl = targetEl.querySelector('.emo-face-root');
      internal.els = cacheElements(internal.rootEl);

      const t = nowMs();
      internal.lastFrameTime = t;
      internal.lastInteractionAt = t;
      internal.nextIdleGlanceAt = t + 2200;
      internal.nextSaccadeAt = t + 900;
      internal.nextThinkingFlipAt = t + 1100;
      scheduleNextBlink(t);
      syncDomAttributes();

      if (typeof global.requestAnimationFrame === 'function') {
        internal.rafId = global.requestAnimationFrame(step);
      }
      return EmoFace;
    },

    setState(state) {
      if (!SUPPORTED_STATES.includes(state)) {
        if (typeof console !== 'undefined' && console.warn) {
          console.warn(`[EmoFace] Estado desconhecido ignorado: ${state}`);
        }
        return internal.state;
      }
      const prevState = internal.state;
      internal.state = state;
      registerInteraction();

      const t = nowMs();
      if (state === 'thinking' && prevState !== 'thinking') {
        internal.thinkingSide = -1;
        internal.nextThinkingFlipAt = t + 1200;
      }
      if (state === 'idle' && prevState !== 'idle') {
        internal.autoLookX = 0;
        internal.autoLookY = 0;
        internal.nextIdleGlanceAt = t + 2000;
      }
      if (state !== 'speaking' && prevState === 'speaking') {
        internal.targetAudioLevel = 0;
      }

      syncDomAttributes();
      return internal.state;
    },

    setEmotion(emotion, opts) {
      if (!SUPPORTED_EMOTIONS.includes(emotion)) {
        if (typeof console !== 'undefined' && console.warn) {
          console.warn(`[EmoFace] Emoção desconhecida ignorada: ${emotion}`);
        }
        return internal.emotion;
      }

      if (internal.emotionTimer !== null) {
        clearTimeout(internal.emotionTimer);
        internal.emotionTimer = null;
      }

      internal.emotion = emotion;
      registerInteraction();

      if (emotion === 'surprised') {
        internal.popBoost = 0.14;
      }

      if (opts && typeof opts.durationMs === 'number' && opts.durationMs > 0) {
        internal.emotionTimer = setTimeout(() => {
          internal.emotionTimer = null;
          internal.emotion = 'neutral';
          syncDomAttributes();
        }, opts.durationMs);
      }

      syncDomAttributes();
      return internal.emotion;
    },

    lookAt(x, y) {
      internal.manualLookX = clamp(Number(x), -1, 1);
      internal.manualLookY = clamp(Number(y), -1, 1);
      internal.manualLookUntil = nowMs() + 4000;
      registerInteraction();
    },

    blink() {
      const t = nowMs();
      registerInteraction(t);
      internal.blinkPendingDouble = false;
      startBlink(t);
    },

    setAudioLevel(level) {
      const clamped = clamp(Number(level), 0, 1);
      internal.targetAudioLevel = clamped;
      if (clamped > 0.02) {
        registerInteraction();
      }
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
  };

  global.EmoFace = EmoFace;
})(typeof window !== 'undefined' ? window : globalThis);
