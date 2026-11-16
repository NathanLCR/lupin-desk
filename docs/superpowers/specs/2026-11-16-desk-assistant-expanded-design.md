# Desk Assistant (Pet Vivo + Copiloto LLM + Dock & Stream Deck Mac) — Especificação Expandida

**Data:** 2026-11-16  
**Workspace do projeto:** `/Users/nathanlucio/Desktop/desk-assistant`  
**Dispositivos alvo (nativos):** Anbernic RG406H (Android 13, 960×720, Gamepad completo, Wi-Fi / USB ADB), macOS (Apple Silicon `arm64`, com suporte a tela externa), e iPhone (iOS Safari / Home Screen PWA — testes finais no iPhone ficam para o dia seguinte).

---

## 1. Visão & Princípio Central ("90% Pet Vivo / 10% Produtividade sob Demanda")

O **Desk Assistant** é primariamente um **pet de mesa vivo** (inspirado em *Living.AI EMO*, *Anki Vector / Cozmo*, *LOOI*, *Stack-chan* e *RoboEyes*) que vive em tela cheia sobre fundo preto `#000000` e reage emocionalmente, emite sons procedurais e acompanha você no dia a dia.

Dentro desse pet habita um **copiloto LLM completo** com memória cognitiva, voz bidirecional, **Dock Viva do macOS**, **controle de Espaços/janelas** e um **Stream Deck de atalhos configuráveis** que resolve o problema real de usar Mac + tela externa com a Dock sempre escondida e sem precisar decorar atalhos de teclado.

---

## 2. O que já existe (Baseline da Fase 1 — Commit `8860da4`)

Já construído, testado (`13 passed`) e versionado em `main`:
- `app/config.py`: `Settings` (`BASE_DIR`, `.env`, `SecretRedactingFilter` nos logs).
- `app/memory.py`: `MemoryStore` em SQLite (`messages` janela deslizante de 10 mensagens + `user_facts` até 25 fatos extraídos via `[fact:...]` e heurísticas PT-BR).
- `app/llm.py`: `LLMClient` em streaming para `http://127.0.0.1:31415/v1` (`claude-haiku-4-5`), ignorando `delta.reasoning` e usando `TagStreamParser` para remover `[emotion:...]` / `[<emoção>]` e `[fact:...]`.
- `app/main.py`: FastAPI com `GET /`, `/health`, `/api/memory*`, `WS /ws` (`typing`, `text`, `clear_history`).
- `static/face.css` & `static/face.js`: `window.EmoFace` SVG com 5 estados (`idle`, `listening`, `thinking`, `speaking`, `error`) e 10 emoções (`neutral`, `happy`, `excited`, `curious`, `skeptical`, `surprised`, `sad`, `wink`, `love`, `sleepy`).
- `static/index.html`, `static/style.css`, `static/app.js`: HUD auto-ocultável, gaveta de Memória, testador de Expressões, legenda em streaming e TTS inicial via `window.speechSynthesis`.

---

## 3. Arquitetura Expandida (6 Pilares)

### Pilar 1 — Rosto Pet Vivo & Áudio Procedural (`static/face.js`, `static/audio_synth.js`)
1. **Sintetizador Procedural via Web Audio API (`window.EmoAudio`)** — 0 KB de arquivos MP3:
   - Oscilador FM + *pitch glides* exponenciais para gerar vocabulário emocional estilo *Vector/Cozmo*:
     - `happy` / `excited`: arpejos curtos ascendentes.
     - `curious`: *chirp* subindo de frequência (`450Hz -> 950Hz`).
     - `sad` / `sleepy`: *glide* descendente suave / suspiro filtrado.
     - `pet` / `love`: ronronar (*purr*) grave (`~60Hz`) com LFO suave durante carinho.
     - `error` / `alert`: dois bips metálicos curtos.
   - Botão/toggle na HUD para ativar/silenciar os sons do pet independentemente da voz TTS.
   - Sincroniza micro-pulsos nos olhos com `AudioContext.currentTime`.
