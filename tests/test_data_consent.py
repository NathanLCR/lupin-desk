"""Testes do Data Consent (issue 03): agenda e e-mail só vão ao LLM com consentimento."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.config import Settings
from app.consent import DataConsent, build_personal_context
from app.llm import LLMClient, build_system_prompt
from app.main import create_app
from app.memory import MemoryStore

IP_DO_MAC = "192.168.1.10"
IP_DE_OUTRO = "192.168.1.50"
AGENDA = [{"inicio": "09:00", "titulo": "Defesa do Zeca", "dia_todo": False}]
INBOX = {
    "nao_lidos": 7,
    "recentes": [{"remetente": "Carla Souza", "assunto": "Contrato assinado"}],
}
SEGREDOS = ("Defesa do Zeca", "Carla Souza", "Contrato assinado")


def _como_cliente(app: Any, host: str) -> Any:
    async def asgi(scope: dict[str, Any], receive: Any, send: Any) -> None:
        patched = dict(scope)
        patched["client"] = (host, 54321)
        await app(patched, receive, send)

    return asgi


def _app(tmp_path: Path, chamadas: list[dict[str, Any]], agenda: Any = AGENDA, inbox: Any = INBOX) -> Any:
    settings = Settings(
        llm_base_url="http://127.0.0.1:31415/v1",
        llm_api_key="test-key",
        llm_model="claude-haiku-4-5",
        db_path=tmp_path / "memory.db",
        cowork_workspace_path=tmp_path / "Cowork",
        desk_dev_sem_token=True,
    )

    async def fake_stream(**kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        chamadas.append(kwargs)
        yield {"type": "sentence", "text": "Oi!"}
        yield {"type": "result", "text": "Oi!", "raw_text": "Oi!", "emotion": "neutral"}

    return create_app(
        settings=settings,
        llm_client=LLMClient(settings=settings, stream_fn=fake_stream),
        agenda_reader=lambda: agenda,
        inbox_reader=lambda: inbox,
        local_ips=lambda: frozenset({IP_DO_MAC}),
    )


def _ate_resposta(ws: Any) -> None:
    """Espera o `done` da resposta do turno (ignora o do First Wake, se houver)."""
    while True:
        ev = ws.receive_json()
        if ev["type"] == "done" and not ev.get("first_wake"):
            return


def _conversa(client: Any, texto: str = "o que tenho hoje?") -> None:
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "body": "rg406h-web", "protocol": 1})
        ws.receive_json()
        ws.send_json({"type": "text", "text": texto})
        _ate_resposta(ws)


def test_padrao_desligado_e_receptor_nomeado(tmp_path: Path) -> None:
    app = _app(tmp_path, [])
    with TestClient(app) as mac:
        dados = mac.get("/api/data-consent").json()
    assert dados["agenda"] is False and dados["email"] is False
    assert dados["receiver"] == "Proxy Local (127.0.0.1:31415)"
    assert dados["can_edit"] is True
    assert "test-key" not in repr(dados)


def test_sem_consentimento_nada_de_agenda_ou_email_vai_ao_llm(tmp_path: Path) -> None:
    chamadas: list[dict[str, Any]] = []
    with TestClient(_app(tmp_path, chamadas)) as client:
        _conversa(client)
    assert len(chamadas) == 1
    for segredo in SEGREDOS:
        assert segredo not in repr(chamadas[0])
    ctx = chamadas[0]["personal_context"]
    assert "NÃO tem acesso à agenda" in ctx and "NÃO tem acesso aos e-mails" in ctx


def test_com_consentimento_agenda_e_email_chegam_ao_llm(tmp_path: Path) -> None:
    chamadas: list[dict[str, Any]] = []
    app = _app(tmp_path, chamadas)
    with TestClient(app) as mac:
        assert mac.put("/api/data-consent", json={"agenda": True, "email": True}).status_code == 200
        _conversa(mac)
    ctx = chamadas[0]["personal_context"]
    assert "09:00 Defesa do Zeca" in ctx
    assert "Carla Souza" in ctx and "Contrato assinado" in ctx


def test_consentimento_so_de_agenda_nao_vaza_email(tmp_path: Path) -> None:
    chamadas: list[dict[str, Any]] = []
    app = _app(tmp_path, chamadas)
    with TestClient(app) as mac:
        mac.put("/api/data-consent", json={"agenda": True})
        _conversa(mac)
    ctx = chamadas[0]["personal_context"]
    assert "Defesa do Zeca" in ctx
    assert "Carla Souza" not in repr(chamadas[0]) and "Contrato assinado" not in repr(chamadas[0])


def test_leitura_falhou_com_consentimento_avisa_sem_dados(tmp_path: Path) -> None:
    chamadas: list[dict[str, Any]] = []
    app = _app(tmp_path, chamadas, agenda=None, inbox=None)
    with TestClient(app) as mac:
        mac.put("/api/data-consent", json={"agenda": True, "email": True})
        _conversa(mac)
    ctx = chamadas[0]["personal_context"]
    assert "não conseguiu ler a agenda" in ctx and "não conseguiu ler os e-mails" in ctx


def test_agenda_e_email_nao_vao_para_o_historico_salvo(tmp_path: Path) -> None:
    chamadas: list[dict[str, Any]] = []
    app = _app(tmp_path, chamadas)
    with TestClient(app) as mac:
        mac.put("/api/data-consent", json={"agenda": True, "email": True})
        with mac.websocket_connect("/ws") as ws:
            ws.send_json({"type": "hello", "body": "rg406h-web", "protocol": 1})
            ws.receive_json()
            ws.send_json({"type": "text", "text": "o que tenho hoje?"})
            _ate_resposta(ws)
        salvo = repr(app.state.memory.get_recent_messages()) + repr(app.state.memory.get_facts())
    for segredo in SEGREDOS:
        assert segredo not in salvo


def test_alterar_fora_do_mac_da_403_e_leitura_continua(tmp_path: Path) -> None:
    app = _app(tmp_path, [])
    with TestClient(app) as mac:
        mac.put("/api/data-consent", json={"agenda": True})
        outro = TestClient(_como_cliente(app, IP_DE_OUTRO))
        assert outro.put("/api/data-consent", json={"agenda": False}).status_code == 403
        assert outro.put("/api/data-consent", json={"email": True}).status_code == 403
        lido = outro.get("/api/data-consent").json()
        assert lido["agenda"] is True and lido["email"] is False and lido["can_edit"] is False
        assert mac.get("/api/data-consent").json()["agenda"] is True


def test_trocar_provider_ou_base_url_desliga_os_dois(tmp_path: Path) -> None:
    app = _app(tmp_path, [])
    corpo = {"provider_id": "local_proxy", "base_url": "http://127.0.0.1:31415/v1", "model": "m"}
    with TestClient(app) as mac:
        mac.put("/api/data-consent", json={"agenda": True, "email": True})
        # Mesmo provider e host: segue ligado.
        mac.put("/api/llm/provider", json=corpo)
        assert mac.get("/api/data-consent").json()["agenda"] is True
        # Outro host, mesmo provider (custom).
        mac.put("/api/llm/provider", json={**corpo, "provider_id": "custom", "base_url": "http://10.0.0.5:1/v1"})
        dados = mac.get("/api/data-consent").json()
        assert dados["agenda"] is False and dados["email"] is False
        # Voltar ao proxy local não reativa sozinho.
        mac.put("/api/llm/provider", json=corpo)
        assert mac.get("/api/data-consent").json()["agenda"] is False
        # Liga de novo, troca só o provider (Ollama): desliga.
        mac.put("/api/data-consent", json={"agenda": True, "email": True})
        mac.put("/api/llm/provider", json={"provider_id": "ollama", "model": "llama3.2"})
        dados = mac.get("/api/data-consent").json()
        assert dados["agenda"] is False and dados["email"] is False
        assert dados["receiver"].startswith("Ollama")
        # Mudar só a base_url do mesmo provider também desliga.
        mac.put("/api/data-consent", json={"agenda": True})
        mac.put("/api/llm/provider", json={"provider_id": "ollama", "base_url": "http://127.0.0.1:9999/v1", "model": "llama3.2"})
        assert mac.get("/api/data-consent").json()["agenda"] is False


def test_assinatura_na_classe(tmp_path: Path) -> None:
    mem = MemoryStore(db_path=tmp_path / "m.db")
    try:
        sig = [("ollama", "http://127.0.0.1:11434/v1")]
        consent = DataConsent(mem, lambda: sig[0])
        consent.update(agenda=True, email=True)
        assert consent.get() == {"agenda": True, "email": True}
        sig[0] = ("ollama", "http://127.0.0.1:11435/v1")
        assert consent.get() == {"agenda": False, "email": False}
        sig[0] = ("ollama", "http://127.0.0.1:11434/v1")
        assert consent.get() == {"agenda": False, "email": False}, "voltar não reativa"
    finally:
        mem.close()


def test_contexto_pessoal_e_prompt() -> None:
    off = build_personal_context({"agenda": False, "email": False}, AGENDA, INBOX)
    assert not any(s in off for s in SEGREDOS)
    on = build_personal_context({"agenda": True, "email": True}, AGENDA, INBOX)
    assert "Defesa do Zeca" in on and "Contrato assinado" in on
    assert "corpo" in on  # lembra que só vê remetente e assunto
    assert "Defesa do Zeca" in build_system_prompt(personal_context=on)
    assert "Agenda e e-mails" not in build_system_prompt()
