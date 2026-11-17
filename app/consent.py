"""Data Consent (issue 03): o que o provedor de LLM pode ver da agenda e dos e-mails.

O consentimento vale só para o provedor e o host que estavam ativos quando foi dado.
Trocar de provedor ou de base_url desliga os dois interruptores sozinho (sem exceção,
nem para Ollama). Sem consentimento, nada de agenda ou e-mail entra na chamada ao LLM.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from app.memory import MemoryStore
from app.providers import get_preset

_META_KEY = "data_consent"


def _host_of(base_url: str) -> str:
    return urlparse((base_url or "").strip()).netloc.lower()


class DataConsent:
    """Guarda os dois consentimentos em `app_meta`, presos à assinatura do provedor ativo."""

    def __init__(self, memory: MemoryStore, signature: Callable[[], tuple[str, str]]) -> None:
        self._memory = memory
        self._signature = signature

    def _current(self) -> dict[str, Any]:
        provider_id, base_url = self._signature()
        return {"provider_id": provider_id, "host": _host_of(base_url)}

    def _write(self, agenda: bool, email: bool) -> None:
        payload = {"agenda": agenda, "email": email, **self._current()}
        self._memory.set_meta(_META_KEY, json.dumps(payload, ensure_ascii=False))

    def get(self) -> dict[str, bool]:
        """Lê os consentimentos; se o provedor ou o host mudou, zera e regrava desligado."""
        raw = self._memory.get_meta(_META_KEY)
        if not raw:
            return {"agenda": False, "email": False}
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("formato inválido")
        except (ValueError, json.JSONDecodeError):
            self._write(False, False)
            return {"agenda": False, "email": False}
        agenda = data.get("agenda") is True
        email = data.get("email") is True
        sig = self._current()
        if data.get("provider_id") != sig["provider_id"] or data.get("host") != sig["host"]:
            if agenda or email or data.get("provider_id") != sig["provider_id"]:
                self._write(False, False)
            return {"agenda": False, "email": False}
        return {"agenda": agenda, "email": email}

    def update(self, agenda: bool | None = None, email: bool | None = None) -> dict[str, bool]:
        """Altera um ou os dois interruptores para o provedor ativo agora."""
        atual = self.get()
        novo_agenda = atual["agenda"] if agenda is None else bool(agenda)
        novo_email = atual["email"] if email is None else bool(email)
        self._write(novo_agenda, novo_email)
        return {"agenda": novo_agenda, "email": novo_email}

    def receiver_name(self) -> str:
        """Nome de quem recebe os dados, ex.: 'Proxy Local (127.0.0.1:31415)'."""
        provider_id, base_url = self._signature()
        preset = get_preset(provider_id)
        nome = preset.name if preset is not None else "Provedor personalizado"
        host = _host_of(base_url)
        return f"{nome} ({host})" if host else nome


def build_personal_context(
    consent: dict[str, bool],
    agenda: list[dict[str, Any]] | None,
    inbox: dict[str, Any] | None,
) -> str:
    """Contexto efêmero do turno com agenda e e-mails, só do que tem consentimento.

    `agenda`/`inbox` só devem ser lidos quando há consentimento; None significa que a leitura
    falhou. Nunca inclui o corpo dos e-mails. Não é salvo no histórico.
    """
    partes: list[str] = []

    if not consent.get("agenda"):
        partes.append(
            "Você NÃO tem acesso à agenda do usuário. Se ele perguntar sobre compromissos ou agenda, "
            "diga que não pode ver a agenda dele; não adivinhe nem invente."
        )
    elif agenda is None:
        partes.append(
            "Você não conseguiu ler a agenda agora. Se o usuário perguntar sobre ela, diga isso."
        )
    elif not agenda:
        partes.append("Agenda de hoje (leitura permitida pelo usuário): sem eventos.")
    else:
        linhas = []
        for ev in agenda:
            titulo = str(ev.get("titulo") or "").strip()
            hora = "dia todo" if ev.get("dia_todo") else str(ev.get("inicio") or "")
            linhas.append(f"- {hora} {titulo}".rstrip())
        partes.append("Agenda de hoje (leitura permitida pelo usuário):\n" + "\n".join(linhas))

    if not consent.get("email"):
        partes.append(
            "Você NÃO tem acesso aos e-mails do usuário. Se ele perguntar sobre e-mails, diga que não "
            "pode ver os e-mails dele; não adivinhe nem invente."
        )
    elif inbox is None:
        partes.append(
            "Você não conseguiu ler os e-mails agora. Se o usuário perguntar sobre eles, diga isso."
        )
    else:
        recentes = inbox.get("recentes") or []
        if not recentes:
            partes.append("E-mails não lidos das últimas 24h (leitura permitida pelo usuário): nenhum.")
        else:
            linhas = [
                f"- de {str(m.get('remetente') or '').strip()}: {str(m.get('assunto') or '').strip()}"
                for m in recentes[:10]
            ]
            partes.append(
                "E-mails não lidos das últimas 24h (leitura permitida pelo usuário; você só vê remetente "
                "e assunto, nunca o corpo):\n" + "\n".join(linhas)
            )

    return "\n\n".join(partes)