2. **Vida Procedural e Física nos Olhos (`pycozmo` + `RoboEyes` + `EMO`)**:
   - **Squash-and-stretch** preservando área aproximada (`scaleX * scaleY ≈ 1`) em piscadas, sustos e transições rápidas.
   - **Curiosidade direcional**: quando `|lookX| > 0.6`, aumenta levemente `scaleY` do olho externo.
   - **Mini-eventos autônomos em `idle`** (a cada 25–45s antes de entrar em `sleepy` aos 90s): caçar um "inseto virtual" com `lookAt` na tela, bocejo rápido, espiar o relógio no canto.
   - **One-shots e emoções extras**: `angry` (`\ /` em âmbar-vermelho), `dizzy` / `confused`, `anim_laugh`, `anim_confused`, gotinha de suor SVG (`setSweat`).
   - **Toque direto no rosto (`EmoFace.reactToTouch(kind, nx, ny)`)**:
     - *Tap / Poke*: olho atingido pisca/semicerra e olha para o ponto tocado; múltiplos toques rápidos em sequência disparam `skeptical` ou `angry` brincalhão.
     - *Carinho / Arraste (`pet`)*: `lookAt` segue o dedo + expressão `love`/`happy` + *purr* no `EmoAudio` + aumento gradual de afinidade.
     - *Toque durante `speaking`*: dispara **barge-in** (`interrupt`).
   - **Acessórios & Overlays (`setAccessory`, `setWeather`)**:
     - Acessórios SVG sobre `#emo-face-head`: `sunglasses`, `headphones` (quando música está tocando), `pomodoro` (óculos de estudo durante foco), `blush`.
     - Camada `<canvas>` leve para partículas de clima, corações, `Zzz`, vapor de raiva e barras reativas de música/voz.

### Pilar 2 — Sistema Completo de Atalhos Configuráveis + Controle do Mac (`app/shortcuts.py`, `app/mac_control.py`)
Projetado para resolver o uso do Mac com **tela externa** e **Dock sempre escondida**, permitindo acionar tudo por **toque**, **controles físicos do RG406H** ou **voz/texto pelo agente LLM**.

1. **Banco de Atalhos Configuráveis no SQLite (tabela `shortcuts`)**:
   - Campos:
     - `id` (slug único ou inteiro auto-incremento + `slug` legível, ex. `find_replace`, `mission_control`)
     - `title` (ex.: `"Pesquisar e Substituir"`)
     - `icon` (emoji ou ícone SVG curto, ex.: `"🔄"`)
     - `category` (`"spaces"` | `"apps"` | `"capture"` | `"editing"` | `"media"` | `"custom"`)
     - `action_type` (`"keystroke"` | `"app_activate"` | `"mac_command"` | `"agent_prompt"`)
     - `payload` (JSON):
       - `keystroke`: `{"keys": "cmd+opt+f"}` (executado via `osascript` `System Events` usando `argv` em lista Python, **nunca** shell string)
       - `app_activate`: `{"app": "Google Chrome"}` (`open -a` / `osascript activate`)
       - `mac_command`: comandos seguros pré-definidos (`mission_control`, `app_expose`, `space_left`, `space_right`, `screenshot_clipboard`, `screenshot_file`, `screenshot_full`, `play_pause`, `next_track`, `prev_track`, `volume_up`, `volume_down`, `volume_mute`, `lock_screen`, `toggle_dock`, `pomodoro_start`)
       - `agent_prompt`: `{"prompt": "..."}` (envia um prompt rápido direto para o agente)
     - `voice_triggers` (string separada por vírgula, ex.: `"pesquisar e substituir, substituir, find and replace"`)
     - `color` (cor do tile no Deck, ex. `"cyan"`, `"amber"`, `"violet"`, `"emerald"`, `"rose"`)
     - `pinned_on_deck` (bool)
     - `sort_order` (int)
     - `is_default` (bool)
2. **Catálogo Padrão Pré-Mapeado (Seed Automático)**:
   - **Espaços & Janelas**:
     - `Mission Control` (`mac_command: mission_control`)
     - `Exposé do App` (`mac_command: app_expose`)
     - `Espaço ⬅️` (`keystroke: ctrl+left`)
     - `Espaço ➡️` (`keystroke: ctrl+right`)
     - `Trocar Janela do App` (`keystroke: cmd+grave`)
     - `Alternar App` (`keystroke: cmd+tab`)
     - `Tela Cheia Janela` (`keystroke: ctrl+cmd+f`)
     - `Mostrar/Ocultar Dock` (`keystroke: opt+cmd+d`)
   - **Captura / Prints**:
     - `Print Seleção → Clipboard` (`keystroke: cmd+ctrl+shift+4`)
     - `Print Seleção → Arquivo` (`mac_command: screenshot_area_file` via `screencapture -i`)
     - `Print Tela Inteira` (`keystroke: cmd+shift+3`)
   - **Edição & Busca ("Sem Decorar")**:
     - `Pesquisar` (`keystroke: cmd+f`)
     - `Pesquisar e Substituir` (`keystroke: cmd+opt+f`)
     - `Colar Sem Formatação` (`keystroke: opt+cmd+shift+v`)
     - `Desfazer` (`keystroke: cmd+z`)
     - `Refazer` (`keystroke: cmd+shift+z`)
   - **Mídia & Sistema**:
     - `Play / Pause`, `Próxima Faixa`, `Volume +`, `Volume -`, `Mudo`, `Bloquear Tela` (`ctrl+cmd+q`), `Pomodoro 25m`.
