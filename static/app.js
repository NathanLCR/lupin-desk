/**
 * Controlador principal da interface web do Assistente de Mesa.
 * Integra WebSocket (/ws), API de memória (/api/memory), síntese de voz (TTS),
 * expressões faciais (window.EmoFace), legendas em streaming e tela cheia.
 */
(() => {
  'use strict';

  const FALLBACK_EMOTIONS = [
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
  ];

  const FALLBACK_STATES = ['idle', 'listening', 'thinking', 'speaking', 'error'];

  const EMOTION_LABELS_PT = {
    neutral: 'neutro',
    happy: 'feliz',
    excited: 'animado',
    curious: 'curioso',
    skeptical: 'cético',
    surprised: 'surpreso',
    sad: 'triste',
    wink: 'piscando',
    love: 'carinhoso',
    sleepy: 'sonolento',
  };

  const STATE_LABELS_PT = {
    idle: 'ocioso',
    listening: 'ouvindo',
    thinking: 'pensando',
    speaking: 'falando',
    error: 'erro',
  };

  const CATEGORY_LABELS_PT = {
    general: 'geral',
    name: 'nome',
    identity: 'identidade',
    location: 'local',
    preference: 'preferência',
    routine: 'rotina',
    personal: 'pessoal',
    work: 'trabalho',
  };

  const TYPING_IDLE_MS = 2500;
  const HUD_AUTO_HIDE_MS = 5000;
  const WS_RECONNECT_BASE_MS = 2000;
  const WS_RECONNECT_MAX_MS = 8000;
  const TTS_STORAGE_KEY = 'desk_assistant_tts_enabled';
  const CAPTION_STORAGE_KEY = 'desk_assistant_caption_visible';

  // Referências de DOM
  const els = {
    faceContainer: document.getElementById('face-container'),
    hud: document.getElementById('hud'),
    wsDot: document.getElementById('ws-dot'),
    wsStatusText: document.getElementById('ws-status-text'),
    stateLabel: document.getElementById('state-label'),
    emotionLabel: document.getElementById('emotion-label'),
    btnExpressions: document.getElementById('btn-expressions'),
    btnMemory: document.getElementById('btn-memory'),
    memoryCount: document.getElementById('memory-count'),
    btnTts: document.getElementById('btn-tts'),
    btnCaption: document.getElementById('btn-caption'),
    btnFullscreen: document.getElementById('btn-fullscreen'),
    btnHudPin: document.getElementById('btn-hud-pin'),
    expressionsBar: document.getElementById('expressions-bar'),
    emotionChips: document.getElementById('emotion-chips'),
    stateChips: document.getElementById('state-chips'),
    audioUnlockBanner: document.getElementById('audio-unlock-banner'),
    captionBox: document.getElementById('caption-box'),
    captionText: document.getElementById('caption-text'),
    chatForm: document.getElementById('chat-form'),
    chatInput: document.getElementById('chat-input'),
    memoryBackdrop: document.getElementById('memory-backdrop'),
    memoryDrawer: document.getElementById('memory-drawer'),
    btnCloseMemory: document.getElementById('btn-close-memory'),
    recentMessagesBadge: document.getElementById('recent-messages-badge'),
    btnClearChat: document.getElementById('btn-clear-chat'),
    factsCountBadge: document.getElementById('facts-count-badge'),
    addFactForm: document.getElementById('add-fact-form'),
    factInput: document.getElementById('fact-input'),
    factCategory: document.getElementById('fact-category'),
    factsEmpty: document.getElementById('facts-empty'),
    factsList: document.getElementById('facts-list'),
    btnResetMemory: document.getElementById('btn-reset-memory'),
    resetConfirmBox: document.getElementById('reset-confirm-box'),
    btnConfirmReset: document.getElementById('btn-confirm-reset'),
    btnCancelReset: document.getElementById('btn-cancel-reset'),
  };

  // Estado da aplicação
  const state = {
    ws: null,
    wsConnected: false,
    reconnectDelayMs: WS_RECONNECT_BASE_MS,
    reconnectTimer: null,
    typingActive: false,
    typingTimer: null,
    hudPinned: false,
    hudTimer: null,
    expressionsOpen: false,
    memoryOpen: false,
    captionVisible: loadBoolPref(CAPTION_STORAGE_KEY, true),
    ttsEnabled: loadBoolPref(TTS_STORAGE_KEY, true),
    audioUnlocked: false,
    selectedVoice: null,
    activeUtterance: null,
    audioLevelTimer: null,
    speechStartGuardTimer: null,
    audioPhase: 0,
    streamingText: '',
    facts: [],
    recentMessagesCount: 0,
    wakeLock: null,
  };

  function loadBoolPref(key, fallback) {
    try {
      const raw = window.localStorage.getItem(key);
      if (raw === null) return fallback;
      return raw === 'true';
    } catch {
      return fallback;
    }
  }

  function saveBoolPref(key, value) {
    try {
      window.localStorage.setItem(key, String(Boolean(value)));
    } catch {
      // Ignora erro de armazenamento em modo restrito
    }
  }

  // Acesso seguro à API pública window.EmoFace
  function faceApi() {
    return window.EmoFace || null;
  }

  function applyFaceState(nextState) {
    const api = faceApi();
    if (api && typeof api.setState === 'function') {
      api.setState(nextState);
    }
    syncFaceBadges();
  }

  function applyFaceEmotion(nextEmotion, opts) {
    const api = faceApi();
    if (api && typeof api.setEmotion === 'function') {
      api.setEmotion(nextEmotion, opts);
    }
    syncFaceBadges();
  }

  function lookAtSafe(x, y) {
    const api = faceApi();
    if (api && typeof api.lookAt === 'function') {
      api.lookAt(x, y);
    }
  }

  function setAudioLevelSafe(level) {
    const api = faceApi();
    if (api && typeof api.setAudioLevel === 'function') {
      api.setAudioLevel(level);
    }
  }

  function syncFaceBadges() {
    const api = faceApi();
    const currentState = api && typeof api.getState === 'function' ? api.getState() : 'idle';
    const currentEmotion = api && typeof api.getEmotion === 'function' ? api.getEmotion() : 'neutral';

    els.stateLabel.textContent = currentState;
    els.emotionLabel.textContent = currentEmotion;

    updateChipSelection(els.stateChips, currentState);
    updateChipSelection(els.emotionChips, currentEmotion);
  }

  function updateChipSelection(container, activeValue) {
    if (!container) return;
    const buttons = container.querySelectorAll('.chip-btn');
    buttons.forEach((btn) => {
      btn.classList.toggle('is-selected', btn.dataset.value === activeValue);
    });
  }

  // Monta os chips de teste das 10 emoções e 5 estados
  function buildExpressionChips() {
    const api = faceApi();
    const emotions =
      api && typeof api.getSupportedEmotions === 'function'
        ? api.getSupportedEmotions()
        : FALLBACK_EMOTIONS;
    const states =
      api && typeof api.getSupportedStates === 'function'
        ? api.getSupportedStates()
        : FALLBACK_STATES;

    els.emotionChips.textContent = '';
    emotions.forEach((emotion) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'chip-btn';
      btn.dataset.value = emotion;
      btn.textContent = `${emotion} (${EMOTION_LABELS_PT[emotion] || emotion})`;
      btn.addEventListener('click', () => {
        applyFaceEmotion(emotion);
      });
      els.emotionChips.appendChild(btn);
    });

    els.stateChips.textContent = '';
    states.forEach((st) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'chip-btn';
      btn.dataset.value = st;
      btn.textContent = `${st} (${STATE_LABELS_PT[st] || st})`;
      btn.addEventListener('click', () => {
        applyFaceState(st);
      });
      els.stateChips.appendChild(btn);
    });

    syncFaceBadges();
  }

  // Controle de visibilidade e auto-ocultar da HUD superior
  function showHud() {
    els.hud.classList.remove('is-hidden');
    scheduleHudAutoHide();
  }

  function scheduleHudAutoHide() {
    if (state.hudTimer) {
      window.clearTimeout(state.hudTimer);
      state.hudTimer = null;
    }

    const canAutoHide =
      !state.hudPinned &&
      !state.expressionsOpen &&
      !state.memoryOpen &&
      document.activeElement !== els.chatInput;

    if (!canAutoHide) return;

    state.hudTimer = window.setTimeout(() => {
      const stillCanHide =
        !state.hudPinned &&
        !state.expressionsOpen &&
        !state.memoryOpen &&
        document.activeElement !== els.chatInput;
      if (stillCanHide) {
        els.hud.classList.add('is-hidden');
      }
    }, HUD_AUTO_HIDE_MS);
  }

  function toggleHudPin() {
    state.hudPinned = !state.hudPinned;
    els.btnHudPin.classList.toggle('is-active', state.hudPinned);
    els.btnHudPin.setAttribute('aria-pressed', String(state.hudPinned));
    showHud();
  }

  // Controle de legendas em streaming
  function setCaption(text, { isError = false } = {}) {
    const clean = (text || '').trim();
    els.captionText.textContent = clean;
    els.captionBox.classList.toggle('is-empty', clean.length === 0);
    els.captionBox.classList.toggle('is-error', isError);
    if (clean.length > 0) {
      els.captionBox.scrollTop = els.captionBox.scrollHeight;
    }
  }

  function syncCaptionVisibilityUI() {
    els.captionBox.classList.toggle('is-hidden-by-user', !state.captionVisible);
    els.btnCaption.classList.toggle('is-active', state.captionVisible);
    els.btnCaption.setAttribute('aria-pressed', String(state.captionVisible));
  }

  // Síntese de voz (TTS) via Web Speech API
  function supportsSpeechSynthesis() {
    return typeof window !== 'undefined' && 'speechSynthesis' in window;
  }

  function pickBestPortugueseVoice() {
    if (!supportsSpeechSynthesis()) return null;
    const voices = window.speechSynthesis.getVoices() || [];
    if (voices.length === 0) return null;

    const ptBrVoices = voices.filter((v) => /^pt[-_]br$/i.test(v.lang));
    const ptAnyVoices = voices.filter((v) => /^pt\b/i.test(v.lang));
    const pool = ptBrVoices.length > 0 ? ptBrVoices : ptAnyVoices;
    if (pool.length === 0) return null;

    // Prioriza vozes naturais conhecidas no macOS e Chrome
    const preferredPatterns = [
      /luciana/i,
      /felipe/i,
      /google.*portugu/i,
      /natural/i,
      /enhanced/i,
      /neural/i,
    ];
    for (const pattern of preferredPatterns) {
      const match = pool.find((v) => pattern.test(v.name));
      if (match) return match;
    }

    return pool[0];
  }

  function refreshVoices() {
    state.selectedVoice = pickBestPortugueseVoice();
  }

  function unlockAudio() {
    if (state.audioUnlocked) return;
    state.audioUnlocked = true;
    els.audioUnlockBanner.classList.add('hidden');

    if (!supportsSpeechSynthesis()) return;
    try {
      window.speechSynthesis.resume();
      // Utterance silenciosa curta destrava autoplay em navegadores baseados em WebKit/Blink
      if (!window.speechSynthesis.speaking) {
        const primer = new SpeechSynthesisUtterance(' ');
        primer.volume = 0;
        primer.rate = 10;
        primer.lang = 'pt-BR';
        window.speechSynthesis.speak(primer);
      }
      refreshVoices();
    } catch {
      // Silencia eventuais bloqueios de ambiente headless
    }
  }

  function clearAudioLevelTimer() {
    if (state.audioLevelTimer) {
      window.clearInterval(state.audioLevelTimer);
      state.audioLevelTimer = null;
    }
    if (state.speechStartGuardTimer) {
      window.clearTimeout(state.speechStartGuardTimer);
      state.speechStartGuardTimer = null;
    }
    setAudioLevelSafe(0);
  }

  function startAudioLevelAnimation() {
    clearAudioLevelTimer();
    state.audioPhase = 0;
    state.audioLevelTimer = window.setInterval(() => {
      state.audioPhase += 0.48;
      // Modulação orgânica simulando sílabas enquanto o navegador fala
      const wave =
        0.5 +
        0.26 * Math.sin(state.audioPhase) +
        0.16 * Math.sin(state.audioPhase * 2.3 + 0.7) +
        (Math.random() - 0.5) * 0.14;
      const clamped = Math.max(0.15, Math.min(0.95, wave));
      setAudioLevelSafe(clamped);
    }, 65);
  }

  function stopSpeaking({ resetState = true } = {}) {
    state.activeUtterance = null;
    clearAudioLevelTimer();
    if (supportsSpeechSynthesis()) {
      try {
        window.speechSynthesis.cancel();
      } catch {
        // Ignora erro caso speechSynthesis não esteja ativo
      }
    }
    if (resetState) {
      applyFaceState('idle');
    }
  }

  function speakText(text) {
    const clean = (text || '').trim();
    if (!state.ttsEnabled || !clean || !supportsSpeechSynthesis()) {
      applyFaceState('idle');
      return;
    }

    stopSpeaking({ resetState: false });
    refreshVoices();

    const utterance = new SpeechSynthesisUtterance(clean);
    utterance.lang = 'pt-BR';
    utterance.rate = 1.02;
    utterance.pitch = 1.0;
    if (state.selectedVoice) {
      utterance.voice = state.selectedVoice;
    }

    state.activeUtterance = utterance;
    let started = false;

    utterance.onstart = () => {
      if (state.activeUtterance !== utterance) return;
      started = true;
      if (state.speechStartGuardTimer) {
        window.clearTimeout(state.speechStartGuardTimer);
        state.speechStartGuardTimer = null;
      }
      applyFaceState('speaking');
      startAudioLevelAnimation();
    };

    utterance.onboundary = () => {
      if (state.activeUtterance !== utterance) return;
      // Pequeno reforço rítmico no início de cada palavra quando o navegador emite onboundary
      setAudioLevelSafe(0.88);
    };

    const handleFinish = () => {
      if (state.activeUtterance !== utterance) return;
      state.activeUtterance = null;
      clearAudioLevelTimer();
      applyFaceState('idle');
    };

    utterance.onend = handleFinish;
    utterance.onerror = handleFinish;

    // Salvaguarda caso o navegador bloqueie autoplay ou não dispare onstart
    state.speechStartGuardTimer = window.setTimeout(() => {
      if (
        state.activeUtterance === utterance &&
        !started &&
        !window.speechSynthesis.speaking
      ) {
        state.activeUtterance = null;
        clearAudioLevelTimer();
        applyFaceState('idle');
        if (!state.audioUnlocked) {
          els.audioUnlockBanner.classList.remove('hidden');
        }
      }
    }, 1000);

    try {
      window.speechSynthesis.speak(utterance);
    } catch {
      handleFinish();
    }
  }

  function syncTtsUI() {
    els.btnTts.textContent = state.ttsEnabled ? '🔊 Voz' : '🔇 Mudo';
    els.btnTts.classList.toggle('is-active', state.ttsEnabled);
    els.btnTts.setAttribute('aria-pressed', String(state.ttsEnabled));
  }

  // Conexão WebSocket com reconexão automática (backoff a partir de 2s)
  function setWsStatus(mode, label) {
    els.wsDot.classList.remove('is-connected', 'is-reconnecting');
    if (mode === 'connected') {
      els.wsDot.classList.add('is-connected');
    } else if (mode === 'reconnecting') {
      els.wsDot.classList.add('is-reconnecting');
    }
    els.wsStatusText.textContent = label;
  }

  function sendWs(payload) {
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
      return false;
    }
    state.ws.send(JSON.stringify(payload));
    return true;
  }

  function scheduleReconnect() {
    if (state.reconnectTimer) return;
    const waitMs = state.reconnectDelayMs;
    state.reconnectDelayMs = Math.min(state.reconnectDelayMs * 1.5, WS_RECONNECT_MAX_MS);
    setWsStatus('reconnecting', 'Reconectando...');

    state.reconnectTimer = window.setTimeout(() => {
      state.reconnectTimer = null;
      connectWebSocket();
    }, waitMs);
  }

  function connectWebSocket() {
    if (
      state.ws &&
      (state.ws.readyState === WebSocket.OPEN || state.ws.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    setWsStatus('reconnecting', 'Conectando...');

    const ws = new WebSocket(wsUrl);
    state.ws = ws;

    ws.addEventListener('open', () => {
      state.wsConnected = true;
      state.reconnectDelayMs = WS_RECONNECT_BASE_MS;
      setWsStatus('connected', 'Conectado');
      fetchMemory();
    });

    ws.addEventListener('message', (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }
      handleWsMessage(msg);
    });

    ws.addEventListener('close', () => {
      state.wsConnected = false;
      state.ws = null;
      setWsStatus('disconnected', 'Desconectado');
      scheduleReconnect();
    });

    ws.addEventListener('error', () => {
      setWsStatus('reconnecting', 'Erro na conexão');
    });
  }

  function handleWsMessage(msg) {
    if (!msg || typeof msg.type !== 'string') return;

    switch (msg.type) {
      case 'state': {
        if (msg.state) {
          applyFaceState(msg.state);
        }
        break;
      }
      case 'emotion': {
        if (msg.emotion) {
          applyFaceEmotion(msg.emotion);
        }
        break;
      }
      case 'delta': {
        const chunk = typeof msg.text === 'string' ? msg.text : '';
        if (chunk) {
          state.streamingText += chunk;
          setCaption(state.streamingText);
        }
        break;
      }
      case 'done': {
        const finalText =
          typeof msg.text === 'string' && msg.text.length > 0
            ? msg.text
            : state.streamingText;
        state.streamingText = finalText;
        setCaption(finalText);
        if (msg.emotion) {
          applyFaceEmotion(msg.emotion);
        }
        speakText(finalText);
        break;
      }
      case 'memory_updated': {
        renderMemoryState(msg.facts, msg.recent_messages_count);
        break;
      }
      case 'error': {
        stopSpeaking({ resetState: false });
        applyFaceState('error');
        setCaption(msg.message || 'Ocorreu um erro ao processar sua mensagem.', {
          isError: true,
        });
        break;
      }
      default:
        break;
    }
  }

  // Controle de digitação com debounce e olhar sutil para a caixa de texto
  function stopTypingSignal({ resetLook = true } = {}) {
    if (state.typingTimer) {
      window.clearTimeout(state.typingTimer);
      state.typingTimer = null;
    }
    if (state.typingActive) {
      state.typingActive = false;
      sendWs({ type: 'typing', active: false });
    }
    if (resetLook) {
      lookAtSafe(0, 0);
    }
  }

  function handleInputActivity() {
    const hasText = els.chatInput.value.trim().length > 0;
    if (!hasText) {
      stopTypingSignal({ resetLook: document.activeElement !== els.chatInput });
      return;
    }

    if (!state.typingActive) {
      state.typingActive = true;
      sendWs({ type: 'typing', active: true });
    }
    lookAtSafe(0, 0.35);

    if (state.typingTimer) {
      window.clearTimeout(state.typingTimer);
    }
    state.typingTimer = window.setTimeout(() => {
      stopTypingSignal({ resetLook: true });
    }, TYPING_IDLE_MS);
  }

  function handleChatSubmit(event) {
    event.preventDefault();
    unlockAudio();

    const text = els.chatInput.value.trim();
    if (!text) return;

    stopSpeaking({ resetState: false });
    if (state.typingTimer) {
      window.clearTimeout(state.typingTimer);
      state.typingTimer = null;
    }
    state.typingActive = false;

    state.streamingText = '';
    setCaption('...');

    const sent = sendWs({ type: 'text', text });
    if (!sent) {
      applyFaceState('error');
      setCaption('Sem conexão no momento. Tentando reconectar...', { isError: true });
      return;
    }

    els.chatInput.value = '';
    lookAtSafe(0, 0);
    scheduleHudAutoHide();
  }

  // API HTTP e renderização do painel de memória
  function renderMemoryState(facts, recentCount) {
    const safeFacts = Array.isArray(facts) ? facts : [];
    const safeCount = typeof recentCount === 'number' ? recentCount : 0;

    state.facts = safeFacts;
    state.recentMessagesCount = safeCount;

    els.memoryCount.textContent = String(safeFacts.length);
    els.factsCountBadge.textContent = String(safeFacts.length);
    els.recentMessagesBadge.textContent =
      safeCount === 1 ? '1 msg' : `${safeCount} msgs`;

    els.factsList.textContent = '';
    els.factsEmpty.classList.toggle('hidden', safeFacts.length > 0);

    safeFacts.forEach((item) => {
      const li = document.createElement('li');
      li.className = 'fact-item';

      const contentDiv = document.createElement('div');
      contentDiv.className = 'fact-content';

      const catSpan = document.createElement('span');
      catSpan.className = 'fact-cat-tag';
      const catKey = item.category || 'general';
      catSpan.textContent = CATEGORY_LABELS_PT[catKey] || catKey;

      const textSpan = document.createElement('span');
      textSpan.className = 'fact-text';
      textSpan.textContent = item.fact || '';

      contentDiv.appendChild(catSpan);
      contentDiv.appendChild(textSpan);

      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className = 'fact-delete-btn';
      delBtn.title = 'Remover este fato';
      delBtn.setAttribute('aria-label', `Remover fato: ${item.fact || ''}`);
      delBtn.textContent = '×';
      delBtn.addEventListener('click', () => {
        deleteFact(item.id);
      });

      li.appendChild(contentDiv);
      li.appendChild(delBtn);
      els.factsList.appendChild(li);
    });
  }

  async function fetchMemory() {
    try {
      const res = await fetch('/api/memory');
      if (!res.ok) return;
      const data = await res.json();
      renderMemoryState(data.facts, data.recent_messages_count);
    } catch {
      // Falha silenciosa durante reconexão
    }
  }

  async function addManualFact(event) {
    event.preventDefault();
    const fact = els.factInput.value.trim();
    const category = els.factCategory.value || 'general';
    if (!fact) return;

    try {
      const res = await fetch('/api/memory/facts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fact, category }),
      });
      if (!res.ok) return;
      els.factInput.value = '';
      await fetchMemory();
    } catch {
      // Ignora erro transitório
    }
  }

  async function deleteFact(factId) {
    if (factId === undefined || factId === null) return;
    try {
      const res = await fetch(`/api/memory/facts/${encodeURIComponent(factId)}`, {
        method: 'DELETE',
      });
      if (!res.ok) return;
      await fetchMemory();
    } catch {
      // Ignora erro transitório
    }
  }

  async function clearMemory({ includeFacts }) {
    try {
      const res = await fetch('/api/memory/clear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ include_facts: Boolean(includeFacts) }),
      });
      if (!res.ok) return;
      const data = await res.json();
      renderMemoryState(data.facts, data.recent_messages_count);
      hideResetConfirmation();
      if (!includeFacts) {
        setCaption('Conversa atual limpa.');
      } else {
        setCaption('Toda a memória foi resetada.');
      }
    } catch {
      // Ignora erro transitório
    }
  }

  function openMemoryDrawer() {
    state.memoryOpen = true;
    els.memoryBackdrop.classList.remove('hidden');
    els.memoryDrawer.classList.remove('hidden');
    els.memoryDrawer.setAttribute('aria-hidden', 'false');
    els.btnMemory.setAttribute('aria-expanded', 'true');
    els.btnMemory.classList.add('is-active');
    hideResetConfirmation();
    fetchMemory();
    showHud();
  }

  function closeMemoryDrawer() {
    state.memoryOpen = false;
    els.memoryBackdrop.classList.add('hidden');
    els.memoryDrawer.classList.add('hidden');
    els.memoryDrawer.setAttribute('aria-hidden', 'true');
    els.btnMemory.setAttribute('aria-expanded', 'false');
    els.btnMemory.classList.remove('is-active');
    hideResetConfirmation();
    scheduleHudAutoHide();
  }

  function showResetConfirmation() {
    els.btnResetMemory.classList.add('hidden');
    els.resetConfirmBox.classList.remove('hidden');
  }

  function hideResetConfirmation() {
    els.resetConfirmBox.classList.add('hidden');
    els.btnResetMemory.classList.remove('hidden');
  }

  function toggleExpressionsBar() {
    state.expressionsOpen = !state.expressionsOpen;
    els.expressionsBar.classList.toggle('hidden', !state.expressionsOpen);
    els.btnExpressions.classList.toggle('is-active', state.expressionsOpen);
    els.btnExpressions.setAttribute('aria-expanded', String(state.expressionsOpen));
    if (state.expressionsOpen) {
      syncFaceBadges();
      showHud();
    } else {
      scheduleHudAutoHide();
    }
  }

  // Tela cheia e Wake Lock opcional
  async function requestWakeLock() {
    if (!('wakeLock' in navigator) || state.wakeLock) return;
    try {
      state.wakeLock = await navigator.wakeLock.request('screen');
      state.wakeLock.addEventListener('release', () => {
        state.wakeLock = null;
      });
    } catch {
      // Navegador pode negar Wake Lock sem foco ou permissão
    }
  }

  async function releaseWakeLock() {
    if (!state.wakeLock) return;
    try {
      await state.wakeLock.release();
    } catch {
      // Ignora erro ao liberar
    } finally {
      state.wakeLock = null;
    }
  }

  async function toggleFullscreen() {
    try {
      if (!document.fullscreenElement) {
        await document.documentElement.requestFullscreen();
        await requestWakeLock();
      } else {
        await document.exitFullscreen();
        await releaseWakeLock();
      }
    } catch {
      // Ignora caso tela cheia não seja suportada no ambiente
    }
  }

  function syncFullscreenUI() {
    const isFull = Boolean(document.fullscreenElement);
    els.btnFullscreen.classList.toggle('is-active', isFull);
    els.btnFullscreen.setAttribute('aria-pressed', String(isFull));
    els.btnFullscreen.textContent = isFull ? '⛶ Sair' : '⛶ Tela Cheia';
  }

  // Registra eventos e inicializa a aplicação
  function bindEvents() {
    // Atividade do usuário mantém a HUD visível e destrava áudio no primeiro toque
    ['mousemove', 'pointerdown', 'touchstart'].forEach((evtName) => {
      document.addEventListener(
        evtName,
        () => {
          showHud();
          if (evtName !== 'mousemove') {
            unlockAudio();
          }
        },
        { passive: true }
      );
    });

    document.addEventListener('keydown', (event) => {
      showHud();
      if (event.key === 'Escape' && state.memoryOpen) {
        closeMemoryDrawer();
      }
    });

    els.audioUnlockBanner.addEventListener('click', unlockAudio);
    els.btnHudPin.addEventListener('click', toggleHudPin);

    els.btnExpressions.addEventListener('click', toggleExpressionsBar);

    els.btnMemory.addEventListener('click', () => {
      if (state.memoryOpen) {
        closeMemoryDrawer();
      } else {
        openMemoryDrawer();
      }
    });
    els.btnCloseMemory.addEventListener('click', closeMemoryDrawer);
    els.memoryBackdrop.addEventListener('click', closeMemoryDrawer);

    els.btnTts.addEventListener('click', () => {
      unlockAudio();
      state.ttsEnabled = !state.ttsEnabled;
      saveBoolPref(TTS_STORAGE_KEY, state.ttsEnabled);
      syncTtsUI();
      if (!state.ttsEnabled) {
        stopSpeaking({ resetState: true });
      }
    });

    els.btnCaption.addEventListener('click', () => {
      state.captionVisible = !state.captionVisible;
      saveBoolPref(CAPTION_STORAGE_KEY, state.captionVisible);
      syncCaptionVisibilityUI();
    });

    els.btnFullscreen.addEventListener('click', toggleFullscreen);
    document.addEventListener('fullscreenchange', () => {
      syncFullscreenUI();
      if (!document.fullscreenElement) {
        releaseWakeLock();
      }
    });

    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && document.fullscreenElement) {
        requestWakeLock();
      }
    });

    els.chatForm.addEventListener('submit', handleChatSubmit);
    els.chatInput.addEventListener('input', handleInputActivity);
    els.chatInput.addEventListener('focus', () => {
      showHud();
      lookAtSafe(0, 0.35);
    });
    els.chatInput.addEventListener('blur', () => {
      if (!state.typingActive) {
        lookAtSafe(0, 0);
      }
      scheduleHudAutoHide();
    });

    els.addFactForm.addEventListener('submit', addManualFact);
    els.btnClearChat.addEventListener('click', () => clearMemory({ includeFacts: false }));
    els.btnResetMemory.addEventListener('click', showResetConfirmation);
    els.btnCancelReset.addEventListener('click', hideResetConfirmation);
    els.btnConfirmReset.addEventListener('click', () => clearMemory({ includeFacts: true }));

    if (supportsSpeechSynthesis() && 'onvoiceschanged' in window.speechSynthesis) {
      window.speechSynthesis.addEventListener('voiceschanged', refreshVoices);
    }
  }

  function init() {
    const api = faceApi();
    if (api && typeof api.init === 'function' && els.faceContainer) {
      api.init(els.faceContainer);
    }

    buildExpressionChips();
    syncTtsUI();
    syncCaptionVisibilityUI();
    syncFullscreenUI();
    refreshVoices();
    bindEvents();
    connectWebSocket();
    fetchMemory();
    showHud();

    // Mantém o badge de estado/emoção sincronizado caso o rosto entre em modo sonolento automático
    window.setInterval(syncFaceBadges, 1000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
