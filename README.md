# Desk Assistant (Pet Vivo + Copiloto LLM + Dock & Stream Deck Mac)

Assistente de mesa carismático estilo **EMO / Vector / Cozmo** em tela cheia sobre fundo preto `#000000`, projetado nativamente para **Anbernic RG406H** (Android 13, `960×720`, Gamepad API), **macOS** (Desktop / tela externa) e **iPhone** (iOS Safari / PWA).

Combina um **pet de mesa vivo** (rosto SVG + partículas em Canvas + áudio procedural 100% Web Audio API), **copiloto LLM com memória cognitiva em SQLite**, **voz bidirecional com barge-in**, **Dock Viva do macOS** e um **Stream Deck de atalhos configuráveis** acionável por toque, controle físico ou voz.

---

## Arquitetura do Projeto

### Backend (`app/`)
- **`app/main.py`**: servidor FastAPI com canal WebSocket concorrente (`/ws`), endpoints REST de memória (`/api/memory*`), Stream Deck (`/api/shortcuts*`), Dock Viva & telemetria do Mac (`/api/mac/*`, `/api/weather`), voz (`/api/tts`, `/api/tts/voices`, `/api/stt`), diagnóstico (`/api/diagnostics`), saúde (`/health`) e manifesto PWA (`/manifest.json`).
- **`app/llm.py`**: cliente assíncrono em streaming (`/chat/completions`) com 12 emoções suportadas (`neutral`, `happy`, `excited`, `curious`, `skeptical`, `surprised`, `sad`, `wink`, `love`, `sleepy`, `angry`, `dizzy`). O `TagStreamParser` remove tags `[emotion:...]`, `[fact:...]`, `[action:shortcut:...]`, `[action:app:...]` e `[action:pomodoro:...]`, ignora `delta.reasoning` e emite eventos incrementais `sentence` para TTS frase-a-frase de baixa latência.
- **`app/memory.py`**: memória cognitiva persistente em SQLite (`WAL`):
  - **Curto Prazo (`messages`)**: janela deslizante configurável (`MAX_SHORT_TERM_MESSAGES=10`).
  - **Resumo Contínuo (`rolling_state`)**: resumo conciso de contexto quando mensagens antigas saem da janela.
  - **Longo Prazo (`user_facts`)**: fatos com `pinned` (Core Memory protegida), `importance`, decaimento por recência, busca `FTS5` e consolidação (`consolidate_facts()`), respeitando o orçamento de prompt (`1200` chars) e regra *Show, Don't Tell*.
  - **Estado Emocional (`companion_state`)**: `pleasure`, `arousal`, `energy` e `affinity` (sobe com conversas e carinhos `pet`, decai suavemente ao longo do tempo).
- **`app/shortcuts.py`**: `ShortcutStore` em SQLite com seed automático de 24 atalhos padrão (`spaces`, `capture`, `editing`, `apps`, `media`, `custom`), CRUD completo, reordenação, busca por gatilho de voz e `build_agent_shortcuts_prompt()` para mapear dinamicamente os atalhos e apps abertos para o LLM.
- **`app/mac_control.py`**: `MacController` com execução estrita via `subprocess.run(..., shell=False)` em listas `argv`:
  - Whitelist de modificadores (`cmd`, `opt`, `ctrl`, `shift`), teclas seguras e comandos (`VALID_MAC_COMMANDS`).
  - Validação estrita de nomes de apps (`_APP_NAME_RE`, bloqueando `..` e flags).
  - Diagnóstico explícito de permissão de Acessibilidade do macOS.
  - Dock Viva (`list_running_apps`), telemetria leve com cache de 3s (`get_mac_status`: app ativo, bateria, volume, Spotify/Music *Now Playing*) e clima via Open-Meteo com cache de 15 min (`get_weather`).
