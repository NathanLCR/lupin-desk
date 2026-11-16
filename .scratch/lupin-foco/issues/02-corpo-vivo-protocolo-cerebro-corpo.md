# 02 - Corpo vivo: protocolo Brain-Body

Status: ready-for-agent

## Contexto

Feature 1 da fila. O Body principal será um ESP32-S3 JC4832W535 (3,5" 480x320, touch, Arduino + LVGL) quando chegar; então ele vira o Active Body e o RG406H vira Dock (e Body quando o ESP32 estiver desligado). Para que portar seja só escrever firmware, o Body web do RG406H deve falar com o Brain exclusivamente pelo protocolo que o ESP32 usará (ADR 0001).

## Escopo

- Definir o protocolo WebSocket Brain-Body, aberto pelo Body: eventos JSON de Expression, Mood, frase sendo falada e toque, mais chunks de áudio da voz.
- Documentar o protocolo como contrato (versão, tipos de evento, campos).
- Implementar o lado Brain do protocolo.
- Migrar o Body web do RG406H para usar apenas esse protocolo, sem endpoints paralelos.
- Garantir um único Active Body por vez.
- Sem firmware ESP32 nesta issue.

## Critérios de aceite

- [ ] Existe documento do protocolo com todos os eventos e exemplos JSON.
- [ ] O Brain envia Expression, Mood, frase falada e áudio; recebe toque pelo mesmo WebSocket.
- [ ] O Body web do RG406H não usa nenhum outro canal para mostrar ou ouvir Lupin.
- [ ] Lupin nunca está em dois Bodies ao mesmo tempo.
- [ ] O Body cuida sozinho dos comportamentos ociosos pequenos (piscar, olhar em volta).
- [ ] Uso real no RG406H por 1 semana (mín. 4 dias) sem bug irritante antes de iniciar a 03.
