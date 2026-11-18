"""Tests for the Mac-only credentials routes (GET/PUT /api/credentials) backed by `.env`."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.panels import credentials

SECRET = "sk-test-SECRETVALUE1234"
SECRET_TAIL = "1234"
ALL_KEYS = [key for key, _label in credentials.CREDENTIAL_KEYS]


def _require_testclient(request: Request) -> None:
    if request.client is None or request.client.host != "testclient":
        raise HTTPException(status_code=403, detail="Mac only.")


def _always_deny(request: Request) -> None:
    raise HTTPException(status_code=403, detail="Mac only.")


def _app(env_path: Path, require: Any = _require_testclient) -> FastAPI:
    app = FastAPI()
    credentials.register(app, require, env_path)
    return app


def _by_key(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["key"]: item for item in payload["credentials"]}


@pytest.fixture(autouse=True)
def _restore_credential_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Start each test with the managed keys unset; monkeypatch restores os.environ afterwards.
    for key in ALL_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_get_with_missing_file_reports_all_unset(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path / ".env"))

    response = client.get("/api/credentials")

    assert response.status_code == 200
    payload = response.json()
    assert [item["key"] for item in payload["credentials"]] == ALL_KEYS
    assert [item["label"] for item in payload["credentials"]] == [
        "Home Assistant URL",
        "Home Assistant token",
        "OBS WebSocket URL",
        "OBS WebSocket password",
        "GitHub token",
    ]
    assert all(item["set"] is False and item["preview"] == "" for item in payload["credentials"])


def test_get_with_empty_file_reports_all_unset(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    client = TestClient(_app(env))

    payload = client.get("/api/credentials").json()

    assert all(item["set"] is False for item in payload["credentials"])


def test_put_then_get_shows_masked_preview(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    client = TestClient(_app(env))

    put = client.put("/api/credentials", json={"values": {"GITHUB_TOKEN": SECRET}})
    get = client.get("/api/credentials")

    assert put.status_code == 200
    assert get.status_code == 200
    item = _by_key(get.json())["GITHUB_TOKEN"]
    assert item["set"] is True
    assert item["preview"] == "••••" + SECRET_TAIL
    assert _by_key(get.json())["OBS_WS_URL"]["set"] is False


def test_short_value_is_fully_masked(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path / ".env"))

    payload = client.put("/api/credentials", json={"values": {"OBS_WS_PASSWORD": "abcdefgh"}}).json()

    item = _by_key(payload)["OBS_WS_PASSWORD"]
    assert item["set"] is True
    assert item["preview"] == "••••"


def test_raw_secret_never_appears_in_any_response(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path / ".env"))

    put = client.put("/api/credentials", json={"values": {"GITHUB_TOKEN": SECRET}})
    get = client.get("/api/credentials")

    assert SECRET not in put.text
    assert SECRET not in get.text


def test_env_file_keeps_unrelated_lines_and_escapes_value(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    original = '# Local settings\nLLM_API_KEY=abc\n\nexport OTHER_VALUE="kept"\n'
    env.write_text(original, encoding="utf-8")
    client = TestClient(_app(env))
    tricky = 'pa"ss\\word'

    response = client.put("/api/credentials", json={"values": {"OBS_WS_PASSWORD": tricky}})

    assert response.status_code == 200
    content = env.read_text(encoding="utf-8")
    assert content.startswith('# Local settings\nLLM_API_KEY=abc\n\nexport OTHER_VALUE="kept"\n')
    assert 'OBS_WS_PASSWORD="pa\\"ss\\\\word"\n' in content
    assert _by_key(client.get("/api/credentials").json())["OBS_WS_PASSWORD"]["set"] is True


def test_replacing_a_key_keeps_its_position(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "FIRST=1\nGITHUB_TOKEN=\"old-token-value\"\n# trailing comment\nLAST=2\n",
        encoding="utf-8",
    )
    client = TestClient(_app(env))

    client.put("/api/credentials", json={"values": {"GITHUB_TOKEN": "new-token-value"}})

    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines == [
        "FIRST=1",
        'GITHUB_TOKEN="new-token-value"',
        "# trailing comment",
        "LAST=2",
    ]


def test_reading_accepts_single_quotes_export_and_comments(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# comment\n\nexport HOME_ASSISTANT_URL='http://ha.local:8123'\nGITHUB_TOKEN=plain\n",
        encoding="utf-8",
    )
    client = TestClient(_app(env))

    payload = _by_key(client.get("/api/credentials").json())

    assert payload["HOME_ASSISTANT_URL"]["set"] is True
    assert payload["GITHUB_TOKEN"]["set"] is True
    assert payload["GITHUB_TOKEN"]["preview"] == "••••"  # 5 characters: fully masked


def test_clearing_with_empty_string_removes_the_line(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("KEEP=yes\nGITHUB_TOKEN=\"secret-value-here\"\nALSO=yes\n", encoding="utf-8")
    client = TestClient(_app(env))

    response = client.put("/api/credentials", json={"values": {"GITHUB_TOKEN": "   "}})

    assert response.status_code == 200
    assert _by_key(response.json())["GITHUB_TOKEN"]["set"] is False
    assert env.read_text(encoding="utf-8") == "KEEP=yes\nALSO=yes\n"


def test_unknown_key_is_rejected_with_422(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("KEEP=yes\n", encoding="utf-8")
    client = TestClient(_app(env))

    response = client.put(
        "/api/credentials",
        json={"values": {"GITHUB_TOKEN": "valid-token-value", "NOT_ALLOWED": "x"}},
    )

    assert response.status_code == 422
    assert env.read_text(encoding="utf-8") == "KEEP=yes\n"


def test_newline_in_value_is_rejected_and_file_untouched(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("KEEP=yes\n", encoding="utf-8")
    client = TestClient(_app(env))

    response = client.put(
        "/api/credentials",
        json={"values": {"GITHUB_TOKEN": "good-value-1", "OBS_WS_PASSWORD": "line1\nINJECTED=1"}},
    )

    assert response.status_code == 422
    assert env.read_text(encoding="utf-8") == "KEEP=yes\n"
    assert "INJECTED" not in env.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "bad_value",
    [
        "nul\x00byte",
        "carriage\rreturn",
        "tab\there",
        "x" * 513,
        12345,
        None,
    ],
)
def test_invalid_values_are_rejected_with_422(tmp_path: Path, bad_value: Any) -> None:
    env = tmp_path / ".env"
    client = TestClient(_app(env))

    response = client.put("/api/credentials", json={"values": {"GITHUB_TOKEN": bad_value}})

    assert response.status_code == 422
    assert not env.exists()


def test_value_with_512_characters_is_accepted(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path / ".env"))

    response = client.put("/api/credentials", json={"values": {"GITHUB_TOKEN": "a" * 512}})

    assert response.status_code == 200
    assert _by_key(response.json())["GITHUB_TOKEN"]["set"] is True


def test_non_mac_client_gets_403_on_both_routes_and_file_is_untouched(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("KEEP=yes\n", encoding="utf-8")
    client = TestClient(_app(env, require=_always_deny))

    get = client.get("/api/credentials")
    put = client.put("/api/credentials", json={"values": {"GITHUB_TOKEN": SECRET}})

    assert get.status_code == 403
    assert put.status_code == 403
    assert env.read_text(encoding="utf-8") == "KEEP=yes\n"
    assert SECRET not in put.text


def test_new_file_is_created_with_mode_0600(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    client = TestClient(_app(env))

    client.put("/api/credentials", json={"values": {"GITHUB_TOKEN": SECRET}})

    assert env.exists()
    assert env.stat().st_mode & 0o777 == 0o600


def test_existing_file_mode_is_kept(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("KEEP=yes\n", encoding="utf-8")
    os.chmod(env, 0o640)
    client = TestClient(_app(env))

    client.put("/api/credentials", json={"values": {"GITHUB_TOKEN": SECRET}})

    assert env.stat().st_mode & 0o777 == 0o640


def test_os_environ_is_updated_and_cleared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    client = TestClient(_app(env))
    monkeypatch.setenv("OBS_WS_URL", "ws://old:4455")

    client.put(
        "/api/credentials",
        json={"values": {"GITHUB_TOKEN": SECRET, "OBS_WS_URL": "ws://new:4455"}},
    )
    assert os.environ["GITHUB_TOKEN"] == SECRET
    assert os.environ["OBS_WS_URL"] == "ws://new:4455"

    client.put("/api/credentials", json={"values": {"GITHUB_TOKEN": ""}})
    assert "GITHUB_TOKEN" not in os.environ


def test_logs_never_contain_the_secret(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    client = TestClient(_app(tmp_path / ".env"))
    caplog.set_level(logging.DEBUG)

    put = client.put("/api/credentials", json={"values": {"GITHUB_TOKEN": SECRET}})
    client.get("/api/credentials")

    assert put.status_code == 200
    assert SECRET not in caplog.text
    assert SECRET_TAIL not in caplog.text
    assert "GITHUB_TOKEN" in caplog.text