3. **Dock Viva do Mac (`GET /api/mac/apps`, `POST /api/mac/apps/activate`, `GET /api/mac/status`)**:
   - Lista em tempo real os apps abertos (`System Events` -> processos não-background, incluindo janela/foco atual) + lista de apps favoritos fixados para abrir/trazer para frente com 1 toque ou pelo RG406H, resolvendo a Dock escondida em tela única ou tela externa.
   - Lê estado do Mac em cache leve (mídia tocando via `osascript` Spotify/Music, volume atual, bateria/energia, app ativo no momento).
   - **Segurança obrigatória**: toda execução usa `subprocess.run(argv_list)` sem `shell=True`, com whitelist estrita de teclas modificadoras (`cmd`, `ctrl`, `opt`, `shift`), códigos de tecla validados e nomes de apps sanitizados. Caso a permissão de Acessibilidade do macOS ainda esteja desligada para keystrokes, retorna erro amigável indicando exatamente `Ajustes do Sistema → Privacidade e Segurança → Acessibilidade` (sem quebrar o resto do app).
4. **Configuração, Edição, Troca e Criação de Atalhos na UI ("⚙️ Configurar Atalhos")**:
   - API REST completa:
     - `GET /api/shortcuts`
     - `POST /api/shortcuts`
     - `PUT /api/shortcuts/{id}`
     - `DELETE /api/shortcuts/{id}`
     - `POST /api/shortcuts/{id}/run`
     - `POST /api/shortcuts/reorder`
     - `POST /api/shortcuts/reset-defaults`
   - UI acessível no Mac, Android (RG406H) e iPhone:
     - Botão **➕ Novo Atalho**, botão **✏️ Editar / Trocar** em cada tile, botão **🗑️ Remover** e **↺ Restaurar Padrões**.
     - **Gravador de Teclas ao Vivo** no navegador (no Mac basta pressionar a combinação no teclado físico, ex. `Cmd+Option+F`, que preenche `cmd+opt+f` automaticamente; no celular/RG406H há construtor por botões de modificadores `⌘ Cmd`, `⌥ Opt`, `⌃ Ctrl`, `⇧ Shift` + tecla!).
5. **Mapeamento Dinâmico para dentro do Agente LLM (`app/llm.py`)**:
   - A cada turno de conversa, `build_system_prompt()` recebe o resumo compacto dos atalhos ativos no banco (`[id] título (gatilhos)` + apps abertos no momento).
   - O LLM pode disparar ações embutindo tags invisíveis no stream (parseadas pelo `TagStreamParser`, nunca mostradas ou lidas pelo TTS):
     - `[action:shortcut:<id>]` (executa qualquer atalho cadastrado, inclusive os que você criou/editou!)
     - `[action:app:<nome_do_app>]` (foca/abre um app no Mac)
     - `[action:pomodoro:start|stop]`
   - Exemplo: você fala *"Tira um print de seleção pro clipboard"* ou *"Abre o pesquisar e substituir"* ou *"Vai pro espaço da direita"* -> o `TagStreamParser` detecta `[action:shortcut:find_replace]`, executa imediatamente no Mac, notifica o frontend (`{"type": "action_executed", ...}`) e o pet responde com expressão `happy` / `wink`.
   - Adicionalmente, suportar **aprovação explícita** (`tool_approval_request` via WS) caso um atalho marcado como sensível exija confirmação, ou execução direta imediata para atalhos configurados pelo usuário.

