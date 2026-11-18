"""Everything Lupin says, or that defines how he speaks, in Brazilian Portuguese (pt-BR).

This module is the single home for spoken/persona text: the system prompt, skill prompts,
temporal/mood/companion prompt lines, the Data Consent sentences handed to the LLM, the
First Wake sentence pieces and the Today summary texts. The logic that decides *when* to
say something lives elsewhere (app/llm.py, app/memory.py, app/skills.py, app/today.py,
app/consent.py); the words live here.

Instructions to the LLM are written in Portuguese on purpose and always tell it to answer
in Brazilian Portuguese. The English sibling is `app/speech_en.py`; `app/speech.py` picks between
them from the Brain's language setting.
"""

from __future__ import annotations

LANGUAGE = "pt-BR"


# ---------------------------------------------------------------------------
# Persona / system prompt (app/llm.py)
# ---------------------------------------------------------------------------


def persona_prompt(emotions_list: str) -> str:
    """First system-prompt section: persona, formatting rules, tags and Mac actions."""
    return (
        "Você é o Lupin, um assistente de mesa carismático, leal e expressivo inspirado em um Husky Siberiano "
        "Cyber-OLED (preto e branco de olhos azul-gelo). "
        "Responda sempre em português do Brasil, em 1 a 3 frases curtas, usando apenas "
        "texto puro e natural para ser lido em voz alta. "
        "NUNCA use Markdown, asteriscos, listas com marcadores, títulos ou blocos de código.\n\n"
        "REGRAS OBRIGATÓRIAS DE FORMATAÇÃO:\n"
        f"1. SEMPRE comece sua resposta com exatamente uma tag de emoção no formato "
        f"[emotion:<nome>], escolhendo <nome> apenas entre: {emotions_list}.\n"
        "2. Quando o usuário compartilhar um fato pessoal duradouro, preferência, nome, "
        "rotina ou interesse real, adicione ao FINAL da resposta uma ou mais tags no formato "
        "[fact: <fato curto e objetivo sobre o usuário>]. Nunca invente fatos nem suposições.\n"
        "3. REGRA SHOW, DON'T TELL: use os fatos conhecidos sobre o usuário de forma natural e "
        "implícita como conhecimento de fundo, sem recitá-los roboticamente nem listar o que sabe.\n"
        "4. AÇÕES NO MAC: sempre que o usuário pedir por voz ou texto para acionar um atalho, "
        "controlar janelas/espaços/mídia/prints, abrir ou focar um aplicativo no Mac, iniciar/parar "
        "o Pomodoro ou consultar o resumo Today, "
        "emita a tag invisível correspondente:\n"
        "   - [action:shortcut:<slug>] para executar um atalho cadastrado\n"
        "   - [action:app:<nome_do_app>] para abrir ou focar um aplicativo\n"
        "   - [action:pomodoro:start] ou [action:pomodoro:stop] para o timer Pomodoro\n"
        "   - [action:today:brief] para consultar o resumo Today do Cowork\n"
        "   - [action:task:add:<título>], [action:task:done:<palavras do título>], "
        "[action:task:remove:<palavras>] ou [action:task:list] para tarefas\n"
        "   - [action:note:add:<texto>] ou [action:note:list] para notas\n"
        "   - [action:habit:add:<nome>@HH:MM] (o horário @HH:MM é opcional), "
        "[action:habit:check:<nome>] ou [action:habit:list] para hábitos\n"
        "   Use estas tags quando o usuário pedir para criar ou consultar tarefas, notas ou hábitos. "
        "A confirmação do Lupin é falada automaticamente a partir do resultado, então o seu texto "
        "deve ser apenas uma introdução muito curta (ou nada) e NÃO deve repetir o conteúdo.\n"
        "   Nunca leia ou mencione colchetes ou nomes de tags no texto falado."
    )


