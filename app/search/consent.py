"""Files Data Consent: the third switch, for reading local files with the LLM.

Same rules as the calendar and e-mail consent (see app/consent.py): it only holds
for the provider and host that were active when it was given. Switching provider or
host turns it off. Ollama on a loopback host never asks for consent, because the data
stays on the Mac. Stored under the `app_meta` key `data_consent_files`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from app.consent import _host_of, is_local_provider
from app.memory import MemoryStore

_META_KEY = "data_consent_files"


class FilesConsent:
    """Stores the files consent in `app_meta`, bound to the active provider's signature."""

    def __init__(self, memory: MemoryStore, signature: Callable[[], tuple[str, str]]) -> None:
        self._memory = memory
        self._signature = signature

    def _current(self) -> dict[str, Any]:
        provider_id, base_url = self._signature()
        return {"provider_id": provider_id, "host": _host_of(base_url)}

    def _write(self, files: bool) -> None:
        payload = {"files": files, **self._current()}
        self._memory.set_meta(_META_KEY, json.dumps(payload, ensure_ascii=False))

    @staticmethod
    def _read_signature(raw: str) -> dict[str, Any] | None:
        try:
            data = json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        return {"provider_id": data.get("provider_id"), "host": data.get("host")}

    def is_local(self) -> bool:
        """True when the active provider is local Ollama (no consent needed)."""
        provider_id, base_url = self._signature()
        return is_local_provider(provider_id, base_url)

    def get(self) -> bool:
        """Read the files consent; if the provider or host changed, reset it to off."""
        if self.is_local():
            # Drop any cloud consent on record, so it can't come back when a cloud provider returns.
            stored = self._memory.get_meta(_META_KEY)
            if stored and (self._read_signature(stored) != self._current()):
                self._write(False)
            return True
        raw = self._memory.get_meta(_META_KEY)
        if not raw:
            return False
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("invalid format")
        except (ValueError, json.JSONDecodeError):
            self._write(False)
            return False
        sig = self._current()
        if data.get("provider_id") != sig["provider_id"] or data.get("host") != sig["host"]:
            self._write(False)
            return False
        return data.get("files") is True

    def update(self, files: bool) -> bool:
        """Change the switch for the provider that is active right now."""
        if self.is_local():
            return True
        value = bool(files)
        self._write(value)
        return value
