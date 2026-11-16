# 03 - Manhã: First Wake

Status: needs-triage

## Contexto

First Wake é a primeira interação do usuário com Lupin no dispositivo principal depois das 5h. Nesse momento Lupin FALA o Today, com a própria voz. Depende da 02.

## Escopo

- Detectar o First Wake (primeira interação após 5h no Active Body).
- Lupin fala o Today em 2 a 3 frases.
- Incluir Calendar (via Calendar.app) e Inbox (via Gmail), ambos somente leitura.
- Dados de e-mail e agenda só vão para o provedor de LLM que o usuário escolheu explicitamente.
- Today continua checado para não afirmar o que o Cowork não contém.

## Critérios de aceite

- [ ] A primeira interação após 5h dispara o First Wake uma única vez por dia.
- [ ] A fala tem 2 a 3 frases e sai pela voz de Lupin.
- [ ] Calendar e Inbox são lidos sem nenhuma escrita.
- [ ] Sem escolha explícita de provedor, nenhum dado de e-mail/agenda sai da máquina.
- [ ] Today não inventa nada fora do Cowork, Calendar e Inbox.
- [ ] 1 semana de uso real (mín. 4 dias) sem bug irritante.

## Perguntas em aberto

- Como o usuário escolhe e confirma o provedor de LLM para dados sensíveis?
- Como autenticar o Gmail somente leitura?
