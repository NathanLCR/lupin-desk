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

## Feedback do teste no RG406H (2026-11-16) e decisões

- A barra superior (Pet/Dock + 9 ações) confunde: some. Pet sem barra; um botão discreto + `Start` abrem Ajustes; Pet↔Dock por `L1`/`R1` ou deslize; Expressões vai para Ajustes › Diagnóstico; Memória, sons, voz e legenda vão para Ajustes; tela cheia automática; "fixar barra" removido.
- Ajustes: Voz e som, Cérebro (provedor/modelo, endereço do Mac Wi-Fi/USB), Memória, Skills, Dock (só ver Atalhos), Diagnóstico.
- O visual do Lupin está errado: ele é o husky de desenho preto e branco da referência (olhos ciano, dois pontos ciano, contorno ciano, focinho branco, nariz rosa, coleira com onda ciano). Busto como padrão; corpo inteiro só nos Truques. Animação por camadas (cabeça, olhos, pálpebras, sobrancelhas, boca/língua, orelhas, coleira), iguais na web e no LVGL.

### Ordem de entrega (2026-11-16)

1. Primeiro barra removida + Ajustes (botão discreto, `Start`, `L1`/`R1`/deslize, Diagnóstico com Expressões), em commit próprio.
2. Depois o husky em camadas (issue 10), em outro commit.
3. O rosto antigo EMO (`face.js`/`face.css`) é removido quando o husky entrar; não fica como fallback. O painel de Expressões em Diagnóstico passa a mostrar o husky.

### Entregue: passo 1 (barra e Ajustes)

- [x] Pet sem barra superior; só um botão discreto (engrenagem com ponto de conexão) no canto.
- [x] Ajustes com 6 seções: Voz e som, Cérebro (conexão, endereço do Mac, provedor e modelo, só leitura), Memória, Skills, Dock (só lista os Atalhos) e Diagnóstico (Expressões e Estados).
- [x] `Start` abre/fecha Ajustes; `B`/`Esc` fecham; `L1`/`R1` trocam de Modo (Pet↔Dock) e, dentro dos Ajustes, de seção. Deslize horizontal rápido e `Alt`+setas fazem o mesmo.
- [x] Tela cheia automática no primeiro toque ou tecla (`Select` ainda alterna); "fixar barra" removido.
- Fora do passo: trocar endereço/provedor/modelo pelo RG406H (continua no Mac); o rosto EMO segue até o passo 2 (issue 10).
- Teste do mini-pet `minipet-state.test.cjs` já falhava antes (rótulo "Ativar som"); não faz parte deste passo.
