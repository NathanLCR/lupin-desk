# Desk Assistant — Contexto e Regras para o Agente

Você está trabalhando diretamente dentro de `/Users/nathanlucio/Desktop/desk-assistant`.

## Leia primeiro
1. `docs/superpowers/specs/2026-11-16-desk-assistant-expanded-design.md` — especificação completa aprovada por Nathan.
2. `docs/superpowers/plans/2026-11-16-desk-assistant-implementation-plan.md` — divisão de implementação para a swarm.
3. `README.md` — estado atual da Fase 1.

## Regras do Projeto
- **Não modifique outros diretórios** (como `nathan-os-app` ou `Cowork`). Trabalhe apenas dentro de `/Users/nathanlucio/Desktop/desk-assistant`.
- **Segurança & Menor Privilégio**:
  - Nunca versione `.env`, `certs/`, `.venv/` ou `data/*.db*`.
  - Nunca exponha `LLM_API_KEY` em logs, respostas HTTP/WS ou testes.
  - Execuções no macOS (`app/mac_control.py`) devem usar apenas `subprocess.run` com lista `argv` e whitelist estrita (nunca `shell=True`, nunca comandos arbitrários vindos do cliente).
- **Idioma**: comentários no código, mensagens de UI, commits e `README.md` em **português do Brasil (PT-BR)**.
- **Multiplataforma nativa**: manter compatibilidade nativa para **Anbernic RG406H** (Android 13, 960×720, Gamepad API), **macOS** e **iPhone** (iOS Safari / PWA `safe-area-inset-*` + áudio fallback do servidor). O iPhone será testado apenas quando Nathan acordar.
- **Ambiente Python**: use sempre `/Users/nathanlucio/Desktop/desk-assistant/.venv/bin/python` e `.venv/bin/pytest` (ou `/Users/nathanlucio/.local/bin/uv`).
- **Dispositivo conectado**: Anbernic RG406H está conectado via ADB (`RG406H01980952`), já com `adb reverse tcp:8000 tcp:8000` e `RECORD_AUDIO` liberado para o Chrome.
- **Ao usar swarm**: se o usuário pedir para construir usando swarm (ou durante a madrugada), use `gemini-4-hydrogen-high`, divida os arquivos sem sobreposição e só considere concluído após rodar todos os testes, smoke test ao vivo e subir o servidor atualizado.
