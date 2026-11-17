# 03 - Manhã: First Wake

Status: em andamento (Calendar pronto; Inbox pendente)

## Contexto

First Wake é a primeira interação do usuário com Lupin no dispositivo principal depois das 5h. Nesse momento Lupin FALA o Today, com a própria voz. Depende da 02.

## Escopo

- Detectar o First Wake (primeira interação após 5h no Active Body).
- Lupin fala o Today em 2 a 3 frases.
- Incluir Calendar (via Calendar.app) e Inbox (via Gmail), ambos somente leitura.
- Dados de e-mail e agenda só vão para o provedor de LLM que o usuário escolheu explicitamente.
- Today continua checado para não afirmar o que o Cowork não contém.

## Critérios de aceite

- [x] A primeira interação após 5h dispara o First Wake uma única vez por dia.
- [x] A fala tem 2 a 3 frases e sai pela voz de Lupin.
- [ ] Calendar e Inbox são lidos sem nenhuma escrita.
- [ ] Sem escolha explícita de provedor, nenhum dado de e-mail/agenda sai da máquina.
- [ ] Today não inventa nada fora do Cowork, Calendar e Inbox.
- [ ] 1 semana de uso real (mín. 4 dias) sem bug irritante.

## Perguntas em aberto

- Como o usuário escolhe e confirma o provedor de LLM para dados sensíveis?
- Como autenticar o Gmail somente leitura?

## Feito em 2026-11-17

- Gatilho no `/ws`: o primeiro toque, texto ou áudio do Active Body depois das 5h dispara o First Wake. O dia é marcado antes de falar, então não repete nem se a conexão cair. Body que não é o Active Body não dispara e não gasta o First Wake do dia.
- Ordem: no toque, o `mood` sai primeiro e o First Wake vem em seguida. No texto/áudio, o First Wake fala antes e depois vem a resposta do turno.
- A fala (`compor_fala_first_wake` em `app/today.py`) é montada sem LLM: saudação + tarefas abertas, agenda de hoje (até 3 itens, "e mais N") e a prioridade (tarefa que vence hoje, senão a primeira aberta). Ela não entra no histórico, então agenda e Cowork não vão para o provedor de LLM.
- O protocolo ganhou `first_wake: true` no `done` dessa fala. A voz vai pelo mesmo `audio` do servidor quando o Body pediu áudio.
- Calendar: `MacController.read_today_agenda` roda um script fixo de `osascript` (somente leitura, sem entrada do cliente). Se o macOS negar acesso ao Calendar, a fala só omite a agenda.
- O card antigo (`/api/first-wake`, card no Pet Mode e "Ouvir resumo" no navegador) saiu.

Ainda falta:

- Inbox (Gmail somente leitura) e a escolha explícita de provedor para dados sensíveis.
- O script do Calendar não expande eventos recorrentes nem eventos que começaram antes de hoje; ver no uso real se isso incomoda.
- 1 semana de uso real.
