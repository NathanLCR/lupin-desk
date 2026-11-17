"""Shared fixtures: tests never read the Mac's real Mail.app or Calendar."""

from __future__ import annotations

import pytest

from app.mac_control import MacController


@pytest.fixture(autouse=True)
def _no_real_mail_or_calendar_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(MacController, "read_inbox", lambda self: None)
    monkeypatch.setattr(MacController, "read_today_calendar", lambda self: None)
