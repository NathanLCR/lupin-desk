"""Files Data Consent tests: local files reach the LLM only with consent, per provider and host."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.memory import MemoryStore
from app.search.consent import FilesConsent

OLLAMA_LOCAL = ("ollama", "http://127.0.0.1:11434/v1")
OLLAMA_LAN = ("ollama", "http://192.168.1.20:11434/v1")
CLOUD = ("custom", "https://proxy.example.com/v1")
CLOUD_OTHER_HOST = ("custom", "https://other.example.com/v1")
OPENAI = ("openai", "https://api.openai.com/v1")
META_KEY = "data_consent_files"


class _Signature:
    def __init__(self, value: tuple[str, str]) -> None:
        self.value = value

    def __call__(self) -> tuple[str, str]:
        return self.value


def _consent(tmp_path: Path, start: tuple[str, str]) -> tuple[MemoryStore, _Signature, FilesConsent]:
    memory = MemoryStore(db_path=tmp_path / "m.db")
    signature = _Signature(start)
    return memory, signature, FilesConsent(memory, signature)


def test_default_is_off(tmp_path: Path) -> None:
    _, _, consent = _consent(tmp_path, CLOUD)
    assert consent.get() is False


def test_update_on_then_read_back(tmp_path: Path) -> None:
    _, _, consent = _consent(tmp_path, CLOUD)
    assert consent.update(True) is True
    assert consent.get() is True


def test_update_off_after_on(tmp_path: Path) -> None:
    _, _, consent = _consent(tmp_path, CLOUD)
    consent.update(True)
    assert consent.update(False) is False
    assert consent.get() is False


def test_provider_change_turns_it_off_and_going_back_does_not_reenable(tmp_path: Path) -> None:
    _, signature, consent = _consent(tmp_path, CLOUD)
    consent.update(True)

    signature.value = OPENAI
    assert consent.get() is False

    signature.value = CLOUD
    assert consent.get() is False


def test_host_change_turns_it_off(tmp_path: Path) -> None:
    _, signature, consent = _consent(tmp_path, CLOUD)
    consent.update(True)

    signature.value = CLOUD_OTHER_HOST
    assert consent.get() is False


def test_local_ollama_is_always_true_and_update_does_not_persist(tmp_path: Path) -> None:
    memory, _, consent = _consent(tmp_path, OLLAMA_LOCAL)
    assert consent.is_local() is True
    assert consent.get() is True
    assert consent.update(False) is True
    assert consent.get() is True
    assert memory.get_meta(META_KEY) is None


def test_ollama_on_another_host_is_not_local(tmp_path: Path) -> None:
    _, _, consent = _consent(tmp_path, OLLAMA_LAN)
    assert consent.is_local() is False
    assert consent.get() is False
    assert consent.update(True) is True
    assert consent.get() is True


def test_local_ollama_drops_stale_cloud_consent(tmp_path: Path) -> None:
    memory, signature, consent = _consent(tmp_path, CLOUD)
    consent.update(True)

    signature.value = OLLAMA_LOCAL
    assert consent.get() is True

    signature.value = CLOUD
    assert consent.get() is False


def test_corrupt_meta_reads_as_off(tmp_path: Path) -> None:
    memory, _, consent = _consent(tmp_path, CLOUD)
    memory.set_meta(META_KEY, "{not json")
    assert consent.get() is False
    stored = json.loads(memory.get_meta(META_KEY) or "{}")
    assert stored.get("files") is False


def test_non_object_meta_reads_as_off(tmp_path: Path) -> None:
    memory, _, consent = _consent(tmp_path, CLOUD)
    memory.set_meta(META_KEY, "[true]")
    assert consent.get() is False
