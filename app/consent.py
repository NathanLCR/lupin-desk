"""Data Consent (issue 03): what the LLM provider may see of the calendar and e-mail.

Consent only holds for the provider and host that were active when it was given.
Switching provider or base_url turns both switches off on its own (no exception,
not even for Ollama). Without consent, no calendar or e-mail data enters the LLM call.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from app import speech_pt_br as speech
from app.memory import MemoryStore
from app.providers import get_preset

_META_KEY = "data_consent"


def _host_of(base_url: str) -> str:
    return urlparse((base_url or "").strip()).netloc.lower()


class DataConsent:
    """Stores the two consents in `app_meta`, bound to the active provider's signature."""

    def __init__(self, memory: MemoryStore, signature: Callable[[], tuple[str, str]]) -> None:
        self._memory = memory
        self._signature = signature

    def _current(self) -> dict[str, Any]:
        provider_id, base_url = self._signature()
        return {"provider_id": provider_id, "host": _host_of(base_url)}

    def _write(self, calendar: bool, email: bool) -> None:
        payload = {"calendar": calendar, "email": email, **self._current()}
        self._memory.set_meta(_META_KEY, json.dumps(payload, ensure_ascii=False))

    def get(self) -> dict[str, bool]:
        """Read the consents; if the provider or host changed, reset and rewrite them as off."""
        raw = self._memory.get_meta(_META_KEY)
        if not raw:
            return {"calendar": False, "email": False}
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("invalid format")
        except (ValueError, json.JSONDecodeError):
            self._write(False, False)
            return {"calendar": False, "email": False}
        # Older versions stored the calendar switch under the key "agenda".
        calendar_raw = data["calendar"] if "calendar" in data else data.get("agenda")
        calendar = calendar_raw is True
        email = data.get("email") is True
        sig = self._current()
        if data.get("provider_id") != sig["provider_id"] or data.get("host") != sig["host"]:
            if calendar or email or data.get("provider_id") != sig["provider_id"]:
                self._write(False, False)
            return {"calendar": False, "email": False}
        if "calendar" not in data and "agenda" in data:
            # Migrate the old-format value to the new key.
            self._write(calendar, email)
        return {"calendar": calendar, "email": email}

    def update(self, calendar: bool | None = None, email: bool | None = None) -> dict[str, bool]:
        """Change one or both switches for the provider that is active right now."""
        current = self.get()
        new_calendar = current["calendar"] if calendar is None else bool(calendar)
        new_email = current["email"] if email is None else bool(email)
        self._write(new_calendar, new_email)
        return {"calendar": new_calendar, "email": new_email}

    def receiver_name(self) -> str:
        """Name of who receives the data, e.g. 'Proxy Local (127.0.0.1:31415)'."""
        provider_id, base_url = self._signature()
        preset = get_preset(provider_id)
        name = preset.name if preset is not None else speech.CUSTOM_PROVIDER_NAME
        host = _host_of(base_url)
        return f"{name} ({host})" if host else name


def build_personal_context(
    consent: dict[str, bool],
    calendar: list[dict[str, Any]] | None,
    inbox: dict[str, Any] | None,
) -> str:
    """Ephemeral per-turn context with the calendar and e-mail, only what has consent.

    `calendar`/`inbox` must only be read when consent exists; None means the read
    failed. Never includes the e-mail body. It is not saved to the history.
    """
    parts: list[str] = []

    if not consent.get("calendar"):
        parts.append(speech.CALENDAR_NO_ACCESS)
    elif calendar is None:
        parts.append(speech.CALENDAR_READ_FAILED)
    elif not calendar:
        parts.append(speech.CALENDAR_EMPTY)
    else:
        lines = []
        for ev in calendar:
            title = str(ev.get("title") or "").strip()
            when = speech.ALL_DAY if ev.get("all_day") else str(ev.get("start") or "")
            lines.append(f"- {when} {title}".rstrip())
        parts.append(speech.CALENDAR_HEADER + "\n".join(lines))

    if not consent.get("email"):
        parts.append(speech.EMAIL_NO_ACCESS)
    elif inbox is None:
        parts.append(speech.EMAIL_READ_FAILED)
    else:
        recent = inbox.get("recent") or []
        if not recent:
            parts.append(speech.EMAIL_NONE)
        else:
            lines = [
                speech.email_line(str(m.get("sender") or "").strip(), str(m.get("subject") or "").strip())
                for m in recent[:10]
            ]
            parts.append(speech.EMAIL_HEADER + "\n".join(lines))

    return "\n\n".join(parts)
