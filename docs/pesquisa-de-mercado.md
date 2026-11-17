# Pesquisa de mercado: companheiros de mesa com IA (novembro de 2026)

Objetivo: entender o que existe parecido com o Lupin, no que cada um é bom, onde falha, e o que isso diz sobre o Desk Assistant como produto pessoal e como portfólio.

## O mapa do mercado

O mercado se divide em cinco grupos.

### 1. Robôs companheiros (hardware fechado, foco em fofura)

| Produto | Preço | No que é bom | Onde falha |
|---|---|---|---|
| **EMO** (Living.AI) | US$ 279 (US$ 379 com dock) | Mais de mil expressões, anda pela mesa sem cair, reconhece até 10 rostos, conversa via ChatGPT | Bateria de ~2 h, voz só em inglês, app instável, suporte fraco, Wi-Fi só 2,4 GHz. Reações roteirizadas; não faz tarefas |
| **Loona** (KEYi) | US$ 429 | O mais "cachorro": anda pela casa, volta sozinho para o dock, ChatGPT-4o sem assinatura | ~2 h de bateria, motor barulhento, às vezes não acha o carregador |
| **Eilik** (Energize Lab) | US$ 140 | Barato, offline, sem app nem conta, 8–10 h de bateria, tem Pomodoro | Não conversa; é um brinquedo expressivo |
| **Vector 2.0** | US$ 250 + plano anual | Personalidade autônoma, fãs do original | Voz atrás de assinatura. A Anki, empresa original, quebrou e o robô quase virou peso de papel |
| **Moflin** (Casio) | — | Vínculo emocional forte, áudio só no aparelho (privacidade) | Não fala, não faz nada; motor zumbindo |
| **LOOI** | US$ 180–220 | Barato, usa o celular como cérebro e rosto, ~5 h | Prende o seu celular; lento em celular antigo |

**Padrão:** todos vendem **presença e personalidade**. Quase nenhum é útil. As reclamações se repetem: bateria, app ruim, nuvem obrigatória, assinatura e o risco de a empresa sumir e o robô morrer junto.

### 2. Robôs de mesa "que trabalham" (o grupo mais próximo do Lupin)

- **Autonomous Lamp** (US$ 699): robô de mesa open source que roda agentes (Claude Code, Codex, OpenCode…) e skills instaláveis, como lembrete de água, pausa e postura, além de agenda e Home Assistant. Deixa trocar o agente e usar suas próprias chaves. Ligado na tomada, sem bateria e ainda sem histórico de donos.
- **Reachy Mini** (Hugging Face/Pollen, US$ 399–499): kit para quem programa. Faz o que você codar.

O próprio blog da Autonomous propõe um teste de três perguntas para separar companheiro de "robô que trabalha":
1. Dá para escolher a IA?
2. Ele age fora do próprio corpo (agenda, computador)?
3. Dá para mudar as skills sem esperar o fabricante?

**O Lupin passa nas três:** tem provider escolhível (inclusive Ollama local), age no Mac (Shortcuts, Dock, Cowork Tasks) e tem Skills. Quase todo o grupo 1 falha nas três.

### 3. Assistentes de software com mascote (o "Taby" e parecidos)

- **Taby** (heytaby.com): é a referência mais próxima e já está no ADR 0001. É um bichinho no topo da tela do Mac/Windows que:
  - planeja o dia em cima da agenda (Google, Outlook ou Apple);
  - tria o inbox ("3 e-mails precisam de você");
  - faz busca inteligente de arquivos e fotos, ditado e voz;
  - fecha distrações.

  A IA roda **local** e funciona com o Wi-Fi desligado. Não pede conta. É grátis, com Premium na nuvem a €8,99/mês. Também existe um **Taby físico "build your own"**, e usuários já ligam o Taby a outros agentes via MCP local.
- **Toby, DeskFerry e similares:** assistentes de Mac sem personagem, focados em e-mail, agenda e automação.
- **Pets de desktop com LLM:** Nibbii (no notch do MacBook), Desktop Pet, PetClaw, DumbPet, Your Friendly AI, Ollama Pet, PawPal. Muitos são open source ou feitos por indie devs. Normalmente são um personagem na tela com chat, e às vezes trazem Pomodoro e lembretes.

**Padrão:** o Taby prova que "bichinho + utilidade + privacidade local" é uma proposta que as pessoas querem, e a comunidade dele reage muito ao lado fofo e físico. Os pets de desktop são muitos e rasos: chat com skin.

### 4. Open source em ESP32 (o mesmo hardware do Body do Lupin)

- **xiaozhi-esp32** (licença MIT): firmware de chatbot de voz para ESP32, com mais de 170 releases e comunidade enorme. Fala com LLMs (Qwen, DeepSeek), tem wake word offline e controla dispositivos via **MCP**. É a referência técnica mais forte para o firmware do ESP32 do Lupin.
- **StackChan** (M5Stack, ESP32-S3): robozinho de mesa com tela, câmera e servos, open source, com "AI Agent", animações e OTA. Tem variantes que usam só serviços locais de STT, LLM e TTS.

**Padrão:** a parte de "ESP32 que conversa com um LLM" virou commodity. O diferencial não está aí.

### 5. Ambições e nichos

- **Razer Project AVA:** companheiro holográfico em um pote, previsto para o fim de 2026.
- **ElliQ:** companheiro para idosos.
- **Friend:** pingente que escuta tudo, o mais polêmico em privacidade.

## Onde o Lupin se encaixa