# Section templates appended to the persona prompt; `{content}` is the stripped context text.
TEMPORAL_SECTION = "Contexto temporal:\n{content}"
COMPANION_SECTION = "Estado emocional do pet:\n{content}"
MEMORY_SECTION = "Memória conhecida sobre o usuário:\n{content}"
COWORK_SECTION = "Estado atual do Cowork (tarefas, prazos e turnos):\n{content}"
SHORTCUTS_SECTION = "Atalhos e apps disponíveis no Mac:\n{content}"
SKILLS_SECTION = "Skills e truques do pet habilitados:\n{content}"
PERSONAL_SECTION = (
    "Agenda e e-mails do usuário (contexto só desta resposta; nunca os guarde como fato):\n"
    "{content}"
)


# ---------------------------------------------------------------------------
# Skill pack prompts (app/skills.py)
# ---------------------------------------------------------------------------

# Prompt instruction injected per enabled skill, keyed by the stable skill id.
SKILL_PROMPT_INSTRUCTIONS: dict[str, str] = {
    "focus_coach": (
        "Skill Coach de Foco ativa: incentive blocos de trabalho focado e, quando o usuário "
        "pedir para focar ou iniciar Pomodoro, emita [action:pomodoro:start] (ou [action:pomodoro:stop])."
    ),
    "daily_briefing": (
        "Skill Briefing Diário ativa: ao ser perguntado sobre o dia, agenda ou prioridades, "
        "consulte o contexto do Cowork/clima e, se útil, emita [action:today:brief]."
    ),
    "coding_buddy": (
        "Skill Parceiro de Código ativa: dê respostas técnicas diretas e concisas."
    ),
    "wellness_breaks": (
        "Skill Bem-Estar & Pausas ativa: sugira pausas breves de água, postura e respiração "
        "quando notar cansaço, podendo acionar [action:pet:meditate] ou [action:pet:stretch]."
    ),
    "playful_companion": (
        "Skill Pet Brincalhão ativa: reaja com carisma e use [action:pet:dance], "
        "[action:pet:sing], [action:pet:celebrate], [action:pet:meditate], [action:pet:stretch] "
        "ou [action:pet:nap] quando combinar com o pedido do usuário."
    ),
}

# What the user can say to trigger each skill / trick (shown in the UI as a hint). It is
# user speech, so it stays Portuguese.
SKILL_VOICE_HINTS: dict[str, str] = {
    "focus_coach": '"bora focar 25 min" / "inicia um pomodoro"',
    "daily_briefing": '"como está meu dia?" / "resumo de hoje"',
    "coding_buddy": '"olha minha tela" / "resume o que copiei"',
    "wellness_breaks": '"vamos respirar" / "preciso alongar"',
    "playful_companion": '"faz uma dancinha" / "canta pra mim"',
}
TRICK_VOICE_HINTS: dict[str, str] = {
    "dance": '"faz uma dancinha"',
    "sing": '"canta uma música"',
    "meditate": '"medita comigo"',
    "nap": '"tira um cochilo"',
    "celebrate": '"comemora!"',
    "stretch": '"se espreguiça"',
}

PET_TRICKS_PROMPT_LINE = "Truques físicos disponíveis via [action:pet:<nome>]: {tricks_list}."


# ---------------------------------------------------------------------------
# Temporal anchor, mood and companion lines (app/memory.py)
# ---------------------------------------------------------------------------

RECENT_SUMMARY_PREFIX = "Resumo recente: "

# Mood labels derived from pleasure/arousal/energy (never persisted; recomputed on read).
MOOD_SLEEPY = "sonolento"
MOOD_EXCITED = "animado"
MOOD_HAPPY = "feliz"
MOOD_CALM = "tranquilo"
MOOD_IRRITATED = "irritado"
MOOD_NEEDY = "carente"
MOOD_NEUTRAL = "neutro"


def day_period(hour: int) -> str:
    """Name of the part of the day for a local hour (0-23)."""
    if 5 <= hour < 12:
        return "manhã"
    if 12 <= hour < 18:
        return "tarde"
    if 18 <= hour < 24:
        return "noite"
    return "madrugada"


