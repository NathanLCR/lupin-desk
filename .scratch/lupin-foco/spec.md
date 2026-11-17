# Lupin em foco

Direção (ADR 0001): Lupin é o produto. Mac control, Cowork, Shortcuts e recursos de assistente são formas de Lupin ajudar, não produtos próprios. O Brain roda no Mac; o Body (ESP32-S3 JC4832W535, 3,5" 480x320, Arduino + LVGL) mostra Lupin, toca o som e sente o usuário. Cada feature nasce no RG406H e depois é portada para o ESP32. Quando o ESP32 chegar, ele vira o Active Body e o RG406H vira Dock (e Body quando o ESP32 estiver desligado).

## Regra de execução

- As features vêm **uma de cada vez**, na ordem 02..08.
- Cada feature precisa **sobreviver 1 semana de uso real** (no mínimo 4 dias de uso, sem bug irritante) antes de a próxima começar.
- Operação offline **não** é requisito.
- Não adicionar Bodies nem Modes sem rever o ADR 0001.

## Issues

| # | Issue | Status |
|---|-------|--------|
| 01 | Cortes | ready-for-agent |
| 02 | Corpo vivo: protocolo Brain-Body | ready-for-agent |
| 03 | Manhã: First Wake | em andamento |
| 04 | Presença | needs-triage |
| 05 | Tarefas, notas e hábitos por voz | needs-triage |
| 06 | Busca inteligente | needs-triage |
| 07 | Ditado | needs-triage |
| 08 | Editor de imagens | needs-triage |
| 09 | Redesign do Dock | feito (falta teste no RG406H) |
| 10 | Visual do Lupin: husky em camadas | primeira arte entregue |
| 11 | Fully local mode | needs-triage |
| 12 | Lupin as an MCP server | needs-triage |
| 13 | Showcase: README, video and opening the repo | needs-triage |

A issue 01 vem antes de tudo (limpa o terreno). A 09 não entra na fila 02..08 e só começa depois que o ESP32 estiver em uso, ou quando o usuário decidir.

O código cortado fica apenas no branch `snapshot/swarm-2026-11-16`.
