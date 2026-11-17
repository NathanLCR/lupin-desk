# Desk Assistant (Live Pet + LLM Copilot + Mac Dock & Stream Deck)

A charismatic desk assistant in the style of **EMO / Vector / Cozmo**, full screen on a `#000000` background, designed natively for the **Anbernic RG406H** (Android 13, `960×720`, Gamepad API), **macOS** (desktop / external display) and **iPhone** (iOS Safari / PWA).

It combines a **live desk pet** (Lupin, a husky made of SVG layers, with 100% procedural Web Audio API sound), an **LLM copilot with cognitive memory in SQLite**, **two-way voice with barge-in**, the **Live Dock for macOS** and a **Stream Deck of configurable shortcuts** that can be triggered by touch, physical controller or voice.

---

## Project Architecture

### Backend (`app/`)
- **`app/main.py`**: FastAPI server with a concurrent WebSocket channel (`/ws`), REST endpoints for memory (`/api/memory*`), Stream Deck (`/api/shortcuts*`), Live Dock & Mac telemetry (`/api/mac/*`, `/api/weather`), voice (`/api/tts`, `/api/tts/voices`, `/api/stt`), diagnostics (`/api/diagnostics`), health (`/health`) and the PWA manifest (`/manifest.json`).
- **`app/llm.py`**: asynchronous streaming client (`/chat/completions`) with 12 supported emotions (`neutral`, `happy`, `excited`, `curious`, `skeptical`, `surprised`, `sad`, `wink`, `love`, `sleepy`, `angry`, `dizzy`). The `TagStreamParser` strips `[emotion:...]`, `[fact:...]`, `[action:shortcut:...]`, `[action:app:...]` and `[action:pomodoro:...]` tags, ignores `delta.reasoning` and emits incremental `sentence` events for low-latency, sentence-by-sentence TTS.
- **`app/memory.py`**: persistent cognitive memory in SQLite (`WAL`):
  - **Short term (`messages`)**: configurable sliding window (`MAX_SHORT_TERM_MESSAGES=10`).
  - **Rolling summary (`rolling_state`)**: concise context summary when old messages leave the window.
  - **Long term (`user_facts`)**: facts with `pinned` (protected Core Memory), `importance`, recency decay, `FTS5` search and consolidation (`consolidate_facts()`), respecting the prompt budget (`1200` chars) and the *Show, Don't Tell* rule.
  - **Emotional state (`companion_state`)**: `pleasure`, `arousal`, `energy` and `affinity` (rises with conversations and `pet` caresses, decays smoothly over time).
- **`app/shortcuts.py`**: `ShortcutStore` in SQLite with automatic seeding of 24 default shortcuts (`spaces`, `capture`, `editing`, `apps`, `media`, `custom`), full CRUD, reordering, lookup by voice trigger and `build_agent_shortcuts_prompt()` to dynamically map shortcuts and open apps for the LLM.
- **`app/mac_control.py`**: `MacController` with strict execution through `subprocess.run(..., shell=False)` using `argv` lists:
  - Whitelist of modifiers (`cmd`, `opt`, `ctrl`, `shift`), safe keys and commands (`VALID_MAC_COMMANDS`).
  - Strict app-name validation (`_APP_NAME_RE`, blocking `..` and flags).
  - Explicit diagnosis of the macOS Accessibility permission.
  - Live Dock (`list_running_apps`), lightweight telemetry with a 3s cache (`get_mac_status`: active app, battery, volume, Spotify/Music *Now Playing*) and weather through Open-Meteo with a 15 min cache (`get_weather`).