- **`app/stt.py`**: `LocalSTT` com carregamento sob demanda (*lazy-load*) para `mlx-whisper` ou `faster-whisper`, conversão de áudio via `PyAV` (`av`) ou `/usr/bin/afconvert` (`shell=False`) e fallback limpo quando nenhum motor Whisper estiver instalado.
- **`app/tts.py`**: `ServerTTS` 100% offline no macOS via `/usr/bin/say` + `/usr/bin/afconvert` (`shell=False`), gerando `.m4a` (`audio/mp4`) ou `.wav` (`audio/wav`) com listagem de vozes priorizando `pt_BR` (`Luciana`).
- **`app/providers.py`**: catálogo de provedores LLM compatíveis com OpenAI (`local_proxy`, `ollama`, `openai`, `openrouter`, `gemini`, `custom`), persistência da seleção em `app_meta` sem gravar segredos no SQLite e descoberta dinâmica de modelos.
- **`app/skills.py`**: pacotes de habilidades modulares injetáveis no *system prompt* (`focus_coach`, `daily_briefing`, `coding_buddy`, `wellness_breaks`, `playful_companion`) e truques físicos/audiovisuais do pet (`[action:pet:<id>]`).
- **`app/cowork.py`**: ponte confinada ao workspace `COWORK_WORKSPACE_PATH` (`state/*.yaml` com preview de diff + `.backup/` e `ActionsRunner` com `shell=False` e aprovação para ações `write`/`external`).
- **`app/today.py`**: motor do resumo diário **Today** com validação anti-alucinação, fallback determinístico e rastreamento de *First Wake*.
- **`app/config.py`**: carregamento de `.env` (`Settings`) e `SecretRedactingFilter` nos logs para impedir qualquer vazamento de `LLM_API_KEY` ou tokens `freellmapi-*` / `sk-*`.

### Frontend (`static/`)
- **`static/audio_synth.js` (`window.EmoAudio`)**: sintetizador procedural via Web Audio API (0 KB de MP3/WAV) para `chirp(emotion)`, `purr(active)` (~60Hz com LFO), `click()`, `alert()`, `wake()` e `getPulseLevel()`.
- **`static/face.js` & `static/face.css` (`window.EmoFace`)**: rosto SVG em 60fps + camada `<canvas class="emo-particles-canvas">` com física *squash-and-stretch*, curiosidade direcional (`|lookX| > 0.6`), micro-eventos autônomos em `idle` (inseto virtual, bocejo, espiar canto) antes de `sleepy` aos 90s, toque direto `reactToTouch('poke' | 'pet', nx, ny)`, acessórios (`none`, `sunglasses`, `headphones`, `pomodoro`, `blush`), clima (`rain`, `snow`, `sun`), gotinha de suor (`setSweat`) e modo compacto (`.emo-compact`).
- **`static/gamepad.js` (`window.DeskGamepad`)**: suporte nativo ao controle do **Anbernic RG406H** via Gamepad API com *haptics* (`navigator.vibrate`) e snapshot ao vivo.
- **`static/skills.js`**: gerenciamento visual de Skills/Truques do Lupin e integração com Cowork/Today/Actions.
- **Protocolo Brain↔Body**: o WebSocket `/ws` é o único canal de um Body; veja [`docs/protocolo-cerebro-corpo.md`](docs/protocolo-cerebro-corpo.md).
- **`static/diagnostics.js` (`window.DeskDiagnostics`)**: Estúdio de Diagnóstico de `isSecureContext`, microfones, loopback de 3s, vozes TTS, Gamepad e sensores.
- **`static/app.js`, `static/index.html`, `static/style.css`, `static/manifest.json`, `static/icon.svg`**: interface responsiva multiplataforma (`960×720`, desktop Mac e iPhone `100dvh` + `safe-area-inset-*`).

### Shell Desktop macOS (`electron/`)
- **`electron/main.js` & `electron/preload.js`**: shell Electron com ícone na barra de menus (*Tray*), atalho global `Cmd+Shift+Space`, janela flutuante de mini-pet (`/?widget=minipet`), diálogos nativos de confirmação de escrita e reutilização automática do servidor local em `127.0.0.1:8000` (ou inicialização como *sidecar* quando necessário).
- **Mini-pet flutuante**: passe o ponteiro sobre Lupin ou use `Cmd+Shift+L` para mostrar e focar seus controles. Arraste pelo botão **Mover**, ou use as setas (`Shift` acelera). A posição é lembrada entre sessões e ajustada se um monitor for desconectado. **Painel** abre o dashboard; **Silenciar** alterna voz e sons nas duas janelas; **Ocultar** ou `Esc` esconde o pet. A barra aparece também ao navegar com `Tab`. A janela ignora cliques fora do pet e da barra, respeita movimento reduzido e não inicia consultas Cowork, clima ou uma conversa WebSocket própria.