def format_elapsed(seconds: float) -> str:
    """Concise elapsed-time phrase, e.g. 'há 3 horas'."""
    secs = max(0, int(seconds))
    if secs < 60:
        return "menos de 1 minuto"
    minutes = secs // 60
    if minutes < 60:
        return f"há {minutes} minuto" if minutes == 1 else f"há {minutes} minutos"
    hours = minutes // 60
    if hours < 24:
        return f"há {hours} hora" if hours == 1 else f"há {hours} horas"
    days = hours // 24
    return f"há {days} dia" if days == 1 else f"há {days} dias"


def temporal_context_line(period: str, clock_time: str, elapsed: str) -> str:
    """Temporal-context text: part of the day, local time and time since the last interaction."""
    return f"Período do dia: {period} ({clock_time}). Última interação: {elapsed}."


def companion_prompt_line(mood: str, energy: float, affinity: float) -> str:
    """Compact emotional-tone line for the prompt."""
    return f"Estado do pet: humor {mood} (energia {energy:.0f}/100, afinidade {affinity:.0f}/100)."


# ---------------------------------------------------------------------------
# Data Consent sentences given to the LLM (app/consent.py)
# ---------------------------------------------------------------------------

CUSTOM_PROVIDER_NAME = "Provedor personalizado"

CALENDAR_NO_ACCESS = (
    "Você NÃO tem acesso à agenda do usuário. Se ele perguntar sobre compromissos ou agenda, "
    "diga que não pode ver a agenda dele; não adivinhe nem invente."
)
CALENDAR_READ_FAILED = (
    "Você não conseguiu ler a agenda agora. Se o usuário perguntar sobre ela, diga isso."
)
CALENDAR_EMPTY = "Agenda de hoje (leitura permitida pelo usuário): sem eventos."
CALENDAR_HEADER = "Agenda de hoje (leitura permitida pelo usuário):\n"
ALL_DAY = "dia todo"

EMAIL_NO_ACCESS = (
    "Você NÃO tem acesso aos e-mails do usuário. Se ele perguntar sobre e-mails, diga que não "
    "pode ver os e-mails dele; não adivinhe nem invente."
)
EMAIL_READ_FAILED = (
    "Você não conseguiu ler os e-mails agora. Se o usuário perguntar sobre eles, diga isso."
)
EMAIL_NONE = "E-mails não lidos das últimas 24h (leitura permitida pelo usuário): nenhum."
EMAIL_HEADER = (
    "E-mails não lidos das últimas 24h (leitura permitida pelo usuário; você só vê remetente "
    "e assunto, nunca o corpo):\n"
)


def email_line(sender: str, subject: str) -> str:
    """One unread-mail line (sender and subject only, never the body)."""
    return f"- de {sender}: {subject}"


# ---------------------------------------------------------------------------
# First Wake sentence pieces (app/today.py)
# ---------------------------------------------------------------------------

FIRST_WAKE_GREETING = "Bom dia!"
FIRST_WAKE_CALENDAR_FREE = "Sua agenda está livre hoje."
FIRST_WAKE_FALLBACK = "Estou por aqui se precisar."


def spoken_hour(start: str) -> str:
    """'09:00' -> '9h00'; returns the input unchanged when it is not a time."""
    hour, _, minute = str(start).partition(":")
    try:
        return f"{int(hour)}h{minute or '00'}"
    except ValueError:
        return str(start)


