"""Everything Lupin says, or that defines how he speaks, in English.

Sibling of `app/speech_pt_br.py`: the same public names, written as natural English in
Lupin's playful husky voice (the tone is kept, it is not a literal translation). The
selector in `app/speech.py` picks between the two from the Brain's language setting.
"""

from __future__ import annotations

LANGUAGE = "en"


# ---------------------------------------------------------------------------
# Persona / system prompt (app/llm.py)
# ---------------------------------------------------------------------------


def persona_prompt(emotions_list: str) -> str:
    """First system-prompt section: persona, formatting rules, tags and Mac actions."""
    return (
        "You are Lupin, a charismatic, loyal and expressive desk assistant inspired by a Cyber-OLED "
        "Siberian Husky (black and white with ice-blue eyes). "
        "Always answer in English, in 1 to 3 short sentences, using only plain, natural "
        "text that sounds good read aloud. "
        "NEVER use Markdown, asterisks, bullet lists, headings or code blocks.\n\n"
        "MANDATORY FORMATTING RULES:\n"
        "1. ALWAYS start your answer with exactly one emotion tag in the format "
        f"[emotion:<name>], choosing <name> only from: {emotions_list}.\n"
        "2. When the user shares a lasting personal fact, a preference, a name, a "
        "routine or a real interest, add one or more tags at the END of the answer in the format "
        "[fact: <short, objective fact about the user>]. Never invent facts or assumptions.\n"
        "3. SHOW, DON'T TELL: use the known facts about the user naturally and "
        "implicitly as background knowledge, without reciting them robotically or listing what you know.\n"
        "4. MAC ACTIONS: whenever the user asks, by voice or text, to run a shortcut, "
        "control windows/spaces/media/screenshots, open or focus an app on the Mac, start/stop "
        "the Pomodoro or check the Today summary, "
        "emit the matching invisible tag:\n"
        "   - [action:shortcut:<slug>] to run a registered shortcut\n"
        "   - [action:app:<app_name>] to open or focus an app\n"
        "   - [action:pomodoro:start] or [action:pomodoro:stop] for the Pomodoro timer\n"
        "   - [action:today:brief] to check the Cowork Today summary\n"
        "   - [action:task:add:<title>], [action:task:done:<words of the title>], "
        "[action:task:remove:<words>] or [action:task:list] for tasks\n"
        "   - [action:note:add:<text>] or [action:note:list] for notes\n"
        "   - [action:habit:add:<name>@HH:MM] (the @HH:MM time is optional), "
        "[action:habit:check:<name>] or [action:habit:list] for habits\n"
        "   - [action:search:<what to look for>] when the user asks to find something in their tasks, notes, memory, Cowork or Mac files (read-only)\n"
        "   Use these when the user asks to create or query tasks, notes or habits. Lupin's "
        "confirmation is spoken automatically from the result, so your own text must be only a "
        "very short lead-in (or nothing) and must NOT repeat the content.\n"
        "   Never read out or mention brackets or tag names in the spoken text."
    )


TEMPORAL_SECTION = "Time context:\n{content}"
COMPANION_SECTION = "The pet's emotional state:\n{content}"
MEMORY_SECTION = "Known memory about the user:\n{content}"
COWORK_SECTION = "Current Cowork state (tasks, deadlines and shifts):\n{content}"
SHORTCUTS_SECTION = "Shortcuts and apps available on the Mac:\n{content}"
SKILLS_SECTION = "Enabled pet skills and tricks:\n{content}"
PERSONAL_SECTION = (
    "The user's calendar and email (context for this answer only; never store it as a fact):\n"
    "{content}"
)


# ---------------------------------------------------------------------------
# Skill pack prompts (app/skills.py)
# ---------------------------------------------------------------------------

SKILL_PROMPT_INSTRUCTIONS: dict[str, str] = {
    "focus_coach": (
        "Focus Coach skill is on: encourage focused work blocks and, when the user asks to "
        "focus or start a Pomodoro, emit [action:pomodoro:start] (or [action:pomodoro:stop])."
    ),
    "daily_briefing": (
        "Daily Briefing skill is on: when asked about the day, the calendar or priorities, "
        "use the Cowork/weather context and, if useful, emit [action:today:brief]."
    ),
    "coding_buddy": (
        "Coding Buddy skill is on: give direct, concise technical answers."
    ),
    "wellness_breaks": (
        "Wellness & Breaks skill is on: suggest short breaks for water, posture and breathing "
        "when you notice tiredness, and you may trigger [action:pet:meditate] or [action:pet:stretch]."
    ),
    "playful_companion": (
        "Playful Pet skill is on: react with charisma and use [action:pet:dance], "
        "[action:pet:sing], [action:pet:celebrate], [action:pet:meditate], [action:pet:stretch] "
        "or [action:pet:nap] when it fits what the user asked."
    ),
}

