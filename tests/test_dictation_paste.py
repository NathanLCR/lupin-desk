"""Unit tests for clipboard paste (`MacController.paste_text`) with a fake runner."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

import app.mac_control as mac_control
from app.mac_control import MacController

PBPASTE = ["/usr/bin/pbpaste"]
PBCOPY = ["/usr/bin/pbcopy"]
ACCESSIBILITY_DENIED = (
    "execution error: System Events got an error: osascript is not allowed to send keystrokes. (1002)"
)


@pytest.fixture(autouse=True)
def _no_settle_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mac_control, "_PASTE_SETTLE_SECONDS", 0)


def _make_runner(
    *,
    previous: str = "previous clipboard",
    pbpaste_rc: int = 0,
    pbcopy_rc: int = 0,
    keystroke_stderr: str | None = None,
    calls: list[tuple[list[str], str | None]],
) -> Any:
    """Fake runner that records (argv, input_text) and simulates each binary."""

    def fake_runner(
        argv: list[str], timeout: float = 5.0, input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        calls.append((list(argv), input_text))
        if argv == PBPASTE:
            return subprocess.CompletedProcess(
                args=argv, returncode=pbpaste_rc, stdout=previous, stderr=""
            )
        if argv == PBCOPY:
            stderr = "pbcopy: refused" if pbcopy_rc != 0 else ""
            return subprocess.CompletedProcess(
                args=argv, returncode=pbcopy_rc, stdout="", stderr=stderr
            )
        if argv[0] == "/usr/bin/osascript":
            if keystroke_stderr is not None:
                return subprocess.CompletedProcess(
                    args=argv, returncode=1, stdout="", stderr=keystroke_stderr
                )
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")
        raise AssertionError(f"Unexpected command: {argv}")

    return fake_runner


def test_paste_success_order_and_restore() -> None:
    """pbpaste -> pbcopy(text) -> osascript cmd+v -> pbcopy(previous), text only via stdin."""
    calls: list[tuple[list[str], str | None]] = []
    mac = MacController(runner=_make_runner(previous="old stuff", calls=calls))

    result = mac.paste_text("olá mundo")

    assert result == {"ok": True, "chars": len("olá mundo")}
    assert [argv[0] for argv, _ in calls] == [
        "/usr/bin/pbpaste",
        "/usr/bin/pbcopy",
        "/usr/bin/osascript",
        "/usr/bin/pbcopy",
    ]
    assert calls[0] == (PBPASTE, None)
    assert calls[1] == (PBCOPY, "olá mundo")
    osa_argv = calls[2][0]
    assert osa_argv[:2] == ["/usr/bin/osascript", "-e"]
    assert osa_argv[2] == 'tell application "System Events" to keystroke "v" using {command down}'
    assert calls[3] == (PBCOPY, "old stuff")
    # The text never appears in argv
    assert all("olá mundo" not in arg for argv, _ in calls for arg in argv)


def test_paste_restores_clipboard_when_keystroke_fails() -> None:
    calls: list[tuple[list[str], str | None]] = []
    mac = MacController(
        runner=_make_runner(previous="keep me", keystroke_stderr=ACCESSIBILITY_DENIED, calls=calls)
    )

    result = mac.paste_text("secret dictation")

    assert result["ok"] is False
    assert result["needs_accessibility"] is True
    assert "Accessibility" in result["error"]
    assert "secret dictation" not in result["error"]
    # The clipboard is still restored after the failed keystroke
    assert calls[-1] == (PBCOPY, "keep me")


def test_generic_keystroke_failure_is_not_accessibility() -> None:
    calls: list[tuple[list[str], str | None]] = []
    mac = MacController(
        runner=_make_runner(keystroke_stderr="some other osascript error", calls=calls)
    )

    result = mac.paste_text("hi")

    assert result["ok"] is False
    assert result["needs_accessibility"] is False
    assert result["error"] == "some other osascript error"
    assert calls[-1] == (PBCOPY, "previous clipboard")


def test_pbpaste_failure_skips_restore() -> None:
    calls: list[tuple[list[str], str | None]] = []
    mac = MacController(runner=_make_runner(pbpaste_rc=1, calls=calls))

    result = mac.paste_text("hello")

    assert result == {"ok": True, "chars": 5}
    pbcopy_calls = [c for c in calls if c[0] == PBCOPY]
    assert pbcopy_calls == [(PBCOPY, "hello")]
    assert len([c for c in calls if c[0][0] == "/usr/bin/osascript"]) == 1


def test_pbcopy_failure_returns_error_without_keystroke() -> None:
    calls: list[tuple[list[str], str | None]] = []
    mac = MacController(runner=_make_runner(pbcopy_rc=1, calls=calls))

    result = mac.paste_text("hello")

    assert result == {"ok": False, "error": "pbcopy: refused"}
    assert not any(argv[0] == "/usr/bin/osascript" for argv, _ in calls)


@pytest.mark.parametrize("bad", ["", "   \n\t", None, 123, ["x"]])
def test_empty_or_non_text_is_rejected_without_subprocess(bad: Any) -> None:
    calls: list[tuple[list[str], str | None]] = []
    mac = MacController(runner=_make_runner(calls=calls))

    assert mac.paste_text(bad) == {"ok": False, "error": "Nothing to paste."}
    assert calls == []


def test_too_long_text_is_rejected_without_subprocess() -> None:
    calls: list[tuple[list[str], str | None]] = []
    mac = MacController(runner=_make_runner(calls=calls))

    assert mac.paste_text("a" * 20001) == {"ok": False, "error": "Text too long to paste."}
    assert calls == []


def test_text_at_the_limit_is_accepted() -> None:
    calls: list[tuple[list[str], str | None]] = []
    mac = MacController(runner=_make_runner(calls=calls))

    result = mac.paste_text("a" * 20000)

    assert result == {"ok": True, "chars": 20000}


def test_default_runner_uses_argv_stdin_and_no_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default runner must call subprocess.run with shell=False, an argv list and stdin input."""
    seen: dict[str, Any] = {}

    def fake_subprocess_run(argv: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    proc = MacController._default_runner(["/usr/bin/pbcopy"], input_text="x")

    assert proc.returncode == 0
    assert seen["argv"] == ["/usr/bin/pbcopy"]
    assert isinstance(seen["argv"], list)
    assert seen["kwargs"]["shell"] is False
    assert seen["kwargs"]["input"] == "x"


def test_runner_without_input_param_is_called_as_before() -> None:
    """Legacy runners (no input_text parameter) keep working; input_text is simply not forwarded."""
    recorded: list[list[str]] = []

    def legacy_runner(argv: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
        recorded.append(argv)
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    mac = MacController(runner=legacy_runner)

    assert mac.execute_keystroke("cmd+v")["ok"] is True
    assert recorded[-1][:2] == ["/usr/bin/osascript", "-e"]