- **`app/stt.py`**: `LocalSTT` with on-demand loading (*lazy-load*) for `mlx-whisper` or `faster-whisper`, audio conversion through `PyAV` (`av`) or `/usr/bin/afconvert` (`shell=False`) and a clean fallback when no Whisper engine is installed.
- **`app/tts.py`**: `ServerTTS`, 100% offline on macOS through `/usr/bin/say` + `/usr/bin/afconvert` (`shell=False`), producing `.m4a` (`audio/mp4`) or `.wav` (`audio/wav`) with a voice list that prioritizes `pt_BR` (`Luciana`).
- **`app/providers.py`**: catalog of OpenAI-compatible LLM providers (`local_proxy`, `ollama`, `openai`, `openrouter`, `gemini`, `custom`), persistence of the selection in `app_meta` without writing secrets to SQLite, and dynamic model discovery.
- **`app/skills.py`**: modular skill packs injectable into the *system prompt* (`focus_coach`, `daily_briefing`, `coding_buddy`, `wellness_breaks`, `playful_companion`) and the pet's physical/audiovisual tricks (`[action:pet:<id>]`).
- **`app/cowork.py`**: bridge confined to the `COWORK_WORKSPACE_PATH` workspace (`state/*.yaml` with diff preview + `.backup/`, and an `ActionsRunner` with `shell=False` and approval for `write`/`external` actions).
- **`app/today.py`**: engine for the **Today** daily summary, with anti-hallucination validation, a deterministic fallback and *First Wake* tracking.
- **`app/config.py`**: `.env` loading (`Settings`) and a `SecretRedactingFilter` on the logs to prevent any leak of `LLM_API_KEY` or `freellmapi-*` / `sk-*` tokens.

### Frontend (`static/`)
- **`static/audio_synth.js` (`window.EmoAudio`)**: procedural synthesizer on the Web Audio API (0 KB of MP3/WAV) for `chirp(emotion)`, `purr(active)` (~60Hz with LFO), `click()`, `alert()`, `wake()` and `getPulseLevel()`.
- **`static/lupin.js` & `static/lupin.css` (`window.LupinFace`)**: a black-and-white drawn husky built from layers (chest, collar, ears, head, eyes, cyan dots, mouth) from the SVGs in `static/lupin/layers/`. The `static/lupin/expressions.json` table maps the 12 Expressions and the 5 States to one variant per layer and is the same one the ESP32 Body will use. Blinking and looking around belong to the Body; the collar wave lights up when Lupin speaks; `playTrick` uses the full body only for `dance`, `stretch` and `nap`. `reactToTouch('poke' | 'pet', nx, ny)`, `setAudioLevel`, `lookAt` and `setCompactMode` remain in the API.
- **`scripts/generate_lupin_png.py`**: generates the 480x320 PNGs (transparent, 8-bit indexed) for the ESP32 from the SVGs and fails if any exceeds 20 KB. Needs `pip install pillow resvg-py` (development only).
- **`static/gamepad.js` (`window.DeskGamepad`)**: native support for the **Anbernic RG406H** controller through the Gamepad API, with *haptics* (`navigator.vibrate`) and a live snapshot.
- **`static/skills.js`**: visual management of Lupin's Skills/Tricks and integration with Cowork/Today/Actions.
- **Brain↔Body protocol**: the `/ws` WebSocket is a Body's only channel; see [`docs/brain-body-protocol.md`](docs/brain-body-protocol.md).
- **`static/diagnostics.js` (`window.DeskDiagnostics`)**: Diagnostics Studio for `isSecureContext`, microphones, a 3s loopback, TTS voices, Gamepad and sensors.
- **`static/app.js`, `static/index.html`, `static/style.css`, `static/manifest.json`, `static/icon.svg`**: cross-platform responsive interface (`960×720`, Mac desktop and iPhone `100dvh` + `safe-area-inset-*`).

### macOS Desktop Shell (`electron/`)
- **`electron/main.js` & `electron/preload.js`**: Electron shell with a menu bar icon (*Tray*), the global shortcut `Cmd+Shift+Space`, a floating mini-pet window (`/?widget=minipet`), native write-confirmation dialogs and automatic reuse of the local server at `127.0.0.1:8000` (or starting it as a *sidecar* when needed).
- **Floating mini-pet**: hover over Lupin or use `Cmd+Shift+L` to show and focus his controls. Drag with the **Move** button, or use the arrow keys (`Shift` speeds it up). The position is remembered between sessions and adjusted if a monitor is disconnected. **Panel** opens the dashboard; **Mute** toggles voice and sounds in both windows; **Hide** or `Esc` hides the pet. The bar also appears when navigating with `Tab`. The window ignores clicks outside the pet and the bar, respects reduced motion and does not start Cowork queries, weather or a WebSocket conversation of its own.

