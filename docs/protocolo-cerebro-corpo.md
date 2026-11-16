# Protocolo Cérebro↔Corpo (versão 1)

O **Body** abre um único WebSocket em `/ws` e usa só ele para conversar com o **Brain** (Lupin). Todos os quadros são JSON em texto. Vocabulário em `GLOSSARY.md`; decisão em `docs/adr/0001-companion-first-brain-and-body.md`.

## Body → Brain

| Evento | Campos | Descrição |
|---|---|---|
| `hello` | `body` ("rg406h-web", "esp32", ...), `protocol` (1), `audio`? (lista, ex.: `["m4a"]`) | Primeira mensagem. `audio` não vazio pede a voz do Brain. O Brain responde `welcome`. |
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
| `welcome` | `protocol` (1), `active_body` | Resposta ao `hello`; ecoa o `body` informado. |
| `state` | `state` (`thinking`, `listening`, `idle`, `error`) | Estado do turno. |
| `emotion` | `emotion` | Expression atual do rosto. |
| `mood` | `kind`, `affinity`, `energy`, ... (campos do Mood) | Mood após um `touch`. Substitui `companion_updated`. |
| `delta` | `text` | Trecho de texto em streaming. |
| `sentence` | `text` | Frase completa (a que será falada). |
| `audio` | `sentence` (índice 0 no turno), `seq` (0), `last` (bool), `mime` ("audio/mp4"), `data` (base64, até 24 KiB brutos) | Voz da frase, em chunks. Só enviado se o `hello` pediu áudio e o TTS está disponível. Falha de TTS pula o áudio sem `error`. |
| `done` | `text`, `emotion`, `facts`, `companion` | Fim do turno de texto. Os `audio` finais podem chegar depois dele. |
| `interrupted` | — | Turno cancelado; nenhum `audio` novo é enviado. |
| `error` | `message` | Falha. |

O `/api/tts` HTTP continua existindo para o Dock e outros usos.

## Active Body (futuro)

Lupin vive em um Body por vez: o ESP32 enquanto conectado, senão o RG406H; um ESP32 posterior vence. **Ainda não é imposto:** hoje o Brain apenas responde `welcome` com o `body` do `hello`, sem recusar ou derrubar outras conexões.