### Pilar 3 — Cérebro Cognitivo & Personalidade Viva (`app/memory.py`)
Evolução do SQLite atual mantendo o contexto sempre enxuto:
1. **Tabela `user_facts` aprimorada**:
   - Novas colunas via migração segura (`ALTER TABLE` idempotente): `pinned INTEGER DEFAULT 0`, `importance INTEGER DEFAULT 5`, `access_count INTEGER DEFAULT 1`, `last_accessed TEXT`, `superseded_by INTEGER`.
   - **Core Memory (`pinned=1`)**: identidade/preferências centrais nunca são removidas pelo limite `max_user_facts`.
   - **Decay temporal + FTS5**: ranqueamento de fatos não-fixados por `importance * recency_decay` + busca por palavras-chave relevantes ao turno atual (`FTS5` do SQLite) para manter o prompt abaixo de 1200 chars mesmo com centenas de fatos aprendidos.
   - **Resolução de contradições & Sleep-Time Consolidation**: em repouso (`idle` após X minutos), consolida fatos duplicados/contraditórios sem travar nenhuma resposta.
2. **Tabela `rolling_state(id=1, summary, updated_at)`**:
   - Quando mensagens antigas saem da janela curta (`MAX_SHORT_TERM_MESSAGES=10`), gera/atualiza um resumo conciso (~120–150 palavras) em background para nunca haver amnésia abrupta.
3. **Âncora Temporal + Regra "Show, Don't Tell"**:
   - Injeta no system prompt apenas período do dia (`manhã`, `tarde`, `noite`, `madrugada`) e tempo desde a última interação, instruindo o agente a usar fatos do usuário como conhecimento implícito natural sem recitá-los roboticamente.
4. **Máquina de Estado Emocional do Pet (`companion_state`)**:
   - Persiste no SQLite: `energy (0..100)`, `affinity (0..100)`, `mood` (`pleasure`, `arousal` em `-1..1`), `last_interaction_at`.
   - Decai suavemente com o tempo; sobe com conversa e carinhos (`pet`); injeta apenas 1 linha compacta de tom/energia no prompt (sem jamais alterar a precisão factual/técnica das respostas).

### Pilar 4 — Voz Completa, Baixa Latência & Barge-in (`app/stt.py`, `app/tts.py`, `app/llm.py`)
1. **Streaming Frase-a-Frase + Barge-in Determinístico**:
   - `TagStreamParser` emite `{"type": "sentence", "text": "..."}` assim que fecha `.`, `!` ou `?` para iniciar a fala imediatamente antes de o LLM terminar a resposta inteira.
   - `{"type": "interrupt"}` via WebSocket cancela na hora a `asyncio.Task` do LLM/TTS em voo e limpa a fila de áudio no cliente.
2. **STT Local (`app/stt.py`)**:
   - Recebe áudio do Push-to-Talk via WebSocket (`audio_start` / chunks binários ou base64 / `audio_end`) e transcreve localmente no Mac (usando `faster-whisper` / `mlx-whisper`, com decodificação in-process sem exigir `ffmpeg` externo se possível, ou `afconvert`/PyAV).
   - Retorna `{"type": "transcript", "text": "..."}` antes de chamar o LLM, exibindo o que foi entendido na legenda.
3. **TTS Híbrido Multiplataforma (Mac + Android + iPhone)**:
   - **Modo Browser (`speechSynthesis`)**: padrão leve e instantâneo quando disponível.
   - **Modo Servidor Mac (`POST /api/tts` ou stream no `/ws`)**: fallback e opção de maior qualidade usando `say` + `afconvert` nativo do macOS (100% offline, zero dependências) ou `edge-tts` / `Kokoro-82M` quando instalado — **fundamental para o iPhone Safari e para garantir voz PT-BR consistente no RG406H**.

