"""Integration tests for issue 06 (Smart search): Data Consent files API, provider switch reset, and /ws action."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app import speech
from app.config import Settings
from app.llm import LLMClient
from app.main import create_app
from app.search import register as register_search
from app.search.files import FileSearch

MAC_IP = "192.168.1.10"
OTHER_IP = "192.168.1.50"


def _as_client(app: Any, host: str) -> Any:
    async def asgi(scope: dict[str, Any], receive: Any, send: Any) -> None:
        patched = dict(scope)
        patched["client"] = (host, 54321)
        await app(patched, receive, send)

    return asgi


class _StubRunner:
    def __init__(self, lines_by_root: dict[str, list[str]]) -> None:
        self._lines = lines_by_root

    def __call__(self, argv: list[str], **_kwargs: Any) -> Any:
        root = argv[argv.index("-onlyin") + 1]
        lines = self._lines.get(root, [])
        return type("Proc", (), {"returncode": 0, "stdout": "".join(f"{line}\n" for line in lines)})()


def _make_app(tmp_path: Path, docs_root: Path | None = None) -> Any:
    settings = Settings(
        llm_base_url="http://127.0.0.1:31415/v1",
        llm_api_key="test-key",
        llm_model="claude-haiku-4-5",
        db_path=tmp_path / "memory.db",
        cowork_workspace_path=tmp_path / "Cowork",
        desk_dev_no_token=True,
    )

    async def fake_stream(**_kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "action", "kind": "search", "target": "query: budget"}
        yield {"type": "sentence", "text": "Checking."}
        yield {"type": "result", "text": "Checking.", "raw_text": "[action:search:query: budget] Checking.", "emotion": "neutral"}

    app = create_app(
        settings=settings,
        llm_client=LLMClient(settings=settings, stream_fn=fake_stream),
        local_ips=lambda: frozenset({MAC_IP}),
    )
    if docs_root is not None:
        file_path = docs_root / "budget.txt"
        register_search(
            app,
            store=app.state.productivity.store,
            memory=app.state.memory,
            cowork=app.state.cowork,
            signature=lambda: ("custom", settings.llm_base_url),
            files=FileSearch(roots=[docs_root], runner=_StubRunner({str(docs_root.resolve()): [str(file_path)]})),
        )
    return app


def test_files_consent_api_mac_guard_and_provider_switch_reset(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    with TestClient(app) as mac:
        initial = mac.get("/api/data-consent").json()
        assert initial["files"] is False

        # Non-Mac cannot toggle files consent.
        other = TestClient(_as_client(app, OTHER_IP))
        assert other.put("/api/data-consent", json={"files": True}).status_code == 403
        assert other.get("/api/data-consent").json()["files"] is False

        # Partial update toggles files while leaving calendar/email untouched.
        updated = mac.put("/api/data-consent", json={"files": True}).json()
        assert updated["files"] is True
        assert updated["calendar"] is False
        assert updated["email"] is False

        # Switching cloud A -> cloud B -> cloud A without reading /api/data-consent on B still clears A's consent.
        mac.put(
            "/api/llm/provider",
            json={"provider_id": "custom", "base_url": "http://10.0.0.2:1/v1", "model": "m"},
        )
        mac.put(
            "/api/llm/provider",
            json={"provider_id": "local_proxy", "base_url": "http://127.0.0.1:31415/v1", "model": "m"},
        )
        assert mac.get("/api/data-consent").json()["files"] is False

        # Local Ollama needs no consent and reports files=True.
        mac.put(
            "/api/llm/provider",
            json={"provider_id": "ollama", "base_url": "http://127.0.0.1:11434/v1", "model": "llama3.2"},
        )
        ollama_state = mac.get("/api/data-consent").json()
        assert ollama_state["local"] is True
        assert ollama_state["files"] is True


def test_ws_search_action_respects_files_consent_and_does_not_persist_snippets(tmp_path: Path) -> None:
    docs = tmp_path / "Docs"
    docs.mkdir()
    secret_line = "TOP SECRET BUDGET LINE 9999"
    (docs / "budget.txt").write_text(secret_line + "\n", encoding="utf-8")

    app = _make_app(tmp_path, docs_root=docs)
    with TestClient(app) as mac:
        speech.set_language("en")

        def run_ws_turn() -> tuple[list[dict[str, Any]], dict[str, Any]]:
            events: list[dict[str, Any]] = []
            with mac.websocket_connect("/ws") as ws:
                ws.send_json({"type": "hello", "body": "rg406h-web", "protocol": 1})
                ws.receive_json()  # welcome
                ws.send_json({"type": "text", "text": "find my budget"})
                while True:
                    ev = ws.receive_json()
                    events.append(ev)
                    if ev["type"] == "done" and not ev.get("first_wake"):
                        return events, ev

        # Without consent: file name appears, snippet never appears.
        events_no_consent, done_no_consent = run_ws_turn()
        actions = [e for e in events_no_consent if e["type"] == "action_executed"]
        sentences = [e["text"] for e in events_no_consent if e["type"] == "sentence"]
        assert actions and actions[0]["kind"] == "search" and actions[0]["ok"] is True
        joined = " ".join(sentences)
        assert "budget.txt" in joined
        assert secret_line not in joined
        assert secret_line not in done_no_consent["text"]

        # With consent: snippet is spoken, but still not saved to memory or done.text.
        assert mac.put("/api/data-consent", json={"files": True}).json()["files"] is True
        events_consent, done_consent = run_ws_turn()
        sentences_consent = [e["text"] for e in events_consent if e["type"] == "sentence"]
        assert any(secret_line in s for s in sentences_consent)
        assert secret_line not in done_consent["text"]
        saved = repr(app.state.memory.get_recent_messages()) + repr(app.state.memory.get_facts())
        assert secret_line not in saved