### Native Android App (`android/` and `scripts/build_android_apk.py`)
- **`android/src/com/nathanlucio/deskassistant/MainActivity.java`**: native WebView wrapper in immersive full screen (`sensorLandscape`, `FLAG_KEEP_SCREEN_ON`) for the **Anbernic RG406H**, with an `AndroidBridge`, automatic detection of the ADB USB tunnel (`127.0.0.1:8000`) with a Wi-Fi HTTPS fallback (`https://192.168.0.125:8443`), restricted acceptance of local SSL only on private hosts (`isPrivateOrLocalHost`), granting of `RESOURCE_AUDIO_CAPTURE` and full preservation of Gamepad events in `dispatchKeyEvent`.
- **`scripts/build_android_apk.py`**: pure-Python pipeline (`aapt2` → `javac --release 11` → `d8` → `zipalign` → `apksigner`) that produces `dist/desk-assistant-rg406h.apk`.

---

## Screen Modes

Switch with the top bar or the **`L1` / `R1`** buttons on the RG406H:

1. **🐾 Live Pet (Default)**: full-screen `#000000` face, procedural sounds, a discreet OLED clock in the corner, an active Pomodoro chip and touch interaction:
   - **Tap (`poke`)**: the eye that was hit squints and looks at the spot; repeated quick taps trigger `skeptical` and a playful `angry`.
   - **Drag (`pet`)**: continuous petting with eyes following the finger, heart particles, purring (`EmoAudio.purr`) and an affinity increase in SQLite.
   - **Touch while speaking**: triggers an immediate **barge-in**.
2. **🎛️ Mac Dock & Shortcuts**: compact face in the top strip reacting to actions + **Mac Live Dock** (open apps with the frontmost highlighted + favorites) + **Shortcut Stream Deck** filterable by category (`All`, `Spaces`, `Capture`, `Editing`, `Media`, `Apps`, `Custom`) + the **⚙️ Configure Shortcuts** modal and quick capture into Cowork.
3. **🖥️ Ambient Smart Display**: large clock and date, the Cowork **Today** summary, a **Pomodoro** timer (`25m` focus / `5m` break), *Now Playing* (Spotify / Apple Music with Play/Pause, Previous, Next), weather through Open-Meteo and Mac telemetry + pet affinity and energy bars.
4. **✨ Skills & Tricks**: enable/disable the copilot's behavior packs and trigger the pet's interactive tricks (navigable by touch, mouse or `D-Pad` + `A`).
5. **🩺 Diagnostics Studio**: secure-context validation (`isSecureContext`), LLM provider/model selector, microphone selector + live meter + **3s loopback** recording, TTS voice inspector (Browser vs Mac Server), live RG406H Gamepad inspector and gyroscope/accelerometer readout (with a permission button for iOS 13+).
6. **🧠 Nathan OS (Electron Shell)**: dedicated tab for Cowork Today, proposing/applying tasks with a diff, and `actions.yaml` actions.

---

## Stream Deck, Live Dock & Voice Commands in the Agent

### Managing Shortcuts in the Interface
In **🎛️ Dock** mode, click **➕ New Shortcut**, **✏️** on a tile or **⚙️ Configure Shortcuts**:
- **Supported types**:
  - `keystroke`: a key combination on the Mac (e.g. `cmd+opt+f` for *Find and Replace*).
  - `app_activate`: open an app or bring it to the front (e.g. `Google Chrome`).
  - `mac_command`: pre-mapped safe commands (`mission_control`, `app_expose`, `space_left`, `space_right`, `screenshot_clipboard`, `screenshot_area_file`, `screenshot_full`, `play_pause`, `next_track`, `prev_track`, `volume_up`, `volume_down`, `volume_mute`, `toggle_dock`, `lock_screen`, `pomodoro_start`, `pomodoro_stop`).
  - `agent_prompt`: sends a predefined prompt straight to the assistant.
- **Recorder + Key Builder**:
  - On the **Mac**: click **🎹 Record on Keyboard** and press the physical combination (e.g. `Cmd + Option + F`).
  - On the **RG406H / iPhone**: build the combination by tapping the modifiers `⌘ Cmd`, `⌥ Opt`, `⌃ Ctrl`, `⇧ Shift` + a key.
