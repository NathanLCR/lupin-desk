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

- [ ] A grade é 3x3 fixa, paginada, e mostra só os Pinned Shortcuts na ordem do Mac.
- [ ] A lista de apps abertos é a última página do Dock.
- [ ] `L1`/`R1` e swipe lateral trocam Mode; `L2`/`R2` e swipe vertical trocam página.
- [ ] Não existe edição de Shortcuts fora do Mac, nem pela UI nem pela API (403).
- [ ] Shortcut novo nasce sem fixar.
- [ ] O Lupin pequeno aparece no canto só no Active Body; fora dele, aparece o botão "Falar com Lupin".
- [ ] Falar de qualquer aparelho faz Lupin responder no Active Body, e o aparelho de origem mostra o texto.
- [ ] Fala curta fica no Dock com o Lupin pequeno; fala longa (3ª frase ou First Wake) vai para o Pet e volta sozinha se a troca foi automática.
- [ ] O toggle entre Pet e Dock funciona nos dois sentidos.
