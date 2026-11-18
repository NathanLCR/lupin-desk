"""Dictation (issue 07): text rules, clipboard paste with restore, and the WebSocket flow."""

from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.config import Settings
from app.dictation import format_dictation
from app.mac_control import MacController
from app.main import create_app
from app.stt import LocalSTT


@pytest.mark.parametrize(
    ("raw", "lang", "expected"),
    [
        ("olá vírgula tudo bem ponto de interrogação", "pt-BR", "Olá, tudo bem?"),
        ("Oi, vírgula, eu sou o Lupin. Ponto final. novo parágrafo teste", "pt", "Oi, eu sou o Lupin.\n\nTeste"),
        ("hello comma world period new line second line", "en", "Hello, world.\nSecond line"),
        ("first one. second one scratch that third one.", "en", "First one. Third one."),
        ("ele disse oi apaga isso ele disse tchau", "pt", "Ele disse tchau"),
        ("open parenthesis note close parenthesis period", "en", "(Note)."),
        ("  ", "en", ""),
    ],
)
def test_format_dictation(raw: str, lang: str, expected: str) -> None:
    assert format_dictation(raw, lang) == expected


class _Runner:
    def __init__(self, clipboard: str = "old clip", fail_keystroke: str = "") -> None:
        self.clipboard = clipboard
        self.calls: list[list[str]] = []
        self.events: list[str] = []
        self.fail_keystroke = fail_keystroke

    def __call__(self, argv, timeout=5.0, input=None):
        self.calls.append(list(argv))
        out = ""
        rc = 0
        err = ""
        if argv[0].endswith("pbpaste"):
            out = self.clipboard
        elif argv[0].endswith("pbcopy"):
            self.clipboard = input or ""
            self.events.append("copy:" + self.clipboard)
        elif argv[0].endswith("osascript"):
            self.events.append("paste@" + self.clipboard)
            if self.fail_keystroke:
                rc, err = 1, self.fail_keystroke
        return subprocess.CompletedProcess(argv, rc, out, err)


def test_paste_text_pastes_then_restores_clipboard() -> None:
    runner = _Runner()
    mac = MacController(runner=runner)
    mac.PASTE_SETTLE_SECONDS = 0
    res = mac.paste_text("Hello, world.")
    assert res["ok"] and res["clipboard_restored"]
    assert runner.events == ["copy:Hello, world.", "paste@Hello, world.", "copy:old clip"]
    assert runner.clipboard == "old clip"
    for argv in runner.calls:  # strict whitelist: fixed binaries, text only via stdin
        assert argv[0] in ("/usr/bin/pbpaste", "/usr/bin/pbcopy", "/usr/bin/osascript")
        assert "Hello" not in " ".join(argv)


def test_paste_text_restores_clipboard_even_when_paste_fails() -> None:
    runner = _Runner(fail_keystroke="not allowed to send keystrokes")
    mac = MacController(runner=runner)
    mac.PASTE_SETTLE_SECONDS = 0
    res = mac.paste_text("hi")
    assert res["ok"] is False and res["needs_accessibility"] is True
    assert runner.clipboard == "old clip"


def test_paste_text_rejects_empty() -> None:
    assert MacController(runner=_Runner()).paste_text("")["ok"] is False


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        llm_base_url="http://127.0.0.1:31415/v1",
        llm_api_key="k",
        llm_model="m",
        host="127.0.0.1",
        port=8000,
        max_short_term_messages=10,
        max_user_facts=25,
        db_path=tmp_path / "m.db",
    )


def test_ws_dictation_pastes_and_skips_llm(tmp_path: Path) -> None:
    runner = _Runner()
    mac = MacController(runner=runner)
    mac.PASTE_SETTLE_SECONDS = 0

    def fake_stt(audio, mime, lang):
        return {"text": "olá vírgula mundo"}

    stt = LocalSTT(language="pt", transcribe_fn=fake_stt)
    app = create_app(settings=_settings(tmp_path), mac_controller=mac, stt_engine=stt)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json(
            {
                "type": "audio",
                "dictation": True,
                "mime_type": "audio/wav",
                "data": base64.b64encode(b"RIFF" + b"\0" * 600).decode(),
            }
        )
        seen = []
        for _ in range(10):
            msg = ws.receive_json()
            seen.append(msg)
            if msg.get("type") == "dictation_result":
                break
        result = seen[-1]
        assert result["type"] == "dictation_result" and result["ok"] is True
        assert not any(m.get("type") in ("delta", "sentence", "transcript") for m in seen)
    assert "copy:Olá, mundo" in runner.events