### App Android Nativo (`android/` e `scripts/build_android_apk.py`)
- **`android/src/com/nathanlucio/deskassistant/MainActivity.java`**: invólucro nativo WebView em tela cheia imersiva (`sensorLandscape`, `FLAG_KEEP_SCREEN_ON`) para o **Anbernic RG406H**, com ponte `AndroidBridge`, detecção automática de túnel USB ADB (`127.0.0.1:8000`) com fallback para Wi-Fi HTTPS (`https://192.168.0.125:8443`), aceitação restrita de SSL local apenas em hosts privados (`isPrivateOrLocalHost`), liberação de `RESOURCE_AUDIO_CAPTURE` e preservação total dos eventos de Gamepad em `dispatchKeyEvent`.
- **`scripts/build_android_apk.py`**: pipeline em Python puro (`aapt2` → `javac --release 11` → `d8` → `zipalign` → `apksigner`) gerando `dist/desk-assistant-rg406h.apk`.

---

## Os Modos de Tela

Alterne pela barra superior ou pelos botões **`L1` / `R1`** no RG406H:

1. **🐾 Pet Vivo (Padrão)**: rosto em tela cheia `#000000`, sons procedurais, relógio OLED discreto no canto, chip de Pomodoro ativo e interação por toque:
   - **Tap (`poke`)**: o olho atingido semicerra e olha para o ponto; toques rápidos repetidos ativam `skeptical` e `angry` brincalhão.
   - **Arrastar (`pet`)**: carinho contínuo com olhos seguindo o dedo, partículas de coração, ronronar (`EmoAudio.purr`) e aumento de afinidade no SQLite.
   - **Tocar durante a fala**: dispara **barge-in** imediato.
2. **🎛️ Dock & Atalhos do Mac**: rosto compacto na faixa superior reagindo às ações + **Dock Viva do Mac** (apps abertos com destaque para o frontal + favoritos) + **Stream Deck de Atalhos** filtrável por categoria (`Todos`, `Espaços`, `Captura`, `Edição`, `Mídia`, `Apps`, `Custom`) + modal **⚙️ Configurar Atalhos** e captura rápida no Cowork.
3. **🖥️ Smart Display Ambiente**: relógio e data grandes, resumo **Today** do Cowork, timer **Pomodoro** (`25m` foco / `5m` pausa), *Now Playing* (Spotify / Apple Music com Play/Pause, Anterior, Próxima), clima via Open-Meteo e telemetria do Mac + barras de afinidade e energia do pet.
4. **✨ Skills & Truques**: ativação/desativação de pacotes de comportamento do copiloto e disparo de truques interativos do pet (navegável por toque, mouse ou `D-Pad` + `A`).
5. **🩺 Estúdio de Diagnóstico**: validação de contexto seguro (`isSecureContext`), seletor de provedor/modelo LLM, seletor de microfone + medidor em tempo real + gravação **Loopback 3s**, inspetor de vozes TTS (Browser vs Servidor Mac), inspetor ao vivo do Gamepad RG406H e leitura de giroscópio/acelerômetro (com botão de permissão para iOS 13+).
6. **🧠 Nathan OS (Shell Electron)**: aba dedicada para Cowork Today, proposta/aplicação de tarefas com diff, ações de `actions.yaml`.

---

## Stream Deck, Dock Viva & Comandos por Voz no Agente

### Gerenciar Atalhos na Interface
No modo **🎛️ Dock**, clique em **➕ Novo Atalho**, **✏️** no tile ou **⚙️ Configurar Atalhos**:
- **Tipos suportados**:
  - `keystroke`: combinação de teclas no Mac (ex.: `cmd+opt+f` para *Pesquisar e Substituir*).
  - `app_activate`: abrir ou trazer aplicativo para frente (ex.: `Google Chrome`).
  - `mac_command`: comandos seguros pré-mapeados (`mission_control`, `app_expose`, `space_left`, `space_right`, `screenshot_clipboard`, `screenshot_area_file`, `screenshot_full`, `play_pause`, `next_track`, `prev_track`, `volume_up`, `volume_down`, `volume_mute`, `toggle_dock`, `lock_screen`, `pomodoro_start`, `pomodoro_stop`).
  - `agent_prompt`: envia um prompt pré-definido direto para o assistente.