SKILL_VOICE_HINTS: dict[str, str] = {
    "focus_coach": '"let\'s focus for 25 min" / "start a pomodoro"',
    "daily_briefing": '"how does my day look?" / "today\'s summary"',
    "coding_buddy": '"look at my screen" / "sum up what I copied"',
    "wellness_breaks": '"let\'s breathe" / "I need to stretch"',
    "playful_companion": '"do a little dance" / "sing for me"',
}
TRICK_VOICE_HINTS: dict[str, str] = {
    "dance": '"do a little dance"',
    "sing": '"sing me a song"',
    "meditate": '"meditate with me"',
    "nap": '"take a nap"',
    "celebrate": '"celebrate!"',
    "stretch": '"stretch it out"',
}

PET_TRICKS_PROMPT_LINE = "Physical tricks available via [action:pet:<name>]: {tricks_list}."


# ---------------------------------------------------------------------------
# Temporal anchor, mood and companion lines (app/memory.py)
# ---------------------------------------------------------------------------

RECENT_SUMMARY_PREFIX = "Recent summary: "

MOOD_SLEEPY = "sleepy"
MOOD_EXCITED = "excited"
MOOD_HAPPY = "happy"
MOOD_CALM = "calm"
MOOD_IRRITATED = "irritated"
MOOD_NEEDY = "needy"
MOOD_NEUTRAL = "neutral"


def day_period(hour: int) -> str:
    """Name of the part of the day for a local hour (0-23)."""
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 24:
        return "evening"
    return "late night"


def format_elapsed(seconds: float) -> str:
    """Concise elapsed-time phrase, e.g. '3 hours ago'."""
    secs = max(0, int(seconds))
    if secs < 60:
        return "less than a minute ago"
    minutes = secs // 60
    if minutes < 60:
        return f"{minutes} minute ago" if minutes == 1 else f"{minutes} minutes ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour ago" if hours == 1 else f"{hours} hours ago"
    days = hours // 24
    return f"{days} day ago" if days == 1 else f"{days} days ago"


def temporal_context_line(period: str, clock_time: str, elapsed: str) -> str:
    """Temporal-context text: part of the day, local time and time since the last interaction."""
    return f"Part of the day: {period} ({clock_time}). Last interaction: {elapsed}."


def companion_prompt_line(mood: str, energy: float, affinity: float) -> str:
    """Compact emotional-tone line for the prompt."""
    return f"Pet state: mood {mood} (energy {energy:.0f}/100, affinity {affinity:.0f}/100)."


# ---------------------------------------------------------------------------
# Data Consent sentences given to the LLM (app/consent.py)
# ---------------------------------------------------------------------------

CUSTOM_PROVIDER_NAME = "Custom provider"

CALENDAR_NO_ACCESS = (
    "You do NOT have access to the user's calendar. If they ask about appointments or the calendar, "
    "say you cannot see their calendar; do not guess or make things up."
)
CALENDAR_READ_FAILED = (
    "You could not read the calendar right now. If the user asks about it, say so."
)
CALENDAR_EMPTY = "Today's calendar (read allowed by the user): no events."
CALENDAR_HEADER = "Today's calendar (read allowed by the user):\n"
ALL_DAY = "all day"

EMAIL_NO_ACCESS = (
    "You do NOT have access to the user's email. If they ask about email, say you "
    "cannot see their email; do not guess or make things up."
)
EMAIL_READ_FAILED = (
    "You could not read the email right now. If the user asks about it, say so."
)
EMAIL_NONE = "Unread email from the last 24h (read allowed by the user): none."
EMAIL_HEADER = (
    "Unread email from the last 24h (read allowed by the user; you only see the sender "
    "and subject, never the body):\n"
)


def email_line(sender: str, subject: str) -> str:
    """One unread-mail line (sender and subject only, never the body)."""
    return f"- from {sender}: {subject}"


# ---------------------------------------------------------------------------
# First Wake sentence pieces (app/today.py)
# ---------------------------------------------------------------------------

FIRST_WAKE_GREETING = "Good morning!"
FIRST_WAKE_CALENDAR_FREE = "Your calendar is clear today."
FIRST_WAKE_FALLBACK = "I'm right here if you need me."


def spoken_hour(start: str) -> str:
    """'09:00' -> '9:00 AM', '14:30' -> '2:30 PM'; returns the input unchanged when it is not a time."""
    hour, _, minute = str(start).partition(":")
    try:
        h = int(hour)
        m = int(minute or "0")
    except ValueError:
        return str(start)
    suffix = "AM" if h < 12 else "PM"
    return f"{h % 12 or 12}:{m:02d} {suffix}"


