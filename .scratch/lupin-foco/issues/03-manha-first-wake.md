# 03 - Manhã: First Wake

Status: em andamento (Calendar pronto; Inbox pendente)

## Contexto

First Wake é a primeira interação do usuário com Lupin no dispositivo principal depois das 5h. Nesse momento Lupin FALA o Today, com a própria voz. Depende da 02.

## Escopo

- Detectar o First Wake (primeira interação após 5h no Active Body).
- Lupin fala o Today em 2 a 3 frases.
- Incluir Calendar (via Calendar.app) e Inbox (via Mail.app), ambos somente leitura.
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

Respondidas na spec do resto da 03 (abaixo): o provedor é confirmado pelo Data Consent, e o Inbox vem do Mail.app, sem OAuth e sem senha guardada.

## Spec do resto da 03 (combinada em 2026-11-17)

### Inbox

- Fonte: Mail.app, por um script fixo de `osascript` somente leitura, no mesmo padrão do Calendar (`subprocess.run` com argv, nada vindo do cliente). Sem OAuth, sem senha guardada.
- "Não lidos" = toda mensagem não lida na caixa de entrada de todas as contas do Mail.app (o número do badge do Mail).
- Se o Mail.app não puder ser lido (sem permissão, fechado, erro), o e-mail é só omitido.

### First Wake

- Continua sem LLM.
- A frase 1 ganha a contagem de não lidos: "Bom dia! Você tem 4 tarefas abertas e 12 e-mails não lidos."
- Nunca fala remetente nem assunto.
- Sem leitura do Mail.app, a frase fica como hoje.

### Data Consent

- Dois interruptores: um para a agenda, outro para o e-mail.
- Ficam em Settings → Brain e só podem ser alterados no Mac (`is_mac_client`); os outros aparelhos só veem o estado. Alteração vinda de outro cliente recebe 403.
- O texto nomeia quem recebe, por exemplo: "Permitir que Proxy Local (127.0.0.1:31415) veja sua agenda".
- O consentimento fica ligado ao id do provider e ao host do base_url. Se qualquer um mudar, os dois interruptores desligam sozinhos.
- Sem exceções, Ollama incluído.
- Padrão: desligados.

### Conversa

- Com consentimento de agenda: o contexto do LLM recebe a agenda de hoje (hora e título).
- Com consentimento de e-mail: recebe os não lidos das últimas 24h, no máximo 10, só remetente e assunto, nunca o corpo.
- Sem consentimento: o contexto não recebe nada disso, e o Lupin diz que não pode ver a agenda/o e-mail em vez de adivinhar.
- Agenda e e-mail não entram no histórico salvo nem em log.

### Critérios de aceite extras

- [ ] First Wake fala a contagem de não lidos sem remetente nem assunto.
- [ ] Sem Data Consent, nenhum dado de agenda/e-mail aparece na chamada ao LLM (teste).
- [ ] Trocar provider ou base_url desliga os dois consentimentos (teste).
- [ ] Alterar consentimento fora do Mac retorna 403 (teste).

## Feito em 2026-11-17

- Gatilho no `/ws`: o primeiro toque, texto ou áudio do Active Body depois das 5h dispara o First Wake. O dia é marcado antes de falar, então não repete nem se a conexão cair. Body que não é o Active Body não dispara e não gasta o First Wake do dia.
- Ordem: no toque, o `mood` sai primeiro e o First Wake vem em seguida. No texto/áudio, o First Wake fala antes e depois vem a resposta do turno.
- A fala (`compor_fala_first_wake` em `app/today.py`) é montada sem LLM: saudação + tarefas abertas, agenda de hoje (até 3 itens, "e mais N") e a prioridade (tarefa que vence hoje, senão a primeira aberta). Ela não entra no histórico, então agenda e Cowork não vão para o provedor de LLM.
- O protocolo ganhou `first_wake: true` no `done` dessa fala. A voz vai pelo mesmo `audio` do servidor quando o Body pediu áudio.
- Calendar: `MacController.read_today_agenda` roda um script fixo de `osascript` (somente leitura, sem entrada do cliente). Se o macOS negar acesso ao Calendar, a fala só omite a agenda.
- O card antigo (`/api/first-wake`, card no Pet Mode e "Ouvir resumo" no navegador) saiu.

Ainda falta:

- Inbox (Mail.app somente leitura) e o Data Consent (ver a spec acima).
- O script do Calendar não expande eventos recorrentes nem eventos que começaram antes de hoje; ver no uso real se isso incomoda.
- 1 semana de uso real.
