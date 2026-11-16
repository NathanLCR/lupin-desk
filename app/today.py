"""Motor do resumo Today com validação anti-alucinação e rastreamento de First Wake."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import httpx

from app.config import Settings
from app.cowork import CoworkStore
from app.memory import MemoryStore

logger = logging.getLogger(__name__)

_NUMBER_WORDS_RE = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|"
    r"fifty|sixty|seventy|eighty|ninety|hundred)\b",
    re.IGNORECASE,
)
_MONTH_NAMES = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
_DAY_MONTH_RE = re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{_MONTH_NAMES})\b", re.IGNORECASE)
_MONTH_DAY_RE = re.compile(rf"\b(?:{_MONTH_NAMES})\s+\d{{1,2}}(?:st|nd|rd|th)?\b", re.IGNORECASE)
_SLASHED_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b")
_ORDINAL_DAY_RE = re.compile(r"\b(?:[1-9]|[12]\d|3[01])(?:st|nd|rd|th)\b", re.IGNORECASE)
_RELATIVE_WEEKDAY_RE = re.compile(
    r"\b(?:next|this|last)\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9-])\d+(?:\.\d+)?(?![A-Za-z0-9-])")


@dataclass
class ValidationContext:
    """Conjunto de fatos permitidos extraídos do estado real do Cowork."""

    allowed_ids: set[str] = field(default_factory=set)
    allowed_iso_dates: set[str] = field(default_factory=set)
    allowed_numbers: set[int] = field(default_factory=set)
    input_text: str = ""


def is_valid_calendar_date(date_str: str) -> bool:
    """Valida se `YYYY-MM-DD` é uma data real no calendário."""
    try:
        date.fromisoformat(date_str)
        return True
    except ValueError:
        return False


def find_unverifiable_date_pattern(text: str) -> str | None:
    """Detecta formatos de data não-ISO que podem mascarar alucinação."""
    for regex in (
        _DAY_MONTH_RE,
        _MONTH_DAY_RE,
        _SLASHED_DATE_RE,
        _ORDINAL_DAY_RE,
        _RELATIVE_WEEKDAY_RE,
    ):
        match = regex.search(text)
        if match:
            return match.group(0)
    return None


def scrub_quoted_date_phrases(text: str, input_text: str | None) -> tuple[str, str | None]:
    """Remove frases de data não-ISO apenas quando aparecem literalmente no texto-fonte."""
    scrubbed = text
    for _ in range(100):
        found = find_unverifiable_date_pattern(scrubbed)
        if not found:
            return scrubbed, None
        phrase_re = re.compile(rf"(?<![A-Za-z0-9]){re.escape(found)}(?![A-Za-z0-9])", re.IGNORECASE)
        if not input_text or not phrase_re.search(input_text):
            return scrubbed, found
        scrubbed = phrase_re.sub(" ", scrubbed)
    return scrubbed, "muitas expressões de data"


def validate_today_summary(raw_output: str, ctx: ValidationContext) -> dict[str, Any]:
    """Porta Python da validação anti-alucinação (`validate.ts`) para resumos Today."""
    cleaned = raw_output.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.DOTALL).strip()

    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return {"is_valid": False, "reason": f"JSON inválido: {exc}", "raw_output": raw_output}

    if not isinstance(obj, dict):
        return {"is_valid": False, "reason": "Resumo deve ser um objeto JSON.", "raw_output": raw_output}

    allowed_top_keys = {"headline", "top", "warnings"}
    for key in obj:
        if key not in allowed_top_keys:
            return {"is_valid": False, "reason": f"Chave desconhecida '{key}'.", "raw_output": raw_output}

    headline = obj.get("headline")
    top = obj.get("top")
    warnings = obj.get("warnings")

    if not isinstance(headline, str) or not headline.strip() or len(headline) > 220:
        return {"is_valid": False, "reason": "Campo 'headline' inválido.", "raw_output": raw_output}

    if not isinstance(top, list) or len(top) > 5:
        return {"is_valid": False, "reason": "Campo 'top' deve ser lista com até 5 itens.", "raw_output": raw_output}

    if not isinstance(warnings, list) or len(warnings) > 5:
        return {"is_valid": False, "reason": "Campo 'warnings' deve ser lista com até 5 itens.", "raw_output": raw_output}

    seen_ids: set[str] = set()
    validated_top: list[dict[str, str]] = []
    for idx, item in enumerate(top):
        if not isinstance(item, dict) or set(item.keys()) - {"id", "why"}:
            return {"is_valid": False, "reason": f"Item top[{idx}] inválido.", "raw_output": raw_output}
        item_id = item.get("id")
        why = item.get("why")
        if not isinstance(item_id, str) or not item_id.strip():
            return {"is_valid": False, "reason": f"Item top[{idx}] sem 'id'.", "raw_output": raw_output}
        if not isinstance(why, str) or not why.strip() or len(why) > 200:
            return {"is_valid": False, "reason": f"Item top[{idx}] com 'why' inválido.", "raw_output": raw_output}
        if item_id in seen_ids:
            return {"is_valid": False, "reason": f"ID duplicado '{item_id}'.", "raw_output": raw_output}
        if item_id not in ctx.allowed_ids:
            return {
                "is_valid": False,
                "reason": f"ID desconhecido ou não permitido '{item_id}'.",
                "raw_output": raw_output,
            }
        seen_ids.add(item_id)
        validated_top.append({"id": item_id, "why": why})

    validated_warnings: list[str] = []
    for idx, w in enumerate(warnings):
        if not isinstance(w, str) or len(w) > 200:
            return {"is_valid": False, "reason": f"Warning[{idx}] inválido.", "raw_output": raw_output}
        validated_warnings.append(w)

    for text in [t["why"] for t in validated_top] + validated_warnings:
        word_match = _NUMBER_WORDS_RE.search(text)
        if word_match:
            return {
                "is_valid": False,
                "reason": f"Número por extenso '{word_match.group(0)}' proibido.",
                "raw_output": raw_output,
            }

    for raw_text in [headline, *(t["why"] for t in validated_top), *validated_warnings]:
        scrubbed, unverifiable = scrub_quoted_date_phrases(raw_text, ctx.input_text)
        if unverifiable:
            return {
                "is_valid": False,
                "reason": f"Formato de data não verificável ('{unverifiable}'). Use YYYY-MM-DD.",
                "raw_output": raw_output,
            }

        for date_match in _ISO_DATE_RE.finditer(scrubbed):
            date_str = date_match.group(1)
            if not is_valid_calendar_date(date_str):
                return {"is_valid": False, "reason": f"Data inválida '{date_str}'.", "raw_output": raw_output}
            if date_str not in ctx.allowed_iso_dates:
                return {
                    "is_valid": False,
                    "reason": f"Data '{date_str}' ausente dos dados de entrada.",
                    "raw_output": raw_output,
                }

        scrubbed_no_dates = _ISO_DATE_RE.sub(" ", scrubbed)
        for num_match in _NUMBER_RE.finditer(scrubbed_no_dates):
            raw_num = num_match.group(0)
            try:
                num_val = int(float(raw_num)) if "." in raw_num else int(raw_num)
            except ValueError:
                continue
            if num_val not in ctx.allowed_numbers:
                return {
                    "is_valid": False,
                    "reason": f"Número '{raw_num}' não encontrado nos dados de entrada.",
                    "raw_output": raw_output,
                }

    return {
        "is_valid": True,
        "summary": {
            "headline": headline,
            "top": validated_top,
            "warnings": validated_warnings,
        },
    }


def build_validation_context(state: dict[str, Any], today_iso: str) -> tuple[ValidationContext, str]:
    """Constrói o texto-fonte e o `ValidationContext` estrito a partir do estado Cowork."""
    allowed_ids: set[str] = set()
    allowed_iso_dates: set[str] = {today_iso}
    allowed_numbers: set[int] = set()

    tasks = state.get("tasks") or []
    deadlines = state.get("deadlines") or []
    schedule = state.get("schedule") or {}
    shifts = schedule.get("shifts") or []

    open_tasks = [t for t in tasks if isinstance(t, dict) and t.get("status") == "open"]
    lines: list[str] = [f"TODAY: {today_iso}", f"OPEN_TASKS_COUNT: {len(open_tasks)}"]
    allowed_numbers.add(len(open_tasks))

    lines.append("TASKS:")
    for t in open_tasks[:25]:
        tid = str(t.get("id") or "").strip()
        title = str(t.get("title") or "").strip()
        domain = str(t.get("domain") or "").strip()
        due = str(t.get("due") or "").strip()
        if tid:
            allowed_ids.add(tid)
        if due and is_valid_calendar_date(due):
            allowed_iso_dates.add(due)
        lines.append(f"- {tid} [{domain}] {title}" + (f" (due {due})" if due else ""))

    lines.append("DEADLINES:")
    for d in deadlines[:15]:
        if not isinstance(d, dict):
            continue
        did = str(d.get("id") or "").strip()
        title = str(d.get("title") or "").strip()
        d_date = str(d.get("date") or "").strip()
        hard = bool(d.get("hard"))
        if did:
            allowed_ids.add(did)
        if d_date and is_valid_calendar_date(d_date):
            allowed_iso_dates.add(d_date)
        lines.append(f"- {did} {title} on {d_date} (hard={hard})")

    lines.append("SHIFTS:")
    for s in shifts[:14]:
        if not isinstance(s, dict):
            continue
        s_date = str(s.get("date") or "").strip()
        start = str(s.get("start") or "").strip()
        end = str(s.get("end") or "").strip()
        place = str(s.get("place") or "").strip()
        if s_date and is_valid_calendar_date(s_date):
            allowed_iso_dates.add(s_date)
        lines.append(f"- {s_date} {start}-{end} {place}")

    input_text = "\n".join(lines)
    for num_match in _NUMBER_RE.finditer(_ISO_DATE_RE.sub(" ", input_text)):
        try:
            allowed_numbers.add(int(float(num_match.group(0))))
        except ValueError:
            pass

    return (
        ValidationContext(
            allowed_ids=allowed_ids,
            allowed_iso_dates=allowed_iso_dates,
            allowed_numbers=allowed_numbers,
            input_text=input_text,
        ),
        input_text,
    )


def build_deterministic_fallback(state: dict[str, Any], today_iso: str) -> dict[str, Any]:
    """Gera resumo Today 100% determinístico quando o roteador LLM estiver offline ou inválido."""
    tasks = [t for t in (state.get("tasks") or []) if isinstance(t, dict) and t.get("status") == "open"]
    due_today = [t for t in tasks if str(t.get("due") or "") == today_iso]
    prioritized = due_today + [t for t in tasks if t not in due_today]

    top = [
        {
            "id": str(t.get("id")),
            "why": f"{t.get('title')} ({t.get('due') or t.get('domain') or 'open'})"[:200],
        }
        for t in prioritized[:3]
        if t.get("id")
    ]
    warnings: list[str] = []
    if due_today:
        warnings.append(f"{len(due_today)} tarefa(s) vencem hoje ({today_iso}).")

    return {
        "headline": f"Hoje ({today_iso}): {len(tasks)} tarefas abertas no Cowork.",
        "top": top,
        "warnings": warnings,
    }


class TodayEngine:
    """Gera e valida o resumo Today usando o roteador HTTP unificado (`127.0.0.1:31415/v1`)."""

    def __init__(self, settings: Settings, cowork_store: CoworkStore) -> None:
        self._settings = settings
        self._cowork = cowork_store

    async def generate_today(self, today_iso: str | None = None) -> dict[str, Any]:
        today_str = today_iso or datetime.now().date().isoformat()
        state = self._cowork.load_state()
        if not state.get("workspace_exists"):
            return {
                "ok": False,
                "source": "unavailable",
                "today": today_str,
                "sync_status": state.get("sync_status", "red"),
                "summary": {
                    "headline": "Workspace Cowork não encontrado.",
                    "top": [],
                    "warnings": ["Verifique COWORK_WORKSPACE_PATH."],
                },
            }

        ctx, input_text = build_validation_context(state, today_str)
        prompt = (
            "Gere um resumo JSON estrito para o painel Today em PT-BR com as chaves exatas "
            "`headline` (string <= 200 chars), `top` (lista de até 3 objetos `{id, why}`) e "
            "`warnings` (lista de até 3 strings). "
            "REGRA CRÍTICA: use APENAS IDs, datas YYYY-MM-DD e números presentes nos dados abaixo. "
            "Nunca use números por extenso em inglês nem invente datas.\n\n"
            f"{input_text}"
        )

        headers = {"Content-Type": "application/json"}
        if self._settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self._settings.llm_api_key}"

        payload = {
            "model": self._settings.llm_model,
            "stream": False,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": "Responda apenas JSON válido sem markdown."},
                {"role": "user", "content": prompt},
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{self._settings.llm_base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                validation = validate_today_summary(content, ctx)
                if validation["is_valid"]:
                    return {
                        "ok": True,
                        "source": "llm_validated",
                        "today": today_str,
                        "sync_status": state.get("sync_status", "green"),
                        "summary": validation["summary"],
                    }
                logger.warning("Resumo Today rejeitado pelo validador: %s", validation["reason"])
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            logger.warning("Falha ao consultar roteador LLM para Today: %s", exc)

        return {
            "ok": True,
            "source": "deterministic_fallback",
            "today": today_str,
            "sync_status": state.get("sync_status", "green"),
            "summary": build_deterministic_fallback(state, today_str),
        }


class FirstWakeTracker:
    """Controla o briefing proativo silencioso apenas na primeira interação do dia."""

    _META_KEY = "last_first_wake_date"

    def __init__(self, memory_store: MemoryStore) -> None:
        self._memory = memory_store

    def should_trigger_today(self, today_iso: str | None = None) -> bool:
        today_str = today_iso or datetime.now().date().isoformat()
        return self._memory.get_meta(self._META_KEY) != today_str

    def mark_triggered(self, today_iso: str | None = None) -> str:
        today_str = today_iso or datetime.now().date().isoformat()
        self._memory.set_meta(self._META_KEY, today_str)
        return today_str
