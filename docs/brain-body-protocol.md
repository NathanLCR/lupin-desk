# Protocolo Cérebro↔Corpo (versão 1)

O **Body** abre um único WebSocket em `/ws` e usa só ele para conversar com o **Brain** (Lupin). Todos os quadros são JSON em texto. Vocabulário em `GLOSSARY.md`; decisão em `docs/adr/0001-companion-first-brain-and-body.md`.

## Body → Brain

| Evento | Campos | Descrição |
|---|---|---|
| `hello` | `body` ("esp32", "rg406h-web", "web"), `protocol` (1), `audio`? (lista, ex.: `["m4a"]`) | Primeira mensagem. `audio` não vazio pede a voz do Brain. O Brain responde `welcome`. |
| `text` | `text` | Mensagem de chat do usuário; inicia um turno. |
| `audio` | `data` (base64), `mime_type`, `language`? | Áudio gravado para STT; inicia um turno. (Não confundir com o `audio` Brain→Body.) |
| `touch` | `kind` ("pet" \| "poke"), `intensity`? | Toque no Lupin; o Brain responde `mood`. |
| `interrupt` | — | Cancela o turno ativo (e o áudio dele). |
| `typing` | `active` (bool) | Usuário digitando; o Brain responde `state`. |
| `clear_history` | — | Limpa o histórico curto. |

Há outras mensagens de controle (atalhos, aprovações, ações) usadas pelo Dock; ficam fora deste contrato mínimo.

## Brain → Body

| Evento | Campos | Descrição |
|---|---|---|
| `welcome` | `protocol` (1), `active_body`, `active` (bool) | Resposta ao `hello`: qual Body está com Lupin e se é este. |
| `active_body` | `active_body`, `active` (bool) | O Active Body mudou (outro Body chegou ou saiu). |
| `state` | `state` (`thinking`, `listening`, `idle`, `error`) | Estado do turno. |
| `emotion` | `emotion` | Expression atual do rosto. |
| `mood` | `kind`, `affinity`, `energy`, ... (campos do Mood) | Mood após um `touch`. Substitui `companion_updated`. |
| `delta` | `text` | Trecho de texto em streaming. |
| `sentence` | `text`, `first_wake?`, `from_body?` | Frase completa (a que será falada). `first_wake: true` marca as frases do First Wake (o Dock sobe para o Pet com elas). `from_body` só aparece em eventos espelhados (ver Resposta a quem não é o Active Body). |
| `audio` | `sentence` (índice 0 no turno), `seq` (0), `last` (bool), `mime` ("audio/mp4"), `data` (base64, até 24 KiB brutos) | Voz da frase, em chunks. Só enviado se o `hello` pediu áudio e o TTS está disponível. Falha de TTS pula o áudio sem `error`. |
| `done` | `text`, `emotion`, `facts`, `companion`, `first_wake?` | Fim do turno de texto. Os `audio` finais podem chegar depois dele. `first_wake: true` marca a fala do First Wake (primeira interação do dia depois das 5h no Active Body), que chega antes da resposta ao texto/áudio ou logo depois do `mood` de um toque. |
| `interrupted` | — | Turno cancelado; nenhum `audio` novo é enviado. |
| `error` | `message` | Falha. |

O `/api/tts` HTTP continua existindo para o Dock e outros usos.

## Active Body

Lupin vive em um Body por vez. O Brain escolhe pela prioridade `esp32` > `rg406h-web` > qualquer outro (`web`: navegador do Mac, iPhone); no mesmo tipo, o último `hello` vence. Quando o Active Body muda, os outros Bodies recebem `active_body`. Um Body com `active: false` não recebe `audio`, não fala pelo navegador e fica só como Dock (sem Pet Mode). Quando o Active Body sai, o próximo da fila recebe `active_body` com `active: true`.

## Resposta a quem não é o Active Body

Qualquer Body pode perguntar (`text`, `audio`, `run_shortcut` com `agent_prompt`). Se quem perguntou não é o Active Body, ele recebe os eventos de texto de sempre, **sem `audio`**. O Active Body (outra conexão) recebe cópias de `emotion`, `sentence` e `done`, e os `audio` da resposta se declarou áudio no `hello` e o TTS está disponível, cada um com `"from_body": "<Body que perguntou>"`. Não são espelhados `delta`, `state`, `transcript` nem `memory_updated`. Se quem perguntou é o Active Body, nada muda. Sem Active Body, quem perguntou recebe só texto. Se o Active Body cai no meio do turno, o espelhamento para sem erro e a resposta ao Body que perguntou continua.

## Configuração de Shortcuts só no Mac

`GET /api/client-info` devolve `{"is_mac": bool}` (true para loopback ou para um IP do próprio Mac). Criar, editar, apagar, fixar, reordenar e restaurar Shortcuts (`POST/PUT/DELETE /api/shortcuts...`) devolvem **403** fora do Mac, mesmo com `DESK_DEV_SEM_TOKEN`. Executar (`/run` e `run_shortcut`) continua liberado para qualquer Body. Shortcut novo nasce sem fixar (`pinned_on_deck = 0`; bancos já existentes não são migrados).
