"""Mac-only REST routes to view and edit the secret values kept in the `.env` file.

GET returns, for each allowlisted key, whether it is set and a masked preview. The full
value is never returned, logged, or placed in an error message. PUT writes the `.env`
file atomically, keeps every unrelated line byte for byte, and mirrors the change into
`os.environ`.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from app.config import BASE_DIR

logger = logging.getLogger(__name__)

CREDENTIAL_KEYS: tuple[tuple[str, str], ...] = (
    ("HOME_ASSISTANT_URL", "Home Assistant URL"),
    ("HOME_ASSISTANT_TOKEN", "Home Assistant token"),
    ("OBS_WS_URL", "OBS WebSocket URL"),
    ("OBS_WS_PASSWORD", "OBS WebSocket password"),
    ("GITHUB_TOKEN", "GitHub token"),
)
_ALLOWED_KEYS: frozenset[str] = frozenset(key for key, _label in CREDENTIAL_KEYS)
_MAX_VALUE_CHARS = 512
_MASK = "••••"
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WRITE_LOCK = threading.Lock()


class CredentialsUpdate(BaseModel):
    values: dict[str, Any]


def _mask(value: str) -> str:
    if len(value) <= 8:
        return _MASK
    return _MASK + value[-4:]


def _unescape_double_quoted(inner: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(inner):
        char = inner[i]
        if char == "\\" and i + 1 < len(inner) and inner[i + 1] in ("\\", '"'):
            out.append(inner[i + 1])
            i += 2
            continue
        out.append(char)
        i += 1
    return "".join(out)


def _parse_line(line: str) -> tuple[str, str] | None:
    """Return (key, value) for a `KEY=value` line, or None for blanks, comments and others."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].lstrip()
    if "=" not in stripped:
        return None
    key, _sep, raw = stripped.partition("=")
    key = key.strip()
    if not _KEY_RE.match(key):
        return None
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        return key, _unescape_double_quoted(raw[1:-1])
    if len(raw) >= 2 and raw[0] == "'" and raw[-1] == "'":
        return key, raw[1:-1]
    return key, raw


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.readlines()


def _current_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in _read_lines(path):
        parsed = _parse_line(line)
        if parsed is None:
            continue
        key, value = parsed
        if key in _ALLOWED_KEYS and value:
            values[key] = value
    return values


def _payload(path: Path) -> dict[str, list[dict[str, Any]]]:
    values = _current_values(path)
    credentials: list[dict[str, Any]] = []
    for key, label in CREDENTIAL_KEYS:
        value = values.get(key, "")
        credentials.append(
            {
                "key": key,
                "label": label,
                "set": bool(value),
                "preview": _mask(value) if value else "",
            }
        )
    return {"credentials": credentials}


def _validate(values: dict[str, Any]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, raw in values.items():
        if key not in _ALLOWED_KEYS:
            raise HTTPException(status_code=422, detail="Unknown credential key.")
        if not isinstance(raw, str):
            raise HTTPException(status_code=422, detail=f"Value for {key} must be a string.")
        if any(unicodedata.category(char) == "Cc" for char in raw):
            raise HTTPException(
                status_code=422,
                detail=f"Value for {key} contains a control character.",
            )
        value = raw.strip()
        if len(value) > _MAX_VALUE_CHARS:
            raise HTTPException(
                status_code=422,
                detail=f"Value for {key} is longer than {_MAX_VALUE_CHARS} characters.",
            )
        cleaned[key] = value
    return cleaned


def _render_line(key: str, value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'{key}="{escaped}"\n'


def _merge(lines: list[str], changes: dict[str, str]) -> list[str]:
    """Return the new file lines: replace in place, drop cleared keys, append new keys."""
    result: list[str] = []
    placed: set[str] = set()
    for line in lines:
        parsed = _parse_line(line)
        if parsed is None or parsed[0] not in changes:
            result.append(line)
            continue
        key = parsed[0]
        if key in placed:
            continue
        placed.add(key)
        value = changes[key]
        if value:
            result.append(_render_line(key, value))
    if result and not result[-1].endswith("\n"):
        result[-1] += "\n"
    for key, value in changes.items():
        if key not in placed and value:
            result.append(_render_line(key, value))
    return result


def _write_atomic(path: Path, content: str) -> None:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, tmp_name = tempfile.mkstemp(prefix=".env.", suffix=".tmp", dir=str(parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def _apply(path: Path, changes: dict[str, str]) -> None:
    with _WRITE_LOCK:
        lines = _read_lines(path)
        content = "".join(_merge(lines, changes))
        _write_atomic(path, content)
    for key, value in changes.items():
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)
    logger.info("Credentials updated: %s", ", ".join(sorted(changes)))


def register(
    fastapi_app: FastAPI,
    require_mac_client: Callable[[Request], Any],
    env_path: Path | str | None = None,
) -> None:
    """Register GET and PUT /api/credentials. `require_mac_client` guards both routes."""
    path = Path(env_path) if env_path is not None else BASE_DIR / ".env"

    @fastapi_app.get("/api/credentials")
    def get_credentials(request: Request) -> dict[str, list[dict[str, Any]]]:
        require_mac_client(request)
        return _payload(path)

    @fastapi_app.put("/api/credentials")
    async def put_credentials(request: Request) -> dict[str, list[dict[str, Any]]]:
        require_mac_client(request)
        try:
            body = CredentialsUpdate.model_validate(await request.json())
        except Exception:
            raise HTTPException(status_code=422, detail="Body must be {\"values\": {KEY: string}}.") from None
        changes = _validate(body.values)
        if changes:
            _apply(path, changes)
        return _payload(path)
