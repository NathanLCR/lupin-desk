# Plano de Implementação Overnight — Desk Assistant Expandido

**Spec de referência:** `docs/superpowers/specs/2026-11-16-desk-assistant-expanded-design.md`  
**Workspace:** `/Users/nathanlucio/Desktop/desk-assistant` (branch `main`, ou branches por fase conforme preferência)  
**Execução sugerida:** Swarm de agentes `gemini-4-hydrogen-high` com arquivos estritamente particionados (zero conflito de edição) e verificação completa com `pytest`, `node --check`, `TestClient` e testes ao vivo no servidor/RG406H.

---

## Ambiente já verificado no Mac
- Python 3.13 em `/Users/nathanlucio/Desktop/desk-assistant/.venv/bin/python` (e `uv` em `/Users/nathanlucio/.local/bin/uv`).
- LLM router local rodando em `http://127.0.0.1:31415/v1` (modelo padrão `claude-haiku-4-5`, com quirk conhecido de `delta.reasoning` — manter `max_tokens >= 500` e ignorar `delta.reasoning` no texto falado).
- Utilitários macOS disponíveis: `/usr/bin/osascript`, `/usr/bin/open`, `/usr/sbin/screencapture`, `/usr/bin/pbpaste`, `/usr/bin/pbcopy`, `/usr/bin/say`, `/usr/bin/afconvert`, `/opt/homebrew/bin/openssl`, `/opt/homebrew/bin/brew`.
- Observação: `ffmpeg` e `mkcert` não estão instalados por padrão. Para HTTPS na LAN, suportar `mkcert` (se instalado) **e** script Python/OpenSSL fallback que gera certificado autoassinado em `certs/` para `localhost`, `127.0.0.1` e o IP da LAN (`192.168.0.125`). Para STT, usar `faster-whisper` (via `PyAV`/`av` que decodifica WebM/Opus sem depender do binário `ffmpeg`, ou `afconvert` para WAV).
- Anbernic RG406H conectado via USB (`RG406H01980952`), com `adb reverse tcp:8000 tcp:8000` (e `8443` se HTTPS).

---

## Divisão de Tarefas para a Swarm (`gemini-4-hydrogen-high`)

Divida em **5 workers especialistas + 1 verifier + monitor** (sem colisão de arquivos):

### Worker 1: `face-designer`
**Arquivos exclusivos:**
- `static/audio_synth.js` (novo — módulo `window.EmoAudio` com Web Audio API procedural)
- `static/face.js` (evolução do atual)
- `static/face.css` (evolução do atual)

**Entregas:**
1. `EmoAudio`: sintetizador FM + envelopes para `chirp(emotion)`, `purr(active)`, `click()`, `alert()`, `wake()`, controle de `setMuted(bool)` e `unlock()`.
2. `EmoFace` expandido:
   - Squash-and-stretch (`scaleX * scaleY ≈ 1`), curiosidade lateral (`|x| > 0.6`), sacadas + micro-fixações.
   - Mini-eventos autônomos em `idle` (seguir inseto virtual, bocejo, olhar para o canto).
   - Novas emoções (`angry`, `dizzy`), acessórios (`setAccessory('none'|'sunglasses'|'headphones'|'pomodoro'|'blush')`), e camada `<canvas>` para partículas (`sweat`, vapor, corações, `Zzz`, notas musicais, clima `rain`/`snow`/`sun`).
   - `reactToTouch(kind, nx, ny)` (`poke` e `pet`) + micro-pulse sincronizado ao áudio.
   - Manter 100% compatibilidade retroativa com toda a API da Fase 1 (`init`, `setState`, `setEmotion`, `lookAt`, `blink`, `setAudioLevel`, `getState`, `getEmotion`, `getSupportedEmotions`, `getSupportedStates`).

### Worker 2: `memory`
**Arquivos exclusivos:**
- `app/config.py` (adicionar configurações de STT/TTS/HTTPS/MacControl/Atalhos mantendo redação de segredos)
- `app/memory.py` (evolução do SQLite)
- `tests/test_memory.py` (manter os 7 testes atuais + novos testes)

