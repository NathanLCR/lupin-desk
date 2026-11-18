"""WebSocket wiring for dictation (needs the 07 patch to app/main.py applied)."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

from fastapi.testclient import TestClient

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.config import Settings
from app.mac_control import MacController
from app.main import create_app
from app.stt import LocalSTT

import pytest

_WIRED = "DICTATION_TYPES" in Path(_ROOT_DIR, "app", "main.py").read_text()


class _RecordingMac(MacController):
    def __init__(self) -> None:
        super().__init__(runner=lambda argv, timeout=5.0: None)
        self.pasted: list[str] = []

    def paste_text(self, text: str) -> dict:
        self.pasted.append(text)
        return {"ok": True, "chars": len(text)}


@pytest.mark.skipif(not _WIRED, reason="07-main.py.diff not applied yet")
def test_dictation_roundtrip_over_websocket(tmp_path: Path) -> None:
    settings = Settings(
        llm_base_url="http://127.0.0.1:31415/v1",
        llm_api_key="test-key",
        llm_model="m",
        host="127.0.0.1",
        port=8000,
        max_short_term_messages=10,
        max_user_facts=25,
        db_path=tmp_path / "m.db",
    )
    mac = _RecordingMac()
    stt = LocalSTT(
        transcribe_fn=lambda audio, mime, lang: {
            "text": "hello comma world",
            "available": True,
            "engine": "custom",
            "error": None,
        }
    )
    app = create_app(settings=settings, mac_controller=mac, stt_engine=stt)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "dictation_start"})
        assert ws.receive_json() == {"type": "dictation", "status": "listening"}
        assert ws.receive_json() == {"type": "state", "state": "listening"}

        audio = base64.b64encode(b"x" * 600).decode()
        ws.send_json({"type": "dictation_stop", "data": audio, "mime_type": "audio/webm", "language": "en"})
        seen = []
        while True:
            msg = ws.receive_json()
            seen.append(msg)
            if msg == {"type": "state", "state": "idle"}:
                break
        done = next(m for m in seen if m.get("type") == "dictation")
        assert done["status"] == "done" and done["inserted"] is True
        assert mac.pasted == ["Hello, world"]