- **Gravador + Construtor de Teclas**:
  - No **Mac**: clique em **🎹 Gravar no Teclado** e pressione a combinação física (ex.: `Cmd + Option + F`).
  - No **RG406H / iPhone**: monte a combinação tocando nos modificadores `⌘ Cmd`, `⌥ Opt`, `⌃ Ctrl`, `⇧ Shift` + tecla.
- **Confirmação de Segurança**: marque *Pedir confirmação antes* em atalhos sensíveis para exigir aprovação explícita (`tool_approval_request`) antes da execução.

### Comandos por Voz / Texto no Copiloto
A cada turno, o catálogo atual do SQLite e os apps abertos são injetados no *system prompt*. Exemplos naturais:
- *"Pesquisar e substituir"* → dispara `[action:shortcut:find_replace]` (`cmd+opt+f`).
- *"Vai pro espaço da direita"* / *"Abre o Mission Control"* → aciona espaços/janelas sem precisar decorar atalhos.
- *"Tira um print de seleção pro clipboard"* → dispara `cmd+ctrl+shift+4`.
- *"Abre o Chrome"* / *"Traz o VS Code pra frente"* → dispara `[action:app:Google Chrome]`.
- *"Inicia um Pomodoro"* / *"Para o Pomodoro"* → dispara `[action:pomodoro:start|stop]`.

> **Importante (macOS Acessibilidade)**: para `keystroke` e `app_expose` funcionarem via `System Events`, conceda permissão de Acessibilidade ao terminal/processo que executa o Uvicorn em **Ajustes do Sistema → Privacidade e Segurança → Acessibilidade**.

---

## Controles no Anbernic RG406H (Gamepad API)

| Controle RG406H | Ação no Desk Assistant |
| :--- | :--- |
| **Analógico Esquerdo** | Move o olhar do pet (`EmoFace.lookAt`) |
| **Segurar `L2` ou `R2`** | **Push-to-Talk** (segurar grava, soltar envia áudio + vibração háptica) |
| **`L1` / `R1`** | Alterna entre os Modos `Pet` e `Dock` (dentro dos Ajustes, troca de seção). Deslizar rápido na tela ou `Alt`+setas fazem o mesmo |
| **`D-Pad`** | Navega pelos apps da Dock Viva e tiles do Stream Deck / Display |
| **`A`** | Executa o app/atalho selecionado  |
| **`B`** | **Barge-in** (interrompe fala/LLM na hora) ou fecha modal aberto |
| **`X`** | Mostra / oculta a legenda |
| **`Y`** | Alterna TTS entre **Browser** e **Servidor Mac (`/api/tts`)** |
| **`Select`** | Alterna Tela Cheia + WakeLock |
| **`Start`** | Abre/fecha os **Ajustes** (Voz e som, Cérebro, Memória, Skills, Dock, Diagnóstico) |

**Atalhos no teclado do Mac**: segurar **`Espaço`** (fora de campos de texto) ativa o **Push-to-Talk**; **`Esc`** dispara **barge-in** ou fecha modais.

---

## Configuração (`.env`)

Crie o arquivo local a partir do exemplo (nunca versione `.env`, `certs/`, `.venv/` ou `data/*.db*`):

```bash
cp .env.example .env
```

Principais variáveis:

```env
LLM_BASE_URL=http://127.0.0.1:31415/v1
LLM_API_KEY=sua-chave-aqui
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
```

---

## Como Rodar o Servidor (HTTP, Túnel ADB e HTTPS na LAN)

Certifique-se de que sua API LLM local está rodando (padrão `http://127.0.0.1:31415/v1`).

### 1. Subir em HTTP (Mac local e Túnel USB ADB no RG406H)

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

No Anbernic RG406H conectado via USB com depuração ADB:

```bash
adb reverse tcp:8000 tcp:8000
```

Acesse no Chrome do RG406H em `http://localhost:8000` (tratado como contexto seguro pelo navegador para liberar microfone e Gamepad).

### 2. Setup HTTPS na LAN (Wi-Fi no RG406H e iPhone)

Microfone (`getUserMedia`), sensores de movimento e instalação PWA pela rede Wi-Fi exigem **HTTPS** (`isSecureContext === true`). Gere os certificados locais em `certs/` usando `mkcert` (se instalado) ou fallback `openssl`:

```bash
.venv/bin/python scripts/setup_https.py
```

