"""Fixtures comuns: os testes nunca leem o Mail.app nem o Calendar reais do Mac."""

from __future__ import annotations

import pytest

from app.mac_control import MacController


@pytest.fixture(autouse=True)
def _sem_leitura_real_de_mail_e_agenda(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(MacController, "read_inbox", lambda self: None)
    monkeypatch.setattr(MacController, "read_today_agenda", lambda self: None)
