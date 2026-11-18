/**
 * Main controller of the Desk Assistant web interface (/static/app.js).
 * Integrates:
 * - 4 screen modes (Live Pet, Dock & Mac Shortcuts, Smart Display, Diagnostics)
 * - Lupin's layered face (window.LupinFace) + Procedural Audio (window.EmoAudio)
 * - RG406H gamepad (window.DeskGamepad) + Diagnostics (window.DeskDiagnostics)
 * - WebSocket (/ws) with sentence-by-sentence streaming, Push-to-Talk, barge-in and actions
 * - Hybrid TTS (Browser speechSynthesis vs Mac server via the Brain)
 */
(() => {
  'use strict';

  const DESK_TOKEN_STORAGE_KEY = 'desk_access_token';
  const PET_SYNC_CHANNEL = 'desk-assistant-pet-state';
  const isMiniPet = (() => {
    try {
      return new URL(window.location.href).searchParams.get('widget') === 'minipet';
    } catch {
      return false;
    }
  })();
  let petSyncChannel = null;
  let lastPublishedPetSnapshot = '';
  let pairingPromptOpen = false;

  function initTokenFromUrl() {
    try {
      const url = new URL(window.location.href);
      const tokenParam = (url.searchParams.get('token') || '').trim();
      if (tokenParam) {
        window.localStorage.setItem(DESK_TOKEN_STORAGE_KEY, tokenParam);
        url.searchParams.delete('token');
        window.history.replaceState({}, '', url.toString());
      }
    } catch (_) {
      // Ignore environments without URL/localStorage
    }
  }

  function getDeskAccessToken() {
    try {
      return (window.localStorage.getItem(DESK_TOKEN_STORAGE_KEY) || '').trim();
    } catch (_) {
      return '';
    }
  }

  function setDeskAccessToken(token) {
    try {
      const cleaned = (token || '').trim();
      if (cleaned) {
        window.localStorage.setItem(DESK_TOKEN_STORAGE_KEY, cleaned);
      } else {
        window.localStorage.removeItem(DESK_TOKEN_STORAGE_KEY);
      }
    } catch (_) {
      // Ignore
    }
  }

  function promptForPairingToken(onSaved) {
    if (pairingPromptOpen) return;
    pairingPromptOpen = true;
    const existing = document.getElementById('desk-pairing-modal');
    if (existing) existing.remove();

    const returnFocus = document.activeElement;
    const overlay = document.createElement('div');
    overlay.id = 'desk-pairing-modal';
    overlay.className = 'modal-backdrop';
    overlay.innerHTML = `
      <div class="modal-card" role="dialog" aria-modal="true" aria-label="Device pairing">
        <h3>🔐 Access token</h3>
        <p class="modal-hint">Enter the DESK_ACCESS_TOKEN shown in the Mac terminal to connect this device.</p>
        <input id="desk-pairing-input" type="password" autocomplete="off" placeholder="Paste the access token..." />
        <div class="modal-actions">
          <button id="desk-pairing-cancel" type="button" class="btn-secondary">Cancel</button>
          <button id="desk-pairing-save" type="button" class="btn-primary">Connect</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    const input = document.getElementById('desk-pairing-input');
    const btnSave = document.getElementById('desk-pairing-save');
    const btnCancel = document.getElementById('desk-pairing-cancel');
    if (input) input.focus();

    const close = () => {
      pairingPromptOpen = false;
      overlay.remove();
      if (returnFocus && returnFocus.isConnected !== false) returnFocus.focus();
    };
    overlay.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        close();
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = [input, btnCancel, btnSave].filter(
        (element) => element && !element.disabled
      );
      if (!focusable.length) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
    if (btnCancel) btnCancel.addEventListener('click', close);
    if (btnSave) {
      btnSave.addEventListener('click', () => {
        const val = input ? input.value.trim() : '';
        if (!val) return;
        setDeskAccessToken(val);
        close();
        if (typeof onSaved === 'function') onSaved();
      });
    }
  }

  if (!isMiniPet) initTokenFromUrl();

  if (!isMiniPet && typeof window.fetch === 'function') {
    const nativeFetch = window.fetch.bind(window);
    window.fetch = async (input, init = undefined) => {
      const rawUrl = typeof input === 'string' ? input : (input && input.url) || '';
      const isApi = rawUrl.startsWith('/api/') || rawUrl.startsWith(`${window.location.origin}/api/`);
      let nextInit = init;
      if (isApi) {
        const token = getDeskAccessToken();
        if (token) {
          const headers = new Headers((init && init.headers) || (input instanceof Request ? input.headers : undefined));
          if (!headers.has('Authorization')) {
            headers.set('Authorization', `Bearer ${token}`);
          }
          nextInit = Object.assign({}, init || {}, { headers });
        }
      }
      const resp = await nativeFetch(input, nextInit);
      if (isApi && resp.status === 401) {
        promptForPairingToken(() => connectWebSocket());
      }
      return resp;
    };
  }

  const MODES = ['pet', 'dock', 'nathan'];

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
    'angry',
    'dizzy',
  ];

  const FALLBACK_STATES = ['idle', 'listening', 'thinking', 'speaking', 'error'];

  const EMOTION_LABELS = {
    neutral: 'neutral',
    happy: 'happy',
    excited: 'excited',
    curious: 'curious',
    skeptical: 'skeptical',
    surprised: 'surprised',
    sad: 'sad',
    wink: 'winking',
    love: 'affectionate',
    sleepy: 'sleepy',
    angry: 'angry',
    dizzy: 'dizzy',
  };

  const STATE_LABELS = {
    idle: 'idle',
    listening: 'listening',
    thinking: 'thinking',
    speaking: 'speaking',
    error: 'error',
  };

  const CATEGORY_LABELS = {
    general: 'general',
    name: 'name',
    identity: 'identity',
    location: 'location',
    preference: 'preference',
    routine: 'routine',
    personal: 'personal',
    work: 'work',
  };

  const TYPING_IDLE_MS = 2500;
  const SETTINGS_TABS = ['voice', 'brain', 'memory', 'skills', 'dock', 'diagnostics'];
  const SWIPE_MIN_PX = 180;
  const SWIPE_MAX_MS = 320;
  const SWIPE_MAX_OFF_AXIS_PX = 60;
  const WS_RECONNECT_BASE_MS = 2000;
  const WS_RECONNECT_MAX_MS = 8000;

  const PREFS = {
    ttsEnabled: 'desk_assistant_tts_enabled',
    ttsMode: 'desk_assistant_tts_mode',
    petSoundsEnabled: 'desk_assistant_pet_sounds_enabled',
    captionVisible: 'desk_assistant_caption_visible',
  };

  // Minimal silent WAV (~44 bytes) to unlock <audio> on iOS Safari at the first tap
  const SILENT_WAV_DATA_URI =
    'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA';

  const els = {
    stage: document.getElementById('stage'),
    faceContainer: document.getElementById('face-container'),
    petClockTime: document.getElementById('pet-clock-time'),
    petClockDate: document.getElementById('pet-clock-date'),
    wsDot: document.getElementById('ws-dot'),
    wsStatusText: document.getElementById('ws-status-text'),
    stateLabel: document.getElementById('state-label'),
    emotionLabel: document.getElementById('emotion-label'),
    btnMemory: document.getElementById('btn-memory'),
    memoryCount: document.getElementById('memory-count'),
    btnPetSounds: document.getElementById('btn-pet-sounds'),
    miniPetMute: document.getElementById('mini-pet-mute'),
    btnTts: document.getElementById('btn-tts'),
    btnTtsMode: document.getElementById('btn-tts-mode'),
    btnCaption: document.getElementById('btn-caption'),
    emotionChips: document.getElementById('emotion-chips'),
    stateChips: document.getElementById('state-chips'),
    audioUnlockBanner: document.getElementById('audio-unlock-banner'),
    actionToast: document.getElementById('action-toast'),
    // Dock & Shortcuts mode
    modeDock: document.getElementById('mode-dock'),
    dockActiveApp: document.getElementById('dock-active-app'),
    btnRefreshApps: document.getElementById('btn-refresh-apps'),
    dockAppsGrid: document.getElementById('dock-apps-grid'),
    dockAppsPage: document.getElementById('dock-apps-page'),
    dockPageDots: document.getElementById('dock-page-dots'),
    shortcutsGrid: document.getElementById('shortcuts-grid'),
    dockSpeechStrip: document.getElementById('dock-speech-strip'),
    btnDockTalk: document.getElementById('btn-dock-talk'),
    settingsDockEditor: document.getElementById('settings-dock-editor'),
    settingsDockNote: document.getElementById('settings-dock-note'),
    btnSettingsNewShortcut: document.getElementById('btn-settings-new-shortcut'),
    btnSettingsManageShortcuts: document.getElementById('btn-settings-manage-shortcuts'),
    // Pomodoro and Now Playing on the Mac (small strip in Pet Mode)
    pomodoroPhaseLabel: document.getElementById('pomodoro-phase-label'),
    pomodoroTimer: document.getElementById('pomodoro-timer'),
    btnPomoFocus: document.getElementById('btn-pomo-focus'),
    btnPomoBreak: document.getElementById('btn-pomo-break'),
    btnPomoStop: document.getElementById('btn-pomo-stop'),
    nowPlayingState: document.getElementById('now-playing-state'),
    nowPlayingTitle: document.getElementById('now-playing-title'),
    nowPlayingArtist: document.getElementById('now-playing-artist'),
    btnMediaPrev: document.getElementById('btn-media-prev'),
    btnMediaPlay: document.getElementById('btn-media-play'),
    btnMediaNext: document.getElementById('btn-media-next'),
    // Settings (Skills and Diagnostics)
    modeNathanButton: document.getElementById('btn-mode-nathan'),
    brainAddress: document.getElementById('brain-address'),
    brainProvider: document.getElementById('brain-provider'),
    brainModel: document.getElementById('brain-model'),
    consentCalendar: document.getElementById('btn-consent-calendar'),
    consentEmail: document.getElementById('btn-consent-email'),
    consentCalendarLabel: document.getElementById('consent-calendar-label'),
    consentEmailLabel: document.getElementById('consent-email-label'),
    consentFiles: document.getElementById('btn-consent-files'),
    consentFilesLabel: document.getElementById('consent-files-label'),
    consentNote: document.getElementById('consent-note'),
    settingsShortcutsList: document.getElementById('settings-shortcuts-list'),
    btnSettings: document.getElementById('btn-settings'),
    btnSettingsClose: document.getElementById('btn-settings-close'),
    settingsPanel: document.getElementById('settings-panel'),
    settingsSubtabs: Array.from(document.querySelectorAll('.settings-subtab')),
    skillsRoot: document.getElementById('skills-root'),
    mcpRoot: document.getElementById('mcp-root'),
    diagnosticsRoot: document.getElementById('diagnostics-root'),
    // Nathan OS mode (Electron)
    modeNathan: document.getElementById('mode-nathan'),
    // Bottom dock
    approvalBanner: document.getElementById('approval-banner'),
    approvalText: document.getElementById('approval-text'),
    btnApproveAction: document.getElementById('btn-approve-action'),
    btnDenyAction: document.getElementById('btn-deny-action'),
    captionBox: document.getElementById('caption-box'),
    captionText: document.getElementById('caption-text'),
    chatForm: document.getElementById('chat-form'),
    btnPtt: document.getElementById('btn-ptt'),
    btnDictation: document.getElementById('btn-dictation'),
    chatInput: document.getElementById('chat-input'),
    // Shortcuts CRUD modal
    shortcutModalBackdrop: document.getElementById('shortcut-modal-backdrop'),
    shortcutModal: document.getElementById('shortcut-modal'),
    btnCloseShortcutModal: document.getElementById('btn-close-shortcut-modal'),
    shortcutForm: document.getElementById('shortcut-form'),
    scId: document.getElementById('sc-id'),
    scFormHeading: document.getElementById('sc-form-heading'),
    scTitle: document.getElementById('sc-title'),
    scIcon: document.getElementById('sc-icon'),
    scCategory: document.getElementById('sc-category'),
    scColor: document.getElementById('sc-color'),
    scActionType: document.getElementById('sc-action-type'),
    scPayloadKeystroke: document.getElementById('sc-payload-keystroke'),
    scPayloadApp: document.getElementById('sc-payload-app'),
    scPayloadCommand: document.getElementById('sc-payload-command'),
    scPayloadPrompt: document.getElementById('sc-payload-prompt'),
    btnRecordKeys: document.getElementById('btn-record-keys'),
    scKeys: document.getElementById('sc-keys'),
    scKeySelect: document.getElementById('sc-key-select'),
    modToggles: Array.from(document.querySelectorAll('.mod-toggle')),
    scAppName: document.getElementById('sc-app-name'),
    scMacCommand: document.getElementById('sc-mac-command'),
    scAgentPrompt: document.getElementById('sc-agent-prompt'),
    scVoiceTriggers: document.getElementById('sc-voice-triggers'),
    scPinned: document.getElementById('sc-pinned'),
    scConfirm: document.getElementById('sc-confirm'),
    btnScResetForm: document.getElementById('btn-sc-reset-form'),
    btnScDelete: document.getElementById('btn-sc-delete'),
    btnScResetDefaults: document.getElementById('btn-sc-reset-defaults'),
    scManageList: document.getElementById('sc-manage-list'),
    // Memory drawer
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
    serverTtsAudio: document.getElementById('server-tts-audio'),
    selLupinLanguage: document.getElementById('sel-lupin-language'),
  };

  const state = {
    mode: 'pet',
    ws: null,
    wsConnected: false,
    reconnectDelayMs: WS_RECONNECT_BASE_MS,
    reconnectTimer: null,
    typingActive: false,
    typingTimer: null,
    fullscreenRequested: false,
    memoryOpen: false,
    shortcutModalOpen: false,
    captionVisible: loadBoolPref(PREFS.captionVisible, true),
    ttsEnabled: loadBoolPref(PREFS.ttsEnabled, true),
    ttsMode: loadStringPref(PREFS.ttsMode, 'browser'),
    petSoundsEnabled: loadBoolPref(PREFS.petSoundsEnabled, true),
    audioUnlocked: false,
    selectedVoice: null,
    // Lupin's language lives on the Brain (GET/PUT /api/lupin-language); pt-BR until it answers.
    lupinLanguage: 'pt-BR',
    lupinPhrases: null,
    activeUtterance: null,
    ttsQueue: [],
    ttsPlaying: false,
    ttsGeneration: 0,
    audioChunks: new Map(),
    activeBody: null,
    // false when Lupin is in another Body (e.g. ESP32): the device becomes just a Dock.
    isLupinBody: true,
    mood: null,
    ttsCancelPlayback: null,
    serverAudioUrl: null,
    receivedSentenceStream: false,
    backendTurnActive: false,
    audioLevelTimer: null,
    speechStartGuardTimer: null,
    audioPhase: 0,
    streamingText: '',
    facts: [],
    recentMessagesCount: 0,
    wakeLock: null,
    // Dock & Shortcuts
    macApps: [],
    shortcuts: [],
    dockPage: 0,
    isMac: false,
    dataConsent: { calendar: false, email: false, files: false, receiver: '', can_edit: false, local: false },
    // Speech in the Dock: sentence count per turn and automatic return to Pet.
    dockSentenceCount: 0,
    autoPetFromDock: false,
    dockReturnTimer: null,
    dockStripTimer: null,
    dockTalk: { holdTimer: null, holding: false },
    yHeldPtt: false,
    gamepadFocusIndex: -1,
    recordingShortcutKeys: false,
    // Smart Display & Pomodoro
    pomodoro: {
      active: false,
      phase: 'idle', // 'focus' | 'break' | 'idle'
      remainingSec: 25 * 60,
      intervalId: null,
    },
    musicPlaying: false,
    settingsOpen: false,
    settingsTab: 'voice',
    // Push-to-Talk & Approval
    ptt: {
      active: false,
      stream: null,
      recorder: null,
      chunks: [],
      mimeType: '',
      generation: 0,
      spaceHeld: false,
    },
    // Dictation (issue 07): when armed, touching the face starts/stops recording for typing
    dictation: { armed: false },
    approvalQueue: [],
    pendingApprovalId: null,
    overlayReturnFocus: null,
    toastTimer: null,
    lastPetSentAt: 0,
    pointerTouch: {
      down: false,
      moved: false,
      startX: 0,
      startY: 0,
    },
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

  function loadStringPref(key, fallback) {
    try {
      const raw = window.localStorage.getItem(key);
      return raw || fallback;
    } catch {
      return fallback;
    }
  }

  function savePref(key, value) {
    try {
      window.localStorage.setItem(key, String(value));
    } catch {
      // Ignore storage error
    }
  }

  // Safe helpers for LupinFace and EmoAudio
  function faceApi() {
    return window.LupinFace || null;
  }

  function audioApi() {
    return window.EmoAudio || null;
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
    const aud = audioApi();
    if (aud && typeof aud.chirp === 'function' && state.petSoundsEnabled && nextEmotion) {
      aud.chirp(nextEmotion);
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

  function syncAccessoryForContext() {
    const api = faceApi();
    if (!api || typeof api.setAccessory !== 'function') return;
    if (state.pomodoro.active) {
      api.setAccessory('pomodoro');
    } else if (state.musicPlaying) {
      api.setAccessory('headphones');
    } else {
      api.setAccessory('none');
    }
  }

  function syncFaceBadges() {
    const api = faceApi();
    const currentState = api && typeof api.getState === 'function' ? api.getState() : 'idle';
    const currentEmotion = api && typeof api.getEmotion === 'function' ? api.getEmotion() : 'neutral';

    if (els.stateLabel) els.stateLabel.textContent = currentState;
    if (els.emotionLabel) els.emotionLabel.textContent = currentEmotion;

    updateChipSelection(els.stateChips, currentState);
    updateChipSelection(els.emotionChips, currentEmotion);
    publishPetSnapshot();
  }

  function updateChipSelection(container, activeValue) {
    if (!container) return;
    container.querySelectorAll('.chip-btn').forEach((btn) => {
      btn.classList.toggle('is-selected', btn.dataset.value === activeValue);
    });
  }

  function showToast(message, { isError = false, durationMs = 2800 } = {}) {
    if (!els.actionToast) return;
    if (state.toastTimer) {
      window.clearTimeout(state.toastTimer);
      state.toastTimer = null;
    }
    els.actionToast.textContent = message;
    els.actionToast.classList.toggle('is-error', isError);
    els.actionToast.classList.remove('hidden');
    state.toastTimer = window.setTimeout(() => {
      els.actionToast.classList.add('hidden');
      state.toastTimer = null;
    }, durationMs);
  }

  // Expression/state chips
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
      btn.textContent = `${emotion} (${EMOTION_LABELS[emotion] || emotion})`;
      btn.addEventListener('click', () => applyFaceEmotion(emotion));
      els.emotionChips.appendChild(btn);
    });

    els.stateChips.textContent = '';
    states.forEach((st) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'chip-btn';
      btn.dataset.value = st;
      btn.textContent = `${st} (${STATE_LABELS[st] || st})`;
      btn.addEventListener('click', () => applyFaceState(st));
      els.stateChips.appendChild(btn);
    });

    syncFaceBadges();
  }

  // Screen mode switcher
  function setMode(nextMode, { auto = false } = {}) {
    if (!MODES.includes(nextMode)) return;
    if (nextMode === 'pet' && !state.isLupinBody) return;
    // A switch made by the user cancels the automatic return from Pet to Dock.
    if (!auto) clearAutoPet();
    const previousMode = state.mode;
    state.mode = nextMode;
    state.gamepadFocusIndex = -1;
    if (nextMode === 'dock' && previousMode !== 'dock') state.dockPage = 0;

    document.body.classList.remove(
      'mode-pet',
      'mode-dock',
      'mode-nathan'
    );
    document.body.classList.add(`mode-${nextMode}`);

    els.modeDock.classList.toggle('hidden', nextMode !== 'dock');
    if (els.modeNathan) {
      els.modeNathan.classList.toggle('hidden', nextMode !== 'nathan');
    }

    window.dispatchEvent(new CustomEvent('desk:modechange', { detail: { mode: nextMode } }));

    const api = faceApi();
    if (api && typeof api.setCompactMode === 'function') {
      api.setCompactMode(false);
    }

    setSettingsOpen(false);

    if (nextMode !== 'dock') document.body.classList.remove('dock-text-open');
    syncDockCorner();
    if (nextMode === 'dock') {
      renderDock();
      fetchMacApps();
      fetchShortcuts();
    }

    const aud = audioApi();
    if (aud && typeof aud.click === 'function' && state.petSoundsEnabled) {
      aud.click();
    }
  }

  // Settings: Skills and Diagnostics live in a panel, they are not screen modes
  function setSettingsOpen(open, tab) {
    if (!els.settingsPanel) return;
    if (tab) state.settingsTab = tab;
    state.settingsOpen = Boolean(open);
    document.body.classList.toggle('settings-open', state.settingsOpen);
    els.settingsPanel.classList.toggle('hidden', !state.settingsOpen);
    state.gamepadFocusIndex = -1;
    if (els.btnSettings) {
      els.btnSettings.setAttribute('aria-expanded', String(state.settingsOpen));
      els.btnSettings.classList.toggle('is-active', state.settingsOpen);
    }
    els.settingsSubtabs.forEach((btn) => {
      const current = btn.dataset.subtab === state.settingsTab;
      btn.classList.toggle('is-active', current);
      const panel = document.getElementById(`settings-tab-${btn.dataset.subtab}`);
      if (panel) panel.classList.toggle('hidden', !current);
    });

    const diagnosticsVisible = state.settingsOpen && state.settingsTab === 'diagnostics';
    if (window.DeskDiagnostics) {
      if (diagnosticsVisible) window.DeskDiagnostics.activate();
      else window.DeskDiagnostics.deactivate();
    }
    if (
      state.settingsOpen &&
      state.settingsTab === 'skills' &&
      window.DeskSkills &&
      typeof window.DeskSkills.activate === 'function'
    ) {
      window.DeskSkills.activate();
    }
    if (state.settingsOpen && state.settingsTab === 'skills' && mcpSettings) mcpSettings.reload();
    if (state.settingsOpen && state.settingsTab === 'brain') {
      fetchBrainInfo();
      fetchDataConsent();
    }
    if (state.settingsOpen && state.settingsTab === 'dock') {
      fetchClientInfo();
      fetchShortcuts();
    }
  }

  function cycleSettingsTab(delta) {
    const idx = Math.max(0, SETTINGS_TABS.indexOf(state.settingsTab));
    const next = (idx + delta + SETTINGS_TABS.length) % SETTINGS_TABS.length;
    setSettingsOpen(true, SETTINGS_TABS[next]);
  }

  async function fetchBrainInfo() {
    if (els.brainAddress) els.brainAddress.textContent = window.location.host || window.location.origin || '—';
    try {
      const res = await fetch('/api/llm/providers');
      if (!res.ok) return;
      const data = await res.json();
      const active = data.active || {};
      const preset = (data.presets || []).find((item) => item.id === active.provider_id);
      if (els.brainProvider) els.brainProvider.textContent = (preset && preset.name) || active.provider_id || '—';
      if (els.brainModel) els.brainModel.textContent = active.model || '—';
    } catch {
      // Ignore the transient error; the fields stay as they were
    }
  }

  // Data Consent: who receives the calendar and emails. On the Mac it can be toggled; on other devices it is read-only.
  function renderDataConsent() {
    const dc = state.dataConsent;
    const view = window.LupinLocalMode ? window.LupinLocalMode.consentView(dc) : null;
    if (view && view.local) {
      // Ollama on this Mac: nothing leaves it, so the switches are locked on.
      const localRows = [
        [els.consentCalendar, els.consentCalendarLabel, view.rowText.calendar],
        [els.consentEmail, els.consentEmailLabel, view.rowText.email],
        [els.consentFiles, els.consentFilesLabel, view.rowText.files],
      ];
      for (const [btn, label, text] of localRows) {
        if (label) label.textContent = text;
        if (!btn) continue;
        btn.textContent = 'On';
        btn.setAttribute('aria-checked', 'true');
        btn.classList.add('is-active');
        btn.disabled = true;
      }
      if (els.consentNote) {
        els.consentNote.textContent = view.noteText;
        els.consentNote.classList.remove('hidden');
      }
      return;
    }
    const receiver = dc.receiver || 'the provider';
    const rows = [
      ['calendar', els.consentCalendar, els.consentCalendarLabel, 'your calendar'],
      ['email', els.consentEmail, els.consentEmailLabel, 'your emails'],
      ['files', els.consentFiles, els.consentFilesLabel, 'the contents of your files'],
    ];
    for (const [key, btn, label, what] of rows) {
      if (label) label.textContent = `Let ${receiver} see ${what}`;
      if (!btn) continue;
      const on = Boolean(dc[key]);
      btn.textContent = on ? 'On' : 'Off';
      btn.setAttribute('aria-checked', String(on));
      btn.classList.toggle('is-active', on);
      btn.disabled = !dc.can_edit;
    }
    if (els.consentNote) els.consentNote.classList.toggle('hidden', Boolean(dc.can_edit));
  }

  async function fetchDataConsent() {
    try {
      const res = await fetch('/api/data-consent');
      if (!res.ok) return;
      const data = await res.json();
      state.dataConsent = {
        calendar: Boolean(data.calendar),
        email: Boolean(data.email),
        files: Boolean(data.files),
        receiver: String(data.receiver || ''),
        can_edit: Boolean(data.can_edit),
        local: Boolean(data.local),
      };
      renderDataConsent();
    } catch {
      // No response: the switches stay as they were (read-only)
    }
  }

  async function toggleDataConsent(key) {
    if (!state.dataConsent.can_edit) return;
    try {
      const res = await fetch('/api/data-consent', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [key]: !state.dataConsent[key] }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showToast(err.detail || 'Could not change the permission', { isError: true });
        return;
      }
      await fetchDataConsent();
    } catch {
      showToast('Network error while changing the permission', { isError: true });
    }
  }

  async function fetchClientInfo() {
    try {
      const res = await fetch('/api/client-info');
      if (!res.ok) return;
      const data = await res.json();
      state.isMac = Boolean(data && data.is_mac);
      renderSettingsShortcuts();
    } catch {
      // No response: this device stays read-only
    }
  }

  async function toggleShortcutPinned(sc) {
    const pinned = sc.pinned_on_deck !== false && sc.pinned_on_deck !== 0;
    try {
      const res = await fetch(`/api/shortcuts/${encodeURIComponent(sc.id)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pinned_on_deck: !pinned }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showToast(err.detail || 'Error pinning the shortcut', { isError: true });
        return;
      }
      await fetchShortcuts();
    } catch {
      showToast('Network error while pinning the shortcut', { isError: true });
    }
  }

  // Settings > Dock: on the Mac it is the full editor; on other devices, just the list.
  function renderSettingsShortcuts() {
    if (els.settingsDockEditor) els.settingsDockEditor.classList.toggle('hidden', !state.isMac);
    if (els.settingsDockNote) {
      els.settingsDockNote.textContent = state.isMac
        ? 'Choose here which Shortcuts are pinned to the Dock, their order and what each one does.'
        : 'Dock Shortcuts are created and edited on the Mac. Here you can only see the list.';
    }
    if (!els.settingsShortcutsList) return;
    els.settingsShortcutsList.textContent = '';
    if (!state.shortcuts.length) {
      const empty = document.createElement('li');
      empty.className = 'muted-note';
      empty.textContent = 'No Shortcut configured on the Mac.';
      els.settingsShortcutsList.appendChild(empty);
      return;
    }
    state.shortcuts.forEach((sc) => {
      const item = document.createElement('li');
      const text = document.createElement('div');
      text.className = 'settings-item-text';
      const title = document.createElement('strong');
      title.textContent = sc.title || sc.slug || 'Shortcut';
      const hint = document.createElement('span');
      const pinned = sc.pinned_on_deck !== false && sc.pinned_on_deck !== 0;
      hint.textContent = [pinned ? 'Pinned' : '', formatShortcutBadge(sc)].filter(Boolean).join(' · ');
      text.appendChild(title);
      text.appendChild(hint);
      item.appendChild(text);
      if (state.isMac) {
        const pin = document.createElement('button');
        pin.type = 'button';
        pin.className = 'hud-btn';
        pin.setAttribute('aria-pressed', String(pinned));
        pin.textContent = pinned ? 'Unpin' : 'Pin';
        pin.addEventListener('click', () => toggleShortcutPinned(sc));
        const edit = document.createElement('button');
        edit.type = 'button';
        edit.className = 'hud-btn';
        edit.textContent = 'Edit';
        edit.addEventListener('click', () => openShortcutModal(sc));
        item.appendChild(pin);
        item.appendChild(edit);
      }
      els.settingsShortcutsList.appendChild(item);
    });
  }

  function getVisibleModes() {
    const modes = state.isLupinBody ? ['pet', 'dock'] : ['dock'];
    if (els.modeNathanButton && !els.modeNathanButton.classList.contains('hidden')) modes.push('nathan');
    return modes;
  }

  function cycleMode(delta) {
    const available = getVisibleModes();
    const idx = Math.max(0, available.indexOf(state.mode));
    const nextIdx = (idx + delta + available.length) % available.length;
    setMode(available[nextIdx]);
  }

  // Streaming caption
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
    els.btnCaption.textContent = state.captionVisible ? 'On' : 'Off';
  }

  // Procedural Audio + Hybrid TTS (Browser + Mac server)
  function supportsSpeechSynthesis() {
    return typeof window !== 'undefined' && 'speechSynthesis' in window;
  }

  function speechLocale() {
    return state.lupinLanguage === 'en' ? 'en-US' : 'pt-BR';
  }

  function pickBestVoice() {
    if (!supportsSpeechSynthesis()) return null;
    const voices = window.speechSynthesis.getVoices() || [];
    if (voices.length === 0) return null;

    const english = state.lupinLanguage === 'en';
    const exactVoices = voices.filter((v) => (english ? /^en[-_]us$/i : /^pt[-_]br$/i).test(v.lang));
    const anyVoices = voices.filter((v) => (english ? /^en\b/i : /^pt\b/i).test(v.lang));
    const pool = exactVoices.length > 0 ? exactVoices : anyVoices;
    if (pool.length === 0) return null;

    const preferredPatterns = english
      ? [/samantha/i, /google.*us english/i, /natural/i, /enhanced/i, /neural/i]
      : [/luciana/i, /felipe/i, /google.*portugu/i, /natural/i, /enhanced/i, /neural/i];
    for (const pattern of preferredPatterns) {
      const match = pool.find((v) => pattern.test(v.name));
      if (match) return match;
    }
    return pool[0];
  }

  function refreshVoices() {
    state.selectedVoice = pickBestVoice();
    if (window.DeskDiagnostics && typeof window.DeskDiagnostics.refreshVoices === 'function') {
      window.DeskDiagnostics.refreshVoices();
    }
  }

  function unlockAudio() {
    if (state.audioUnlocked) return;
    state.audioUnlocked = true;
    els.audioUnlockBanner.classList.add('hidden');

    const aud = audioApi();
    if (aud && typeof aud.unlock === 'function') {
      aud.unlock();
    }

    // Unlock <audio> on iOS Safari with a silent WAV on the user gesture
    if (els.serverTtsAudio) {
      try {
        els.serverTtsAudio.src = SILENT_WAV_DATA_URI;
        const p = els.serverTtsAudio.play();
        if (p && typeof p.catch === 'function') p.catch(() => {});
      } catch {
        // Ignore the block in a headless environment
      }
    }

    if (supportsSpeechSynthesis()) {
      try {
        window.speechSynthesis.resume();
        if (!window.speechSynthesis.speaking) {
          const primer = new SpeechSynthesisUtterance(' ');
          primer.volume = 0;
          primer.rate = 10;
          primer.lang = speechLocale();
          window.speechSynthesis.speak(primer);
        }
        refreshVoices();
      } catch {
        // Ignore the block
      }
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
      const wave =
        0.5 +
        0.26 * Math.sin(state.audioPhase) +
        0.16 * Math.sin(state.audioPhase * 2.3 + 0.7) +
        (Math.random() - 0.5) * 0.14;
      setAudioLevelSafe(Math.max(0.15, Math.min(0.95, wave)));
    }, 65);
  }

  function stopSpeaking({ resetState = true } = {}) {
    state.ttsGeneration += 1;
    state.ttsQueue = [];
    state.ttsPlaying = false;
    state.activeUtterance = null;
    clearAudioLevelTimer();
    if (state.speechStartGuardTimer) {
      window.clearTimeout(state.speechStartGuardTimer);
      state.speechStartGuardTimer = null;
    }

    // Discard still-incomplete audio chunks from the Brain
    state.audioChunks.clear();
    const cancelPlayback = state.ttsCancelPlayback;
    state.ttsCancelPlayback = null;
    if (cancelPlayback) cancelPlayback();

    if (els.serverTtsAudio) {
      try {
        els.serverTtsAudio.pause();
        els.serverTtsAudio.currentTime = 0;
      } catch {
        // Ignore error
      }
      if (state.serverAudioUrl) {
        URL.revokeObjectURL(state.serverAudioUrl);
        state.serverAudioUrl = null;
      }
    }

    if (supportsSpeechSynthesis()) {
      try {
        window.speechSynthesis.cancel();
      } catch {
        // Ignore error
      }
    }

    if (resetState) {
      applyFaceState('idle');
    }
  }

  function enqueueTtsSentence(text, forceMode) {
    const clean = (text || '').trim();
    if (!clean) return;
    if (!state.ttsEnabled && !forceMode) return;
    if (!state.isLupinBody) return;
    // In server mode the audio comes from the Brain via the `audio` event (enqueueServerAudio)
    if ((forceMode || state.ttsMode) === 'server') return;

    state.ttsQueue.push({ text: clean, mode: forceMode || state.ttsMode });
    if (!state.ttsPlaying) {
      pumpTtsQueue();
    }
  }

  function enqueueServerAudio(blob) {
    if (!blob || blob.size === 0) return;
    state.ttsQueue.push({ blob, mode: 'server' });
    if (!state.ttsPlaying) pumpTtsQueue();
  }

  // Reassemble the base64 chunks of a sentence and queue the audio when `last` arrives
  function handleAudioChunk(msg) {
    if (!state.ttsEnabled || state.ttsMode !== 'server') return;
    if (typeof msg.data !== 'string') return;
    const key = msg.sentence;
    const entry = state.audioChunks.get(key) || [];
    entry[Number.isInteger(msg.seq) ? msg.seq : entry.length] = msg.data;
    state.audioChunks.set(key, entry);
    if (!msg.last) return;
    state.audioChunks.delete(key);
    const parts = [];
    for (const b64 of entry) {
      if (typeof b64 !== 'string') continue;
      const bin = atob(b64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
      parts.push(bytes);
    }
    enqueueServerAudio(new Blob(parts, { type: msg.mime || 'audio/mp4' }));
  }

  async function pumpTtsQueue() {
    if (state.ttsPlaying) return;
    const item = state.ttsQueue.shift();
    if (!item) {
      clearAudioLevelTimer();
      applyFaceState('idle');
      maybeSpeechEnded();
      return;
    }

    state.ttsPlaying = true;
    const generation = state.ttsGeneration;
    const modeToUse = item.mode === 'server' ? 'server' : 'browser';
    const isServer = modeToUse === 'server';
    const onDone = () => {
      if (generation !== state.ttsGeneration) return;
      state.ttsPlaying = false;
      pumpTtsQueue();
    };

    if (isServer) {
      await playServerTtsItem(item.blob, generation);
      onDone();
      return;
    }
    if (!supportsSpeechSynthesis()) {
      onDone();
      return;
    }

    playBrowserTtsItem(item.text, generation, onDone);
  }

  function playBrowserTtsItem(clean, generation, onDone) {
    refreshVoices();
    const utterance = new SpeechSynthesisUtterance(clean);
    utterance.lang = speechLocale();
    utterance.rate = 1.03;
    utterance.pitch = 1.0;
    if (state.selectedVoice) {
      utterance.voice = state.selectedVoice;
    }

    state.activeUtterance = utterance;
    let started = false;
    let finished = false;

    const finishOnce = () => {
      if (finished) return;
      finished = true;
      if (state.activeUtterance === utterance) {
        state.activeUtterance = null;
      }
      if (generation !== state.ttsGeneration) return;
      clearAudioLevelTimer();
      onDone();
    };

    utterance.onstart = () => {
      if (generation !== state.ttsGeneration || state.activeUtterance !== utterance) return;
      started = true;
      if (state.speechStartGuardTimer) {
        window.clearTimeout(state.speechStartGuardTimer);
        state.speechStartGuardTimer = null;
      }
      applyFaceState('speaking');
      startAudioLevelAnimation();
    };

    utterance.onboundary = () => {
      if (generation === state.ttsGeneration && state.activeUtterance === utterance) {
        setAudioLevelSafe(0.88);
      }
    };

    utterance.onend = finishOnce;
    utterance.onerror = finishOnce;

    state.speechStartGuardTimer = window.setTimeout(() => {
      if (
        generation === state.ttsGeneration &&
        state.activeUtterance === utterance &&
        !started &&
        !window.speechSynthesis.speaking
      ) {
        if (!state.audioUnlocked) {
          els.audioUnlockBanner.classList.remove('hidden');
        }
        finishOnce();
      }
    }, 1100);

    try {
      window.speechSynthesis.speak(utterance);
    } catch {
      finishOnce();
    }
  }

  async function playServerTtsItem(blob, generation) {
    try {
      if (generation !== state.ttsGeneration || !blob || blob.size === 0) return;

      const audioUrl = URL.createObjectURL(blob);
      if (generation !== state.ttsGeneration) {
        URL.revokeObjectURL(audioUrl);
        return;
      }
      if (state.serverAudioUrl) URL.revokeObjectURL(state.serverAudioUrl);
      state.serverAudioUrl = audioUrl;

      await new Promise((resolve) => {
        const audioEl = els.serverTtsAudio;
        if (!audioEl) {
          resolve();
          return;
        }
        let settled = false;
        const done = () => {
          if (settled) return;
          settled = true;
          if (audioEl.onended === done) audioEl.onended = null;
          if (audioEl.onerror === done) audioEl.onerror = null;
          if (state.ttsCancelPlayback === done) state.ttsCancelPlayback = null;
          if (generation === state.ttsGeneration) clearAudioLevelTimer();
          resolve();
        };

        state.ttsCancelPlayback = done;
        audioEl.onended = done;
        audioEl.onerror = done;
        audioEl.src = audioUrl;
        if (generation === state.ttsGeneration) {
          applyFaceState('speaking');
          startAudioLevelAnimation();
        }
        const p = audioEl.play();
        if (p && typeof p.catch === 'function') {
          p.catch(() => {
            if (generation === state.ttsGeneration && !state.audioUnlocked) {
              els.audioUnlockBanner.classList.remove('hidden');
            }
            done();
          });
        }
      });
    } catch {
      // Silence playback errors for the Brain's audio
    }
  }

  // Lupin's spoken phrases come from the Brain with the language setting; until it answers,
  // these pt-BR defaults (the default language) are used.
  const DEFAULT_LUPIN_PHRASES = {
    pomodoro_focus_done: 'Ciclo Pomodoro de foco concluído! Faça uma pausa.',
    pomodoro_break_done: 'Pausa do Pomodoro finalizada! Hora de voltar ao foco.',
    diag_test_browser_tts: 'Olá! Teste de voz do navegador funcionando.',
    diag_test_server_tts: 'Olá! Teste de voz offline do servidor Mac.',
  };

  function lupinPhrase(key) {
    return (state.lupinPhrases && state.lupinPhrases[key]) || DEFAULT_LUPIN_PHRASES[key];
  }

  function renderLupinLanguage() {
    if (els.selLupinLanguage) els.selLupinLanguage.value = state.lupinLanguage;
  }

  function applyLupinLanguage(data) {
    if (!data || typeof data.language !== 'string') return;
    const changed = data.language !== state.lupinLanguage;
    state.lupinLanguage = data.language;
    state.lupinPhrases = data.phrases || null;
    renderLupinLanguage();
    if (changed) refreshVoices();
  }

  async function fetchLupinLanguage() {
    try {
      const res = await fetch('/api/lupin-language');
      if (!res.ok) return;
      applyLupinLanguage(await res.json());
    } catch {
      // No response: keep the current language
    }
  }

  async function changeLupinLanguage(language) {
    try {
      const res = await fetch('/api/lupin-language', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ language }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showToast(err.detail || "Could not change Lupin's language", { isError: true });
        renderLupinLanguage();
        return;
      }
      applyLupinLanguage(await res.json());
    } catch {
      showToast("Network error while changing Lupin's language", { isError: true });
      renderLupinLanguage();
    }
  }

  function speakText(text) {
    const clean = (text || '').trim();
    if (!state.ttsEnabled || !clean) {
      if (!state.ttsPlaying) applyFaceState('idle');
      return;
    }
    enqueueTtsSentence(clean);
  }

  function syncTtsUI() {
    if (els.btnTts) {
      els.btnTts.textContent = state.ttsEnabled ? 'On' : 'Off';
      els.btnTts.classList.toggle('is-active', state.ttsEnabled);
      els.btnTts.setAttribute('aria-pressed', String(state.ttsEnabled));
    }

    if (els.btnTtsMode) {
      els.btnTtsMode.textContent = state.ttsMode === 'server' ? 'Mac' : 'Browser';
      els.btnTtsMode.classList.toggle('is-active', state.ttsMode === 'server');
      els.btnTtsMode.setAttribute('aria-pressed', String(state.ttsMode === 'server'));
    }

    if (els.btnPetSounds) {
      els.btnPetSounds.textContent = state.petSoundsEnabled ? 'On' : 'Off';
      els.btnPetSounds.classList.toggle('is-active', state.petSoundsEnabled);
      els.btnPetSounds.setAttribute('aria-pressed', String(state.petSoundsEnabled));
    }

    const muted = !state.ttsEnabled && !state.petSoundsEnabled;
    if (els.miniPetMute) {
      const label = document.getElementById('mini-pet-mute-label') || els.miniPetMute;
      label.textContent = muted ? 'Unmute' : 'Mute';
      els.miniPetMute.title = muted ? "Unmute the pet's voice and sounds" : "Mute the pet's voice and sounds";
      els.miniPetMute.setAttribute('aria-label', els.miniPetMute.title);
      els.miniPetMute.classList.toggle('is-active', !muted);
      els.miniPetMute.setAttribute('aria-pressed', String(muted));
    }

    const aud = audioApi();
    if (aud && typeof aud.purr === 'function' && (isMiniPet || !state.petSoundsEnabled)) {
      aud.purr(false);
    }
    if (aud && typeof aud.setMuted === 'function') {
      aud.setMuted(isMiniPet || !state.petSoundsEnabled);
    }

    if (!isMiniPet && window.DeskDiagnostics && typeof window.DeskDiagnostics.refreshVoices === 'function') {
      window.DeskDiagnostics.refreshVoices();
    }
  }

  function syncPreferencesFromStorage(event) {
    if (event && event.key && !Object.values(PREFS).includes(event.key)) return;
    const wasTtsEnabled = state.ttsEnabled;
    const wasTtsMode = state.ttsMode;
    state.ttsEnabled = loadBoolPref(PREFS.ttsEnabled, true);
    state.ttsMode = loadStringPref(PREFS.ttsMode, 'browser') === 'server' ? 'server' : 'browser';
    if (state.ttsMode !== wasTtsMode) sendHello();
    state.petSoundsEnabled = loadBoolPref(PREFS.petSoundsEnabled, true);
    state.captionVisible = loadBoolPref(PREFS.captionVisible, true);
    syncTtsUI();
    if (!isMiniPet) {
      if (els.captionBox && els.btnCaption) syncCaptionVisibilityUI();
    }
    if (wasTtsEnabled && !state.ttsEnabled) stopSpeaking({ resetState: true });
  }

  function toggleMiniPetMute() {
    const enable = !state.ttsEnabled && !state.petSoundsEnabled;
    state.ttsEnabled = enable;
    state.petSoundsEnabled = enable;
    savePref(PREFS.ttsEnabled, enable);
    savePref(PREFS.petSoundsEnabled, enable);
    syncTtsUI();
    if (!enable) stopSpeaking({ resetState: true });
  }

  function publishPetSnapshot() {
    if (isMiniPet || !petSyncChannel) return;
    const api = faceApi();
    const snapshot = {
      type: 'snapshot',
      state: api && typeof api.getState === 'function' ? api.getState() : 'idle',
      emotion: api && typeof api.getEmotion === 'function' ? api.getEmotion() : 'neutral',
      musicPlaying: Boolean(state.musicPlaying),
      lupinBody: state.isLupinBody,
    };
    const signature = `${snapshot.state}|${snapshot.emotion}|${snapshot.musicPlaying}|${snapshot.lupinBody}`;
    if (signature === lastPublishedPetSnapshot) return;
    lastPublishedPetSnapshot = signature;
    petSyncChannel.postMessage(snapshot);
  }

  function initPetSync() {
    if (typeof window.BroadcastChannel !== 'function') return;
    try {
      petSyncChannel = new window.BroadcastChannel(PET_SYNC_CHANNEL);
      petSyncChannel.addEventListener('message', (event) => {
        const message = event.data;
        if (!message || typeof message !== 'object') return;
        if (isMiniPet && message.type === 'snapshot') {
          const api = faceApi();
          if (api && typeof api.setState === 'function') api.setState(message.state);
          if (api && typeof api.setEmotion === 'function') api.setEmotion(message.emotion);
          if (api && typeof api.setMusicPlaying === 'function') api.setMusicPlaying(message.musicPlaying);
          // Outside the Active Body the mini-pet hides the drawing and shows only "Talk to Lupin".
          document.body.classList.toggle('lupin-in-other-body', message.lupinBody === false);
          syncFaceBadges();
        } else if (!isMiniPet && message.type === 'request') {
          lastPublishedPetSnapshot = '';
          publishPetSnapshot();
        }
      });
      if (isMiniPet) petSyncChannel.postMessage({ type: 'request' });
      else {
        lastPublishedPetSnapshot = '';
        publishPetSnapshot();
      }
    } catch {
      petSyncChannel = null;
    }
  }

  function bindMiniPetEvents() {
    if (els.miniPetMute) els.miniPetMute.addEventListener('click', toggleMiniPetMute);
    const talk = document.getElementById('mini-pet-talk');
    if (talk) {
      talk.addEventListener('click', () => {
        const api = window.electronAPI;
        if (api && typeof api.openDashboard === 'function') api.openDashboard();
      });
    }
    bindFaceTouchEvents();
  }

  function toggleTtsMode() {
    unlockAudio();
    state.ttsMode = state.ttsMode === 'browser' ? 'server' : 'browser';
    savePref(PREFS.ttsMode, state.ttsMode);
    syncTtsUI();
    sendHello();
    showToast(
      state.ttsMode === 'server'
        ? 'Voice changed to Mac server (Brain)'
        : 'Voice changed to Browser (speechSynthesis)'
    );
  }

  // Deterministic barge-in
  function triggerBargeIn() {
    const api = faceApi();
    const currentFaceState = api && typeof api.getState === 'function' ? api.getState() : 'idle';
    const isBusy =
      state.backendTurnActive ||
      state.ttsPlaying ||
      state.ttsQueue.length > 0 ||
      currentFaceState === 'speaking' ||
      currentFaceState === 'thinking';

    state.backendTurnActive = false;
    stopSpeaking({ resetState: true });
    if (isBusy) {
      sendWs({ type: 'interrupt' });
    }
  }

  // Speech in the Dock: small Lupin in the corner, one-line text and automatic return to Pet.
  const DOCK_STRIP_HIDE_MS = 4000;
  const DOCK_RETURN_MS = 5000;
  const DOCK_TALK_HOLD_MS = 280;
  const DOCK_MAX_SENTENCES = 2;

  function clearAutoPet() {
    state.autoPetFromDock = false;
    if (state.dockReturnTimer !== null) {
      window.clearTimeout(state.dockReturnTimer);
      state.dockReturnTimer = null;
    }
  }

  // Any touch, key, gamepad button or mode switch cancels the automatic return.
  function noteUserInput() {
    clearAutoPet();
  }

  function syncDockCorner() {
    const inDock = state.mode === 'dock';
    document.body.classList.toggle('dock-lupin-corner', inDock && state.isLupinBody);
    if (els.btnDockTalk) {
      els.btnDockTalk.classList.toggle('hidden', state.isLupinBody);
      els.btnDockTalk.textContent = state.ptt.active ? '🔴 Listening...' : 'Talk to Lupin';
    }
  }

  function setDockStrip(text) {
    if (!els.dockSpeechStrip) return;
    const clean = (text || '').replace(/\s+/g, ' ').trim();
    els.dockSpeechStrip.textContent = clean;
    els.dockSpeechStrip.classList.toggle('is-empty', clean.length === 0);
  }

  function onReplySentence(msg, text) {
    setDockStrip(text);
    if (state.dockStripTimer !== null) {
      window.clearTimeout(state.dockStripTimer);
      state.dockStripTimer = null;
    }
    if (state.dockReturnTimer !== null) {
      window.clearTimeout(state.dockReturnTimer);
      state.dockReturnTimer = null;
    }
    // Only the Active Body, in Dock Mode, may go up to Pet because of speech.
    if (state.mode !== 'dock' || !state.isLupinBody) return;
    state.dockSentenceCount += 1;
    if ((msg && msg.first_wake) || state.dockSentenceCount > DOCK_MAX_SENTENCES) {
      setMode('pet', { auto: true });
      if (state.mode === 'pet') state.autoPetFromDock = true;
    }
  }

  function maybeSpeechEnded() {
    if (state.backendTurnActive || state.ttsPlaying || state.ttsQueue.length > 0) return;
    if (state.dockStripTimer !== null) window.clearTimeout(state.dockStripTimer);
    state.dockStripTimer = window.setTimeout(() => {
      state.dockStripTimer = null;
      setDockStrip('');
    }, DOCK_STRIP_HIDE_MS);
    if (state.autoPetFromDock && state.mode === 'pet') {
      if (state.dockReturnTimer !== null) window.clearTimeout(state.dockReturnTimer);
      state.dockReturnTimer = window.setTimeout(() => {
        state.dockReturnTimer = null;
        if (state.autoPetFromDock && state.mode === 'pet') {
          state.autoPetFromDock = false;
          setMode('dock', { auto: true });
        }
      }, DOCK_RETURN_MS);
    }
  }

  // Tapping the small Lupin in the corner opens Pet Mode.
  function handleFaceTap() {
    if (state.mode === 'dock' && state.isLupinBody) {
      setMode('pet');
      return true;
    }
    return false;
  }

  function toggleDockText(open) {
    const next = open === undefined ? !document.body.classList.contains('dock-text-open') : open;
    document.body.classList.toggle('dock-text-open', next);
    if (next && els.chatInput && typeof els.chatInput.focus === 'function') els.chatInput.focus();
  }

  // "Talk to Lupin": holding records the microphone, tapping opens the text input.
  function dockTalkDown() {
    unlockAudio();
    if (state.dockTalk.holdTimer !== null) window.clearTimeout(state.dockTalk.holdTimer);
    state.dockTalk.holding = false;
    state.dockTalk.holdTimer = window.setTimeout(() => {
      state.dockTalk.holdTimer = null;
      state.dockTalk.holding = true;
      startPtt();
    }, DOCK_TALK_HOLD_MS);
  }

  function dockTalkUp() {
    if (state.dockTalk.holdTimer !== null) {
      window.clearTimeout(state.dockTalk.holdTimer);
      state.dockTalk.holdTimer = null;
      toggleDockText();
      return;
    }
    if (state.dockTalk.holding) {
      state.dockTalk.holding = false;
      stopPttAndSend();
    }
  }

  // WebSocket (/ws)
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
    setWsStatus('reconnecting', 'Reconnecting...');

    state.reconnectTimer = window.setTimeout(() => {
      state.reconnectTimer = null;
      connectWebSocket();
    }, waitMs);
  }

  // Brain↔Body handshake (protocol 1); `audio` is only announced in server TTS mode
  // The RG406H (Android) takes priority over regular browsers to be the Active Body.
  function detectBodyKind() {
    const ua = (typeof navigator !== 'undefined' && navigator && navigator.userAgent) || '';
    return window.AndroidBridge || /Android/i.test(ua) ? 'rg406h-web' : 'web';
  }

  // Lupin lives in one Body at a time; outside it the device is just a Dock (ADR 0001).
  function applyActiveBody(msg) {
    state.activeBody = msg.active_body || null;
    const isActive = msg.active !== false;
    if (isActive === state.isLupinBody) return;
    state.isLupinBody = isActive;
    document.body.classList.toggle('lupin-in-other-body', !isActive);
    clearAutoPet();
    syncDockCorner();
    publishPetSnapshot();
    if (!isActive) {
      stopSpeaking();
      setMode('dock');
    } else if (state.mode === 'dock') {
      setMode('pet');
    }
  }

  function sendHello() {
    return sendWs(Object.assign({
      type: 'hello',
      body: detectBodyKind(),
      protocol: 1,
      audio: state.ttsMode === 'server' ? ['m4a'] : [],
    }, window.DeskDevice ? window.DeskDevice.helloFields() : {}));
  }

  function connectWebSocket() {
    if (
      state.ws &&
      (state.ws.readyState === WebSocket.OPEN || state.ws.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const token = getDeskAccessToken();
    const wsUrl = token
      ? `${protocol}//${window.location.host}/ws?token=${encodeURIComponent(token)}`
      : `${protocol}//${window.location.host}/ws`;
    setWsStatus('reconnecting', 'Connecting...');

    const ws = new WebSocket(wsUrl);
    state.ws = ws;

    ws.addEventListener('open', () => {
      state.wsConnected = true;
      state.reconnectDelayMs = WS_RECONNECT_BASE_MS;
      setWsStatus('connected', 'Connected');
      sendHello();
      fetchLupinLanguage();
      fetchMemory();
      const aud = audioApi();
      if (aud && typeof aud.wake === 'function' && state.audioUnlocked && state.petSoundsEnabled) {
        aud.wake();
      }
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

    ws.addEventListener('close', (event) => {
      state.wsConnected = false;
      state.backendTurnActive = false;
      state.ws = null;
      setWsStatus('disconnected', 'Disconnected');
      if (event && event.code === 4401) {
        promptForPairingToken(() => connectWebSocket());
        return;
      }
      scheduleReconnect();
    });

    ws.addEventListener('error', () => {
      setWsStatus('reconnecting', 'Connection error');
    });
  }

  function handleWsMessage(msg) {
    if (!msg || typeof msg.type !== 'string') return;

    switch (msg.type) {
      case 'welcome':
      case 'active_body': {
        applyActiveBody(msg);
        break;
      }
      case 'mood': {
        state.mood = msg;
        break;
      }
      case 'audio': {
        handleAudioChunk(msg);
        break;
      }
      case 'state': {
        if (msg.state) {
          if (msg.state === 'thinking') state.backendTurnActive = true;
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
      case 'dictation_result': {
        if (msg.message) setCaption(msg.message, { isError: msg.ok === false });
        break;
      }
      case 'transcript': {
        const spoken = (msg.text || '').trim();
        if (spoken) {
          state.streamingText = '';
          state.receivedSentenceStream = false;
          setCaption(`🎤 "${spoken}"`);
        }
        break;
      }
      case 'delta': {
        state.backendTurnActive = true;
        const chunk = typeof msg.text === 'string' ? msg.text : '';
        if (chunk) {
          state.streamingText += chunk;
          setCaption(state.streamingText);
        }
        break;
      }
      case 'sentence': {
        state.backendTurnActive = true;
        const sentenceText = typeof msg.text === 'string' ? msg.text.trim() : '';
        if (sentenceText) {
          state.receivedSentenceStream = true;
          onReplySentence(msg, sentenceText);
          enqueueTtsSentence(sentenceText);
        }
        break;
      }
      case 'done': {
        state.backendTurnActive = false;
        const finalText =
          typeof msg.text === 'string' && msg.text.length > 0
            ? msg.text
            : state.streamingText;
        state.streamingText = finalText;
        setCaption(finalText);
        if (msg.emotion) {
          applyFaceEmotion(msg.emotion);
        }
        if (!state.receivedSentenceStream) {
          if (finalText.trim()) onReplySentence(msg, finalText.trim());
          speakText(finalText);
        } else if (!state.ttsPlaying && state.ttsQueue.length === 0) {
          applyFaceState('idle');
        }
        state.receivedSentenceStream = false;
        state.dockSentenceCount = 0;
        maybeSpeechEnded();
        break;
      }
      case 'interrupted': {
        state.backendTurnActive = false;
        stopSpeaking({ resetState: true });
        state.dockSentenceCount = 0;
        maybeSpeechEnded();
        break;
      }
      case 'action_executed': {
        handleActionExecutedEvent(msg);
        break;
      }
      case 'tool_approval_request': {
        showToolApproval(msg);
        break;
      }
      case 'memory_updated': {
        renderMemoryState(msg.facts, msg.recent_messages_count);
        break;
      }
      case 'notice': {
        // A local model is slow: show the thinking state and the caption (the server also speaks it).
        // Lupin speaks unprompted (a Signal): caption, and browser TTS when there is no server audio.
        const signalPlan = window.LupinSignals
          ? window.LupinSignals.noticePlan(msg, {
              ttsEnabled: state.ttsEnabled,
              ttsMode: state.ttsMode,
              isLupinBody: state.isLupinBody,
            })
          : null;
        if (signalPlan) {
          setCaption(signalPlan.caption);
          if (signalPlan.speakInBrowser) enqueueTtsSentence(signalPlan.caption);
          break;
        }
        const slowCaption = window.LupinLocalMode ? window.LupinLocalMode.slowNoticeCaption(msg) : null;
        if (slowCaption) {
          applyFaceState('thinking');
          setCaption(slowCaption);
        }
        break;
      }
      case 'error': {
        state.backendTurnActive = false;
        stopSpeaking({ resetState: false });
        applyFaceState('error');
        setCaption(msg.message || 'An error occurred while processing your message.', {
          isError: true,
        });
        state.dockSentenceCount = 0;
        maybeSpeechEnded();
        break;
      }
      default:
        break;
    }
  }

  function playPetTrick(trickId) {
    const face = faceApi();
    if (face && typeof face.playTrick === 'function') {
      face.playTrick(trickId);
    }
    const aud = audioApi();
    if (aud && typeof aud.playTrick === 'function' && state.petSoundsEnabled) {
      aud.playTrick(trickId);
    }
  }

  function handleActionExecutedEvent(msg) {
    if (msg.kind === 'pet' && msg.ok && msg.target) {
      playPetTrick(msg.target);
    }
    const label = msg.title || msg.target || msg.action || 'Action executed';
    const ok = msg.ok !== false;
    const message = ok
      ? `⚡ ${label}`
      : `⚠️ ${msg.message || msg.error || `Failed: ${label}`}`;
    showToast(message, { isError: !ok });

    const target = String(msg.target || '').toLowerCase();
    const kind = String(msg.kind || '').toLowerCase();
    if (kind === 'pomodoro' || target === 'pomodoro_start' || target === 'pomodoro_25') {
      if (target === 'stop' || target === 'pomodoro_stop') {
        stopPomodoro();
      } else {
        startPomodoro(25 * 60, 'focus');
      }
    }

    if (state.mode === 'dock') {
      fetchMacApps();
    }
  }

  function renderPendingApproval() {
    const approval = state.approvalQueue[0] || null;
    state.pendingApprovalId = approval ? approval.id : null;
    if (!approval) {
      els.approvalBanner.classList.add('hidden');
      return;
    }

    els.approvalText.textContent = `Confirm action: ${approval.title}?`;
    const diffEl = document.getElementById('approval-diff');
    if (diffEl) {
      diffEl.textContent = approval.diff;
      diffEl.classList.toggle('hidden', !approval.diff);
    }
    els.approvalBanner.classList.remove('hidden');
  }

  function showToolApproval(msg) {
    const id = msg.approval_id || msg.id;
    if (id === undefined || id === null || id === '') return;
    const approvalId = String(id);
    if (state.approvalQueue.some((approval) => approval.id === approvalId)) return;

    const desc = msg.title || msg.description || msg.target || 'run a shortcut on the Mac';
    const approval = Object.freeze({
      id: approvalId,
      title: desc,
      message: msg.message || `Confirm write to ${msg.target || 'Cowork'}?`,
      diff: msg.diff || '',
      risk: msg.risk || '',
      target: msg.target || '',
    });
    state.approvalQueue.push(approval);
    renderPendingApproval();

    const aud = audioApi();
    if (aud && typeof aud.alert === 'function' && state.petSoundsEnabled) {
      aud.alert();
    }
    if (window.electronAPI && typeof window.electronAPI.confirmWrite === 'function' && approval.risk === 'write') {
      window.electronAPI
        .confirmWrite({
          title: approval.title,
          message: approval.message,
          diff: approval.diff,
        })
        .then((approved) => resolveToolApproval(Boolean(approved), approval.id))
        .catch(() => {});
    }
  }

  function resolveToolApproval(approved, approvalId = state.pendingApprovalId) {
    if (approvalId === undefined || approvalId === null) return;
    const id = String(approvalId);
    const index = state.approvalQueue.findIndex((approval) => approval.id === id);
    if (index < 0) return;

    sendWs({
      type: 'confirm_action',
      approval_id: id,
      approved: Boolean(approved),
    });
    state.approvalQueue.splice(index, 1);
    renderPendingApproval();
  }

  // Push-to-Talk (Microfone -> Base64 -> WS {type:'audio'})
  function setDictationArmed(armed) {
    state.dictation.armed = Boolean(armed);
    if (els.btnDictation) {
      els.btnDictation.classList.toggle('is-active', state.dictation.armed);
      els.btnDictation.setAttribute('aria-pressed', state.dictation.armed ? 'true' : 'false');
    }
    if (!state.dictation.armed && state.ptt.active) stopPttAndSend();
  }

  // Tap-to-talk for dictation: one touch on the face starts, the next one stops and sends.
  function handleDictationTap() {
    if (!state.dictation.armed) return false;
    if (state.ptt.active) stopPttAndSend();
    else startPtt();
    return true;
  }

  async function startPtt() {
    if (state.ptt.active) return;
    const generation = ++state.ptt.generation;
    unlockAudio();
    triggerBargeIn();

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showToast('Microphone unavailable in this browser/origin (use HTTPS or localhost).', {
        isError: true,
      });
      return;
    }
    if (typeof window.MediaRecorder === 'undefined') {
      showToast('MediaRecorder recording is unavailable in this browser.', { isError: true });
      return;
    }

    state.ptt.active = true;
    els.btnPtt.classList.add('is-recording');
    els.btnPtt.textContent = '🔴 Listening...';
    els.btnPtt.setAttribute('aria-pressed', 'true');
    applyFaceState('listening');
    syncDockCorner();

    let stream = null;
    try {
      const selectedMic =
        window.DeskDiagnostics && typeof window.DeskDiagnostics.getSelectedMicId === 'function'
          ? window.DeskDiagnostics.getSelectedMicId()
          : '';
      const audioConstraints = selectedMic
        ? { deviceId: { exact: selectedMic }, echoCancellation: true, noiseSuppression: true }
        : { echoCancellation: true, noiseSuppression: true };

      stream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraints });
      if (!state.ptt.active || state.ptt.generation !== generation) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }

      const preferred = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];
      const mimeType = preferred.find((t) => window.MediaRecorder.isTypeSupported(t)) || '';
      const recorder = mimeType
        ? new window.MediaRecorder(stream, { mimeType })
        : new window.MediaRecorder(stream);
      const chunks = [];

      state.ptt.stream = stream;
      state.ptt.recorder = recorder;
      state.ptt.chunks = chunks;
      state.ptt.mimeType = mimeType || recorder.mimeType || 'audio/webm';

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunks.push(e.data);
      };

      recorder.start();
    } catch (err) {
      if (stream) stream.getTracks().forEach((t) => t.stop());
      if (state.ptt.generation !== generation) return;
      cancelPttUI();
      showToast(`Error opening microphone: ${err.message || err}`, { isError: true });
      applyFaceState('idle');
    }
  }

  function cancelPttUI() {
    state.ptt.active = false;
    els.btnPtt.classList.remove('is-recording');
    els.btnPtt.textContent = '🎤 Hold to talk';
    els.btnPtt.setAttribute('aria-pressed', 'false');
    syncDockCorner();
  }

  async function stopPttAndSend() {
    if (!state.ptt.active) return;
    cancelPttUI();

    const { recorder, stream, chunks, mimeType } = state.ptt;
    const generation = ++state.ptt.generation;
    state.ptt.recorder = null;
    state.ptt.stream = null;
    state.ptt.chunks = [];

    if (!recorder || recorder.state === 'inactive') {
      if (stream) stream.getTracks().forEach((t) => t.stop());
      if (state.ptt.generation === generation) applyFaceState('idle');
      return;
    }

    await new Promise((resolve) => {
      recorder.onstop = resolve;
      try {
        recorder.stop();
      } catch {
        resolve();
      }
    });

    if (stream) stream.getTracks().forEach((t) => t.stop());
    if (state.ptt.generation !== generation) return;

    const blob = new Blob(chunks, { type: mimeType || 'audio/webm' });
    if (blob.size < 400) {
      applyFaceState('idle');
      return;
    }

    try {
      const base64 = await blobToBase64(blob);
      if (state.ptt.generation !== generation) return;
      state.streamingText = '';
      state.receivedSentenceStream = false;
      setCaption(state.dictation.armed ? '⌨️ Typing...' : '🎤 Transcribing...');
      applyFaceState('thinking');

      const audioMessage = {
        type: 'audio',
        data: base64,
        mime_type: mimeType || 'audio/webm',
      };
      if (state.dictation.armed) audioMessage.dictation = true;
      const sent = sendWs(audioMessage);
      if (sent) {
        state.backendTurnActive = true;
      } else {
        applyFaceState('error');
        setCaption('No connection right now. Trying to reconnect...', { isError: true });
      }
    } catch {
      if (state.ptt.generation === generation) applyFaceState('error');
    }
  }

  function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        const result = String(reader.result || '');
        const commaIdx = result.indexOf(',');
        resolve(commaIdx >= 0 ? result.slice(commaIdx + 1) : result);
      };
      reader.onerror = () => reject(new Error('Failed to read audio'));
      reader.readAsDataURL(blob);
    });
  }

  // Typing and sending text
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

  function submitChatText(text) {
    const clean = (text || '').trim();
    if (!clean) return;

    stopSpeaking({ resetState: false });
    if (state.typingTimer) {
      window.clearTimeout(state.typingTimer);
      state.typingTimer = null;
    }
    state.typingActive = false;

    state.streamingText = '';
    state.receivedSentenceStream = false;
    setCaption('...');

    const sent = sendWs({ type: 'text', text: clean });
    if (!sent) {
      applyFaceState('error');
      setCaption('No connection right now. Trying to reconnect...', { isError: true });
      return;
    }
    state.backendTurnActive = true;
  }

  function handleChatSubmit(event) {
    event.preventDefault();
    unlockAudio();
    const text = els.chatInput.value.trim();
    if (!text) return;
    submitChatText(text);
    els.chatInput.value = '';
    document.body.classList.remove('dock-text-open');
    lookAtSafe(0, 0);
  }

  // Direct touch/petting interaction on the face
  function computeNormalizedTouch(clientX, clientY) {
    const rect = els.faceContainer.getBoundingClientRect();
    if (!rect.width || !rect.height) return { nx: 0, ny: 0 };
    const nx = Math.max(-1, Math.min(1, ((clientX - rect.left) / rect.width) * 2 - 1));
    const ny = Math.max(-1, Math.min(1, ((clientY - rect.top) / rect.height) * 2 - 1));
    return { nx, ny };
  }

  function bindFaceTouchEvents() {
    if (!els.faceContainer) return;

    els.faceContainer.addEventListener('pointerdown', (e) => {
      if (!isMiniPet) unlockAudio();
      const api = faceApi();
      const faceState = api && typeof api.getState === 'function' ? api.getState() : 'idle';
      if (!isMiniPet && (faceState === 'speaking' || state.ttsPlaying)) {
        triggerBargeIn();
        return;
      }
      state.pointerTouch.down = true;
      state.pointerTouch.moved = false;
      state.pointerTouch.startX = e.clientX;
      state.pointerTouch.startY = e.clientY;
    });

    els.faceContainer.addEventListener('pointermove', (e) => {
      if (!state.pointerTouch.down) return;
      const dx = e.clientX - state.pointerTouch.startX;
      const dy = e.clientY - state.pointerTouch.startY;
      if (Math.hypot(dx, dy) > 10) {
        state.pointerTouch.moved = true;
      }
      if (!state.pointerTouch.moved) return;

      const { nx, ny } = computeNormalizedTouch(e.clientX, e.clientY);
      const api = faceApi();
      if (api && typeof api.reactToTouch === 'function') {
        api.reactToTouch('pet', nx, ny);
      } else {
        lookAtSafe(nx, ny);
      }

      if (!isMiniPet) {
        const now = Date.now();
        if (now - state.lastPetSentAt > 900) {
          state.lastPetSentAt = now;
          sendWs({ type: 'touch', kind: 'pet' });
        }
      }
    });

    const endTouch = (e) => {
      if (!state.pointerTouch.down) return;
      const wasMoved = state.pointerTouch.moved;
      state.pointerTouch.down = false;
      state.pointerTouch.moved = false;

      const aud = audioApi();
      if (aud && typeof aud.purr === 'function') {
        aud.purr(false);
      }

      if (!wasMoved && !isMiniPet && handleDictationTap()) {
        syncFaceBadges();
        return;
      }
      if (!wasMoved && !isMiniPet && handleFaceTap()) {
        syncFaceBadges();
        return;
      }
      if (!wasMoved) {
        const { nx, ny } = computeNormalizedTouch(e.clientX, e.clientY);
        const api = faceApi();
        if (api && typeof api.reactToTouch === 'function') {
          api.reactToTouch('poke', nx, ny);
        }
        if (!isMiniPet) sendWs({ type: 'touch', kind: 'poke' });
      }
      syncFaceBadges();
    };

    els.faceContainer.addEventListener('pointerup', endTouch);
    els.faceContainer.addEventListener('pointercancel', endTouch);
  }

  // Live Dock & Shortcuts Stream Deck
  async function fetchMacApps() {
    try {
      const res = await fetch('/api/mac/apps');
      if (!res.ok) return;
      const data = await res.json();
      const apps = Array.isArray(data) ? data : data.apps || [];
      state.macApps = apps;
      renderMacApps();
    } catch {
      // Ignore transient error
    }
  }

  function renderMacApps() {
    els.dockAppsGrid.textContent = '';
    const front = state.macApps.find((a) => a.frontmost || a.is_frontmost);
    els.dockActiveApp.textContent = `Active: ${front ? front.name : '—'}`;

    if (state.macApps.length === 0) {
      const empty = document.createElement('span');
      empty.className = 'panel-pill';
      empty.textContent = 'No apps listed';
      els.dockAppsGrid.appendChild(empty);
      return;
    }

    state.macApps.forEach((app) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'dock-app-tile';
      if (app.running || app.is_running) btn.classList.add('is-running');
      if (app.frontmost || app.is_frontmost) btn.classList.add('is-frontmost');
      btn.dataset.navTile = 'app';

      const dot = document.createElement('span');
      dot.className = 'dock-app-dot';
      dot.setAttribute('aria-hidden', 'true');

      const label = document.createElement('span');
      label.textContent = `${app.icon ? `${app.icon} ` : ''}${app.name}`;

      btn.appendChild(dot);
      btn.appendChild(label);
      btn.addEventListener('click', () => activateMacApp(app.name));
      els.dockAppsGrid.appendChild(btn);
    });
  }

  async function activateMacApp(appName) {
    if (!appName) return;
    unlockAudio();
    const aud = audioApi();
    if (aud && typeof aud.click === 'function' && state.petSoundsEnabled) aud.click();

    try {
      const res = await fetch('/api/mac/apps/activate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ app: appName }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok !== false) {
        showToast(`🖥️ ${appName} in focus`);
        applyFaceEmotion('happy');
        fetchMacApps();
      } else {
        showToast(data.error || data.message || data.detail || `Error activating ${appName}`, {
          isError: true,
        });
      }
    } catch {
      showToast(`Network error while activating ${appName}`, { isError: true });
    }
  }

  async function fetchShortcuts() {
    try {
      const res = await fetch('/api/shortcuts');
      if (!res.ok) return;
      const data = await res.json();
      state.shortcuts = Array.isArray(data) ? data : data.shortcuts || [];
      renderDock();
      renderSettingsShortcuts();
      if (state.shortcutModalOpen) {
        renderShortcutManageList();
      }
    } catch {
      // Ignore transient error
    }
  }

  function formatShortcutBadge(sc) {
    const p = sc.payload || {};
    if (sc.action_type === 'keystroke') return p.keys || '';
    if (sc.action_type === 'app_activate') return p.app || 'App';
    if (sc.action_type === 'mac_command') return p.command || 'Command';
    if (sc.action_type === 'agent_prompt') return 'Assistant';
    return '';
  }

  // Dock: 3x3 grid of Pinned Shortcuts, 9 per page. The last page lists the open apps.
  const DOCK_PAGE_SIZE = 9;
  const DOCK_EMPTY_TEXT = 'No pinned shortcuts. Choose shortcuts on the Mac.';

  function pinnedShortcuts() {
    return state.shortcuts
      .filter((sc) => sc.pinned_on_deck !== false && sc.pinned_on_deck !== 0)
      .map((sc, index) => ({ sc, index }))
      .sort((x, y) => {
        const ox = Number.isFinite(x.sc.sort_order) ? x.sc.sort_order : 0;
        const oy = Number.isFinite(y.sc.sort_order) ? y.sc.sort_order : 0;
        return ox - oy || x.index - y.index;
      })
      .map((item) => item.sc);
  }

  function shortcutPageCount() {
    return Math.max(1, Math.ceil(pinnedShortcuts().length / DOCK_PAGE_SIZE));
  }

  // Shortcut pages + 1 final "Open apps" page.
  function dockPageCount() {
    return shortcutPageCount() + 1;
  }

  function setDockPage(page) {
    const last = dockPageCount() - 1;
    const next = Math.max(0, Math.min(last, Number.isFinite(page) ? Math.trunc(page) : 0));
    const changed = next !== state.dockPage;
    state.dockPage = next;
    state.gamepadFocusIndex = -1;
    renderDock();
    if (changed) {
      const aud = audioApi();
      if (aud && typeof aud.click === 'function' && state.petSoundsEnabled) aud.click();
    }
  }

  function renderDockDots() {
    if (!els.dockPageDots) return;
    els.dockPageDots.textContent = '';
    const total = dockPageCount();
    for (let i = 0; i < total; i += 1) {
      const dot = document.createElement('span');
      dot.className = 'dock-dot';
      const isApps = i === total - 1;
      if (isApps) dot.classList.add('is-apps');
      if (i === state.dockPage) dot.classList.add('is-active');
      dot.setAttribute('aria-hidden', 'true');
      els.dockPageDots.appendChild(dot);
    }
    els.dockPageDots.setAttribute(
      'aria-label',
      `Page ${state.dockPage + 1} of ${total}${state.dockPage === total - 1 ? ' (Open apps)' : ''}`
    );
  }

  function renderDock() {
    const total = dockPageCount();
    if (state.dockPage > total - 1) state.dockPage = total - 1;
    const onApps = state.dockPage === total - 1;
    if (els.shortcutsGrid) els.shortcutsGrid.classList.toggle('hidden', onApps);
    if (els.dockAppsPage) els.dockAppsPage.classList.toggle('hidden', !onApps);
    renderDockDots();
    if (onApps) {
      if (els.shortcutsGrid) els.shortcutsGrid.textContent = '';
      return;
    }
    if (!els.shortcutsGrid) return;
    els.shortcutsGrid.textContent = '';
    const pinned = pinnedShortcuts();
    if (pinned.length === 0) {
      const empty = document.createElement('p');
      empty.className = 'dock-empty';
      empty.textContent = DOCK_EMPTY_TEXT;
      els.shortcutsGrid.appendChild(empty);
      return;
    }
    const start = state.dockPage * DOCK_PAGE_SIZE;
    pinned.slice(start, start + DOCK_PAGE_SIZE).forEach((sc) => {
      els.shortcutsGrid.appendChild(buildShortcutTile(sc));
    });
  }

  function buildShortcutTile(sc) {
    const labelText = sc.title || sc.slug || 'Shortcut';
    const hintText = formatShortcutBadge(sc);

    const tile = document.createElement('div');
    tile.className = `shortcut-tile vsd-key color-${sc.color || 'cyan'}`;
    tile.tabIndex = 0;
    tile.setAttribute('role', 'button');
    tile.setAttribute('aria-label', hintText ? `${labelText} — ${hintText}` : labelText);
    tile.title = hintText ? `${labelText} (${hintText})` : labelText;
    tile.dataset.navTile = 'shortcut';

    const icon = document.createElement('span');
    icon.className = 'vsd-key-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = sc.icon || '⚡';

    const title = document.createElement('div');
    title.className = 'vsd-key-label';
    title.textContent = labelText;

    tile.appendChild(icon);
    tile.appendChild(title);

    tile.addEventListener('click', () => runShortcut(sc, tile));
    tile.addEventListener('keydown', (e) => {
      if (e.target !== tile) return;
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        runShortcut(sc, tile);
      }
    });
    return tile;
  }

  function renderShortcutsGrid() {
    renderDock();
  }

  async function runShortcut(sc, tileEl = null) {
    if (!sc) return;
    if (tileEl) {
      tileEl.classList.add('is-firing');
      window.setTimeout(() => tileEl.classList.remove('is-firing'), 220);
    }
    unlockAudio();
    const aud = audioApi();
    if (aud && typeof aud.click === 'function' && state.petSoundsEnabled) aud.click();

    const idOrSlug = sc.id !== undefined && sc.id !== null ? sc.id : sc.slug;
    const sendShortcutOverWs = () => {
      const sent = sendWs({
        type: 'run_shortcut',
        [sc.id !== undefined && sc.id !== null ? 'id' : 'slug']: idOrSlug,
      });
      if (sent && sc.action_type === 'agent_prompt' && !sc.requires_confirmation) {
        state.backendTurnActive = true;
      }
      return sent;
    };

    if (sc.requires_confirmation || sc.action_type === 'agent_prompt') {
      if (!sendShortcutOverWs()) {
        showToast('No connection to request the shortcut confirmation.', { isError: true });
      }
      return;
    }

    try {
      const res = await fetch(`/api/shortcuts/${encodeURIComponent(idOrSlug)}/run`, {
        method: 'POST',
      });
      const data = await res.json().catch(() => ({}));

      if (res.status === 409 && data.detail && data.detail.code === 'approval_required') {
        if (sendShortcutOverWs()) return;
      }

      if (res.ok && data.ok !== false) {
        showToast(`⚡ ${sc.title}`);
        applyFaceEmotion('happy');
        const cmd = sc.payload && sc.payload.command;
        if (cmd === 'pomodoro_start') startPomodoro(25 * 60, 'focus');
        if (cmd === 'pomodoro_stop') stopPomodoro();
      } else {
        const detailMessage =
          data.detail && typeof data.detail === 'object' ? data.detail.message : data.detail;
        showToast(
          data.error || data.message || detailMessage || `Failed to run ${sc.title}`,
          {
            isError: true,
            durationMs: 4500,
          }
        );
        applyFaceEmotion('sad');
      }
    } catch {
      showToast(`Network error while running ${sc.title}`, { isError: true });
    }
  }

  // Shortcuts CRUD modal
  function updateShortcutPayloadVisibility() {
    const type = els.scActionType.value;
    els.scPayloadKeystroke.classList.toggle('hidden', type !== 'keystroke');
    els.scPayloadApp.classList.toggle('hidden', type !== 'app_activate');
    els.scPayloadCommand.classList.toggle('hidden', type !== 'mac_command');
    els.scPayloadPrompt.classList.toggle('hidden', type !== 'agent_prompt');
  }

  function syncBuilderFromKeysInput() {
    const raw = (els.scKeys.value || '').toLowerCase();
    const parts = raw.split('+').map((p) => p.trim()).filter(Boolean);
    els.modToggles.forEach((btn) => {
      btn.classList.toggle('is-active', parts.includes(btn.dataset.mod));
    });
    const lastKey = parts.find((p) => !['cmd', 'opt', 'alt', 'ctrl', 'shift'].includes(p)) || '';
    if (els.scKeySelect && Array.from(els.scKeySelect.options).some((o) => o.value === lastKey)) {
      els.scKeySelect.value = lastKey;
    }
  }

  function rebuildKeysFromBuilder() {
    const mods = [];
    els.modToggles.forEach((btn) => {
      if (btn.classList.contains('is-active')) mods.push(btn.dataset.mod);
    });
    const key = els.scKeySelect.value || '';
    const all = key ? [...mods, key] : mods;
    els.scKeys.value = all.join('+');
  }

  function resetShortcutForm() {
    els.scId.value = '';
    els.scFormHeading.textContent = 'New Shortcut';
    els.scTitle.value = '';
    els.scIcon.value = '⚡';
    els.scCategory.value = 'custom';
    els.scColor.value = 'cyan';
    els.scActionType.value = 'keystroke';
    els.scKeys.value = '';
    els.scAppName.value = '';
    els.scMacCommand.value = 'mission_control';
    els.scAgentPrompt.value = '';
    els.scVoiceTriggers.value = '';
    els.scPinned.checked = false;
    els.scConfirm.checked = false;
    els.btnScDelete.classList.add('hidden');
    stopRecordingKeys();
    updateShortcutPayloadVisibility();
    syncBuilderFromKeysInput();
  }

  function fillShortcutForm(sc) {
    els.scId.value = sc.id !== undefined ? String(sc.id) : sc.slug || '';
    els.scFormHeading.textContent = `Edit: ${sc.title}`;
    els.scTitle.value = sc.title || '';
    els.scIcon.value = sc.icon || '⚡';
    els.scCategory.value = sc.category || 'custom';
    els.scColor.value = sc.color || 'cyan';
    els.scActionType.value = sc.action_type || 'keystroke';
    const p = sc.payload || {};
    els.scKeys.value = p.keys || '';
    els.scAppName.value = p.app || '';
    els.scMacCommand.value = p.command || 'mission_control';
    els.scAgentPrompt.value = p.prompt || '';
    els.scVoiceTriggers.value = sc.voice_triggers || '';
    els.scPinned.checked = sc.pinned_on_deck !== false && sc.pinned_on_deck !== 0;
    els.scConfirm.checked = Boolean(sc.requires_confirmation);
    els.btnScDelete.classList.remove('hidden');
    stopRecordingKeys();
    updateShortcutPayloadVisibility();
    syncBuilderFromKeysInput();
  }

  function openShortcutModal(shortcutToEdit = null) {
    state.overlayReturnFocus = document.activeElement;
    state.gamepadFocusIndex = -1;
    state.shortcutModalOpen = true;
    els.shortcutModalBackdrop.classList.remove('hidden');
    els.shortcutModal.classList.remove('hidden');
    if (shortcutToEdit) {
      fillShortcutForm(shortcutToEdit);
    } else {
      resetShortcutForm();
    }
    renderShortcutManageList();
    els.scTitle.focus();
  }

  function closeShortcutModal() {
    state.shortcutModalOpen = false;
    state.gamepadFocusIndex = -1;
    stopRecordingKeys();
    els.shortcutModalBackdrop.classList.add('hidden');
    els.shortcutModal.classList.add('hidden');
    const returnFocus = state.overlayReturnFocus;
    state.overlayReturnFocus = null;
    if (returnFocus && returnFocus.isConnected !== false) returnFocus.focus();
  }

  function startRecordingKeys() {
    state.recordingShortcutKeys = !state.recordingShortcutKeys;
    els.btnRecordKeys.classList.toggle('is-active', state.recordingShortcutKeys);
    els.btnRecordKeys.textContent = state.recordingShortcutKeys
      ? '🔴 Press the combination...'
      : '🎹 Record from Keyboard';
  }

  function stopRecordingKeys() {
    state.recordingShortcutKeys = false;
    els.btnRecordKeys.classList.remove('is-active');
    els.btnRecordKeys.textContent = '🎹 Record from Keyboard';
  }

  function normalizeRecordedKey(event) {
    const code = event.code || '';
    const key = (event.key || '').toLowerCase();
    if (['meta', 'control', 'alt', 'shift'].includes(key)) return null;
    if (code === 'Backquote' || key === '`' || key === 'dead') return 'grave';
    if (code === 'Space' || key === ' ') return 'space';
    if (key === 'arrowleft') return 'left';
    if (key === 'arrowright') return 'right';
    if (key === 'arrowup') return 'up';
    if (key === 'arrowdown') return 'down';
    if (key === 'escape') return 'esc';
    if (key === 'enter' || key === 'tab') return key;
    if (/^Key[A-Z]$/.test(code)) return code.slice(3).toLowerCase();
    if (/^Digit[0-9]$/.test(code)) return code.slice(5);
    if (/^f([1-9]|1[0-2])$/.test(key)) return key;
    if (/^[a-z0-9]$/.test(key)) return key;
    return null;
  }

  async function saveShortcutFromForm(event) {
    event.preventDefault();
    const actionType = els.scActionType.value;
    let payload = {};
    if (actionType === 'keystroke') {
      payload = { keys: els.scKeys.value.trim().toLowerCase() };
    } else if (actionType === 'app_activate') {
      payload = { app: els.scAppName.value.trim() };
    } else if (actionType === 'mac_command') {
      payload = { command: els.scMacCommand.value };
    } else if (actionType === 'agent_prompt') {
      payload = { prompt: els.scAgentPrompt.value.trim() };
    }

    const body = {
      title: els.scTitle.value.trim(),
      icon: els.scIcon.value.trim() || '⚡',
      category: els.scCategory.value,
      color: els.scColor.value,
      action_type: actionType,
      payload,
      voice_triggers: els.scVoiceTriggers.value.trim(),
      pinned_on_deck: els.scPinned.checked,
      requires_confirmation: els.scConfirm.checked,
    };

    const existingId = els.scId.value.trim();
    const url = existingId
      ? `/api/shortcuts/${encodeURIComponent(existingId)}`
      : '/api/shortcuts';
    const method = existingId ? 'PUT' : 'POST';

    try {
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showToast(err.detail || 'Error saving shortcut', { isError: true });
        return;
      }
      showToast(existingId ? '✓ Shortcut updated' : '✓ New shortcut created');
      resetShortcutForm();
      await fetchShortcuts();
    } catch {
      showToast('Network error while saving shortcut', { isError: true });
    }
  }

  async function deleteShortcutById(idOrSlug) {
    if (!idOrSlug) return;
    try {
      const res = await fetch(`/api/shortcuts/${encodeURIComponent(idOrSlug)}`, {
        method: 'DELETE',
      });
      if (!res.ok) return;
      showToast('🗑️ Shortcut removed');
      if (els.scId.value === String(idOrSlug)) {
        resetShortcutForm();
      }
      await fetchShortcuts();
    } catch {
      showToast('Error removing shortcut', { isError: true });
    }
  }

  async function moveShortcutOrder(index, direction) {
    const nextIdx = index + direction;
    if (nextIdx < 0 || nextIdx >= state.shortcuts.length) return;
    const copy = [...state.shortcuts];
    const [item] = copy.splice(index, 1);
    copy.splice(nextIdx, 0, item);
    const orderedIds = copy.map((s) => s.id);
    try {
      const res = await fetch('/api/shortcuts/reorder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ordered_ids: orderedIds }),
      });
      if (res.ok) {
        await fetchShortcuts();
      }
    } catch {
      // Ignore transient error
    }
  }

  async function resetDefaultShortcuts() {
    try {
      const res = await fetch('/api/shortcuts/reset-defaults', { method: 'POST' });
      if (!res.ok) return;
      showToast('↺ Shortcuts restored to defaults');
      resetShortcutForm();
      await fetchShortcuts();
    } catch {
      showToast('Error restoring shortcuts', { isError: true });
    }
  }

  function renderShortcutManageList() {
    els.scManageList.textContent = '';
    state.shortcuts.forEach((sc, index) => {
      const li = document.createElement('li');
      li.className = 'sc-manage-item';

      const info = document.createElement('div');
      info.className = 'sc-manage-info';
      const ico = document.createElement('span');
      ico.textContent = sc.icon || '⚡';
      const title = document.createElement('span');
      title.className = 'sc-manage-title';
      title.textContent = sc.title;
      info.appendChild(ico);
      info.appendChild(title);

      const btns = document.createElement('div');
      btns.className = 'sc-manage-btns';

      const upBtn = document.createElement('button');
      upBtn.type = 'button';
      upBtn.className = 'mini-icon-btn';
      upBtn.textContent = '↑';
      upBtn.title = 'Move up';
      upBtn.addEventListener('click', () => moveShortcutOrder(index, -1));

      const downBtn = document.createElement('button');
      downBtn.type = 'button';
      downBtn.className = 'mini-icon-btn';
      downBtn.textContent = '↓';
      downBtn.title = 'Move down';
      downBtn.addEventListener('click', () => moveShortcutOrder(index, 1));

      const editBtn = document.createElement('button');
      editBtn.type = 'button';
      editBtn.className = 'mini-icon-btn';
      editBtn.textContent = '✏️';
      editBtn.title = 'Edit';
      editBtn.addEventListener('click', () => fillShortcutForm(sc));

      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className = 'mini-icon-btn';
      delBtn.textContent = '🗑️';
      delBtn.title = 'Remove';
      delBtn.addEventListener('click', () => deleteShortcutById(sc.id));

      btns.appendChild(upBtn);
      btns.appendChild(downBtn);
      btns.appendChild(editBtn);
      btns.appendChild(delBtn);

      li.appendChild(info);
      li.appendChild(btns);
      els.scManageList.appendChild(li);
    });
  }

  // Pet Mode: clock, Pomodoro and Now Playing on the Mac
  function formatClockParts(date) {
    const hh = String(date.getHours()).padStart(2, '0');
    const mm = String(date.getMinutes()).padStart(2, '0');
    const ss = String(date.getSeconds()).padStart(2, '0');
    const dateStr = date.toLocaleDateString('pt-BR', {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
    });
    return { hm: `${hh}:${mm}`, hms: `${hh}:${mm}:${ss}`, dateStr };
  }

  function tickClocks() {
    const parts = formatClockParts(new Date());
    if (els.petClockTime) els.petClockTime.textContent = parts.hm;
    if (els.petClockDate) els.petClockDate.textContent = parts.dateStr;
  }

  function formatMmSs(totalSeconds) {
    const safe = Math.max(0, Math.floor(totalSeconds));
    const m = String(Math.floor(safe / 60)).padStart(2, '0');
    const s = String(safe % 60).padStart(2, '0');
    return `${m}:${s}`;
  }

  function syncPomodoroUI() {
    const label = formatMmSs(state.pomodoro.remainingSec);
    els.pomodoroTimer.textContent = label;

    if (!state.pomodoro.active) {
      els.pomodoroPhaseLabel.textContent = 'Ready';
    } else if (state.pomodoro.phase === 'break') {
      els.pomodoroPhaseLabel.textContent = 'Break';
    } else {
      els.pomodoroPhaseLabel.textContent = 'Focus active';
    }
    syncAccessoryForContext();
  }

  function startPomodoro(seconds, phase) {
    stopPomodoro({ silent: true });
    state.pomodoro.active = true;
    state.pomodoro.phase = phase;
    state.pomodoro.remainingSec = seconds;
    syncPomodoroUI();

    state.pomodoro.intervalId = window.setInterval(() => {
      state.pomodoro.remainingSec -= 1;
      if (state.pomodoro.remainingSec <= 0) {
        const endedPhase = state.pomodoro.phase;
        stopPomodoro();
        const aud = audioApi();
        if (aud && typeof aud.alert === 'function' && state.petSoundsEnabled) aud.alert();
        applyFaceEmotion('excited');
        // Lupin's spoken line follows his language setting; the toast is UI text.
        const spoken = lupinPhrase(
          endedPhase === 'break' ? 'pomodoro_break_done' : 'pomodoro_focus_done',
        );
        const toastText =
          endedPhase === 'break'
            ? 'Pomodoro break finished! Time to get back to focus.'
            : 'Pomodoro focus cycle complete! Take a break.';
        showToast(`🍅 ${toastText}`, { durationMs: 5000 });
        speakText(spoken);
        return;
      }
      syncPomodoroUI();
    }, 1000);
  }

  function stopPomodoro({ silent = false } = {}) {
    if (state.pomodoro.intervalId) {
      window.clearInterval(state.pomodoro.intervalId);
      state.pomodoro.intervalId = null;
    }
    state.pomodoro.active = false;
    state.pomodoro.phase = 'idle';
    state.pomodoro.remainingSec = 25 * 60;
    if (!silent) syncPomodoroUI();
  }

  async function fetchMacStatus() {
    try {
      const res = await fetch('/api/mac/status');
      if (!res.ok) return;
      const data = await res.json();

      const np = data.now_playing || {};
      const playing = Boolean(np.playing || np.state === 'playing');
      state.musicPlaying = playing;
      const face = faceApi();
      if (face && typeof face.setMusicPlaying === 'function') {
        face.setMusicPlaying(playing);
      }
      els.nowPlayingState.textContent = playing ? 'Playing' : 'Paused';
      els.nowPlayingTitle.textContent = np.track || np.title || 'No active media';
      els.nowPlayingArtist.textContent =
        [np.artist, np.app].filter(Boolean).join(' · ') || 'Spotify / Apple Music';

      syncAccessoryForContext();
      publishPetSnapshot();
    } catch {
      // Silence transient error
    }
  }

  async function triggerQuickMediaCommand(commandSlug) {
    try {
      const res = await fetch(`/api/shortcuts/${encodeURIComponent(commandSlug)}/run`, {
        method: 'POST',
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        showToast(data.error || data.message || data.detail || 'Media command failed', {
          isError: true,
          durationMs: 4000,
        });
      }
      window.setTimeout(fetchMacStatus, 450);
    } catch {
      showToast('Network error while controlling media', { isError: true });
    }
  }

  // Gamepad D-Pad navigation in the Dock, Settings & Nathan OS
  function getNavigableTiles() {
    if (state.pendingApprovalId) return getFocusableElements(els.approvalBanner);
    if (state.shortcutModalOpen) return getFocusableElements(els.shortcutModal);
    if (state.memoryOpen) return getFocusableElements(els.memoryDrawer);

    if (state.settingsOpen && els.settingsPanel) {
      return Array.from(els.settingsPanel.querySelectorAll('button, input[type="checkbox"]')).filter(
        isElementAvailable
      );
    }
    if (state.mode === 'dock') {
      return Array.from(els.modeDock.querySelectorAll('[data-nav-tile]')).filter(isElementAvailable);
    }
    const modeNathan = document.getElementById('mode-nathan');
    if (state.mode === 'nathan' && modeNathan) {
      return Array.from(modeNathan.querySelectorAll('button')).filter(isElementAvailable);
    }
    return [];
  }

  function moveGamepadFocus(direction) {
    const items = getNavigableTiles();
    if (items.length === 0) return;

    items.forEach((el) => el.classList.remove('gamepad-focused'));
    const forward = direction === 'right' || direction === 'down';
    const step = forward ? 1 : -1;
    const inShortcutGrid =
      state.mode === 'dock' &&
      !state.settingsOpen &&
      !state.pendingApprovalId &&
      !state.shortcutModalOpen &&
      !state.memoryOpen &&
      state.dockPage < dockPageCount() - 1;
    if (state.gamepadFocusIndex < 0) {
      state.gamepadFocusIndex = 0;
    } else if (inShortcutGrid && (direction === 'up' || direction === 'down')) {
      // 3x3 grid: up and down move one row; at the edges the focus stays where it is.
      const target = state.gamepadFocusIndex + step * 3;
      if (target >= 0 && target < items.length) state.gamepadFocusIndex = target;
    } else {
      state.gamepadFocusIndex = (state.gamepadFocusIndex + step + items.length) % items.length;
    }

    const target = items[state.gamepadFocusIndex];
    if (target) {
      target.classList.add('gamepad-focused');
      target.focus();
      if (typeof target.scrollIntoView === 'function') {
        target.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      }
    }
  }

  function activateGamepadFocused() {
    const items = getNavigableTiles();
    if (items.length > 0 && state.gamepadFocusIndex >= 0 && items[state.gamepadFocusIndex]) {
      items[state.gamepadFocusIndex].click();
      return;
    }
    if (state.pendingApprovalId || state.shortcutModalOpen || state.memoryOpen) {
      if (items[0]) items[0].focus();
    }
  }

  // HTTP Memory & Drawer
  function renderMemoryState(facts, recentCount) {
    const safeFacts = Array.isArray(facts) ? facts : [];
    const safeCount = typeof recentCount === 'number' ? recentCount : 0;

    state.facts = safeFacts;
    state.recentMessagesCount = safeCount;

    els.memoryCount.textContent = String(safeFacts.length);
    els.factsCountBadge.textContent = String(safeFacts.length);
    els.recentMessagesBadge.textContent = safeCount === 1 ? '1 msg' : `${safeCount} msgs`;

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
      catSpan.textContent = CATEGORY_LABELS[catKey] || catKey;

      const textSpan = document.createElement('span');
      textSpan.className = 'fact-text';
      textSpan.textContent = item.fact || '';

      contentDiv.appendChild(catSpan);
      contentDiv.appendChild(textSpan);

      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className = 'fact-delete-btn';
      delBtn.title = 'Remove this fact';
      delBtn.setAttribute('aria-label', `Remove fact: ${item.fact || ''}`);
      delBtn.textContent = '×';
      delBtn.addEventListener('click', () => deleteFact(item.id));

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
      // Silent failure
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
      // Ignore transient error
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
      // Ignore transient error
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
      setCaption(includeFacts ? 'All memory was reset.' : 'Current conversation cleared.');
    } catch {
      // Ignore transient error
    }
  }

  function openMemoryDrawer() {
    state.overlayReturnFocus = document.activeElement;
    state.gamepadFocusIndex = -1;
    state.memoryOpen = true;
    els.memoryBackdrop.classList.remove('hidden');
    els.memoryDrawer.classList.remove('hidden');
    els.memoryDrawer.setAttribute('aria-hidden', 'false');
    els.btnMemory.setAttribute('aria-expanded', 'true');
    els.btnMemory.classList.add('is-active');
    hideResetConfirmation();
    fetchMemory();
    focusFirstInContainer(els.memoryDrawer);
  }

  function closeMemoryDrawer() {
    state.memoryOpen = false;
    state.gamepadFocusIndex = -1;
    els.memoryBackdrop.classList.add('hidden');
    els.memoryDrawer.classList.add('hidden');
    els.memoryDrawer.setAttribute('aria-hidden', 'true');
    els.btnMemory.setAttribute('aria-expanded', 'false');
    els.btnMemory.classList.remove('is-active');
    hideResetConfirmation();
    const returnFocus = state.overlayReturnFocus;
    state.overlayReturnFocus = null;
    if (returnFocus && returnFocus.isConnected !== false) returnFocus.focus();
  }

  function showResetConfirmation() {
    els.btnResetMemory.classList.add('hidden');
    els.resetConfirmBox.classList.remove('hidden');
  }

  function hideResetConfirmation() {
    els.resetConfirmBox.classList.add('hidden');
    els.btnResetMemory.classList.remove('hidden');
  }

  // Fullscreen & WakeLock
  async function requestWakeLock() {
    if (!('wakeLock' in navigator) || state.wakeLock) return;
    try {
      state.wakeLock = await navigator.wakeLock.request('screen');
      state.wakeLock.addEventListener('release', () => {
        state.wakeLock = null;
      });
    } catch {
      // Ignore permission error
    }
  }

  async function releaseWakeLock() {
    if (!state.wakeLock) return;
    try {
      await state.wakeLock.release();
    } catch {
      // Ignore error
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
      // Ignore if fullscreen is not supported
    }
  }

  // Automatic fullscreen: the browser only accepts it after a user gesture, so
  // we ask once on the first tap or key. If the user exits, we do not insist.
  function requestFullscreenOnce() {
    if (state.fullscreenRequested || document.fullscreenElement) return;
    state.fullscreenRequested = true;
    toggleFullscreen();
  }

  function isElementAvailable(element) {
    if (!element || element.disabled || element.getAttribute('aria-disabled') === 'true') return false;
    for (let current = element; current && current !== document.body; current = current.parentElement) {
      if (
        (current.classList && current.classList.contains('hidden')) ||
        current.inert ||
        (current.getAttribute && current.getAttribute('aria-hidden') === 'true')
      ) {
        return false;
      }
    }
    return true;
  }

  function getFocusableElements(container) {
    if (!container || typeof container.querySelectorAll !== 'function') return [];
    return Array.from(
      container.querySelectorAll(
        'button, input:not([type="hidden"]), select, textarea, [tabindex]:not([tabindex="-1"])'
      )
    ).filter(isElementAvailable);
  }

  function focusFirstInContainer(container) {
    const first = getFocusableElements(container)[0];
    if (first) first.focus();
  }

  function trapDialogFocus(event) {
    const container = state.shortcutModalOpen
      ? els.shortcutModal
      : state.memoryOpen
        ? els.memoryDrawer
        : null;
    if (!container) return false;
    const focusable = getFocusableElements(container);
    if (!focusable.length) {
      event.preventDefault();
      return true;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    } else if (!focusable.includes(document.activeElement)) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
    }
    return true;
  }

  function isTypingInField(target) {
    if (!target || !target.tagName) return false;
    const tag = target.tagName.toLowerCase();
    return tag === 'input' || tag === 'textarea' || tag === 'select' || target.isContentEditable;
  }

  function cycleHorizontally(delta) {
    if (state.pendingApprovalId || state.shortcutModalOpen || state.memoryOpen) return;
    if (state.settingsOpen) cycleSettingsTab(delta);
    else cycleMode(delta);
  }

  function pageDock(delta) {
    if (state.pendingApprovalId || state.shortcutModalOpen || state.memoryOpen || state.settingsOpen) return;
    if (state.mode !== 'dock') return;
    setDockPage(state.dockPage + delta);
  }

  const SWIPE_MIN_VERTICAL_PX = 110;

  // Horizontal swipe switches the Mode; vertical, in the Dock, switches the page.
  function applySwipe(dx, dy, elapsedMs) {
    if (elapsedMs > SWIPE_MAX_MS) return false; // dragging slowly is petting the face
    if (Math.abs(dx) >= SWIPE_MIN_PX && Math.abs(dy) <= SWIPE_MAX_OFF_AXIS_PX) {
      cycleHorizontally(dx < 0 ? 1 : -1);
      return true;
    }
    if (
      state.mode === 'dock' &&
      Math.abs(dy) >= SWIPE_MIN_VERTICAL_PX &&
      Math.abs(dx) <= SWIPE_MAX_OFF_AXIS_PX
    ) {
      pageDock(dy < 0 ? 1 : -1);
      return true;
    }
    return false;
  }

  function bindSwipe() {
    let start = null;
    document.addEventListener(
      'touchstart',
      (event) => {
        const touch = event.touches && event.touches.length === 1 ? event.touches[0] : null;
        const target = event.target;
        const ignored =
          !touch ||
          isTypingInField(target) ||
          Boolean(target && target.closest && target.closest('.bottom-dock, .memory-drawer, .shortcut-modal'));
        start = ignored ? null : { x: touch.clientX, y: touch.clientY, at: Date.now() };
      },
      { passive: true }
    );
    document.addEventListener(
      'touchend',
      (event) => {
        if (!start) return;
        const touch = event.changedTouches && event.changedTouches[0];
        const origin = start;
        start = null;
        if (!touch) return;
        applySwipe(touch.clientX - origin.x, touch.clientY - origin.y, Date.now() - origin.at);
      },
      { passive: true }
    );
  }

  // Event registration
  function bindEvents() {
    bindSwipe();
    ['pointerdown', 'touchstart', 'keydown'].forEach((evtName) => {
      document.addEventListener(evtName, noteUserInput, { passive: true, capture: true });
    });
    ['mousemove', 'pointerdown', 'touchstart'].forEach((evtName) => {
      document.addEventListener(
        evtName,
        () => {
          if (evtName !== 'mousemove') {
            unlockAudio();
            requestFullscreenOnce();
          }
        },
        { passive: true }
      );
    });

    // Keyboard on the Mac: shortcut recorder, Escape (barge-in / close) and Space (PTT)
    document.addEventListener('keydown', (event) => {

      if (event.key === 'Tab' && trapDialogFocus(event)) return;

      if (state.recordingShortcutKeys && state.shortcutModalOpen) {
        const keyPart = normalizeRecordedKey(event);
        if (keyPart) {
          event.preventDefault();
          const mods = [];
          if (event.metaKey) mods.push('cmd');
          if (event.altKey) mods.push('opt');
          if (event.ctrlKey) mods.push('ctrl');
          if (event.shiftKey) mods.push('shift');
          els.scKeys.value = [...mods, keyPart].join('+');
          syncBuilderFromKeysInput();
          stopRecordingKeys();
        }
        return;
      }

      if (event.altKey && (event.key === 'ArrowLeft' || event.key === 'ArrowRight')) {
        event.preventDefault();
        cycleHorizontally(event.key === 'ArrowLeft' ? -1 : 1);
        return;
      }

      if (event.key === 'Escape') {
        if (state.shortcutModalOpen) {
          closeShortcutModal();
        } else if (state.memoryOpen) {
          closeMemoryDrawer();
        } else if (state.settingsOpen) {
          setSettingsOpen(false);
          els.btnSettings.focus();
        } else {
          triggerBargeIn();
        }
        return;
      }

      if (
        event.code === 'Space' &&
        !event.repeat &&
        !state.shortcutModalOpen &&
        !state.memoryOpen &&
        !isTypingInField(document.activeElement)
      ) {
        event.preventDefault();
        state.ptt.spaceHeld = true;
        startPtt();
      }
    });

    document.addEventListener('keyup', (event) => {
      if (event.code === 'Space' && state.ptt.spaceHeld) {
        event.preventDefault();
        state.ptt.spaceHeld = false;
        stopPttAndSend();
      }
    });

    // Switcher for the 4 modes
    if (els.btnSettings) {
      els.btnSettings.addEventListener('click', () => setSettingsOpen(!state.settingsOpen));
    }
    if (els.btnSettingsClose) {
      els.btnSettingsClose.addEventListener('click', () => setSettingsOpen(false));
    }
    els.settingsSubtabs.forEach((btn) => {
      btn.addEventListener('click', () => setSettingsOpen(true, btn.dataset.subtab));
    });
    els.audioUnlockBanner.addEventListener('click', unlockAudio);

    els.btnMemory.addEventListener('click', () => {
      if (state.memoryOpen) closeMemoryDrawer();
      else openMemoryDrawer();
    });
    els.btnCloseMemory.addEventListener('click', closeMemoryDrawer);
    els.memoryBackdrop.addEventListener('click', closeMemoryDrawer);

    els.btnPetSounds.addEventListener('click', () => {
      unlockAudio();
      state.petSoundsEnabled = !state.petSoundsEnabled;
      savePref(PREFS.petSoundsEnabled, state.petSoundsEnabled);
      syncTtsUI();
      if (state.petSoundsEnabled) {
        const aud = audioApi();
        if (aud && typeof aud.click === 'function') aud.click();
      }
    });

    els.btnTts.addEventListener('click', () => {
      unlockAudio();
      state.ttsEnabled = !state.ttsEnabled;
      savePref(PREFS.ttsEnabled, state.ttsEnabled);
      syncTtsUI();
      if (!state.ttsEnabled) {
        stopSpeaking({ resetState: true });
      }
    });

    els.btnTtsMode.addEventListener('click', toggleTtsMode);
    if (els.selLupinLanguage) {
      els.selLupinLanguage.addEventListener('change', () => changeLupinLanguage(els.selLupinLanguage.value));
    }

    if (els.consentCalendar) els.consentCalendar.addEventListener('click', () => toggleDataConsent('calendar'));
    if (els.consentEmail) els.consentEmail.addEventListener('click', () => toggleDataConsent('email'));
    if (els.consentFiles) els.consentFiles.addEventListener('click', () => toggleDataConsent('files'));

    els.btnCaption.addEventListener('click', () => {
      state.captionVisible = !state.captionVisible;
      savePref(PREFS.captionVisible, state.captionVisible);
      syncCaptionVisibilityUI();
    });

    document.addEventListener('fullscreenchange', () => {
      if (!document.fullscreenElement) releaseWakeLock();
    });
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && document.fullscreenElement) {
        requestWakeLock();
      }
    });

    // Push-to-Talk physical button/touch
    els.btnPtt.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      startPtt();
    });
    ['pointerup', 'pointercancel', 'pointerleave'].forEach((evt) => {
      els.btnPtt.addEventListener(evt, () => {
        if (state.ptt.active && !state.ptt.spaceHeld) {
          stopPttAndSend();
        }
      });
    });

    if (els.btnDictation) {
      els.btnDictation.addEventListener('click', () => setDictationArmed(!state.dictation.armed));
    }

    // Chat
    els.chatForm.addEventListener('submit', handleChatSubmit);
    els.chatInput.addEventListener('input', handleInputActivity);
    els.chatInput.addEventListener('focus', () => {
      lookAtSafe(0, 0.35);
    });
    els.chatInput.addEventListener('blur', () => {
      if (!state.typingActive) lookAtSafe(0, 0);
    });

    // Quick approval
    els.btnApproveAction.addEventListener('click', () => resolveToolApproval(true));
    els.btnDenyAction.addEventListener('click', () => resolveToolApproval(false));

    // Dock & Shortcuts
    els.btnRefreshApps.addEventListener('click', fetchMacApps);
    if (els.btnSettingsNewShortcut) {
      els.btnSettingsNewShortcut.addEventListener('click', () => openShortcutModal(null));
    }
    if (els.btnSettingsManageShortcuts) {
      els.btnSettingsManageShortcuts.addEventListener('click', () => openShortcutModal(null));
    }
    if (els.btnDockTalk) {
      els.btnDockTalk.addEventListener('pointerdown', (e) => {
        e.preventDefault();
        dockTalkDown();
      });
      ['pointerup', 'pointercancel', 'pointerleave'].forEach((evt) => {
        els.btnDockTalk.addEventListener(evt, () => {
          if (state.dockTalk.holdTimer !== null || state.dockTalk.holding) dockTalkUp();
        });
      });
      els.btnDockTalk.addEventListener('contextmenu', (e) => e.preventDefault());
    }
    els.btnCloseShortcutModal.addEventListener('click', closeShortcutModal);
    els.shortcutModalBackdrop.addEventListener('click', closeShortcutModal);
    els.scActionType.addEventListener('change', updateShortcutPayloadVisibility);
    els.btnRecordKeys.addEventListener('click', startRecordingKeys);
    els.scKeys.addEventListener('input', syncBuilderFromKeysInput);
    els.modToggles.forEach((btn) => {
      btn.addEventListener('click', () => {
        btn.classList.toggle('is-active');
        rebuildKeysFromBuilder();
      });
    });
    els.scKeySelect.addEventListener('change', rebuildKeysFromBuilder);
    document.querySelectorAll('.emoji-chip').forEach((chip) => {
      chip.addEventListener('click', () => {
        els.scIcon.value = chip.dataset.emoji || '⚡';
      });
    });
    els.shortcutForm.addEventListener('submit', saveShortcutFromForm);
    els.btnScResetForm.addEventListener('click', resetShortcutForm);
    els.btnScDelete.addEventListener('click', () => deleteShortcutById(els.scId.value));
    els.btnScResetDefaults.addEventListener('click', resetDefaultShortcuts);

    // Smart Display
    els.btnPomoFocus.addEventListener('click', () => startPomodoro(25 * 60, 'focus'));
    els.btnPomoBreak.addEventListener('click', () => startPomodoro(5 * 60, 'break'));
    els.btnPomoStop.addEventListener('click', () => stopPomodoro());
    els.btnMediaPrev.addEventListener('click', () => triggerQuickMediaCommand('prev_track'));
    els.btnMediaPlay.addEventListener('click', () => triggerQuickMediaCommand('play_pause'));
    els.btnMediaNext.addEventListener('click', () => triggerQuickMediaCommand('next_track'));

    // Memory
    els.addFactForm.addEventListener('submit', addManualFact);
    els.btnClearChat.addEventListener('click', () => clearMemory({ includeFacts: false }));
    els.btnResetMemory.addEventListener('click', showResetConfirmation);
    els.btnCancelReset.addEventListener('click', hideResetConfirmation);
    els.btnConfirmReset.addEventListener('click', () => clearMemory({ includeFacts: true }));

    if (supportsSpeechSynthesis() && 'onvoiceschanged' in window.speechSynthesis) {
      window.speechSynthesis.addEventListener('voiceschanged', refreshVoices);
    }

    bindFaceTouchEvents();
  }

  function initGamepad() {
    if (!window.DeskGamepad || typeof window.DeskGamepad.init !== 'function') return;
    const overlayOpen = () => state.pendingApprovalId || state.shortcutModalOpen || state.memoryOpen;
    const handlers = {
      onLook: (x, y) => lookAtSafe(x, y),
      // In the Dock, L2/R2 become "previous/next page"; outside it they remain Push-to-Talk.
      triggersAsPage: () => state.mode === 'dock' && !state.settingsOpen && !overlayOpen(),
      onPage: (dir) => pageDock(dir),
      onYPress: () => {
        if (overlayOpen()) return;
        if (state.mode === 'dock' && !state.settingsOpen) {
          state.yHeldPtt = true;
          startPtt();
        } else {
          toggleTtsMode();
        }
      },
      onYRelease: () => {
        if (!state.yHeldPtt) return;
        state.yHeldPtt = false;
        stopPttAndSend();
      },
      onPttStart: () => {
        if (!state.pendingApprovalId && !state.shortcutModalOpen && !state.memoryOpen) startPtt();
      },
      onPttEnd: () => stopPttAndSend(),
      onModeCycle: (dir) => {
        if (state.pendingApprovalId || state.shortcutModalOpen || state.memoryOpen) return;
        // With Settings open, L1/R1 switch section; outside it, they switch Mode.
        if (state.settingsOpen) cycleSettingsTab(dir);
        else cycleMode(dir);
      },
      onDpad: (dir) => moveGamepadFocus(dir),
      onConfirm: () => {
        if (state.pendingApprovalId) {
          resolveToolApproval(true);
          return;
        }
        activateGamepadFocused();
      },
      onBackOrInterrupt: () => {
        if (state.pendingApprovalId) {
          resolveToolApproval(false);
        } else if (state.shortcutModalOpen) {
          closeShortcutModal();
        } else if (state.memoryOpen) {
          closeMemoryDrawer();
        } else if (state.settingsOpen) {
          setSettingsOpen(false);
        } else {
          triggerBargeIn();
        }
      },
      onToggleCaption: () => {
        state.captionVisible = !state.captionVisible;
        savePref(PREFS.captionVisible, state.captionVisible);
        syncCaptionVisibilityUI();
      },
      onToggleTtsMode: () => toggleTtsMode(),
      onSelect: () => toggleFullscreen(),
      onStart: () => {
        if (state.pendingApprovalId) return;
        if (state.shortcutModalOpen) {
          closeShortcutModal();
        } else if (state.memoryOpen) {
          closeMemoryDrawer();
        } else {
          setSettingsOpen(!state.settingsOpen);
        }
      },
    };
    // Any gamepad button counts as interaction and cancels the automatic return from Pet.
    Object.keys(handlers).forEach((name) => {
      if (name === 'onLook' || name === 'triggersAsPage') return;
      const original = handlers[name];
      handlers[name] = (...args) => {
        noteUserInput();
        return original(...args);
      };
    });
    window.DeskGamepad.init(handlers);
  }

  var mcpSettings = null; // var: hoisted, read by the settings renderer before init runs

  function initDiagnostics() {
    if (window.DeskMcpSettings && els.mcpRoot) mcpSettings = window.DeskMcpSettings.mount(els.mcpRoot);
    if (window.DeskSkills && typeof window.DeskSkills.init === 'function' && els.skillsRoot) {
      window.DeskSkills.init(els.skillsRoot, {
        onPlayTrick: (trickId) => {
          setMode('pet');
          playPetTrick(trickId);
        },
      });
    }
    if (!window.DeskDiagnostics || typeof window.DeskDiagnostics.init !== 'function') return;
    window.DeskDiagnostics.init(els.diagnosticsRoot, {
      getTtsMode: () => state.ttsMode,
      getVoiceLang: () => (state.lupinLanguage === 'en' ? 'en' : 'pt'),
      getTestPhrase: (kind) => lupinPhrase(kind === 'server' ? 'diag_test_server_tts' : 'diag_test_browser_tts'),
      onTestBrowserTts: (text) => {
        unlockAudio();
        enqueueTtsSentence(text, 'browser');
      },
      onTestServerTts: (text) => {
        unlockAudio();
        enqueueTtsSentence(text, 'server');
      },
    });
  }

  function init() {
    const aud = audioApi();
    if (aud && typeof aud.init === 'function') {
      aud.init();
    }

    const api = faceApi();
    if (api && typeof api.init === 'function' && els.faceContainer) {
      api.init(els.faceContainer);
    }

    if (isMiniPet) {
      syncTtsUI();
      window.addEventListener('storage', syncPreferencesFromStorage);
      bindMiniPetEvents();
      initPetSync();
      return;
    }

    buildExpressionChips();
    syncTtsUI();
    syncCaptionVisibilityUI();
    syncPomodoroUI();
    refreshVoices();
    window.addEventListener('storage', syncPreferencesFromStorage);
    bindEvents();
    initPetSync();
    initGamepad();
    initDiagnostics();
    connectWebSocket();
    fetchLupinLanguage();
    fetchMemory();
    fetchMacStatus();
    fetchClientInfo();
    renderDock();
    syncDockCorner();
    tickClocks();

    window.setInterval(tickClocks, 1000);
    window.setInterval(fetchMacStatus, 10000);
    window.setInterval(syncFaceBadges, 1000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