**Entregas:**
1. Migração idempotente do SQLite em `MemoryStore._initialize_db()`:
   - Colunas extras em `user_facts`: `pinned`, `importance`, `access_count`, `last_accessed`, `superseded_by`.
   - Tabela `rolling_state(id INTEGER PRIMARY KEY CHECK(id=1), summary TEXT, updated_at TEXT)`.
   - Tabela `companion_state(id INTEGER PRIMARY KEY CHECK(id=1), pleasure REAL, arousal REAL, energy REAL, affinity REAL, last_interaction_at TEXT)`.
   - Tabela `shortcuts(...)` com schema completo para o sistema de atalhos configuráveis (ou método helper de conexão compartilhado com `ShortcutStore`, mantendo cada classe em seu arquivo).
   - Tabela `pomodoro_timers` / lembretes se necessário.
2. Busca e contexto enxuto:
   - Ranking de fatos combinando `pinned`, `importance`, recência (`last_accessed`) e relevância por palavras-chave / `FTS5` (com fallback seguro se FTS5 não encontrar match).
   - `update_rolling_summary(text)` e `get_temporal_context()` (período do dia + tempo desde a última interação).
   - `CompanionState` (`record_interaction`, `record_pet`, `get_prompt_line()`, decaimento por `dt`).
   - Regra "Show, Don't Tell" pronta para uso no prompt.

### Worker 3: `mac-shortcuts`
**Arquivos exclusivos:**
- `app/shortcuts.py` (novo — CRUD SQLite + catálogo padrão pré-mapeado + renderizador de catálogo para o LLM)
- `app/mac_control.py` (novo — execução segura via `argv` + Dock Viva + status do Mac + clima Open-Meteo)
- `tests/test_shortcuts_mac.py` (novo — testes com mocks de subprocess para validar segurança, whitelist de teclas, CRUD de atalhos e geração de prompt para o agente)

**Entregas:**
1. `ShortcutStore(db_path)`:
   - Seed automático de ~20 atalhos padrão em categorias (`spaces`, `capture`, `editing`, `apps`, `media`, `focus`), incluindo explicitamente: Mission Control, App Exposé, Espaço Esquerda/Direita, Alternar Janela (`cmd+grave`), Alternar App (`cmd+tab`), Mostrar/Ocultar Dock (`opt+cmd+d`), Print Seleção Clipboard, Print Seleção Arquivo, Print Tela Inteira, Pesquisar (`cmd+f`), **Pesquisar e Substituir** (`cmd+opt+f`), Colar Limpo, Desfazer/Refazer, Play/Pause, Volume +/-/Mudo, Bloquear Tela, Pomodoro 25m.
   - CRUD completo (`list_shortcuts`, `create_shortcut`, `update_shortcut`, `delete_shortcut`, `reset_defaults`, `get_shortcut`) + `build_agent_shortcuts_prompt()`.
2. `MacController`:
   - `list_running_apps()` via `osascript` `System Events` (retorna apps visíveis + app frontal atual).
   - `activate_app(app_name)` (validação contra caracteres inválidos, usa `open -a` / `osascript`).
   - `execute_keystroke(keys_spec)` (valida e traduz `"cmd+opt+f"`, `"ctrl+left"`, `"cmd+shift+4"`, etc., para AppleScript `keystroke`/`key code` seguro via `argv` sem `shell=True`; detecta falta de permissão de Acessibilidade e devolve diagnóstico claro).
   - `execute_mac_command(command_name)` (whitelist fechada: `mission_control`, `app_expose`, `screenshot_area_file`, `play_pause`, `next_track`, `prev_track`, `volume_up`, `volume_down`, `volume_mute`, `lock_screen`, etc.).
   - `get_mac_status()` (cache leve de 3s: app ativo, bateria/energia, mídia Spotify/Apple Music tocando, volume).
   - `get_weather(city_or_coords)` via `Open-Meteo` (cache de 15 min, sem API key, opcional).