- **Safety confirmation**: tick *Ask for confirmation first* on sensitive shortcuts to require explicit approval (`tool_approval_request`) before running.

### Voice / Text Commands in the Copilot
On every turn, the current SQLite catalog and the open apps are injected into the *system prompt*. Natural examples (Lupin is spoken to in Brazilian Portuguese):
- *"Pesquisar e substituir"* → fires `[action:shortcut:find_replace]` (`cmd+opt+f`).
- *"Vai pro espaço da direita"* / *"Abre o Mission Control"* → switches spaces/windows without memorizing shortcuts.
- *"Tira um print de seleção pro clipboard"* → fires `cmd+ctrl+shift+4`.
- *"Abre o Chrome"* / *"Traz o VS Code pra frente"* → fires `[action:app:Google Chrome]`.
- *"Inicia um Pomodoro"* / *"Para o Pomodoro"* → fires `[action:pomodoro:start|stop]`.

> **Important (macOS Accessibility)**: for `keystroke` and `app_expose` to work through `System Events`, grant Accessibility permission to the terminal/process that runs Uvicorn in **System Settings → Privacy & Security → Accessibility**.

---

## Controls on the Anbernic RG406H (Gamepad API)

| RG406H control | Action in Desk Assistant |
| :--- | :--- |
| **Left analog stick** | Moves the pet's gaze (`LupinFace.lookAt`) |
| **Hold `L2` or `R2`** | **Push-to-Talk** (hold to record, release to send audio + haptic vibration) |
| **`L1` / `R1`** | Switches between the `Pet` and `Dock` modes (inside Settings, switches section). A quick swipe on the screen or `Alt`+arrows do the same |
| **`D-Pad`** | Navigates the Live Dock apps and the Stream Deck / Display tiles |
| **`A`** | Runs the selected app/shortcut |
| **`B`** | **Barge-in** (interrupts speech/LLM immediately) or closes an open modal |
| **`X`** | Shows / hides the caption |
| **`Y`** | Toggles TTS between **Browser** and **Mac Server (`/api/tts`)** |
| **`Select`** | Toggles Full Screen + WakeLock |
| **`Start`** | Opens/closes **Settings** (Voice and sound, Brain, Memory, Skills, Dock, Diagnostics) |

**Mac keyboard shortcuts**: holding **`Space`** (outside text fields) activates **Push-to-Talk**; **`Esc`** triggers **barge-in** or closes modals.

---

## Configuration (`.env`)

Create the local file from the example (never commit `.env`, `certs/`, `.venv/` or `data/*.db*`):

```bash
cp .env.example .env
```

Main variables:

```env
LLM_BASE_URL=http://127.0.0.1:31415/v1
LLM_API_KEY=your-key-here
LLM_MODEL=claude-haiku-4-5

HOST=0.0.0.0
PORT=8000
HTTPS_PORT=8443
CERT_FILE=certs/cert.pem
KEY_FILE=certs/key.pem

MAX_SHORT_TERM_MESSAGES=10
MAX_USER_FACTS=25
DB_PATH=data/memory.db

STT_MODEL=base
STT_LANGUAGE=pt
TTS_VOICE=Luciana

WEATHER_CITY=São Paulo
WEATHER_LATITUDE=-23.5505
WEATHER_LONGITUDE=-46.6333

DESK_ACCESS_TOKEN=
DESK_DEV_NO_TOKEN=0
```

Devices on the network (RG406H/iPhone over Wi-Fi) need the access token on `/api` and `/ws`; from the Mac (`localhost`) and through the ADB tunnel, never. Without `DESK_ACCESS_TOKEN`, the server generates a token on every start and prints it in the terminal. During development, `DESK_DEV_NO_TOKEN=1` turns the token off (the server warns in the log on startup); leave it at `0` otherwise, because with it on, any device on the same network controls the assistant and the Mac. The variable was renamed from `DESK_DEV_SEM_TOKEN`; the old name is still accepted as a fallback when the new one is unset.

---

## Running the Server (HTTP, ADB Tunnel and LAN HTTPS)

Make sure your local LLM API is running (default `http://127.0.0.1:31415/v1`).

### 1. Start over HTTP (local Mac and ADB USB tunnel on the RG406H)

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