O Lupin fica no cruzamento que quase ninguém ocupa: o **personagem com corpo físico** dos grupos 1 e 4, com a **utilidade real no computador** dos grupos 2 e 3, e um **controle de privacidade explícito**.

| | Robôs companheiros | Autonomous Lamp | Taby | xiaozhi/StackChan | **Lupin** |
|---|---|---|---|---|---|
| Personagem com Mood/memória | ✅ | parcial | ✅ (leve) | parcial | ✅ (Mood, Affinity, Energy) |
| Corpo físico | ✅ | ✅ | DIY | ✅ | ✅ ESP32 + RG406H |
| Age no computador | ❌ | ✅ (agentes) | ✅ | via MCP | ✅ Shortcuts, Dock, Cowork |
| Escolha de LLM | ❌/parcial | ✅ | local + nuvem | ✅ | ✅ (Ollama, OpenAI, Gemini…) |
| Funciona offline | Eilik/Moflin | ❌ | ✅ | depende | ❌ (ainda) |
| Consentimento de dados por provider | ❌ | ❌ | "nada sai" | ❌ | ✅ (Data Consent) |
| Vários aparelhos, um personagem | ❌ | ❌ | ❌ | ❌ | ✅ (Active Body) |
| Preço | US$ 140–430 | US$ 699 | grátis / €9 | ~US$ 30–100 | hardware barato |

### Diferenciais reais do Lupin

1. **Brain separado do Body com um protocolo próprio.** Um Lupin só pode morar em vários aparelhos (ESP32, RG406H, mini-pet no Mac) sem aparecer em dois ao mesmo tempo, e você fala de qualquer aparelho. Nenhum concorrente faz isso.
2. **Ação com aprovação por risco.** Cowork Tasks com nível read/write/external, e escrita de Shortcuts só no Mac. Mais seguro que "o agente faz tudo".
3. **Privacidade concreta.** Agenda e e-mail só saem com Data Consent para um provider nomeado, e o consentimento cai sozinho se o provider mudar.
4. **Today que não inventa.** O First Wake é determinístico e não passa por LLM. É uma resposta direta ao problema de alucinação que quase todo assistente tem.
5. **Expressão local no Body.** O Body anima sozinho e o Brain só manda a Expression. Pela mesma razão que fez você rejeitar o streaming de pixels, a animação continua viva com Wi-Fi ruim.

### Lacunas comparando com o mercado

- **Offline:** o Taby funciona sem Wi-Fi. O Lupin depende do provider (o padrão é o proxy local, que encaminha para a nuvem) e de TTS no servidor. Um modo 100% local (Ollama + STT/TTS locais) seria um argumento forte.
- **Microfone e câmera no Body:** EMO, Loona e StackChan ouvem e enxergam pelo próprio corpo. O Lupin escuta pelo Mac.
- **Movimento:** o Lupin não se mexe fisicamente. Isso é escolha consciente (ADR 0001), mas vale assumir isso na apresentação.
- **Ecossistema de Skills e MCP:** a Lamp e o xiaozhi abrem para agentes externos via MCP. Expor o Lupin como servidor MCP (ou consumir MCP) o encaixaria nesse ecossistema.
- **Instalação:** os concorrentes saem da caixa funcionando. O Lupin hoje exige o setup do servidor, certificados etc.

## Para o portfólio

O que este projeto demonstra, e que vale destacar:

- **Arquitetura distribuída de verdade:** Brain/Body, um protocolo WebSocket versionado (`docs/protocolo-cerebro-corpo.md`), roteamento de Active Body e espelhamento de resposta.
- **Decisões documentadas:** ADRs com opções rejeitadas e o motivo, além de um glossário de domínio. Pouca gente mostra isso em projeto pessoal.
- **Segurança e privacidade como requisito:** `subprocess` com whitelist, nenhum segredo em logs, Data Consent ligado ao provider, Mac-only para escrita.
- **Testes:** suíte Python e frontend, com TDD nas features recentes.
- **Hardware + web + LLM no mesmo projeto:** firmware ESP32 (LVGL), web Body no RG406H e Electron no Mac.

Sugestões de apresentação:

1. **Um vídeo de 60–90 s** mostrando o First Wake no ESP32, você falando pelo RG406H e o Lupin respondendo no ESP32, e um Shortcut agindo no Mac. Nesse mercado, todo mundo vende pelo vídeo.
2. **Um README de vitrine:** um GIF do Lupin, o diagrama Brain/Body, a tabela comparativa acima (versão curta) e os três diferenciais.
3. **Usar o teste de três perguntas** da Autonomous como gancho: "um companheiro que passa no teste de robô que trabalha, a uma fração do preço".
4. **Um post técnico** sobre um problema específico: "por que o Today não usa LLM" ou "como um personagem mora em vários aparelhos sem se duplicar".

## Fontes

- [Best AI Desk Robots in 2026: Companions vs Work Bots (Autonomous)](https://www.autonomous.ai/ourblog/best-ai-desk-robots)
- [Best AI Companion Robots 2026 (Robot Review Desk)](https://robotreviewdesk.com/guides/best-ai-companion-robots-2026/)
- [AI Companion Robots in 2026 (PocketAnimus)](https://pocketanimus.com/guides/ai-companion-robots/)
- [Taby (heytaby.com)](https://www.heytaby.com)
- [xiaozhi-esp32 (GitHub)](https://github.com/78/xiaozhi-esp32)
- [StackChan (M5Stack docs)](https://docs.m5stack.com/en/StackChan/)
- Busca por pets de desktop com LLM: Nibbii, Desktop Pet, PetClaw, Ollama Pet, PawPal (resultados do DuckDuckGo)