### Worker 4: `voice-backend`
**Arquivos exclusivos:**
- `app/stt.py` (novo — transcrição local de áudio com lazy-load de `faster-whisper` ou `mlx-whisper` + fallback gracioso caso dependência não esteja instalada)
- `app/tts.py` (novo — síntese opcional no servidor Mac via `say` + `afconvert` / `edge-tts` se disponível, gerando WAV/M4A para iPhone Safari e RG406H)
- `app/llm.py` (evolução — injetar catálogo de atalhos + apps abertos + estado emocional/temporal; emitir `sentence` events para TTS frase-a-frase; parsear `[action:shortcut:<id>]`, `[action:app:<nome>]`, `[action:pomodoro:...]` no `TagStreamParser`)
- `app/main.py` (evolução — novos endpoints `/api/shortcuts*`, `/api/mac/*`, `/api/tts`, `/api/diagnostics`, `/api/weather`, suporte a `WS /ws` com `interrupt`, `audio`, `pet`, `run_shortcut`, `activate_app`, `pomodoro`)
- `scripts/setup_https.py` (novo — gera certificados locais em `certs/` usando `mkcert` ou `openssl` fallback e imprime URLs + comando `adb reverse`)
- `tests/test_ws_chat.py` (manter testes da Fase 1 + cobrir `[action:...]`, `sentence`, `interrupt`, endpoints de atalhos/Mac/STT/TTS)

**Entregas:**
- Instalar dependências necessárias via `uv pip install` no `.venv` apenas se leves e compatíveis com Python 3.13 `arm64` (ex. `faster-whisper` se compatível, ou `python-multipart` se precisar upload, deixando `mlx-whisper`/`faster-whisper` com instalação segura e fallback limpo nos testes).

### Worker 5: `frontend`
**Arquivos exclusivos:**
- `static/manifest.json` (novo — PWA Android + iOS)
- `static/icon.svg` (novo — ícone vetorial do pet para PWA/favicon)
- `static/gamepad.js` (novo — suporte completo ao RG406H via Gamepad API + sensor de movimento/giroscópio + haptics)
- `static/diagnostics.js` (novo — Estúdio de Diagnóstico de microfone/loopback, vozes TTS, Gamepad e sensores)
- `static/index.html` (evolução)
- `static/style.css` (evolução responsiva: 960×720 RG406H + Desktop Mac + iPhone `100dvh` / `safe-area-inset-*`)
- `static/app.js` (evolução: 4 modos de tela, Push-to-Talk com captura MediaRecorder/WebAudio, barge-in ao tocar/falar, TTS híbrido Browser/Server `<audio>`, Modo Dock & Atalhos + Modal CRUD Gravador de Atalhos, Smart Display com Pomodoro/Clima/Now Playing, integração `EmoAudio` + `EmoFace.reactToTouch`)

### Worker 6: `verifier`
- Valida contratos cruzados (`EmoFace`, `EmoAudio`, `ShortcutStore`, `MacController`, endpoints REST, eventos WS, PWA/iOS meta tags, Gamepad).
- Executa `.venv/bin/pytest tests -v`, `node --check static/*.js`, `TestClient` em todas as rotas, verificação de zero segredos no git e checagem do túnel ADB no RG406H.
- Atualiza `README.md` com guia completo em PT-BR (Mac, RG406H USB/HTTPS, diagnóstico de microfone, fallback USB-C/Bluetooth e guia do iPhone para testar amanhã).

---

## Ordem de Execução Sugerida no Novo Chat
1. Ler `docs/superpowers/specs/2026-11-16-desk-assistant-expanded-design.md` e este plano.
2. Subir a swarm com `model="gemini-4-hydrogen-high"` seguindo os 6 workers acima (sem tocar em outros repositórios).
3. Ao final, garantir 100% dos testes verdes, verificar no navegador headless/TestClient, validar acesso no RG406H conectado (`adb reverse` + HTTPS LAN), fazer commit limpo na `main` (sem `.env`, `certs/`, `.venv/`, `data/*.db*`), reiniciar o servidor com a nova versão e deixar o relatório completo pronto para Nathan ler ao acordar.