On the Anbernic RG406H connected over USB with ADB debugging:

```bash
adb reverse tcp:8000 tcp:8000
```

Open `http://localhost:8000` in the RG406H's Chrome (treated as a secure context by the browser, which unlocks microphone and Gamepad).

### 2. LAN HTTPS setup (Wi-Fi on the RG406H and iPhone)

Microphone (`getUserMedia`), motion sensors and PWA installation over Wi-Fi require **HTTPS** (`isSecureContext === true`). Generate the local certificates in `certs/` using `mkcert` (if installed) or the `openssl` fallback:

```bash
.venv/bin/python scripts/setup_https.py
```

Start the server with TLS on port `8443`:

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8443 \
  --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem
```

*(Optional for a USB tunnel over HTTPS: `adb reverse tcp:8443 tcp:8443`.)*

Open the IP printed by the script (e.g. `https://192.168.0.125:8443`). When using a self-signed certificate in Chrome Android or iOS Safari for the first time, accept the local certificate warning (or install the `mkcert` root CA).

### 3. Local Voice (STT and TTS)
- **Mac Server TTS (`/api/tts`)**: works natively on macOS through `/usr/bin/say` + `/usr/bin/afconvert` with no extra dependencies. Recommended on **iPhone Safari** and the **RG406H** in Settings › Voice and sound › Voice source (Browser or Mac).
- **Local STT (`/api/stt` and Push-to-Talk)**: requires `faster-whisper` (or `mlx-whisper` on Apple Silicon) installed in the `.venv`. If it is not installed, the server keeps working normally and reports the missing engine in `/api/diagnostics`. To enable it:

```bash
/Users/nathanlucio/Desktop/desk-assistant/.venv/bin/pip install faster-whisper
# or on Apple Silicon:
# /Users/nathanlucio/Desktop/desk-assistant/.venv/bin/pip install mlx-whisper
```

---

## Native Android App for the Anbernic RG406H (`com.nathanlucio.deskassistant`)

Besides direct browser access, the project includes a native Android app dedicated to the **Anbernic RG406H** (`minSdk 26`, `targetSdk 34`) that runs Desk Assistant in immersive full screen with no browser bars, keeps the screen always on (`FLAG_KEEP_SCREEN_ON`) and preserves 100% of the Gamepad API controls.

### 1. Build the APK (`dist/desk-assistant-rg406h.apk`)
Requires **OpenJDK 17** and the **Android SDK** (platform `android-34` + `build-tools`). The script locates the toolchain automatically (including `/opt/homebrew/opt/openjdk@17` and `/opt/homebrew/share/android-commandlinetools`), generates `certs/debug.keystore` if needed, builds and validates the signature:

```bash
.venv/bin/python scripts/build_android_apk.py
```

### 2. Install on the RG406H and Allow the Microphone (`RECORD_AUDIO`)
With the Anbernic RG406H connected over USB ADB:

```bash
adb install -r dist/desk-assistant-rg406h.apk
```

The app asks for the `RECORD_AUDIO` permission on first launch. To grant it beforehand through ADB:

```bash
adb shell pm grant com.nathanlucio.deskassistant android.permission.RECORD_AUDIO
```

### 3. Switching Between USB ADB and Wi-Fi LAN
On startup, the app quickly probes the local port `127.0.0.1:8000` (800 ms): if the `adb reverse tcp:8000 tcp:8000` tunnel is active, it opens `http://localhost:8000`; otherwise it automatically uses `https://192.168.0.125:8443` (accepting a self-signed local certificate **only** on `localhost`/RFC 1918 private networks).

To switch manually at any time:
- Tap the discreet **`⚙`** button in the top right corner (it becomes almost invisible after 3 seconds; tap to reveal it and tap again to open the menu), **or**
- Press the Android **`Back`** button **twice** (within 1.5 s).
- In the **Server — Desk Assistant** menu, choose **USB ADB (`http://localhost:8000`)**, **Wi-Fi HTTPS (`https://192.168.0.125:8443`)**, **Custom URL...** or **Reload Page**.

---

## Microphone Troubleshooting & USB-C / Bluetooth Fallback