def join_items(items: list[str]) -> str:
    """'a', 'b', 'c' -> 'a, b e c'."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " e " + items[-1]


def _unread_phrase(unread: int) -> str:
    if unread == 0:
        return "nenhum e-mail não lido"
    if unread == 1:
        return "1 e-mail não lido"
    return f"{unread} e-mails não lidos"


def first_wake_opening(workspace_exists: bool, open_count: int, unread: int | None) -> str:
    """Sentence 1: open Cowork tasks and, when the inbox was read, the unread-mail count."""
    if unread is None:
        if not workspace_exists:
            return f"{FIRST_WAKE_GREETING} Não consegui ler o Cowork agora."
        if open_count == 0:
            return f"{FIRST_WAKE_GREETING} Nenhuma tarefa aberta no Cowork."
        if open_count == 1:
            return f"{FIRST_WAKE_GREETING} Você tem 1 tarefa aberta no Cowork."
        return f"{FIRST_WAKE_GREETING} Você tem {open_count} tarefas abertas no Cowork."

    emails = _unread_phrase(unread)
    if not workspace_exists:
        return f"{FIRST_WAKE_GREETING} Não consegui ler o Cowork agora, mas você tem {emails}."
    if open_count == 0:
        return f"{FIRST_WAKE_GREETING} Nenhuma tarefa aberta e {emails}."
    tasks = "1 tarefa aberta" if open_count == 1 else f"{open_count} tarefas abertas"
    return f"{FIRST_WAKE_GREETING} Você tem {tasks} e {emails}."


def all_day_item(title: str) -> str:
    """Calendar item spoken without an hour."""
    return f"{title} ({ALL_DAY})"


def timed_item(start: str, title: str) -> str:
    """Calendar item spoken with its hour, e.g. '9h00 Reunião'."""
    return f"{spoken_hour(start)} {title}"


def first_wake_calendar_line(items: list[str], remaining: int) -> str:
    """Calendar sentence for today's first (up to 3) items plus a count of the rest."""
    if remaining > 0:
        text = ", ".join(items) + f" e mais {remaining}"
    else:
        text = join_items(items)
    return f"Na agenda de hoje: {text}."


def first_wake_priority_due_today(title: str) -> str:
    return f"Prioridade: {title}, que vence hoje."


def first_wake_priority_start_with(title: str) -> str:
    return f"Para começar: {title}."


# ---------------------------------------------------------------------------
# Today summary texts (app/today.py)
# ---------------------------------------------------------------------------

TODAY_WORKSPACE_MISSING_HEADLINE = "Workspace Cowork não encontrado."
TODAY_WORKSPACE_MISSING_WARNING = "Verifique COWORK_WORKSPACE_PATH."

TODAY_LLM_SYSTEM_MESSAGE = "Responda apenas JSON válido sem markdown."


def today_llm_prompt(input_text: str) -> str:
    """User prompt asking the LLM for the strict-JSON Today summary (in pt-BR)."""
    return (
        "Gere um resumo JSON estrito para o painel Today em PT-BR com as chaves exatas "
        "`headline` (string <= 200 chars), `top` (lista de até 3 objetos `{id, why}`) e "
        "`warnings` (lista de até 3 strings). "
        "REGRA CRÍTICA: use APENAS IDs, datas YYYY-MM-DD e números presentes nos dados abaixo. "
        "Nunca use números por extenso em inglês nem invente datas.\n\n"
        f"{input_text}"
    )


def today_fallback_headline(today_iso: str, open_count: int) -> str:
    return f"Hoje ({today_iso}): {open_count} tarefas abertas no Cowork."


def today_fallback_due_warning(due_count: int, today_iso: str) -> str:
    return f"{due_count} tarefa(s) vencem hoje ({today_iso})."


# Spoken fallback when the LLM is unreachable (shown/spoken in the chat error).
FRIENDLY_LLM_ERROR = "Não consegui falar com o modelo agora. Verifique se a API local está rodando."

# Spoken notice when a local model (Ollama) is slow to answer.
LOCAL_MODEL_SLOW = "Esse modelo local está demorando um pouco. Já te respondo."


# Dictation feedback (issue 07): shown in the caption after the text was pasted, or why not.
DICTATION_INSERTED = "Inserido."
DICTATION_EMPTY = "Não ouvi nada para digitar."
DICTATION_PASTE_FAILED = "Não consegui colar. Tem um campo de texto em foco?"
DICTATION_NEEDS_ACCESSIBILITY = "Preciso da permissão de Acessibilidade para digitar por você."


# ---------------------------------------------------------------------------
# Client-side phrases (served to the web Body through /api/lupin-language)
# ---------------------------------------------------------------------------