Suba o servidor com TLS na porta `8443`:

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8443 \
  --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem
```

*(Opcional para túnel USB em HTTPS: `adb reverse tcp:8443 tcp:8443`.)*

Acesse pelo IP exibido pelo script (ex.: `https://192.168.0.125:8443`). Ao usar certificado autoassinado no Chrome Android ou iOS Safari pela primeira vez, aceite o aviso de certificado local (ou instale a CA raiz do `mkcert`).

### 3. Voz Local (STT e TTS)
- **TTS do Servidor Mac (`/api/tts`)**: funciona nativamente no macOS via `/usr/bin/say` + `/usr/bin/afconvert` sem dependências extras. Recomendado no **iPhone Safari** e no **RG406H** em Ajustes › Voz e som › Origem da voz (Navegador ou Mac).
- **STT Local (`/api/stt` e Push-to-Talk)**: requer `faster-whisper` (ou `mlx-whisper` no Apple Silicon) instalado no `.venv`. Caso não esteja instalado, o servidor continua funcionando normalmente e informa a ausência do motor no `/api/diagnostics`. Para habilitar:

```bash
/Users/nathanlucio/Desktop/desk-assistant/.venv/bin/pip install faster-whisper
# ou no Apple Silicon:
# /Users/nathanlucio/Desktop/desk-assistant/.venv/bin/pip install mlx-whisper
```

---

## App Android Nativo para o Anbernic RG406H (`com.nathanlucio.deskassistant`)

Além do acesso direto pelo navegador, o projeto inclui um app Android nativo dedicado ao **Anbernic RG406H** (`minSdk 26`, `targetSdk 34`) que roda o Desk Assistant em tela cheia imersiva sem barras do navegador, mantém a tela sempre ligada (`FLAG_KEEP_SCREEN_ON`) e preserva 100% dos controles na Gamepad API.

### 1. Compilar o APK (`dist/desk-assistant-rg406h.apk`)
Requer **OpenJDK 17** e **Android SDK** (plataforma `android-34` + `build-tools`). O script localiza o toolchain automaticamente (incluindo `/opt/homebrew/opt/openjdk@17` e `/opt/homebrew/share/android-commandlinetools`), gera `certs/debug.keystore` se necessário, compila e valida a assinatura:

```bash
.venv/bin/python scripts/build_android_apk.py
```

### 2. Instalar no RG406H e Liberar Microfone (`RECORD_AUDIO`)
Com o Anbernic RG406H conectado via USB ADB:

```bash
adb install -r dist/desk-assistant-rg406h.apk
```

O app solicita a permissão `RECORD_AUDIO` na primeira abertura. Caso queira conceder previamente via ADB:

```bash
adb shell pm grant com.nathanlucio.deskassistant android.permission.RECORD_AUDIO
```

### 3. Alternar entre USB ADB e Wi-Fi LAN
Ao iniciar, o app testa rapidamente a porta local `127.0.0.1:8000` (800 ms): se o túnel `adb reverse tcp:8000 tcp:8000` estiver ativo, abre `http://localhost:8000`; caso contrário, usa automaticamente `https://192.168.0.125:8443` (aceitando certificado local autoassinado **apenas** em `localhost`/redes privadas RFC 1918).

Para trocar manualmente a qualquer momento:
- Toque no botão discreto **`⚙`** no canto superior direito (ele fica quase invisível após 3 segundos; toque para revelar e toque novamente para abrir o menu), **ou**
- Pressione **duas vezes o botão `Voltar`** do Android (dentro de 1,5 s).
- No menu **Servidor — Desk Assistant**, escolha entre **USB ADB (`http://localhost:8000`)**, **Wi-Fi HTTPS (`https://192.168.0.125:8443`)**, **URL Customizada...** ou **Recarregar Página**.

---

## Troubleshooting de Microfone & Fallback USB-C / Bluetooth

1. **Erro *"Microfone exige HTTPS ou localhost"* / `navigator.mediaDevices` indefinido**:
   - Você abriu `http://192.168.x.x:8000` pela rede Wi-Fi. Use `https://<IP_DO_MAC>:8443` ou o túnel USB `http://localhost:8000` via `adb reverse`.
2. **Permissão bloqueada no Android / RG406H**:
   - No Chrome do RG406H, toque no ícone de cadeado/configurações da barra de endereço → **Permissões → Microfone → Permitir**.
   - Se estiver via ADB, confirme a permissão do pacote Chrome no Android (`RECORD_AUDIO`).