1. **Error *"Microphone requires HTTPS or localhost"* / `navigator.mediaDevices` undefined**:
   - You opened `http://192.168.x.x:8000` over Wi-Fi. Use `https://<MAC_IP>:8443` or the USB tunnel `http://localhost:8000` through `adb reverse`.
2. **Permission blocked on Android / RG406H**:
   - In the RG406H's Chrome, tap the lock/settings icon in the address bar → **Permissions → Microphone → Allow**.
   - If using ADB, confirm the Chrome package's permission on Android (`RECORD_AUDIO`).
3. **How to confirm real capture (Diagnostics Studio)**:
   - Open the **🩺 Diagnostics** tab → **🎙️ Microphone & Loopback** card.
   - Click **↻ List**, choose the desired input and click **⏺️ Record 3s and play back**.
4. **Fallback with a USB-C microphone or Bluetooth headset**:
   - If the handheld's internal microphone is quiet or noisy, connect a **USB-C** or **Bluetooth** microphone/headset to the RG406H (or to the Mac/iPhone), click **↻ List** in the **🎙️ Microphone & Loopback** card, select the device from the list and validate it in the 3s loopback. The **🎤 Hold to talk** button will automatically use the microphone selected in Diagnostics.
5. **No TTS audio on iPhone Safari**:
   - Tap the screen once (or the *Tap anywhere to enable sound and voice* banner) to unlock the `AudioContext` and the hidden `<audio>`.
   - In Settings › Voice and sound, change the Voice source to **Mac** to play the `.m4a` audio generated by the Mac, avoiding `speechSynthesis` hangs on iOS.
6. **Gyroscope/Accelerometer not updating on iPhone**:
   - In **🩺 Diagnostics** mode, click **📱 Enable Sensors (iOS / Motion)** to trigger `DeviceMotionEvent.requestPermission()`.

---

## Automated Tests

```bash
node --check static/*.js
.venv/bin/pytest tests -v
```

---

## Validation Checklist

### Mac (Desktop / External Display)
- [ ] Open `http://localhost:8000` and confirm the `#000000` background, **Connected** status (green) and procedural sounds when changing expressions or tapping/dragging on the face (`poke` / `pet`).
- [ ] Hold **`Space`** outside the text field for Push-to-Talk (or send text) and test **barge-in** with **`Esc`** or by tapping the face during speech.
- [ ] Open **🎛️ Dock**, check the **Mac Live Dock**, trigger *Find and Replace* (`cmd+opt+f`), create a new shortcut with the key recorder and test it through the agent via chat (*"executa pesquisar e substituir"*).
- [ ] Open **🖥️ Display** and validate the clock, Pomodoro, *Now Playing*, weather and affinity/energy bars.
- [ ] Open **🩺 Diagnostics**, validate `isSecureContext: OK`, the 3s loopback and the **Test Browser** / **Test Mac Server** buttons.

### Anbernic RG406H (Android 13, `960×720`)
- [ ] Validate access through the USB tunnel (`http://localhost:8000`) and through Wi-Fi HTTPS (`https://<IP>:8443`).
- [ ] Confirm the 4:3 layout with no clipping in the 4 modes and legible text.
- [ ] Test the Gamepad: left analog stick moves the eyes, `L1`/`R1` switches mode, `D-Pad` + `A` navigates and runs on the Live Dock / Stream Deck, `L2`/`R2` does Push-to-Talk with vibration, `B` does barge-in, `Y` toggles TTS Browser/Mac Server.
- [ ] In the Diagnostics Studio, check that the RG406H buttons/axes light up live and that the 3s loopback records and plays back (internal or USB-C/Bluetooth).

### iPhone (iOS Safari / PWA "Add to Home Screen")
- [ ] Open `https://<IP>:8443` in Safari and validate `safe-area-inset-*` in portrait and landscape (no overlap with the notch/Dynamic Island or the home bar).
- [ ] Use **Share → Add to Home Screen** and confirm it opens in `standalone` mode (`manifest.json` + `icon.svg`).
- [ ] Tap once to unlock audio, switch to **🖥️ Mac TTS** and confirm continuous `.m4a` playback.
- [ ] In **🩺 Diagnostics**, test **📱 Enable Sensors (iOS / Motion)** and the microphone loopback.