### Pilar 5 — Experiência Nativa em Android (RG406H), Mac e iPhone (`static/`)
1. **Anbernic RG406H (Android 13, 960×720, Wi-Fi / USB ADB)**:
   - Layout nativo 4:3 (`960×720`) sem barras sobrando.
   - **Gamepad API (`static/gamepad.js`)**:
     - Segurar **`L2` (`buttons[6]`) ou `R2` (`buttons[7]`, `value > 0.35`)**: **Push-to-Talk** (com feedback háptico `navigator.vibrate(18)`).
     - **Analógico Esquerdo (`axes[0]`, `axes[1]`, deadzone `0.15`)**: move `EmoFace.lookAt(x, y)`.
     - **`D-Pad`**: alterna modo ou navega pelas células da Dock Viva / Stream Deck.
     - **`A`**: aciona o atalho/app selecionado (ou foca chat no modo Pet).
     - **`B`**: **Barge-in** (para a fala na hora) / volta / fecha modais.
     - **`L1` / `R1`**: troca entre os modos de tela (`Pet` ↔ `Dock & Atalhos` ↔ `Smart Display` ↔ `Diagnóstico`).
     - **`X` / `Y` / `Start` / `Select`**: alterna legenda, expressões, abre Memória / Config de Atalhos / Tela Cheia.
   - **WakeLock** + conexão via túnel USB (`adb reverse tcp:8000 tcp:8000` em `http://localhost:8000`) **e** suporte a **HTTPS na LAN** (`certs/` + script gerador com `mkcert` ou `openssl` na porta `8443` + `README.md` passo a passo).
2. **Mac (Browser Desktop / App Instalado PWA)**:
   - Suporte a atalho de teclado global na página (ex. segurar `Espaço` quando fora do input para Push-to-Talk, `Esc` para barge-in), gravador de teclas no modal de atalhos, hover HUD.
3. **iPhone (iOS Safari / "Adicionar à Tela de Início" — testar amanhã)**:
   - `static/manifest.json` (`display: standalone`, `background_color: #000000`, `theme_color: #000000`, ícones SVG/PNG).
   - Meta tags iOS (`apple-mobile-web-app-capable`, `apple-mobile-web-app-status-bar-style: black-translucent`, `viewport-fit=cover`) + CSS usando `100dvh` e `env(safe-area-inset-top/bottom/left/right)` para respeitar Dynamic Island / notch e barra home em retrato e paisagem.
   - Áudio destravado no primeiro toque (`AudioContext.resume()` + `<audio>` server-TTS para evitar que o `speechSynthesis` do iOS Safari trave em segundo plano).
   - Botão explícito opcional para `DeviceMotionEvent.requestPermission()` (exigido pelo iOS 13+ para usar giroscópio/sacudir).

### Pilar 6 — 4 Modos de Tela Integrados
1. **Modo Pet Vivo (Padrão)**: 100% rosto vivo `#000000`, sons procedurais, toques/carinhos, relógio OLED discreto no canto e chip opcional de Pomodoro.
2. **Modo Dock & Atalhos do Mac**: olhos vivos reduzidos na faixa superior reagindo a cada ação + **Dock Viva (apps abertos/favoritos)** + **Grade de Atalhos Configuráveis** filtrável por categoria + botão **⚙️ Configurar Atalhos**.
3. **Modo Smart Display Ambiente**: relógio/data grandes, Pomodoro interativo, música tocando no Mac (*Now Playing*), clima (`Open-Meteo` sem API key) e telemetria básica do Mac (CPU/RAM/Bateria/modelo ativo) com olhos do pet acompanhando no canto.
4. **Estúdio de Diagnóstico (Áudio, Voz, Gamepad & Sensores)**:
   - Valida `isSecureContext` (HTTPS / `localhost`).
   - Testa microfone (`enumerateDevices`), barra de nível em tempo real e **teste de loopback** (*"Gravar 3s e reproduzir"*), com documentação de fallback mic USB-C / Bluetooth no `README.md`.
   - Lista vozes TTS (navegador + servidor Mac) com botão de teste.
   - Inspetor ao vivo do **Gamepad do RG406H** (mostra qual botão/eixo está sendo apertado) e leitura de **Giroscópio/Acelerômetro**.

---

## 4. Regras de Execução & Segurança
- **Zero segredos no Git**: `.env`, `certs/`, `data/*.db*`, `.venv/` sempre no `.gitignore`.
- **Menor privilégio**: servidor escuta apenas na LAN/localhost; atalhos de teclado e apps no Mac executam exclusivamente via `argv` arrays (nunca `shell=True`) com validação estrita de teclas/comandos e sem execução arbitrária de shell enviada pelo cliente.
- **Não tocar em `/Users/nathanlucio/Desktop/nathan-os-app`** nem `/Users/nathanlucio/Desktop/Cowork`. Todo trabalho acontece exclusivamente em `/Users/nathanlucio/Desktop/desk-assistant`.
- **Idioma**: código limpo, comentários, UI e `README.md` em português do Brasil (PT-BR).