3. **Como confirmar captação real (Estúdio de Diagnóstico)**:
   - Abra a aba **🩺 Diagnóstico** → card **🎙️ Microfone & Loopback**.
   - Clique em **↻ Listar**, escolha a entrada desejada e clique em **⏺️ Gravar 3s e reproduzir**.
4. **Fallback com Microfone USB-C ou Fone Bluetooth**:
   - Se o microfone interno do portátil estiver baixo ou com ruído, conecte um microfone/headset **USB-C** ou **Bluetooth** no RG406H (ou no Mac/iPhone), clique em **↻ Listar** no card **🎙️ Microfone & Loopback**, selecione o dispositivo na lista e valide no loopback de 3s. O botão **🎤 Segure para falar** usará automaticamente o microfone selecionado no Diagnóstico.
5. **Sem áudio de TTS no iPhone Safari**:
   - Toque uma vez na tela (ou no banner *Toque em qualquer lugar para ativar som e voz*) para destravar o `AudioContext` e o `<audio>` oculto.
   - Em Ajustes › Voz e som, mude a Origem da voz para **Mac** para reproduzir áudio `.m4a` gerado pelo Mac, evitando travamentos do `speechSynthesis` no iOS.
6. **Giroscópio/Acelerômetro não atualiza no iPhone**:
   - No modo **🩺 Diagnóstico**, clique em **📱 Ativar Sensores (iOS / Movimento)** para disparar `DeviceMotionEvent.requestPermission()`.

---

## Testes Automatizados

```bash
node --check static/*.js
.venv/bin/pytest tests -v
```

---

## Checklist de Validação

### Mac (Desktop / Tela Externa)
- [ ] Abrir `http://localhost:8000` e confirmar fundo `#000000`, status **Conectado** (verde) e sons procedurais ao trocar expressões ou tocar/arrastar no rosto (`poke` / `pet`).
- [ ] Segurar **`Espaço`** fora do campo de texto para Push-to-Talk (ou enviar texto) e testar **barge-in** com **`Esc`** ou tocando no rosto durante a fala.
- [ ] Abrir **🎛️ Dock**, verificar **Dock Viva do Mac**, acionar *Pesquisar e Substituir* (`cmd+opt+f`), criar um novo atalho com o gravador de teclas e testar pelo agente via chat (*"executa pesquisar e substituir"*).
- [ ] Abrir **🖥️ Display** e validar relógio, Pomodoro, *Now Playing*, clima e barras de afinidade/energia.
- [ ] Abrir **🩺 Diagnóstico**, validar `isSecureContext: OK`, loopback de 3s e botões **Testar Browser** / **Testar Servidor Mac**.

### Anbernic RG406H (Android 13, `960×720`)
- [ ] Validar acesso via túnel USB (`http://localhost:8000`) e via Wi-Fi HTTPS (`https://<IP>:8443`).
- [ ] Confirmar layout 4:3 sem corte nos 4 modos e texto legível.
- [ ] Testar Gamepad: analógico esquerdo move os olhos, `L1`/`R1` troca de modo, `D-Pad` + `A` navega e executa na Dock Viva / Stream Deck, `L2`/`R2` faz Push-to-Talk com vibração, `B` faz barge-in, `Y` alterna TTS Browser/Servidor Mac.
- [ ] Conferir no Estúdio de Diagnóstico que botões/eixos do RG406H acendem ao vivo e que o loopback de 3s grava e reproduz (interno ou USB-C/Bluetooth).

### iPhone (iOS Safari / PWA "Adicionar à Tela de Início")
- [ ] Abrir `https://<IP>:8443` no Safari e validar `safe-area-inset-*` em retrato e paisagem (sem sobreposição no notch/Dynamic Island ou barra home).
- [ ] Usar **Compartilhar → Adicionar à Tela de Início** e confirmar abertura em modo `standalone` (`manifest.json` + `icon.svg`).
- [ ] Tocar uma vez para destravar áudio, alternar para **🖥️ Mac TTS** e confirmar reprodução contínua em `.m4a`.
- [ ] No **🩺 Diagnóstico**, testar **📱 Ativar Sensores (iOS / Movimento)** e o loopback de microfone.