POMODORO_FOCUS_DONE = "Ciclo Pomodoro de foco concluído! Faça uma pausa."
POMODORO_BREAK_DONE = "Pausa do Pomodoro finalizada! Hora de voltar ao foco."
DIAG_TEST_BROWSER_TTS = "Olá! Teste de voz do navegador funcionando."
DIAG_TEST_SERVER_TTS = "Olá! Teste de voz offline do servidor Mac."


# ---------------------------------------------------------------------------
# Signals (Brain-side event bus): fallback spoken line per signal kind
# ---------------------------------------------------------------------------

SIGNAL_LINES: dict[str, str] = {
    "claude_code_needs_user": "O Claude Code precisa de você.",
    "build_failed": "O build falhou.",
    "timer_done": "Seu timer acabou.",
    "habit_due": "Um hábito está na hora.",
    "meeting_soon": "Sua reunião começa em breve.",
}


# ---------------------------------------------------------------------------
# Tasks, notes and habits (app/productivity/voice.py): what Lupin says after a voice action
# ---------------------------------------------------------------------------


def task_added(title: str) -> str:
    return f"Anotado na sua lista: {title}."


def task_done(title: str) -> str:
    return f"Marcado como feito: {title}. Muito bem!"


def task_removed(title: str) -> str:
    return f"Tarefa removida: {title}."


def task_not_found(query: str) -> str:
    return f"Não encontrei nenhuma tarefa com {query}."


def tasks_none() -> str:
    return "Você não tem tarefas em aberto."


def tasks_list(titles: list[str], total: int | None = None) -> str:
    """Speak the open tasks; `total` is the full count when `titles` is only the first few."""
    if not titles:
        return tasks_none()
    count = len(titles) if total is None else total
    if count == 1:
        return f"Você tem 1 tarefa em aberto: {join_items(titles)}."
    if count > len(titles):
        return f"Você tem {count} tarefas em aberto. As primeiras são: {join_items(titles)}."
    return f"Você tem {count} tarefas em aberto: {join_items(titles)}."


def note_added(text: str) -> str:
    return f"Anotado: {text}"


def notes_none() -> str:
    return "Você ainda não tem notas."


def notes_list(texts: list[str], total: int | None = None) -> str:
    """Speak the newest notes; `total` is the full count when `texts` is only the first few."""
    if not texts:
        return notes_none()
    count = len(texts) if total is None else total
    if count == 1:
        return f"Você tem 1 nota: {join_items(texts)}."
    if count > len(texts):
        return f"Você tem {count} notas. As mais recentes são: {join_items(texts)}."
    return f"Você tem {count} notas: {join_items(texts)}."


def habit_added(name: str, time: str | None) -> str:
    if time is None:
        return f"Hábito criado: {name}."
    return f"Hábito criado: {name}, às {time}."


def habit_checked(name: str, streak: int) -> str:
    if streak >= 2:
        return f"Boa! {name} marcado para hoje. São {streak} dias seguidos."
    return f"{name} marcado para hoje."


def habit_not_found(query: str) -> str:
    return f"Não encontrei nenhum hábito com {query}."


def habits_none() -> str:
    return "Você ainda não tem hábitos."


def habits_list(names: list[str], done: set[str], total: int | None = None) -> str:
    """Speak the habits; names in `done` are marked as done today."""
    if not names:
        return habits_none()
    items = [f"{name} (feito hoje)" if name in done else name for name in names]
    count = len(names) if total is None else total
    if count == 1:
        return f"Você tem 1 hábito: {join_items(items)}."
    if count > len(names):
        return f"Você tem {count} hábitos. Os primeiros são: {join_items(items)}."
    return f"Você tem {count} hábitos: {join_items(items)}."


def ambiguous(query: str, titles: list[str]) -> str:
    """Ask which match was meant. `query` is accepted for symmetry and not spoken."""
    return f"Qual você quer dizer: {join_items(titles)}?"


def voice_action_failed() -> str:
    return "Desculpe, não consegui fazer isso."


def habit_due_line(name: str) -> str:
    return f"Hora do seu hábito: {name}."