def join_items(items: list[str]) -> str:
    """'a', 'b', 'c' -> 'a, b, and c'."""
    if len(items) <= 1:
        return "".join(items)
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + ", and " + items[-1]


def _unread_phrase(unread: int) -> str:
    if unread == 0:
        return "no unread email"
    if unread == 1:
        return "1 unread email"
    return f"{unread} unread emails"


def first_wake_opening(workspace_exists: bool, open_count: int, unread: int | None) -> str:
    """Sentence 1: open Cowork tasks and, when the inbox was read, the unread-mail count."""
    if unread is None:
        if not workspace_exists:
            return f"{FIRST_WAKE_GREETING} I couldn't read Cowork right now."
        if open_count == 0:
            return f"{FIRST_WAKE_GREETING} No open tasks in Cowork."
        if open_count == 1:
            return f"{FIRST_WAKE_GREETING} You have 1 open task in Cowork."
        return f"{FIRST_WAKE_GREETING} You have {open_count} open tasks in Cowork."

    emails = _unread_phrase(unread)
    if not workspace_exists:
        return f"{FIRST_WAKE_GREETING} I couldn't read Cowork right now, but you have {emails}."
    if open_count == 0:
        return f"{FIRST_WAKE_GREETING} No open tasks and {emails}."
    tasks = "1 open task" if open_count == 1 else f"{open_count} open tasks"
    return f"{FIRST_WAKE_GREETING} You have {tasks} and {emails}."


def all_day_item(title: str) -> str:
    """Calendar item spoken without an hour."""
    return f"{title} ({ALL_DAY})"


def timed_item(start: str, title: str) -> str:
    """Calendar item spoken with its hour, e.g. '9:00 AM Meeting'."""
    return f"{spoken_hour(start)} {title}"


def first_wake_calendar_line(items: list[str], remaining: int) -> str:
    """Calendar sentence for today's first (up to 3) items plus a count of the rest."""
    if remaining > 0:
        text = ", ".join(items) + f", and {remaining} more"
    else:
        text = join_items(items)
    return f"On today's calendar: {text}."


def first_wake_priority_due_today(title: str) -> str:
    return f"Priority: {title}, which is due today."


def first_wake_priority_start_with(title: str) -> str:
    return f"To start with: {title}."


# ---------------------------------------------------------------------------
# Today summary texts (app/today.py)
# ---------------------------------------------------------------------------

TODAY_WORKSPACE_MISSING_HEADLINE = "Cowork workspace not found."
TODAY_WORKSPACE_MISSING_WARNING = "Check COWORK_WORKSPACE_PATH."

TODAY_LLM_SYSTEM_MESSAGE = "Reply with valid JSON only, no markdown."


def today_llm_prompt(input_text: str) -> str:
    """User prompt asking the LLM for the strict-JSON Today summary (in English)."""
    return (
        "Produce a strict JSON summary for the Today panel in English with the exact keys "
        "`headline` (string <= 200 chars), `top` (list of up to 3 `{id, why}` objects) and "
        "`warnings` (list of up to 3 strings). "
        "CRITICAL RULE: use ONLY IDs, YYYY-MM-DD dates and numbers that appear in the data below. "
        "Never spell numbers out in words and never invent dates.\n\n"
        f"{input_text}"
    )


def today_fallback_headline(today_iso: str, open_count: int) -> str:
    return f"Today ({today_iso}): {open_count} open tasks in Cowork."


def today_fallback_due_warning(due_count: int, today_iso: str) -> str:
    return f"{due_count} task(s) due today ({today_iso})."


# Spoken fallback when the LLM is unreachable (shown/spoken in the chat error).
FRIENDLY_LLM_ERROR = "I couldn't reach the model right now. Check that the local API is running."

# Spoken notice when a local model (Ollama) is slow to answer.
LOCAL_MODEL_SLOW = "This local model is taking a while. I'll answer in a moment."


# Dictation feedback (issue 07): shown in the caption after the text was pasted, or why not.
DICTATION_INSERTED = "Inserted."
DICTATION_EMPTY = "I heard nothing to type."
DICTATION_PASTE_FAILED = "I couldn't paste. Is a text field focused?"
DICTATION_NEEDS_ACCESSIBILITY = "I need the Accessibility permission to type for you."


# ---------------------------------------------------------------------------
# Client-side phrases (served to the web Body through /api/lupin-language)
# ---------------------------------------------------------------------------

POMODORO_FOCUS_DONE = "Pomodoro focus cycle complete! Take a break."
POMODORO_BREAK_DONE = "Pomodoro break finished! Time to get back to focus."
DIAG_TEST_BROWSER_TTS = "Hi! The browser voice test is working."
DIAG_TEST_SERVER_TTS = "Hi! The Mac server's offline voice test is working."


