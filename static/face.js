/**
 * Rosto animado estilo EMO (/static/face.js)
 * Renderiza os olhos e expressões em SVG puro + camada leve de partículas em Canvas
 * a 60fps via requestAnimationFrame, expondo a API pública em window.EmoFace.
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

  // Expressões faciais suportadas (12 emoções)
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
    'angry',
    'dizzy',
  ]);

  // Acessórios suportados sobre #emo-face-head
  const SUPPORTED_ACCESSORIES = Object.freeze([
    'none',
    'sunglasses',
    'headphones',
    'pomodoro',
    'blush',
  ]);

  // Efeitos climáticos na camada de partículas
  const SUPPORTED_WEATHER = Object.freeze(['none', 'rain', 'snow', 'sun']);

  // Animações one-shot suportadas
  const SUPPORTED_ANIMATIONS = Object.freeze(['laugh', 'confused', 'yawn']);

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
  // Janela de micro-eventos autônomos em idle (25s a 45s)
  const IDLE_MICRO_MIN_MS = 25000;
  const IDLE_MICRO_SPAN_MS = 20000;

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

  function nowMs() {
    return typeof performance !== 'undefined' && performance.now
      ? performance.now()
      : Date.now();
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
      dizzyOpacity: 0,
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

      case 'angry':
        // Sobrancelhas fechadas em diagonal (\ /)
        left.upperOuter = -66;
        left.upperMid = -20;
        left.upperInner = 20;
        left.lowerOuter = 72;
        left.lowerMid = 64;
        left.lowerInner = 74;
        left.rx = 34;
        left.scaleX = 1.04;
        left.scaleY = 0.92;

        right.upperOuter = -66;
        right.upperMid = -20;
        right.upperInner = 20;
        right.lowerOuter = 72;
        right.lowerMid = 64;
        right.lowerInner = 74;
        right.rx = 34;
        right.scaleX = 1.04;
        right.scaleY = 0.92;
        headTiltDeg = 1.5;
        break;

      case 'dizzy':
        left.capsuleOpacity = 0;
        left.dizzyOpacity = 1;
        left.highlightOpacity = 0;
        left.scaleX = 1.02;
        left.scaleY = 1.02;

        right.capsuleOpacity = 0;
        right.dizzyOpacity = 1;
        right.highlightOpacity = 0;
        right.scaleX = 0.96;
        right.scaleY = 0.96;
        headTiltDeg = -4;
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
      left.dizzyOpacity = 0;
      left.errorOpacity = 1;
      left.highlightOpacity = 0;

      right.capsuleOpacity = 0;
      right.heartOpacity = 0;
      right.dizzyOpacity = 0;
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

  // Cria a estrutura HTML/SVG interna do rosto + camada canvas de partículas
  function buildFaceMarkup() {
    const xPos = -EYE_HALF_W;
    const yPos = -EYE_HALF_H;

    // Gera 9 barras para o equalizador da coleira Cyber-Husky
    const barCount = 9;
    const barSpacing = 13;
    const startX = 400 - ((barCount - 1) * barSpacing) / 2;
    let voiceBarsMarkup = '';
    for (let i = 0; i < barCount; i += 1) {
      const bx = startX + i * barSpacing - 2.5;
      voiceBarsMarkup += `<rect class="emo-voice-bar" data-bar-index="${i}" x="${bx}" y="427" width="5" height="10" rx="2.5" ry="2.5"></rect>`;
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

          <g class="emo-dizzy-group" data-dizzy-group="${side}" style="opacity: 0;">
            <g class="emo-dizzy-spinner emo-dizzy-spinner-${side}">
              <path
                class="emo-dizzy-spiral"
                d="M 0 0 m 0 -6 a 6 6 0 1 1 -6 6 a 12 12 0 1 1 12 12 a 20 20 0 1 1 -22 -20 a 30 30 0 1 1 34 30 a 42 42 0 1 1 -46 -42 a 55 55 0 0 1 56 -8"
              ></path>
              <circle class="emo-dizzy-core" cx="0" cy="0" r="6"></circle>
            </g>
          </g>
        </g>
      </g>
    `;

    return `
      <div
        class="emo-face-root emo-state-idle emo-emotion-neutral"
        data-state="idle"
        data-emotion="neutral"
        data-auto-sleepy="false"
        data-accessory="none"
        data-weather="none"
        data-sweat="false"
        data-compact="false"
      >
        <canvas class="emo-particles-canvas" aria-hidden="true"></canvas>
        <svg id="emo-face-svg" class="emo-face-svg" viewBox="0 0 800 660" role="img" aria-label="Lupin Cyber-Husky animado">
          <defs>
            <clipPath id="emo-clip-left">
              <rect data-clip-rect="left" x="${xPos}" y="${yPos}" width="${EYE_WIDTH}" height="${EYE_HEIGHT}" rx="${EYE_BASE_RX}" ry="${EYE_BASE_RX}"></rect>
            </clipPath>
            <clipPath id="emo-clip-right">
              <rect data-clip-rect="right" x="${xPos}" y="${yPos}" width="${EYE_WIDTH}" height="${EYE_HEIGHT}" rx="${EYE_BASE_RX}" ry="${EYE_BASE_RX}"></rect>
            </clipPath>
          </defs>

          <!-- Halo sutil para estado listening -->
          <ellipse id="emo-listening-halo" class="emo-listening-halo" cx="400" cy="246" rx="315" ry="170"></ellipse>

          <!-- Rig completo de corpo inteiro do Lupin (Cyber-Husky OLED) -->
          <g id="lupin-full-rig" class="lupin-full-rig">
            <!-- Pose enrolada para soneca (nap) -->
            <g id="lupin-nap-group" class="lupin-nap-group" aria-hidden="true">
              <ellipse class="lupin-fur-dark" cx="400" cy="548" rx="176" ry="74"></ellipse>
              <path class="lupin-tail-plume" d="M 244 558 C 216 510, 266 472, 342 486 C 412 498, 466 544, 434 596 C 384 624, 272 612, 244 558 Z"></path>
              <path class="lupin-fur-mane" d="M 358 470 C 424 446, 514 476, 534 534 C 546 570, 502 604, 444 596 C 398 590, 344 532, 358 470 Z"></path>
              <path class="emo-husky-ear-outer" d="M 392 482 L 378 430 Q 386 422 396 428 L 424 468 Z"></path>
              <path class="emo-husky-ear-outer" d="M 476 474 L 494 424 Q 504 422 508 434 L 502 486 Z"></path>
              <ellipse class="emo-husky-brow-mark" cx="418" cy="502" rx="14" ry="5" transform="rotate(-8 418 502)"></ellipse>
              <ellipse class="emo-husky-brow-mark" cx="470" cy="502" rx="14" ry="5" transform="rotate(8 470 502)"></ellipse>
              <path class="emo-husky-mouth" d="M 404 524 Q 418 534 432 524"></path>
              <path class="emo-husky-mouth" d="M 456 524 Q 470 534 484 524"></path>
              <path class="emo-husky-nose" d="M 432 548 Q 446 540 460 548 Q 460 562 446 566 Q 432 562 432 548 Z"></path>
              <ellipse class="emo-husky-nose-pink" cx="446" cy="555" rx="6" ry="3.5"></ellipse>
            </g>

            <!-- Corpo acordado (sentado / andando / balançando com música) -->
            <g id="lupin-awake-body" class="lupin-awake-body">
              <!-- Cauda fofa enrolada (pluma branca + base escura) -->
              <g id="lupin-tail-group" class="lupin-tail-group" transform="translate(514, 520)">
                <path class="lupin-tail-plume" d="M 0 36 C 58 26, 126 -14, 134 -88 C 140 -144, 96 -178, 54 -158 C 22 -142, 34 -96, 62 -92 C 78 -90, 82 -62, 54 -44 C 30 -28, 12 -14, 0 6 Z"></path>
                <path class="lupin-tail-dark" d="M 2 22 C 36 14, 72 -6, 86 -36 C 64 -26, 32 -16, 4 -4 Z"></path>
              </g>

              <!-- Patas traseiras -->
              <g id="lupin-leg-bl" class="lupin-leg">
                <path class="lupin-fur-dark" d="M 314 510 C 276 522, 268 566, 286 594 L 330 594 C 334 568, 336 534, 332 510 Z"></path>
                <ellipse class="lupin-fur-white" cx="304" cy="596" rx="28" ry="14"></ellipse>
              </g>
              <g id="lupin-leg-br" class="lupin-leg">
                <path class="lupin-fur-dark" d="M 486 510 C 524 522, 532 566, 514 594 L 470 594 C 466 568, 464 534, 468 510 Z"></path>
                <ellipse class="lupin-fur-white" cx="496" cy="596" rx="28" ry="14"></ellipse>
              </g>

              <!-- Tronco e juba wooly preta + peito branco -->
              <g id="lupin-body-group" class="lupin-body-group">
                <path class="lupin-fur-dark" d="M 294 404 C 266 446, 272 544, 314 576 C 354 598, 446 598, 486 576 C 528 544, 534 446, 506 404 Z"></path>
                <!-- Peito branco fofo -->
                <path class="lupin-fur-white" d="M 326 424 C 316 476, 328 548, 366 574 C 388 588, 412 588, 434 574 C 472 548, 484 476, 474 424 C 446 446, 422 456, 400 456 C 378 456, 354 446, 326 424 Z"></path>
                <!-- Juba fofa nos ombros -->
                <path class="lupin-fur-mane" d="M 272 390 C 260 426, 286 458, 324 468 C 344 444, 366 436, 400 436 C 434 436, 456 444, 476 468 C 514 458, 540 426, 528 390 C 498 408, 448 416, 400 416 C 352 416, 302 408, 272 390 Z"></path>

                <!-- Patas dianteiras -->
                <g id="lupin-leg-fl" class="lupin-leg">
                  <path class="lupin-fur-white" d="M 336 488 C 328 534, 328 574, 336 604 L 376 604 C 380 572, 382 532, 376 488 Z"></path>
                  <ellipse class="lupin-fur-white" cx="354" cy="608" rx="26" ry="13"></ellipse>
                </g>
                <g id="lupin-leg-fr" class="lupin-leg">
                  <path class="lupin-fur-white" d="M 464 488 C 472 534, 472 574, 464 604 L 424 604 C 420 572, 418 532, 424 488 Z"></path>
                  <ellipse class="lupin-fur-white" cx="446" cy="608" rx="26" ry="13"></ellipse>
                </g>

                <!-- Coleira Cyber-Husky com equalizador de áudio -->
                <g id="lupin-collar-group" class="lupin-collar-group">
                  <path class="lupin-collar-band" d="M 308 408 Q 400 444 492 408 L 488 436 Q 400 472 312 436 Z"></path>
                  <rect class="lupin-collar-core" x="334" y="416" width="132" height="32" rx="14"></rect>
                  <g id="emo-voice-wave" class="emo-voice-wave">
                    ${voiceBarsMarkup}
                  </g>
                </g>
              </g>
            </g>

          <!-- Grupo principal da cabeça (respiração, bounce e inclinação) -->
          <g id="emo-face-head" class="emo-face-head">
            <!-- Camada Lupin/Lupe (Husky Siberiano preto e branco) -->
            <g id="emo-husky-layer" class="emo-husky-layer" aria-hidden="true">
              <!-- Orelhas pontudas pretas com pelo interno claro -->
              <g class="emo-husky-ear emo-husky-ear-left">
                <path class="emo-husky-ear-outer" d="M 148 156 L 122 34 Q 124 18 140 24 L 248 92 Z"></path>
                <path class="emo-husky-ear-inner" d="M 156 138 L 140 50 L 220 98 Z"></path>
              </g>
              <g class="emo-husky-ear emo-husky-ear-right">
                <path class="emo-husky-ear-outer" d="M 652 156 L 678 34 Q 676 18 660 24 L 552 92 Z"></path>
                <path class="emo-husky-ear-inner" d="M 644 138 L 660 50 L 580 98 Z"></path>
              </g>

              <!-- Capuz/máscara preta do topo da cabeça e listra central -->
              <path class="emo-husky-fur-black" d="M 134 196 C 140 94, 244 76, 400 76 C 556 76, 660 94, 666 196 C 654 148, 608 118, 536 122 C 470 126, 434 166, 400 184 C 366 166, 330 126, 264 122 C 192 118, 146 148, 134 196 Z"></path>

              <!-- Bochechas e focinho brancos estilizados -->
              <path class="emo-husky-fur-white" d="M 152 292 C 148 372, 224 416, 400 416 C 576 416, 652 372, 648 292 C 622 316, 560 326, 492 318 C 446 312, 424 288, 400 288 C 376 288, 354 312, 308 318 C 240 326, 178 316, 152 292 Z"></path>

              <!-- Sobrancelhas/manchinhas claras acima dos olhos -->
              <ellipse class="emo-husky-brow-mark" cx="256" cy="116" rx="34" ry="12" transform="rotate(-10 256 116)"></ellipse>
              <ellipse class="emo-husky-brow-mark" cx="544" cy="116" rx="34" ry="12" transform="rotate(10 544 116)"></ellipse>

              <!-- Focinho/Nariz preto com detalhe rosado no centro (como o Lupin) -->
              <path class="emo-husky-nose" d="M 366 340 Q 400 326 434 340 Q 436 364 400 374 Q 364 364 366 340 Z"></path>
              <ellipse class="emo-husky-nose-pink" cx="400" cy="356" rx="14" ry="7"></ellipse>
              <ellipse class="emo-husky-nose-shine" cx="386" cy="340" rx="9" ry="4"></ellipse>

              <!-- Boca estilo husky + linguinha rosa -->
              <path class="emo-husky-mouth" d="M 360 384 Q 380 400 400 382 Q 420 400 440 384"></path>
              <path class="emo-husky-tongue" d="M 384 388 L 416 388 L 414 418 Q 400 434 386 418 Z"></path>
              <line class="emo-husky-tongue-line" x1="400" y1="392" x2="400" y2="416"></line>
            </g>

            <g id="emo-eye-left" class="emo-eye-group emo-eye-left" transform="translate(${LEFT_EYE_X}, ${EYE_CENTER_Y})">
              ${eyeInnerMarkup('left')}
            </g>
            <g id="emo-eye-right" class="emo-eye-group emo-eye-right" transform="translate(${RIGHT_EYE_X}, ${EYE_CENTER_Y})">
              ${eyeInnerMarkup('right')}
            </g>

            <!-- Acessórios SVG sobre a cabeça -->
            <g id="emo-accessories" class="emo-accessories">
              <!-- Rubor (blush) nas bochechas -->
              <g class="emo-accessory emo-acc-blush" aria-hidden="true">
                <ellipse class="emo-blush-oval" cx="192" cy="332" rx="44" ry="19"></ellipse>
                <ellipse class="emo-blush-oval" cx="608" cy="332" rx="44" ry="19"></ellipse>
                <line class="emo-blush-stripe" x1="176" y1="338" x2="188" y2="324"></line>
                <line class="emo-blush-stripe" x1="194" y1="338" x2="206" y2="324"></line>
                <line class="emo-blush-stripe" x1="594" y1="338" x2="606" y2="324"></line>
                <line class="emo-blush-stripe" x1="612" y1="338" x2="624" y2="324"></line>
              </g>

              <!-- Óculos escuros cyber -->
              <g class="emo-accessory emo-acc-sunglasses" aria-hidden="true">
                <path class="emo-sunglasses-frame" d="M 154 152 L 352 152 Q 368 152 370 172 L 364 258 Q 360 288 320 290 L 204 290 Q 160 288 156 254 L 148 172 Q 146 152 154 152 Z"></path>
                <path class="emo-sunglasses-frame" d="M 448 152 L 646 152 Q 654 152 652 172 L 644 254 Q 640 288 596 290 L 480 290 Q 440 288 436 258 L 430 172 Q 432 152 448 152 Z"></path>
                <path class="emo-sunglasses-bridge" d="M 366 176 Q 400 162 434 176"></path>
                <line class="emo-sunglasses-arm" x1="148" y1="174" x2="114" y2="184"></line>
                <line class="emo-sunglasses-arm" x1="652" y1="174" x2="686" y2="184"></line>
                <polygon class="emo-sunglasses-glare" points="184,166 226,166 196,274 168,274"></polygon>
                <polygon class="emo-sunglasses-glare" points="480,166 522,166 492,274 464,274"></polygon>
              </g>

              <!-- Fones de ouvido sobre a cabeça -->
              <g class="emo-accessory emo-acc-headphones" aria-hidden="true">
                <path class="emo-hp-band" d="M 122 216 C 122 66, 678 66, 678 216"></path>
                <path class="emo-hp-band-cushion" d="M 272 95 Q 400 72 528 95"></path>
                <rect class="emo-hp-cup" x="92" y="164" width="44" height="124" rx="20"></rect>
                <rect class="emo-hp-cup-pad" x="128" y="176" width="16" height="100" rx="8"></rect>
                <rect class="emo-hp-led" x="103" y="204" width="10" height="44" rx="5"></rect>
                <rect class="emo-hp-cup" x="664" y="164" width="44" height="124" rx="20"></rect>
                <rect class="emo-hp-cup-pad" x="656" y="176" width="16" height="100" rx="8"></rect>
                <rect class="emo-hp-led" x="687" y="204" width="10" height="44" rx="5"></rect>
              </g>

              <!-- Óculos de estudo Pomodoro -->
              <g class="emo-accessory emo-acc-pomodoro" aria-hidden="true">
                <rect class="emo-pomo-rim" x="166" y="136" width="188" height="172" rx="44"></rect>
                <rect class="emo-pomo-rim" x="446" y="136" width="188" height="172" rx="44"></rect>
                <path class="emo-pomo-bridge" d="M 354 202 Q 400 186 446 202"></path>
                <line class="emo-pomo-arm" x1="166" y1="196" x2="128" y2="202"></line>
                <line class="emo-pomo-arm" x1="634" y1="196" x2="672" y2="202"></line>
                <circle class="emo-pomo-badge" cx="626" cy="146" r="10"></circle>
                <path class="emo-pomo-leaf" d="M 626 136 Q 631 129 637 132 Q 631 138 626 136 Z"></path>
              </g>
            </g>

            <!-- Gotinha de suor SVG -->
            <g id="emo-sweat-drop" class="emo-sweat-drop" transform="translate(652, 126)" aria-hidden="true">
              <path class="emo-sweat-body" d="M 0 -22 C 11 -4, 16 8, 16 16 A 16 16 0 1 1 -16 16 C -16 8, -11 -4, 0 -22 Z"></path>
              <ellipse class="emo-sweat-shine" cx="-5" cy="12" rx="4" ry="7" transform="rotate(-14 -5 12)"></ellipse>
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
          </g><!-- /#lupin-full-rig -->
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
    prefersReducedMotion: false,
    motionQuery: null,
    motionChangeHandler: null,

    state: 'idle',
    emotion: 'neutral',
    emotionTimer: null,
    autoSleepy: false,
    lastInteractionAt: 0,

    accessory: 'none',
    weather: 'none',
    sweat: false,
    compactMode: false,
    musicPlaying: false,

    // Comportamento corporal autônomo (sit | walk | nap)
    behavior: 'sit',
    walkX: 0,
    walkDir: 1,
    nextBehaviorAt: 0,

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

    // Piscadas e física squash-and-stretch
    blinkActive: false,
    blinkStartAt: 0,
    blinkDuration: 155,
    blinkPendingDouble: false,
    nextAutoBlinkAt: 0,
    leftStretch: 0,
    leftStretchVel: 0,
    rightStretch: 0,
    rightStretchVel: 0,

    // Micro-eventos autônomos em idle (inseto virtual, bocejo rápido, espiar canto)
    nextIdleMicroEventAt: 0,
    microEvent: null,

    // Animação one-shot (laugh | confused | yawn)
    activeAnim: null,

    // Interação direta por toque (poke / pet)
    leftPokeUntil: 0,
    rightPokeUntil: 0,
    pokeTimestamps: [],
    petStreak: 0,
    lastPetAt: 0,
    petPurrTimer: null,

    // Áudio e pop de expressão
    targetAudioLevel: 0,
    smoothAudioLevel: 0,
    popBoost: 0,
    currentTiltDeg: 0,

    // Poses interpoladas de cada olho
    leftPose: createDefaultEyePose(),
    rightPose: createDefaultEyePose(),

    // Camada de partículas em Canvas
    canvasCtx: null,
    canvasWidth: 0,
    canvasHeight: 0,
    canvasDpr: 1,
    weatherParticles: [],
    fxParticles: [],
    lastFxSpawnAt: 0,
    bugTrail: [],
  };

  function isMiniPet() {
    return typeof document !== 'undefined' && document.body && document.body.classList.contains('is-minipet');
  }

  function shouldReduceMotion() {
    return internal.prefersReducedMotion && isMiniPet();
  }

  function clearMotionPreferenceListener() {
    const query = internal.motionQuery;
    const handler = internal.motionChangeHandler;
    if (query && handler) {
      if (typeof query.removeEventListener === 'function') {
        query.removeEventListener('change', handler);
      } else if (typeof query.removeListener === 'function') {
        query.removeListener(handler);
      }
    }
    internal.motionQuery = null;
    internal.motionChangeHandler = null;
  }

  function settleReducedMotion() {
    const sleepy = internal.autoSleepy || internal.emotion === 'sleepy';
    internal.behavior = sleepy ? 'nap' : 'sit';
    internal.walkX = 0;
    internal.walkDir = 1;
    internal.nextBehaviorAt = 0;
    internal.microEvent = null;
    internal.activeAnim = null;
    internal.bugTrail.length = 0;
    internal.fxParticles.length = 0;
    internal.weatherParticles.length = 0;
    internal.lastFxSpawnAt = nowMs();
    internal.popBoost = 0;
    internal.leftStretch = 0;
    internal.leftStretchVel = 0;
    internal.rightStretch = 0;
    internal.rightStretchVel = 0;

    if (!internal.els) return;
    const els = internal.els;
    const targets = resolveEyeTargets(internal.emotion, internal.state, internal.autoSleepy);
    internal.currentTiltDeg = targets.headTiltDeg;
    if (els.rig) els.rig.setAttribute('transform', 'translate(0 0)');
    if (els.tail) els.tail.setAttribute('transform', 'translate(514, 520) rotate(0 0 24)');
    if (els.head) {
      els.head.setAttribute(
        'transform',
        `translate(0 0) rotate(${internal.currentTiltDeg.toFixed(2)} 400 ${EYE_CENTER_Y})`
      );
    }
    if (els.legFL && els.legFR) {
      els.legFL.setAttribute('transform', 'rotate(0 356 490)');
      els.legFR.setAttribute('transform', 'rotate(0 444 490)');
    }
    if (els.legBL && els.legBR) {
      els.legBL.setAttribute('transform', 'rotate(0 312 515)');
      els.legBR.setAttribute('transform', 'rotate(0 488 515)');
    }
    if (internal.canvasCtx) {
      internal.canvasCtx.clearRect(0, 0, internal.canvasWidth, internal.canvasHeight);
    }
    syncDomAttributes();
  }

  function bindMotionPreference() {
    if (typeof global.matchMedia !== 'function') {
      internal.prefersReducedMotion = false;
      return;
    }

    const query = global.matchMedia('(prefers-reduced-motion: reduce)');
    internal.motionQuery = query;
    internal.prefersReducedMotion = Boolean(query.matches);
    internal.motionChangeHandler = (event) => {
      const wasReduced = shouldReduceMotion();
      internal.prefersReducedMotion = Boolean(event.matches);
      if (!wasReduced && shouldReduceMotion()) settleReducedMotion();
    };
    if (typeof query.addEventListener === 'function') {
      query.addEventListener('change', internal.motionChangeHandler);
    } else if (typeof query.addListener === 'function') {
      query.addListener(internal.motionChangeHandler);
    }
    if (shouldReduceMotion()) settleReducedMotion();
  }

  function registerInteraction(ts) {
    const t = ts || nowMs();
    internal.lastInteractionAt = t;
    if (internal.autoSleepy) {
      internal.autoSleepy = false;
      syncDomAttributes();
    }
    if (internal.nextIdleMicroEventAt < t + 12000) {
      scheduleNextMicroEvent(t);
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
    root.dataset.accessory = internal.accessory;
    root.dataset.weather = internal.weather;
    root.dataset.sweat = internal.sweat ? 'true' : 'false';
    root.dataset.compact = internal.compactMode ? 'true' : 'false';
    root.dataset.behavior = internal.behavior;
    root.dataset.music = internal.musicPlaying ? 'true' : 'false';

    // Atualiza classes de estado, emoção e acessórios para seletores CSS
    SUPPORTED_STATES.forEach((s) => {
      root.classList.toggle(`emo-state-${s}`, s === internal.state);
    });
    SUPPORTED_EMOTIONS.forEach((e) => {
      root.classList.toggle(`emo-emotion-${e}`, e === internal.emotion);
    });
    SUPPORTED_ACCESSORIES.forEach((acc) => {
      root.classList.toggle(`emo-accessory-${acc}`, acc === internal.accessory && acc !== 'none');
    });
    root.classList.toggle('emo-auto-sleepy', internal.autoSleepy);
    root.classList.toggle('emo-has-sweat', internal.sweat);
    root.classList.toggle('emo-compact', internal.compactMode);
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

  function scheduleNextMicroEvent(ts) {
    internal.nextIdleMicroEventAt = ts + IDLE_MICRO_MIN_MS + Math.random() * IDLE_MICRO_SPAN_MS;
  }

  function triggerStretchImpulse(leftAmount, rightAmount) {
    if (shouldReduceMotion()) return;
    internal.leftStretchVel += leftAmount;
    internal.rightStretchVel += rightAmount != null ? rightAmount : leftAmount;
  }

  function cacheElements(rootEl) {
    const q = (sel) => rootEl.querySelector(sel);
    const voiceBars = Array.from(rootEl.querySelectorAll('.emo-voice-bar'));
    const canvas = q('.emo-particles-canvas');
    return {
      canvas,
      svg: q('#emo-face-svg'),
      rig: q('#lupin-full-rig'),
      tail: q('#lupin-tail-group'),
      body: q('#lupin-body-group'),
      legFL: q('#lupin-leg-fl'),
      legFR: q('#lupin-leg-fr'),
      legBL: q('#lupin-leg-bl'),
      legBR: q('#lupin-leg-br'),
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
        dizzyGroup: q('[data-dizzy-group="left"]'),
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
        dizzyGroup: q('[data-dizzy-group="right"]'),
      },
    };
  }

  // -------------------- Partículas em Canvas --------------------

  function syncCanvasSize() {
    const canvas = internal.els && internal.els.canvas;
    const root = internal.rootEl;
    if (!canvas || !root) {
      return false;
    }
    const width = Math.max(1, root.clientWidth || 800);
    const height = Math.max(1, root.clientHeight || 480);
    const dpr = Math.min(2, (global.devicePixelRatio || 1));

    if (
      internal.canvasWidth !== width ||
      internal.canvasHeight !== height ||
      internal.canvasDpr !== dpr
    ) {
      internal.canvasWidth = width;
      internal.canvasHeight = height;
      internal.canvasDpr = dpr;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      internal.canvasCtx = canvas.getContext('2d');
    } else if (!internal.canvasCtx) {
      internal.canvasCtx = canvas.getContext('2d');
    }
    return Boolean(internal.canvasCtx);
  }

  function spawnHeartParticle(nx, ny, count) {
    if (shouldReduceMotion()) return;
    const w = internal.canvasWidth || 800;
    const h = internal.canvasHeight || 480;
    const baseX = (0.5 + clamp(nx || 0, -1, 1) * 0.34) * w;
    const baseY = (0.48 + clamp(ny || 0, -1, 1) * 0.25) * h;
    const total = count || 1;

    for (let i = 0; i < total; i += 1) {
      if (internal.fxParticles.length > 48) {
        internal.fxParticles.shift();
      }
      internal.fxParticles.push({
        kind: 'heart',
        x: baseX + (Math.random() - 0.5) * 44,
        y: baseY + (Math.random() - 0.5) * 26,
        vx: (Math.random() - 0.5) * 26,
        vy: -38 - Math.random() * 44,
        size: 7 + Math.random() * 7,
        life: 0,
        maxLife: 1.15 + Math.random() * 0.55,
        wobbleSeed: Math.random() * Math.PI * 2,
      });
    }
  }

  function spawnAngerSteam(count) {
    if (shouldReduceMotion()) return;
    const w = internal.canvasWidth || 800;
    const h = internal.canvasHeight || 480;
    const total = count || 2;
    for (let i = 0; i < total; i += 1) {
      if (internal.fxParticles.length > 48) {
        internal.fxParticles.shift();
      }
      const side = Math.random() < 0.5 ? 0.34 : 0.66;
      internal.fxParticles.push({
        kind: 'steam',
        x: w * side + (Math.random() - 0.5) * 32,
        y: h * 0.26 + (Math.random() - 0.5) * 14,
        vx: (Math.random() - 0.5) * 22,
        vy: -32 - Math.random() * 28,
        size: 6 + Math.random() * 7,
        life: 0,
        maxLife: 0.9 + Math.random() * 0.45,
        wobbleSeed: Math.random() * Math.PI * 2,
      });
    }
  }

  function spawnZzzParticle() {
    if (shouldReduceMotion()) return;
    const w = internal.canvasWidth || 800;
    const h = internal.canvasHeight || 480;
    if (internal.fxParticles.length > 48) {
      internal.fxParticles.shift();
    }
    internal.fxParticles.push({
      kind: 'zzz',
      x: w * 0.72 + (Math.random() - 0.5) * 26,
      y: h * 0.34,
      vx: 14 + Math.random() * 12,
      vy: -24 - Math.random() * 14,
      size: 13 + Math.random() * 6,
      life: 0,
      maxLife: 1.8,
      wobbleSeed: Math.random() * Math.PI * 2,
    });
  }

  function spawnSweatParticle() {
    if (shouldReduceMotion()) return;
    const w = internal.canvasWidth || 800;
    const h = internal.canvasHeight || 480;
    if (internal.fxParticles.length > 48) {
      internal.fxParticles.shift();
    }
    internal.fxParticles.push({
      kind: 'sweat',
      x: w * 0.77 + (Math.random() - 0.5) * 8,
      y: h * 0.32,
      vx: 4,
      vy: 56 + Math.random() * 24,
      size: 3.5 + Math.random() * 2,
      life: 0,
      maxLife: 0.75,
      wobbleSeed: 0,
    });
  }

  function initWeatherPool(effect) {
    internal.weatherParticles = [];
    if (effect === 'none') {
      return;
    }
    const w = internal.canvasWidth || 800;
    const h = internal.canvasHeight || 480;
    const count = effect === 'rain' ? 36 : effect === 'snow' ? 28 : 20;
    for (let i = 0; i < count; i += 1) {
      internal.weatherParticles.push({
        x: Math.random() * w,
        y: Math.random() * h,
        speed: effect === 'rain' ? 340 + Math.random() * 180 : effect === 'snow' ? 32 + Math.random() * 38 : 14 + Math.random() * 16,
        size: effect === 'rain' ? 10 + Math.random() * 12 : effect === 'snow' ? 2 + Math.random() * 3.5 : 2 + Math.random() * 4.5,
        phase: Math.random() * Math.PI * 2,
        alpha: 0.28 + Math.random() * 0.45,
      });
    }
  }

  function drawHeart(ctx, x, y, size, alpha) {
    ctx.save();
    ctx.translate(x, y);
    ctx.globalAlpha = alpha;
    ctx.fillStyle = '#ff4d8d';
    ctx.beginPath();
    const s = size * 0.08;
    ctx.moveTo(0, 4 * s);
    ctx.bezierCurveTo(-9 * s, -2 * s, -9 * s, -10 * s, -4 * s, -10 * s);
    ctx.bezierCurveTo(-1 * s, -10 * s, 0, -7 * s, 0, -6 * s);
    ctx.bezierCurveTo(0, -7 * s, 1 * s, -10 * s, 4 * s, -10 * s);
    ctx.bezierCurveTo(9 * s, -10 * s, 9 * s, -2 * s, 0, 4 * s);
    ctx.fill();
    ctx.restore();
  }

  function updateAndRenderParticles(ts, dt, bugCoords) {
    if (!syncCanvasSize()) {
      return;
    }
    const ctx = internal.canvasCtx;
    if (shouldReduceMotion()) {
      internal.fxParticles.length = 0;
      internal.weatherParticles.length = 0;
      internal.bugTrail.length = 0;
      ctx.clearRect(0, 0, internal.canvasWidth, internal.canvasHeight);
      return;
    }
    const w = internal.canvasWidth;
    const h = internal.canvasHeight;
    const dpr = internal.canvasDpr;

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    // 1. Clima ambiente (chuva, neve ou sol)
    if (internal.weather !== 'none') {
      if (internal.weatherParticles.length === 0) {
        initWeatherPool(internal.weather);
      }
      if (internal.weather === 'sun') {
        const grad = ctx.createRadialGradient(w * 0.88, h * 0.1, 8, w * 0.88, h * 0.1, Math.min(w, h) * 0.42);
        grad.addColorStop(0, 'rgba(255, 210, 96, 0.18)');
        grad.addColorStop(1, 'rgba(255, 210, 96, 0)');
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, w, h);
      }

      for (let i = 0; i < internal.weatherParticles.length; i += 1) {
        const p = internal.weatherParticles[i];
        if (internal.weather === 'rain') {
          p.y += p.speed * dt;
          p.x -= p.speed * 0.12 * dt;
          if (p.y > h + 20) {
            p.y = -20;
            p.x = Math.random() * (w + 60);
          }
          ctx.strokeStyle = `rgba(110, 225, 255, ${p.alpha.toFixed(2)})`;
          ctx.lineWidth = 1.4;
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(p.x - 2.5, p.y + p.size);
          ctx.stroke();
        } else if (internal.weather === 'snow') {
          p.y += p.speed * dt;
          p.x += Math.sin(ts * 0.0018 + p.phase) * 18 * dt;
          if (p.y > h + 10) {
            p.y = -10;
            p.x = Math.random() * w;
          }
          ctx.fillStyle = `rgba(224, 246, 255, ${p.alpha.toFixed(2)})`;
          ctx.beginPath();
          ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
          ctx.fill();
        } else if (internal.weather === 'sun') {
          p.y -= p.speed * 0.55 * dt;
          p.x += Math.sin(ts * 0.0012 + p.phase) * 10 * dt;
          if (p.y < -12) {
            p.y = h + 12;
            p.x = Math.random() * w;
          }
          ctx.fillStyle = `rgba(255, 218, 118, ${(p.alpha * 0.72).toFixed(2)})`;
          ctx.beginPath();
          ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }

    // 2. Emissão automática sutil de partículas para love / angry / sleepy / sweat
    if (ts - internal.lastFxSpawnAt > 580) {
      if (internal.emotion === 'love') {
        spawnHeartParticle((Math.random() - 0.5) * 1.1, -0.1, 1);
        internal.lastFxSpawnAt = ts;
      } else if (internal.emotion === 'angry') {
        spawnAngerSteam(1);
        internal.lastFxSpawnAt = ts;
      } else if (internal.emotion === 'sleepy' || internal.autoSleepy) {
        if (Math.random() < 0.55) {
          spawnZzzParticle();
        }
        internal.lastFxSpawnAt = ts;
      } else if (internal.sweat) {
        spawnSweatParticle();
        internal.lastFxSpawnAt = ts;
      }
    }

    // 3. Atualiza e desenha partículas transitórias
    for (let i = internal.fxParticles.length - 1; i >= 0; i -= 1) {
      const fp = internal.fxParticles[i];
      fp.life += dt;
      if (fp.life >= fp.maxLife) {
        internal.fxParticles.splice(i, 1);
        continue;
      }
      const progress = fp.life / fp.maxLife;
      const alpha = (1 - progress) * 0.85;
      fp.x += fp.vx * dt + Math.sin(fp.life * 4 + fp.wobbleSeed) * 10 * dt;
      fp.y += fp.vy * dt;

      if (fp.kind === 'heart') {
        drawHeart(ctx, fp.x, fp.y, fp.size, alpha);
      } else if (fp.kind === 'steam') {
        ctx.fillStyle = `rgba(255, 118, 72, ${(alpha * 0.65).toFixed(2)})`;
        ctx.beginPath();
        ctx.arc(fp.x, fp.y, fp.size * (0.7 + progress * 0.8), 0, Math.PI * 2);
        ctx.fill();
      } else if (fp.kind === 'zzz') {
        ctx.save();
        ctx.globalAlpha = alpha * 0.72;
        ctx.fillStyle = '#8fe3ee';
        ctx.font = `700 ${Math.round(fp.size)}px -apple-system, BlinkMacSystemFont, sans-serif`;
        ctx.fillText('z', fp.x, fp.y);
        ctx.restore();
      } else if (fp.kind === 'sweat') {
        ctx.fillStyle = `rgba(110, 230, 255, ${alpha.toFixed(2)})`;
        ctx.beginPath();
        ctx.arc(fp.x, fp.y, fp.size, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // 4. Inseto virtual (vagalume) quando o micro-evento estiver ativo
    if (bugCoords) {
      const bx = (0.5 + bugCoords.x * 0.42) * w;
      const by = (0.48 + bugCoords.y * 0.36) * h;
      internal.bugTrail.push({ x: bx, y: by });
      if (internal.bugTrail.length > 10) {
        internal.bugTrail.shift();
      }
      for (let i = 0; i < internal.bugTrail.length; i += 1) {
        const pt = internal.bugTrail[i];
        const ratio = (i + 1) / internal.bugTrail.length;
        ctx.fillStyle = `rgba(190, 255, 110, ${(ratio * 0.35).toFixed(2)})`;
        ctx.beginPath();
        ctx.arc(pt.x, pt.y, 1.5 + ratio * 2.2, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.fillStyle = '#d8ff7a';
      ctx.beginPath();
      ctx.arc(bx, by, 4, 0, Math.PI * 2);
      ctx.fill();
    } else if (internal.bugTrail.length > 0) {
      internal.bugTrail.length = 0;
    }
  }

  // -------------------- Aplicação das poses no SVG --------------------

  function applyEyePoseToDom(
    pose,
    els,
    isLeft,
    blinkAmount,
    popBoost,
    speakingPulse,
    synthPulse,
    stretchVal,
    curiosityScaleY,
    pokeSquint
  ) {
    // Squash-and-stretch preservando área aproximada (scaleX * scaleY ≈ 1)
    const blinkFactorY = 1 - blinkAmount * (pose.heartOpacity > 0.3 ? 0.88 : 0.16);
    const blinkFactorX = pose.heartOpacity > 0.3 ? 1 + blinkAmount * 0.12 : 1 / Math.max(0.75, blinkFactorY);
    const springFactorY = clamp(1 + stretchVal, 0.72, 1.32);
    const springFactorX = 1 / springFactorY;

    const pulseScale = 1 + speakingPulse + synthPulse * 0.045;
    const sx =
      pose.scaleX *
      (1 + popBoost) *
      (1 + speakingPulse * 0.4) *
      blinkFactorX *
      springFactorX;
    const sy =
      pose.scaleY *
      (1 + popBoost) *
      pulseScale *
      blinkFactorY *
      springFactorY *
      curiosityScaleY;

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
    if (els.dizzyGroup) {
      els.dizzyGroup.style.opacity = pose.dizzyOpacity.toFixed(3);
    }

    const effectiveBlink = clamp(Math.max(blinkAmount, pokeSquint), 0, 1);
    els.lidUpper.setAttribute('d', buildUpperLidPath(pose, isLeft, effectiveBlink));
    els.lidLower.setAttribute('d', buildLowerLidPath(pose, isLeft, effectiveBlink));
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
      internal.microEvent = null;
      syncDomAttributes();
    }

    // 1b. Micro-eventos autônomos em idle (a cada 25-45s antes dos 90s)
    if (
      internal.state === 'idle' &&
      !internal.autoSleepy &&
      internal.emotion === 'neutral' &&
      !internal.activeAnim &&
      !internal.microEvent &&
      !shouldReduceMotion() &&
      ts >= internal.nextIdleMicroEventAt &&
      ts - internal.lastInteractionAt < IDLE_SLEEP_TIMEOUT_MS - 3500
    ) {
      const choices = ['bug', 'yawn', 'peek_corner'];
      const pick = choices[Math.floor(Math.random() * choices.length)];
      if (pick === 'bug') {
        internal.microEvent = {
          kind: 'bug',
          startAt: ts,
          duration: 3600,
          seed: Math.random() * Math.PI * 2,
        };
      } else if (pick === 'yawn') {
        internal.microEvent = {
          kind: 'yawn',
          startAt: ts,
          duration: 2100,
        };
      } else {
        internal.microEvent = {
          kind: 'peek_corner',
          startAt: ts,
          duration: 2400,
          x: (Math.random() < 0.5 ? -1 : 1) * (0.72 + Math.random() * 0.14),
          y: Math.random() < 0.5 ? -0.46 : 0.4,
        };
      }
    }

    // Avança ou encerra micro-evento atual
    let bugCoords = null;
    let microYawnFactor = 0;
    if (internal.microEvent) {
      const ev = internal.microEvent;
      const elapsed = ts - ev.startAt;
      if (elapsed >= ev.duration) {
        internal.microEvent = null;
        startBlink(ts);
        scheduleNextMicroEvent(ts);
      } else if (ev.kind === 'bug') {
        const p = elapsed / ev.duration;
        const bx = clamp(Math.sin(p * Math.PI * 2.5 + ev.seed) * 0.78, -0.88, 0.88);
        const by = clamp(Math.cos(p * Math.PI * 3.2 + ev.seed * 0.7) * 0.55, -0.7, 0.7);
        bugCoords = { x: bx, y: by };
      } else if (ev.kind === 'yawn') {
        const p = elapsed / ev.duration;
        microYawnFactor = Math.sin(p * Math.PI);
      }
    }

    // 1c. Avança animação one-shot (laugh | confused | yawn)
    let animBounceY = 0;
    let animTiltDeg = 0;
    let animYawnFactor = 0;
    let animConfused = false;
    if (internal.activeAnim) {
      const anim = internal.activeAnim;
      const elapsed = ts - anim.startAt;
      if (elapsed >= anim.duration) {
        internal.activeAnim = null;
        if (anim.name === 'yawn') {
          startBlink(ts);
        }
      } else {
        const p = elapsed / anim.duration;
        if (anim.name === 'laugh') {
          animBounceY = -Math.abs(Math.sin(p * Math.PI * 6)) * 14 * (1 - p * 0.3);
          animTiltDeg = Math.sin(p * Math.PI * 4) * 3.5;
        } else if (anim.name === 'confused') {
          animConfused = true;
          animTiltDeg = Math.sin(p * Math.PI * 2.5) * 9;
        } else if (anim.name === 'yawn') {
          animYawnFactor = Math.sin(p * Math.PI);
          animTiltDeg = -4 * animYawnFactor;
        }
      }
    }

    // 2. Atualiza piscada natural e ocasional piscada dupla
    let blinkAmount = 0;
    if (internal.blinkActive) {
      const elapsed = ts - internal.blinkStartAt;
      if (elapsed >= internal.blinkDuration) {
        internal.blinkActive = false;
        // Rebote elástico sutil ao abrir os olhos
        triggerStretchImpulse(0.65, 0.65);
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
        blinkAmount =
          p < 0.42
            ? Math.sin((p / 0.42) * (Math.PI / 2))
            : Math.cos(((p - 0.42) / 0.58) * (Math.PI / 2));
      }
    } else if (ts >= internal.nextAutoBlinkAt && internal.state !== 'error') {
      internal.blinkPendingDouble = Math.random() < 0.18;
      startBlink(ts);
    }

    // 2b. Atualiza mola squash-and-stretch dos olhos
    const springK = 190;
    const springDamp = 16;
    internal.leftStretchVel += (-springK * internal.leftStretch - springDamp * internal.leftStretchVel) * dt;
    internal.leftStretch += internal.leftStretchVel * dt;
    internal.rightStretchVel += (-springK * internal.rightStretch - springDamp * internal.rightStretchVel) * dt;
    internal.rightStretch += internal.rightStretchVel * dt;

    // 3. Atualiza alvos de expressão/estado e interpola poses dos olhos
    const targets = resolveEyeTargets(internal.emotion, internal.state, internal.autoSleepy);

    // Ajustes temporários de animações one-shot e bocejo autônomo
    const yawnTotal = Math.max(animYawnFactor, microYawnFactor);
    if (yawnTotal > 0.02) {
      targets.left.upperOuter = lerp(targets.left.upperOuter, 4, yawnTotal);
      targets.left.upperMid = lerp(targets.left.upperMid, 12, yawnTotal);
      targets.left.upperInner = lerp(targets.left.upperInner, 4, yawnTotal);
      targets.left.lowerMid = lerp(targets.left.lowerMid, 72, yawnTotal);
      targets.left.scaleY *= 1 + yawnTotal * 0.06;

      targets.right.upperOuter = lerp(targets.right.upperOuter, 4, yawnTotal);
      targets.right.upperMid = lerp(targets.right.upperMid, 12, yawnTotal);
      targets.right.upperInner = lerp(targets.right.upperInner, 4, yawnTotal);
      targets.right.lowerMid = lerp(targets.right.lowerMid, 72, yawnTotal);
      targets.right.scaleY *= 1 + yawnTotal * 0.06;
    } else if (internal.activeAnim && internal.activeAnim.name === 'laugh') {
      targets.left.lowerOuter = 50;
      targets.left.lowerMid = -34;
      targets.left.lowerInner = 50;
      targets.right.lowerOuter = 50;
      targets.right.lowerMid = -34;
      targets.right.lowerInner = 50;
    } else if (animConfused) {
      targets.left.upperOuter = -18;
      targets.left.upperMid = -18;
      targets.left.upperInner = -18;
      targets.left.scaleY *= 0.92;
      targets.right.scaleX *= 1.12;
      targets.right.scaleY *= 1.15;
    }

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
      'dizzyOpacity',
      'highlightOpacity',
    ];
    for (let i = 0; i < keys.length; i += 1) {
      const k = keys[i];
      internal.leftPose[k] = lerp(internal.leftPose[k], targets.left[k], poseRate);
      internal.rightPose[k] = lerp(internal.rightPose[k], targets.right[k], poseRate);
    }

    // 4. Atualiza olhar 2D (estado + manual + micro-eventos + olhares em idle + sacadas)
    let desiredX = targets.gazeBiasX;
    let desiredY = targets.gazeBiasY;

    if (ts < internal.manualLookUntil) {
      desiredX = internal.manualLookX;
      desiredY = internal.manualLookY;
    } else if (bugCoords) {
      desiredX = bugCoords.x;
      desiredY = bugCoords.y;
    } else if (internal.microEvent && internal.microEvent.kind === 'peek_corner') {
      desiredX = internal.microEvent.x;
      desiredY = internal.microEvent.y;
    } else if (internal.state === 'thinking') {
      if (!shouldReduceMotion() && ts >= internal.nextThinkingFlipAt) {
        internal.thinkingSide *= -1;
        internal.nextThinkingFlipAt = ts + 1350;
      }
      desiredX = internal.thinkingSide * 0.48;
      desiredY = -0.54;
    } else if (internal.state === 'listening') {
      desiredX = 0;
      desiredY = 0;
    } else if (internal.state === 'idle' && !internal.autoSleepy) {
      if (shouldReduceMotion()) {
        desiredX = targets.gazeBiasX;
        desiredY = targets.gazeBiasY;
      } else {
        if (ts >= internal.nextIdleGlanceAt) {
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
      }
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

    // Curiosidade direcional: quando |lookX| > 0.6, aumenta levemente scaleY do olho externo
    let leftCuriosityY = 1;
    let rightCuriosityY = 1;
    const absLookX = Math.abs(internal.currentLookX);
    if (absLookX > 0.6 && internal.state !== 'error') {
      const extra = ((absLookX - 0.6) / 0.4) * 0.14;
      if (internal.currentLookX < 0) {
        leftCuriosityY = 1 + extra;
      } else {
        rightCuriosityY = 1 + extra;
      }
    }

    // 5. Atualiza nível de áudio suavizado, pulso do sintetizador, bounce e respiração
    const audioFactor = internal.targetAudioLevel > internal.smoothAudioLevel ? 0.3 : 0.16;
    internal.smoothAudioLevel = lerp(internal.smoothAudioLevel, internal.targetAudioLevel, audioFactor);

    const synthPulse =
      global.EmoAudio && typeof global.EmoAudio.getPulseLevel === 'function'
        ? clamp(global.EmoAudio.getPulseLevel(), 0, 1)
        : 0;
    const eyeSynthPulse = shouldReduceMotion() ? 0 : synthPulse;

    const isSpeaking = internal.state === 'speaking' || internal.smoothAudioLevel > 0.02;
    const breathAmp = internal.autoSleepy || internal.emotion === 'sleepy' ? 2.8 : 4.5;
    const breathFreq = internal.autoSleepy || internal.emotion === 'sleepy' ? 1.1 : 1.65;
    let headOffsetY = shouldReduceMotion() ? 0 : Math.sin(tSec * breathFreq) * breathAmp + animBounceY;
    let headOffsetX = 0;

    if (!shouldReduceMotion() && internal.emotion === 'excited') {
      headOffsetY += Math.abs(Math.sin(tSec * 5.5)) * -7;
    }
    if (!shouldReduceMotion() && internal.emotion === 'dizzy') {
      headOffsetX += Math.sin(tSec * 4.2) * 5.5;
      headOffsetY += Math.cos(tSec * 3.1) * 3.5;
    }
    if (isSpeaking && !shouldReduceMotion()) {
      const energy =
        internal.state === 'speaking'
          ? Math.max(0.18, internal.smoothAudioLevel)
          : internal.smoothAudioLevel;
      headOffsetY += Math.sin(tSec * 15.5) * (2.5 + energy * 8.5) - energy * 3.5;
    }
    if (internal.state === 'error' && !shouldReduceMotion()) {
      headOffsetX = Math.sin(tSec * 11) * 1.8;
    }

    const desiredTilt = targets.headTiltDeg + animTiltDeg;
    internal.currentTiltDeg = lerp(internal.currentTiltDeg, desiredTilt, 1 - Math.exp(-dt * 10));
    internal.els.head.setAttribute(
      'transform',
      `translate(${headOffsetX.toFixed(2)} ${headOffsetY.toFixed(2)}) rotate(${internal.currentTiltDeg.toFixed(2)} 400 ${EYE_CENTER_Y})`
    );

    // 6. Pop de escala, pulso de voz/sintetizador e semicerrar por poke
    internal.popBoost *= Math.exp(-dt * 11);
    if (internal.popBoost < 0.001) {
      internal.popBoost = 0;
    }
    const speakingPulse = isSpeaking && !shouldReduceMotion() ? internal.smoothAudioLevel * 0.068 : 0;

    const leftPokeSquint =
      ts < internal.leftPokeUntil ? Math.sin(((internal.leftPokeUntil - ts) / 420) * Math.PI) * 0.85 : 0;
    const rightPokeSquint =
      ts < internal.rightPokeUntil ? Math.sin(((internal.rightPokeUntil - ts) / 420) * Math.PI) * 0.85 : 0;

    applyEyePoseToDom(
      internal.leftPose,
      internal.els.left,
      true,
      blinkAmount,
      internal.popBoost,
      speakingPulse,
      eyeSynthPulse,
      internal.leftStretch,
      leftCuriosityY,
      clamp(leftPokeSquint, 0, 1)
    );
    applyEyePoseToDom(
      internal.rightPose,
      internal.els.right,
      false,
      blinkAmount,
      internal.popBoost,
      speakingPulse,
      eyeSynthPulse,
      internal.rightStretch,
      rightCuriosityY,
      clamp(rightPokeSquint, 0, 1)
    );

    // 7. Atualiza barras da onda de voz na coleira Cyber-Husky (sempre presente, pulsa com áudio)
    const showWave = internal.state === 'speaking' || internal.smoothAudioLevel > 0.02 || synthPulse > 0.06;
    internal.els.voiceWave.classList.toggle('is-active', showWave);
    const bars = internal.els.voiceBars;
    const centerIdx = (bars.length - 1) / 2;
    const baseLevel = showWave
      ? (internal.state === 'speaking'
          ? Math.max(0.22, internal.smoothAudioLevel, synthPulse * 0.7)
          : Math.max(internal.smoothAudioLevel, synthPulse * 0.75))
      : (internal.musicPlaying ? 0.18 : 0.06);
    for (let i = 0; i < bars.length; i += 1) {
      const distWeight = 1 - Math.abs(i - centerIdx) / (centerIdx + 1.15);
      const wave = shouldReduceMotion()
        ? 1
        : 0.45 + 0.55 * Math.abs(Math.sin(tSec * (showWave ? 13 : 4.2) + i * 0.85));
      const h = 4 + baseLevel * 20 * distWeight * wave;
      const y = 432 - h / 2;
      bars[i].setAttribute('height', h.toFixed(2));
      bars[i].setAttribute('y', y.toFixed(2));
    }

    // 7b. Comportamento corporal do Lupin (soneca, balanço musical, cauda e caminhada no overlay)
    const isSleepy = internal.autoSleepy || internal.emotion === 'sleepy';
    const miniPet = isMiniPet();
    const reducedMotion = shouldReduceMotion();
    if (isSleepy) {
      if (internal.behavior !== 'nap') {
        internal.behavior = 'nap';
        syncDomAttributes();
      }
    } else if (reducedMotion) {
      if (internal.behavior !== 'sit') {
        internal.behavior = 'sit';
        syncDomAttributes();
      }
    } else if (miniPet && !internal.compactMode && internal.state === 'idle') {
      if (!internal.nextBehaviorAt) {
        internal.nextBehaviorAt = ts + 7000;
      }
      if (ts >= internal.nextBehaviorAt) {
        internal.behavior = internal.behavior === 'walk' ? 'sit' : 'walk';
        internal.nextBehaviorAt = ts + (internal.behavior === 'walk' ? 6500 : 9000);
        syncDomAttributes();
      }
    } else if (internal.behavior !== 'sit') {
      internal.behavior = 'sit';
      syncDomAttributes();
    }

    // Balanço da cauda (acelera em happy/excited/love/speaking/music)
    if (internal.els.tail) {
      const happyBoost =
        internal.emotion === 'excited' || internal.emotion === 'love' || internal.emotion === 'happy'
          ? 1.8
          : 1;
      const wagFreq = isSleepy ? 0.9 : (internal.musicPlaying ? 5.2 : 2.6) * happyBoost;
      const wagAmp = isSleepy ? 3 : (internal.state === 'speaking' || internal.musicPlaying ? 12 : 6.5) * happyBoost;
      const tailRot = reducedMotion ? 0 : Math.sin(tSec * wagFreq) * wagAmp;
      internal.els.tail.setAttribute('transform', `translate(514, 520) rotate(${tailRot.toFixed(2)} 0 24)`);
    }

    // Ciclo de passos + caminhada horizontal no overlay desktop
    let rigOffsetX = 0;
    let rigOffsetY = 0;
    let legSwing = 0;
    if (internal.behavior === 'walk' && !reducedMotion) {
      internal.walkX += internal.walkDir * dt * 42;
      if (internal.walkX > 190) {
        internal.walkX = 190;
        internal.walkDir = -1;
      } else if (internal.walkX < -190) {
        internal.walkX = -190;
        internal.walkDir = 1;
      }
      rigOffsetX = internal.walkX;
      rigOffsetY = -Math.abs(Math.sin(tSec * 9.5)) * 6;
      legSwing = Math.sin(tSec * 9.5) * 11;
    } else {
      internal.walkX = lerp(internal.walkX, isMiniPet ? internal.walkX : 0, 1 - Math.exp(-dt * 6));
      rigOffsetX = isMiniPet ? internal.walkX : 0;
      if (internal.musicPlaying && !isSleepy && !reducedMotion) {
        rigOffsetY = Math.sin(tSec * 6.2) * 3.5;
      }
    }

    if (internal.els.legFL && internal.els.legFR) {
      internal.els.legFL.setAttribute('transform', `rotate(${legSwing.toFixed(2)} 356 490)`);
      internal.els.legFR.setAttribute('transform', `rotate(${(-legSwing).toFixed(2)} 444 490)`);
    }
    if (internal.els.legBL && internal.els.legBR) {
      internal.els.legBL.setAttribute('transform', `rotate(${(-legSwing * 0.75).toFixed(2)} 312 515)`);
      internal.els.legBR.setAttribute('transform', `rotate(${(legSwing * 0.75).toFixed(2)} 488 515)`);
    }
    if (internal.els.rig) {
      const facing = internal.behavior === 'walk' && internal.walkDir < 0 && !reducedMotion ? -1 : 1;
      const scaleTransform = facing < 0 ? 'translate(800, 0) scale(-1, 1)' : '';
      internal.els.rig.setAttribute(
        'transform',
        `translate(${rigOffsetX.toFixed(2)} ${rigOffsetY.toFixed(2)}) ${scaleTransform}`.trim()
      );
    }

    // 8. Atualiza partículas leves em canvas (clima, corações, Zzz, vapor, inseto)
    updateAndRenderParticles(ts, dt, bugCoords);

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
      clearMotionPreferenceListener();
      if (internal.rafId !== null && typeof global.cancelAnimationFrame === 'function') {
        global.cancelAnimationFrame(internal.rafId);
        internal.rafId = null;
      }
      if (internal.petPurrTimer !== null) {
        clearTimeout(internal.petPurrTimer);
        internal.petPurrTimer = null;
      }

      internal.container = targetEl;
      targetEl.innerHTML = buildFaceMarkup();
      internal.rootEl = targetEl.querySelector('.emo-face-root');
      internal.els = cacheElements(internal.rootEl);
      internal.canvasCtx = null;
      internal.canvasWidth = 0;
      internal.canvasHeight = 0;

      const t = nowMs();
      internal.lastFrameTime = t;
      internal.lastInteractionAt = t;
      internal.nextIdleGlanceAt = t + 2200;
      internal.nextSaccadeAt = t + 900;
      internal.nextThinkingFlipAt = t + 1100;
      scheduleNextBlink(t);
      scheduleNextMicroEvent(t);
      syncDomAttributes();
      bindMotionPreference();

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

      if (state !== prevState) {
        triggerStretchImpulse(0.75, 0.75);
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

      const prevEmotion = internal.emotion;
      internal.emotion = emotion;
      registerInteraction();

      if (emotion === 'surprised') {
        internal.popBoost = shouldReduceMotion() ? 0 : 0.14;
        triggerStretchImpulse(1.6, 1.6);
      } else if (emotion === 'angry') {
        internal.popBoost = shouldReduceMotion() ? 0 : 0.06;
        triggerStretchImpulse(-0.9, -0.9);
      } else if (emotion !== prevEmotion) {
        triggerStretchImpulse(0.85, 0.85);
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
      triggerStretchImpulse(-0.55, -0.55);
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

    /**
     * Reage ao toque direto no rosto ('poke' ou 'pet') com coordenadas normalizadas (-1..1).
     */
    reactToTouch(kind, nx, ny) {
      const t = nowMs();
      const x = clamp(Number(nx) || 0, -1, 1);
      const y = clamp(Number(ny) || 0, -1, 1);

      if (kind === 'pet_end' || kind === 'release') {
        if (internal.petPurrTimer !== null) {
          clearTimeout(internal.petPurrTimer);
          internal.petPurrTimer = null;
        }
        internal.petStreak = 0;
        if (global.EmoAudio && typeof global.EmoAudio.purr === 'function') {
          global.EmoAudio.purr(false);
        }
        return;
      }

      registerInteraction(t);

      if (kind === 'poke') {
        internal.manualLookX = x;
        internal.manualLookY = y;
        internal.manualLookUntil = t + 1800;

        // Olho atingido pisca/semicerra com squash elástico
        if (x < -0.1) {
          internal.leftPokeUntil = t + 420;
          triggerStretchImpulse(-2.1, 0.35);
        } else if (x > 0.1) {
          internal.rightPokeUntil = t + 420;
          triggerStretchImpulse(0.35, -2.1);
        } else {
          internal.leftPokeUntil = t + 420;
          internal.rightPokeUntil = t + 420;
          triggerStretchImpulse(-1.8, -1.8);
        }

        // Registra toques rápidos em sequência (janela de 3.5s)
        internal.pokeTimestamps = internal.pokeTimestamps.filter((ts) => t - ts < 3500);
        internal.pokeTimestamps.push(t);

        if (internal.pokeTimestamps.length >= 5) {
          EmoFace.setEmotion('angry', { durationMs: 3600 });
          spawnAngerSteam(4);
          if (global.EmoAudio && typeof global.EmoAudio.chirp === 'function') {
            global.EmoAudio.chirp('angry');
          }
        } else if (internal.pokeTimestamps.length >= 3) {
          EmoFace.setEmotion('skeptical', { durationMs: 3000 });
          if (global.EmoAudio && typeof global.EmoAudio.chirp === 'function') {
            global.EmoAudio.chirp('skeptical');
          }
        } else if (global.EmoAudio && typeof global.EmoAudio.click === 'function') {
          global.EmoAudio.click();
        }
        return;
      }

      if (kind === 'pet') {
        EmoFace.lookAt(x, y);
        if (t - internal.lastPetAt > 1200) {
          internal.petStreak = 0;
        }
        internal.lastPetAt = t;
        internal.petStreak += 1;

        const targetExpr = internal.petStreak >= 3 ? 'love' : 'happy';
        EmoFace.setEmotion(targetExpr, { durationMs: 2400 });
        spawnHeartParticle(x, y, 2);

        if (global.EmoAudio && typeof global.EmoAudio.purr === 'function') {
          global.EmoAudio.purr(true);
          if (internal.petPurrTimer !== null) {
            clearTimeout(internal.petPurrTimer);
          }
          internal.petPurrTimer = setTimeout(() => {
            internal.petPurrTimer = null;
            internal.petStreak = 0;
            if (global.EmoAudio && typeof global.EmoAudio.purr === 'function') {
              global.EmoAudio.purr(false);
            }
          }, 480);
        }
      }
    },

    /**
     * Define o acessório SVG exibido sobre #emo-face-head.
     */
    setAccessory(name) {
      const normalized = typeof name === 'string' ? name.toLowerCase() : 'none';
      if (!SUPPORTED_ACCESSORIES.includes(normalized)) {
        if (typeof console !== 'undefined' && console.warn) {
          console.warn(`[EmoFace] Acessório desconhecido ignorado: ${name}`);
        }
        return internal.accessory;
      }
      internal.accessory = normalized;
      syncDomAttributes();
      return internal.accessory;
    },

    /**
     * Define o efeito climático na camada de partículas canvas.
     */
    setWeather(effect) {
      const normalized = typeof effect === 'string' ? effect.toLowerCase() : 'none';
      if (!SUPPORTED_WEATHER.includes(normalized)) {
        if (typeof console !== 'undefined' && console.warn) {
          console.warn(`[EmoFace] Efeito de clima desconhecido ignorado: ${effect}`);
        }
        return internal.weather;
      }
      internal.weather = normalized;
      initWeatherPool(normalized);
      syncDomAttributes();
      return internal.weather;
    },

    /**
     * Ativa ou oculta a gotinha de suor SVG.
     */
    setSweat(active) {
      internal.sweat = Boolean(active);
      syncDomAttributes();
      return internal.sweat;
    },

    /**
     * Alterna o modo compacto (.emo-compact) para a faixa superior no modo Dock & Atalhos.
     */
    setCompactMode(active) {
      internal.compactMode = Boolean(active);
      if (internal.els && internal.els.svg) {
        internal.els.svg.setAttribute('viewBox', internal.compactMode ? '0 0 800 470' : '0 0 800 660');
      }
      syncDomAttributes();
      return internal.compactMode;
    },

    /**
     * Informa ao Lupin que há música tocando (ativa balanço rítmico e onda na coleira).
     */
    setMusicPlaying(active) {
      internal.musicPlaying = Boolean(active);
      syncDomAttributes();
      return internal.musicPlaying;
    },

    /**
     * Retorna o retângulo de tela atual do rig do Lupin (usado para click-through no Electron).
     */
    getHitboxRect() {
      if (!internal.els || !internal.els.rig) return null;
      return internal.els.rig.getBoundingClientRect();
    },

    /**
     * Executa uma coreografia visual de truque do pet ('dance', 'sing', 'meditate', 'nap', 'celebrate', 'stretch').
     */
    playTrick(trickId) {
      const id = typeof trickId === 'string' ? trickId.toLowerCase() : '';
      const t = nowMs();
      registerInteraction(t);

      if (shouldReduceMotion()) {
        const emotions = {
          dance: 'excited',
          sing: 'happy',
          meditate: 'love',
          nap: 'sleepy',
          celebrate: 'excited',
          stretch: 'happy',
        };
        if (!emotions[id]) return false;
        EmoFace.setEmotion(emotions[id]);
        return true;
      }

      if (id === 'dance') {
        EmoFace.setEmotion('excited', { durationMs: 2800 });
        [-0.7, 0.7, -0.6, 0.6, 0].forEach((lx, idx) => {
          setTimeout(() => {
            EmoFace.lookAt(lx, idx % 2 === 0 ? -0.35 : 0.25);
            triggerStretchImpulse(idx % 2 === 0 ? 1.8 : -1.5, idx % 2 === 0 ? -1.5 : 1.8);
            spawnHeartParticle(lx, -0.2, 2);
          }, idx * 420);
        });
        return true;
      }

      if (id === 'sing') {
        EmoFace.setEmotion('happy', { durationMs: 3000 });
        [0, 1, 2, 3, 4].forEach((step) => {
          setTimeout(() => {
            EmoFace.lookAt(step % 2 === 0 ? -0.35 : 0.35, -0.3);
            triggerStretchImpulse(1.2, 1.2);
            spawnHeartParticle(step % 2 === 0 ? -0.4 : 0.4, -0.3, 1);
          }, step * 480);
        });
        return true;
      }

      if (id === 'meditate') {
        EmoFace.setEmotion('love', { durationMs: 3400 });
        EmoFace.lookAt(0, 0.15);
        [0, 1, 2].forEach((step) => {
          setTimeout(() => {
            triggerStretchImpulse(-0.6, -0.6);
            spawnHeartParticle(0, -0.2, 1);
          }, step * 950);
        });
        return true;
      }

      if (id === 'nap') {
        EmoFace.setEmotion('sleepy', { durationMs: 3600 });
        EmoFace.lookAt(0, 0.4);
        [0, 1, 2, 3].forEach((step) => {
          setTimeout(() => {
            spawnZzzParticle();
          }, step * 700);
        });
        return true;
      }

      if (id === 'celebrate') {
        EmoFace.setEmotion('excited', { durationMs: 2600 });
        triggerStretchImpulse(2.4, 2.4);
        spawnHeartParticle(0, 0, 5);
        setTimeout(() => {
          triggerStretchImpulse(2.0, 2.0);
          spawnHeartParticle(-0.5, -0.3, 3);
          spawnHeartParticle(0.5, -0.3, 3);
        }, 500);
        return true;
      }

      if (id === 'stretch') {
        EmoFace.setEmotion('happy', { durationMs: 2400 });
        triggerStretchImpulse(2.6, 2.6);
        setTimeout(() => {
          triggerStretchImpulse(-1.6, -1.6);
          EmoFace.lookAt(0, -0.2);
        }, 650);
        return true;
      }

      return false;
    },

    /**
     * Executa uma animação one-shot ('laugh' | 'confused' | 'yawn').
     */
    playAnimation(name) {
      const normalized = typeof name === 'string' ? name.toLowerCase() : '';
      if (!SUPPORTED_ANIMATIONS.includes(normalized)) {
        if (typeof console !== 'undefined' && console.warn) {
          console.warn(`[EmoFace] Animação desconhecida ignorada: ${name}`);
        }
        return false;
      }
      const t = nowMs();
      registerInteraction(t);

      const durations = { laugh: 1600, confused: 1600, yawn: 2200 };
      internal.activeAnim = shouldReduceMotion()
        ? null
        : {
            name: normalized,
            startAt: t,
            duration: durations[normalized],
          };

      if (normalized === 'laugh') {
        triggerStretchImpulse(1.2, 1.2);
        if (global.EmoAudio && typeof global.EmoAudio.chirp === 'function') {
          global.EmoAudio.chirp('happy');
        }
      } else if (normalized === 'confused') {
        triggerStretchImpulse(-0.7, 1.1);
        if (global.EmoAudio && typeof global.EmoAudio.chirp === 'function') {
          global.EmoAudio.chirp('curious');
        }
      } else if (normalized === 'yawn') {
        triggerStretchImpulse(0.9, 0.9);
        if (global.EmoAudio && typeof global.EmoAudio.chirp === 'function') {
          global.EmoAudio.chirp('sleepy');
        }
      }

      return true;
    },
  };

  global.EmoFace = EmoFace;
})(typeof window !== 'undefined' ? window : globalThis);
