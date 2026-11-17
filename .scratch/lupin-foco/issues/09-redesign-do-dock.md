# 09 - Redesign do Dock

Status: ready-for-agent

## Contexto

O Dock é a superfície de controle do Mac. Hoje o RG406H é Body e Dock ao mesmo tempo (Pet e Dock Modes). Quando o ESP32 chegar, ele vira o Active Body e o RG406H fica só Dock. Esta issue cobre os dois casos e foi fechada numa sessão de grilling em 2026-11-17 (ver `GLOSSARY.md`: Dock, Pinned Shortcut, Active Body, Mode).

## Spec

### Grade e páginas

- O Dock Mode mostra uma grade fixa 3x3 só com os Pinned Shortcuts (`pinned_on_deck = 1`), na ordem de `sort_order`.
- A grade é paginada. A última página é "Apps abertos" (a lista de apps do Mac); ela não é um Mode novo.
- `L1`/`R1` e o swipe lateral trocam Mode (como hoje). `L2`/`R2` e o swipe vertical trocam a página. Pontos de página ficam embaixo. O D-pad move o foco dentro da grade.
- Saem do Dock: as abas de categoria, o botão "Teclas: Padrão/Grande" e os botões Novo/Editar/Gerenciar.
- Sem Pinned Shortcuts, a primeira página diz "Nenhum atalho fixado. Escolha os atalhos no Mac." A página "Apps abertos" continua funcionando.

### Configuração só no Mac

- "O Mac" é o cliente rodando na própria máquina (loopback: navegador ou Electron do Mac).
- Lá, Settings → Dock tem o editor de Shortcuts: criar, editar, apagar, fixar/desafixar e reordenar.
- Em qualquer outro aparelho, Settings → Dock só lista os Shortcuts, sem editar.
- O servidor recusa criar, editar, apagar, fixar e reordenar Shortcuts quando o cliente não é loopback (403), mesmo com o modo dev sem token.
- Shortcut novo nasce sem fixar (`pinned_on_deck = 0`). Os Shortcuts que já existem ficam como estão (sem migração).

### Confirmação

- Shortcut com `requires_confirmation` pede "Executar?" no aparelho em que foi tocado, mesmo que ele seja só Dock.

### Canto do Dock

- No Active Body, o canto do Dock Mode mostra um Lupin pequeno. Tocar nele vai para o Pet Mode.
- Em aparelho que não é o Active Body, o canto mostra o botão "Falar com Lupin": segurar (ou `Y`) fala pelo microfone do aparelho; tocar abre o teclado para digitar.
- O mini-pet do Mac segue a mesma regra: fora do Active Body, o desenho de Lupin some e fica só o botão.

### Respostas de Lupin

- Qualquer aparelho pode falar com Lupin. Lupin sempre responde no Active Body (voz, rosto, Expression). O aparelho de onde veio a fala recebe só o texto, numa linha, sem áudio. Sem Active Body conectado, o aparelho que perguntou recebe só o texto.
- Fala longa = a resposta chega à 3ª frase. O First Wake sempre conta como fala longa.
- No Active Body em Dock Mode:
  - fala curta (1 ou 2 frases): o Lupin pequeno fala (coleira acesa, boca mexendo) e o texto aparece numa linha ao lado dele, cortado com "…", e some 4 s depois que o áudio termina. A grade não se mexe nem é coberta.
  - fala longa: a tela vai para o Pet Mode. Se essa troca foi automática e o usuário não tocou em nada, a tela volta ao Dock 5 s depois que o áudio termina. Se o usuário trocou para o Pet por conta própria, fica no Pet.

## Critérios de aceite

- [x] A grade é 3x3 fixa, paginada, e mostra só os Pinned Shortcuts na ordem do Mac.
- [x] A lista de apps abertos é a última página do Dock.
- [x] `L1`/`R1` e swipe lateral trocam Mode; `L2`/`R2` e swipe vertical trocam página.
- [x] Não existe edição de Shortcuts fora do Mac, nem pela UI nem pela API (403).
- [x] Shortcut novo nasce sem fixar.
- [x] O Lupin pequeno aparece no canto só no Active Body; fora dele, aparece o botão "Falar com Lupin".
- [x] Falar de qualquer aparelho faz Lupin responder no Active Body, e o aparelho de origem mostra o texto.
- [x] Fala curta fica no Dock com o Lupin pequeno; fala longa (3ª frase ou First Wake) vai para o Pet e volta sozinha se a troca foi automática.
- [x] O toggle entre Pet e Dock funciona nos dois sentidos. (Pet -> Dock por L1/R1/swipe; Dock -> Pet também tocando no Lupin pequeno.)

## Feito em 2026-11-17

- Backend: `GET /api/client-info`; escrita de Shortcuts (incl. `reset-defaults`) só do Mac (403 fora); Shortcut novo nasce sem fixar; resposta a quem não é o Active Body (texto para quem perguntou, `emotion`/`sentence`/`done`/`audio` espelhados no Active Body com `from_body`); `first_wake: true` em cada `sentence` do First Wake. Documentado em `docs/protocolo-cerebro-corpo.md`.
- Dock: grade 3x3 de Pinned Shortcuts ordenada por `sort_order`, 9 por página, última página "Apps abertos", bolinhas de página, estado vazio "Nenhum atalho fixado. Escolha os atalhos no Mac.". Sem abas, botão de tamanho, Novo/Editar/Gerenciar.
- Controles: `L1`/`R1` e swipe horizontal trocam Mode; `L2`/`R2` e swipe vertical trocam página (só no Dock; fora dele `L2`/`R2` seguem como Push-to-Talk); D-pad anda na grade (cima/baixo pulam uma linha).
- Ajustes > Dock: no Mac, editor completo (novo, editar, apagar, fixar/desafixar, reordenar, via modal existente); nos outros aparelhos, lista somente leitura.
- Canto: Lupin pequeno (mesmo rosto, encolhido por CSS) no Active Body, toque abre o Pet; nos outros, botão "Falar com Lupin" (segurar grava, tocar abre o texto). `Y` segurado também grava no Dock.
- Fala no Dock: 1-2 frases ficam no Dock com faixa de uma linha (some 4 s depois); 3ª frase ou `first_wake` sobe para o Pet e volta 5 s depois da fala só se a troca foi automática; qualquer entrada do usuário cancela a volta. Aparelho que não é o Active Body só mostra texto.
- Mini-pet (Electron): fora do Active Body esconde o desenho e mostra só "Falar com Lupin".
- Testes: Python `tests/test_dock_redesign.py`; frontend `tests/frontend/dock.test.cjs` (harness compartilhado em `harness.cjs`).

Pendente / a conferir à mão:
- Códigos reais de `L2`/`R2` e `Y` no RG406H (o código assume botões 6/7 e 3 do mapeamento standard).
- Layout do canto e da grade na tela do RG406H e no iPhone; swipe vertical no toque real.
- No mini-pet, "Falar com Lupin" só abre o painel (o mini-pet não tem WebSocket próprio).
- Bancos antigos mantêm `pinned_on_deck` como estava (sem migração).
