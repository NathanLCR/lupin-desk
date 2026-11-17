"""Testes do First Wake (issue 03): fala do Today pela voz de Lupin no Active Body."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.config import Settings
from app.llm import LLMClient
from app.mac_control import parse_calendar_output
from app.main import create_app
from app.memory import MemoryStore
from app.today import FirstWakeTracker, compor_fala_first_wake
from app.tts import ServerTTS

HOJE = "2026-11-17"
ESTADO = {
    "workspace_exists": True,
    "tasks": [
        {"id": "t-1", "title": "Revisar a introdução", "status": "open", "due": HOJE},
        {"id": "t-2", "title": "Responder orientador", "status": "open"},
        {"id": "t-3", "title": "Tarefa fechada", "status": "done"},
    ],
}
AGENDA = [
    {"inicio": "09:00", "titulo": "Reunião de laboratório", "dia_todo": False},
    {"inicio": "14:30", "titulo": "Dentista", "dia_todo": False},
]


def test_fala_tem_tarefas_agenda_e_prioridade_em_tres_frases() -> None:
    frases = compor_fala_first_wake(ESTADO, AGENDA, HOJE)
    assert len(frases) == 3
    texto = " ".join(frases)
    assert "2 tarefas abertas" in texto
    assert "9h00 Reunião de laboratório" in texto and "14h30 Dentista" in texto
    assert "Revisar a introdução" in texto  # vence hoje, vem primeiro
    assert "Tarefa fechada" not in texto


def test_agenda_vazia_ou_indisponivel() -> None:
    livre = compor_fala_first_wake(ESTADO, [], HOJE)
    assert any("agenda está livre" in f for f in livre)
    sem = compor_fala_first_wake(ESTADO, None, HOJE)
    assert not any("agenda" in f.lower() for f in sem)
    assert 2 <= len(sem) <= 3


def test_sem_cowork_e_sem_agenda_ainda_fala_duas_frases_sem_inventar() -> None:
    frases = compor_fala_first_wake({"workspace_exists": False}, None, HOJE)
    assert 2 <= len(frases) <= 3
    assert not any(ch.isdigit() for ch in " ".join(frases))


def test_agenda_longa_resume_em_tres_itens() -> None:
    muitos = [{"inicio": f"{h:02d}:00", "titulo": f"Evento {h}", "dia_todo": False} for h in range(8, 14)]
    frase = [f for f in compor_fala_first_wake(ESTADO, muitos, HOJE) if "agenda" in f.lower()][0]
    assert "Evento 10" in frase and "Evento 11" not in frase and "mais 3" in frase


def test_dia_todo_aparece_sem_hora() -> None:
    frases = compor_fala_first_wake(ESTADO, [{"inicio": "00:00", "titulo": "Feriado", "dia_todo": True}], HOJE)
    assert any("Feriado (dia todo)" in f for f in frases)


def test_tracker_so_dispara_depois_das_5h_e_uma_vez_por_dia(tmp_path: Path) -> None:
    mem = MemoryStore(db_path=tmp_path / "m.db")
    try:
        relogio = [datetime(2026, 11, 17, 4, 59)]
        tracker = FirstWakeTracker(mem, clock=lambda: relogio[0])
        assert tracker.is_due() is False
        relogio[0] = datetime(2026, 11, 17, 5, 0)
        assert tracker.is_due() is True
        tracker.mark_triggered()
        assert tracker.is_due() is False
        relogio[0] = datetime(2026, 11, 18, 6, 0)
        assert tracker.is_due() is True
    finally:
        mem.close()


def test_le_saida_do_calendar_app() -> None:
    saida = "32400\tfalse\tReunião\n0\ttrue\tFeriado\n52200\tfalse\tDentista\tcom tab\n\nlixo\n"
    assert parse_calendar_output(saida) == [
        {"inicio": "00:00", "titulo": "Feriado", "dia_todo": True},
        {"inicio": "09:00", "titulo": "Reunião", "dia_todo": False},
        {"inicio": "14:30", "titulo": "Dentista com tab", "dia_todo": False},
    ]


# ---------------------------------------------------------------------------
# Pelo WebSocket
# ---------------------------------------------------------------------------


def _app(tmp_path: Path, hora: int, chamadas_llm: list[dict[str, Any]]) -> tuple[Any, list[str]]:
    settings = Settings(
        llm_base_url="http://127.0.0.1:31415/v1",
        llm_api_key="test-key",
        llm_model="claude-haiku-4-5",
        db_path=tmp_path / "memory.db",
        cowork_workspace_path=tmp_path / "Cowork",
    )
    sintetizadas: list[str] = []

    async def fake_stream(**kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        chamadas_llm.append(kwargs)
        yield {"type": "sentence", "text": "Oi!"}
        yield {"type": "result", "text": "Oi!", "raw_text": "Oi!", "emotion": "neutral"}

    async def synth(text: str, voice: str, fmt: str) -> bytes:
        sintetizadas.append(text)
        return b"x"

    memory = MemoryStore(db_path=settings.db_path)
    tracker = FirstWakeTracker(memory, clock=lambda: datetime(2026, 11, 17, hora, 10))
    app = create_app(
        settings=settings,
        memory_store=memory,
        llm_client=LLMClient(settings=settings, stream_fn=fake_stream),
        tts_engine=ServerTTS(synth_fn=synth),
        first_wake=tracker,
        agenda_reader=lambda: list(AGENDA),
    )
    return app, sintetizadas


def _ate_done(ws: Any) -> list[dict[str, Any]]:
    eventos = []
    while True:
        ev = ws.receive_json()
        eventos.append(ev)
        if ev["type"] == "done":
            return eventos


def test_primeiro_toque_depois_das_5h_fala_o_today_com_voz(tmp_path: Path) -> None:
    app, sintetizadas = _app(tmp_path, 7, [])
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "body": "rg406h-web", "protocol": 1, "audio": ["m4a"]})
        ws.receive_json()
        ws.send_json({"type": "touch", "kind": "pet"})
        assert ws.receive_json()["type"] == "mood"
        eventos = _ate_done(ws)
        frases = [e["text"] for e in eventos if e["type"] == "sentence"]
        assert 2 <= len(frases) <= 3
        assert eventos[-1]["first_wake"] is True
        # A voz de cada frase chega depois do done.
        audios = []
        while len(audios) < len(frases):
            ev = ws.receive_json()
            if ev["type"] == "audio" and ev["last"]:
                audios.append(ev)
        assert sintetizadas == frases

        # Segundo toque no mesmo dia: só mood.
        ws.send_json({"type": "touch", "kind": "pet"})
        assert ws.receive_json()["type"] == "mood"
        ws.send_json({"type": "typing", "active": False})
        assert ws.receive_json() == {"type": "state", "state": "idle"}


def test_antes_das_5h_nao_tem_first_wake(tmp_path: Path) -> None:
    app, _ = _app(tmp_path, 3, [])
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "body": "rg406h-web", "protocol": 1})
        ws.receive_json()
        ws.send_json({"type": "touch", "kind": "pet"})
        assert ws.receive_json()["type"] == "mood"
        ws.send_json({"type": "typing", "active": False})
        assert ws.receive_json() == {"type": "state", "state": "idle"}


def test_body_que_nao_e_o_active_body_nao_dispara(tmp_path: Path) -> None:
    app, _ = _app(tmp_path, 7, [])
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as esp, client.websocket_connect("/ws") as rg:
            esp.send_json({"type": "hello", "body": "esp32", "protocol": 1})
            esp.receive_json()
            rg.send_json({"type": "hello", "body": "rg406h-web", "protocol": 1})
            assert rg.receive_json()["active"] is False
            rg.send_json({"type": "touch", "kind": "pet"})
            assert rg.receive_json()["type"] == "mood"
            rg.send_json({"type": "typing", "active": False})
            assert rg.receive_json() == {"type": "state", "state": "idle"}
            # O First Wake continua guardado para o Active Body.
            esp.send_json({"type": "touch", "kind": "pet"})
            assert esp.receive_json()["type"] == "mood"
            assert _ate_done(esp)[-1]["first_wake"] is True


def test_texto_recebe_first_wake_antes_e_agenda_nao_vai_para_o_llm(tmp_path: Path) -> None:
    chamadas: list[dict[str, Any]] = []
    app, _ = _app(tmp_path, 7, chamadas)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "body": "rg406h-web", "protocol": 1})
        ws.receive_json()
        ws.send_json({"type": "text", "text": "bom dia"})
        primeiro = _ate_done(ws)
        assert primeiro[-1]["first_wake"] is True
        segundo = _ate_done(ws)
        assert segundo[-1].get("first_wake") is not True
        assert segundo[-1]["text"] == "Oi!"
    assert len(chamadas) == 1
    assert "Dentista" not in repr(chamadas[0])
    assert "Reunião de laboratório" not in repr(chamadas[0])
