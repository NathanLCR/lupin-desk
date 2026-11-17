# 03 - Manhã: First Wake

Status: em andamento (Calendar, Inbox e Data Consent prontos; falta o uso real)

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
- [x] Calendar e Inbox são lidos sem nenhuma escrita (scripts fixos de `osascript`, só leitura).
- [x] Sem escolha explícita de provedor (Data Consent), nenhum dado de e-mail/agenda sai da máquina.
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

- [x] First Wake fala a contagem de não lidos sem remetente nem assunto.
- [x] Sem Data Consent, nenhum dado de agenda/e-mail aparece na chamada ao LLM (teste).
- [x] Trocar provider ou base_url desliga os dois consentimentos (teste).
- [x] Alterar consentimento fora do Mac retorna 403 (teste).

## Feito em 2026-11-17

- Gatilho no `/ws`: o primeiro toque, texto ou áudio do Active Body depois das 5h dispara o First Wake. O dia é marcado antes de falar, então não repete nem se a conexão cair. Body que não é o Active Body não dispara e não gasta o First Wake do dia.
- Ordem: no toque, o `mood` sai primeiro e o First Wake vem em seguida. No texto/áudio, o First Wake fala antes e depois vem a resposta do turno.
- A fala (`compor_fala_first_wake` em `app/today.py`) é montada sem LLM: saudação + tarefas abertas, agenda de hoje (até 3 itens, "e mais N") e a prioridade (tarefa que vence hoje, senão a primeira aberta). Ela não entra no histórico, então agenda e Cowork não vão para o provedor de LLM.
- O protocolo ganhou `first_wake: true` no `done` dessa fala. A voz vai pelo mesmo `audio` do servidor quando o Body pediu áudio.
- Calendar: `MacController.read_today_agenda` roda um script fixo de `osascript` (somente leitura, sem entrada do cliente). Se o macOS negar acesso ao Calendar, a fala só omite a agenda.
- O card antigo (`/api/first-wake`, card no Pet Mode e "Ouvir resumo" no navegador) saiu.

## Feito (resto) em 2026-11-17

- Inbox: `MacController.read_inbox()` roda um script fixo do Mail.app (somente leitura) e devolve a contagem de não lidos da caixa de entrada de todas as contas e até 10 não lidos das últimas 24h (remetente e assunto, nunca o corpo). Para não travar numa caixa grande, olha só as 300 mensagens mais novas; a contagem do badge é exata. Falha de leitura omite o e-mail.
- First Wake: a frase 1 ganha "e N e-mails não lidos" (singular, zero e sem Cowork tratados), sem remetente nem assunto e sem LLM.
- Data Consent (`app/consent.py`): `GET /api/data-consent` (qualquer cliente) e `PUT /api/data-consent` (só Mac, 403 fora). Dois interruptores, desligados por padrão, presos ao id do provider e ao host:porta do base_url; qualquer troca desliga os dois e voltar ao antigo não reativa. A chave de API nunca aparece. UI em Ajustes > Cérebro, com o nome do receptor no texto.
- Conversa: o turno do LLM recebe `personal_context` efêmero. Com consentimento, agenda de hoje e não lidos (remetente e assunto); sem, só uma instrução de que o Lupin não tem acesso e deve dizer isso; leitura que falhou vira um aviso sem dados. Nada disso entra no histórico salvo nem em log.
- Os testes não leem mais o Mail.app nem o Calendar reais (`tests/conftest.py`).
- Limite conhecido: a resposta do modelo é salva no histórico como sempre; se ele citar um título de agenda ou remetente, isso fica salvo.

Ainda falta:

- O script do Calendar não expande eventos recorrentes nem eventos que começaram antes de hoje; ver no uso real se isso incomoda.
- 1 semana de uso real.

## Decisions after delivery (2026-11-17)

- Mail.app latency: with email consent on, every turn reads Mail.app (~6 s), and First Wake waits ~6 s. Left as is on purpose; revisit only if it bothers in daily use.
- History: the injected calendar/email context is never saved, but Lupin's reply is saved as usual, even when it mentions an event or a sender. Accepted: the reply is what the user asked for.