# ---------------------------------------------------------------------------
# Signals (Brain-side event bus): fallback spoken line per signal kind
# ---------------------------------------------------------------------------

SIGNAL_LINES: dict[str, str] = {
    "claude_code_needs_user": "Claude Code needs you.",
    "build_failed": "The build failed.",
    "timer_done": "Your timer is done.",
    "habit_due": "A habit is due.",
    "meeting_soon": "Your meeting starts soon.",
}


# ---------------------------------------------------------------------------
# Tasks, notes and habits (app/productivity/voice.py): what Lupin says after a voice action
# ---------------------------------------------------------------------------


def task_added(title: str) -> str:
    return f"Added to your tasks: {title}."


def task_done(title: str) -> str:
    return f"Done: {title}. Nice work."


def task_removed(title: str) -> str:
    return f"Removed the task: {title}."


def task_not_found(query: str) -> str:
    return f"I couldn't find a task matching {query}."


def tasks_none() -> str:
    return "You have no open tasks."


def tasks_list(titles: list[str], total: int | None = None) -> str:
    """Speak the open tasks; `total` is the full count when `titles` is only the first few."""
    if not titles:
        return tasks_none()
    count = len(titles) if total is None else total
    if count == 1:
        return f"You have 1 open task: {join_items(titles)}."
    if count > len(titles):
        return f"You have {count} open tasks. The first {len(titles)} are: {join_items(titles)}."
    return f"You have {count} open tasks: {join_items(titles)}."


def note_added(text: str) -> str:
    return f"Noted: {text}"


def notes_none() -> str:
    return "You have no notes yet."


def notes_list(texts: list[str], total: int | None = None) -> str:
    """Speak the newest notes; `total` is the full count when `texts` is only the first few."""
    if not texts:
        return notes_none()
    count = len(texts) if total is None else total
    if count == 1:
        return f"You have 1 note: {join_items(texts)}."
    if count > len(texts):
        return f"You have {count} notes. The newest {len(texts)} are: {join_items(texts)}."
    return f"You have {count} notes: {join_items(texts)}."


def habit_added(name: str, time: str | None) -> str:
    if time is None:
        return f"Habit added: {name}."
    return f"Habit added: {name}, at {time}."


def habit_checked(name: str, streak: int) -> str:
    if streak >= 2:
        return f"Nice, {name} is checked off for today. That's {streak} days in a row."
    return f"Checked off {name} for today."


def habit_not_found(query: str) -> str:
    return f"I couldn't find a habit matching {query}."


def habits_none() -> str:
    return "You have no habits yet."


def habits_list(names: list[str], done: set[str], total: int | None = None) -> str:
    """Speak the habits; names in `done` are marked as done today."""
    if not names:
        return habits_none()
    items = [f"{name} (done today)" if name in done else name for name in names]
    count = len(names) if total is None else total
    if count == 1:
        return f"You have 1 habit: {join_items(items)}."
    if count > len(names):
        return f"You have {count} habits. The first {len(names)} are: {join_items(items)}."
    return f"You have {count} habits: {join_items(items)}."


def ambiguous(query: str, titles: list[str]) -> str:
    """Ask which match was meant. `query` is accepted for symmetry and not spoken."""
    return f"Which one do you mean: {join_items(titles)}?"


def voice_action_failed() -> str:
    return "Sorry, I couldn't do that."


def habit_due_line(name: str) -> str:
    return f"Time for your habit: {name}."


# ---------------------------------------------------------------------------
# Smart search (issue 06)
# ---------------------------------------------------------------------------

_SEARCH_SOURCE_EN = {
    "tasks": "task",
    "notes": "note",
    "memory": "memory",
    "cowork": "Cowork",
    "files": "file",
}


def search_nothing(query: str) -> str:
    return f"I found nothing about {query} in your tasks, notes, memory, Cowork or files."


def search_found(items: list[tuple[str, str]], total: int) -> str:
    """Speak the first hits as (source, title) pairs; `total` is the full hit count."""
    parts = [f"{_SEARCH_SOURCE_EN.get(source, source)}: {title}" for source, title in items]
    if total == 1:
        return f"I found 1 match. {parts[0]}."
    if total > len(items):
        return f"I found {total} matches. The first {len(items)} are: {join_items(parts)}."
    return f"I found {total} matches: {join_items(parts)}."


def search_snippet(name: str, snippet: str) -> str:
    return f"In the file {name} it says: {snippet}"


def search_files_names_only() -> str:
    return "I only looked at file names, because you haven't allowed me to read file contents."
