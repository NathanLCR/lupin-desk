# Desk Assistant (Estilo EMO)

Assistente de mesa carismático com rosto animado em fundo preto (`960x720` / 4:3 e janelas responsivas), streaming de respostas via WebSocket, síntese de voz no navegador (`Web Speech API`) e memória persistente em duas camadas usando SQLite.

## Arquitetura do Projeto

- **Backend (`app/main.py`, `app/llm.py`, `app/config.py`)**: servidor FastAPI com canal WebSocket (`/ws`), API REST para gestão da memória (`/api/memory*`), endpoint de saúde (`/health`) e cliente assíncrono em streaming compatível com a API OpenAI (`/chat/completions`).
  - O `TagStreamParser` filtra tags `[emotion:<nome>]` (e a forma abreviada `[<nome>]`) além de `[fact: <fato>]` em tempo real para que nunca apareçam nas legendas nem sejam lidas pelo TTS.
  - Tokens internos de raciocínio (`delta.reasoning`) emitidos por modelos locais são ignorados do texto falado, mantendo o rosto no estado `thinking` até a resposta útil começar.
  - Logs aplicam redação automática (`SecretRedactingFilter`) para impedir vazamento de chaves de API.
- **Frontend (`static/`)**: palco central `#000000` com olhos animados em SVG (`face.js` / `face.css`), HUD discreta, barra de legenda em streaming, envio de texto, indicador de digitação e controle de voz em `pt-BR`.

### Arquitetura de Memória em 2 Camadas (`app/memory.py`)

1. **Camada 1 — Curto Prazo (Janela Deslizante)**:
   - Armazena o histórico recente da conversa na tabela `messages` do SQLite.
   - Apenas as últimas `MAX_SHORT_TERM_MESSAGES` (padrão: `10`) mensagens são enviadas ao modelo em ordem cronológica, mantendo o contexto leve e previsível.
2. **Camada 2 — Longo Prazo (Fatos sobre o Usuário)**:
   - Armazena fatos duradouros (nome, preferências, interesses, rotina) na tabela `user_facts`, com normalização para atualizar fatos semelhantes sem duplicar.
   - Os fatos são extraídos tanto das tags `[fact: ...]` geradas pelo modelo quanto de declarações explícitas do usuário, respeitando o limite `MAX_USER_FACTS` (padrão: `25`).
   - A cada turno, `build_memory_context()` injeta esses fatos no *system prompt* dentro de um orçamento fixo de caracteres (`1200` chars).
   - Limpar o histórico da conversa (`Limpar conversa atual` ou `clear_history`) apaga apenas a Camada 1 e preserva os fatos aprendidos na Camada 2.

## Configuração (`.env`)

1. Na pasta do projeto, crie o arquivo `.env` a partir do modelo:

```bash
cp .env.example .env
```

2. Edite o `.env` com suas configurações locais (nunca versione o `.env` no Git):

```env
LLM_BASE_URL=http://127.0.0.1:31415/v1
LLM_API_KEY=sua-chave-aqui
LLM_MODEL=claude-haiku-4-5
HOST=0.0.0.0
PORT=8000
MAX_SHORT_TERM_MESSAGES=10
MAX_USER_FACTS=25
```

## Como Rodar o Servidor

Dentro da pasta do projeto, certifique-se de que sua API LLM local está rodando (por padrão em `http://127.0.0.1:31415/v1`).

**Usando `.venv` diretamente:**

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Ou usando `uv`:**

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Depois, abra no navegador do Mac: `http://localhost:8000`

## Como Rodar os Testes

Execute toda a suíte de testes automatizados (memória, parser de tags, HTTP e WebSocket) a partir da pasta do projeto:

```bash
.venv/bin/pytest tests -v
```

Ou com `uv`:

```bash
uv run pytest tests -v
```

## Checklist de Validação — Fase 1 (Navegador do Mac)

1. **Conexão e Visual**:
   - Abrir `http://localhost:8000` (em janela `960x720` ou tela cheia) e confirmar fundo `#000000`, olhos ciano centralizados, piscadas naturais e badge WebSocket conectado (verde).
2. **Expressões e Estados**:
   - Abrir o painel **Expressões** na HUD superior e testar as 10 emoções (`neutral`, `happy`, `excited`, `curious`, `skeptical`, `surprised`, `sad`, `wink`, `love`, `sleepy`) e os 5 estados (`idle`, `listening`, `thinking`, `speaking`, `error`).
3. **Chat em Streaming + TTS**:
   - Digitar na caixa inferior e observar o rosto olhar sutilmente para baixo e entrar em `listening`.
   - Enviar uma mensagem (ex.: `"Oi! Meu nome é Nathan e eu gosto de café."`) e verificar:
     - Estado `thinking` enquanto o modelo raciocina (sem vazar `reasoning` nem tags `[emotion:...]`/`[<emoção>]` ou `[fact:...]`).
     - Legenda recebendo texto limpo em streaming e transição para a emoção retornada.
     - Fala automática em voz `pt-BR` com animação de `speaking` (ou alternar `Voz`/`Mudo`).
4. **Memória em 2 Camadas**:
   - Abrir a gaveta **Memória** e confirmar que o fato aprendido aparece listado.
   - Adicionar um fato manualmente, remover um fato com `×`, clicar em **Limpar conversa atual** (confirmando que os fatos permanecem) e testar **Resetar toda memória**.

## Fases Futuras (Reservado)

- **Fase 2 — Acesso no Anbernic RG406H via LAN**: acesso pelo navegador do Anbernic RG406H na rede local via HTTPS local (`mkcert`/certificado confiável para liberar recursos web seguros) e modo tela cheia otimizado para a tela 4:3 (`960x720`).
- **Fase 3 — Entrada de Voz (Push-to-Talk & STT)**: diagnóstico de microfone no RG406H, botão segurar-para-falar (*Push-to-Talk*), transcrição local com `faster-whisper` no Mac e fallback de áudio via USB-C/Bluetooth.
