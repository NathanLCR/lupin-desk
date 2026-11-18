"""App configuration and logging with automatic secret redaction."""

from __future__ import annotations

import logging
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Project root resolved from this file so it works from any cwd
BASE_DIR = Path(__file__).resolve().parent.parent

_DEFAULT_LLM_BASE_URL = "http://127.0.0.1:31415/v1"
_DEFAULT_LLM_MODEL = "claude-haiku-4-5"
_DEFAULT_HOST = "0.0.0.0"
_DEFAULT_PORT = 8000
_DEFAULT_HTTPS_PORT = 8443
_DEFAULT_CERT_FILE = BASE_DIR / "certs" / "cert.pem"
_DEFAULT_KEY_FILE = BASE_DIR / "certs" / "key.pem"
_DEFAULT_STT_MODEL = "base"
_DEFAULT_STT_LANGUAGE = "pt"
_DEFAULT_TTS_VOICE = "Luciana"
_DEFAULT_TTS_VOICE_EN = "Samantha"
_DEFAULT_LOCAL_LLM_SLOW_AFTER_S = 6.0
_DEFAULT_WEATHER_LATITUDE = -23.5505
_DEFAULT_WEATHER_LONGITUDE = -46.6333
_DEFAULT_WEATHER_CITY = "São Paulo"
_DEFAULT_MAX_SHORT_TERM_MESSAGES = 10
_DEFAULT_MAX_USER_FACTS = 25
_DEFAULT_DB_PATH = BASE_DIR / "data" / "memory.db"
_DEFAULT_COWORK_WORKSPACE_PATH = Path("/Users/nathanlucio/Desktop/Cowork")

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"freellmapi-[A-Za-z0-9_-]+"), "[REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9_-]+"), "[REDACTED]"),
    (re.compile(r"AIza[A-Za-z0-9_-]+"), "[REDACTED]"),
    (re.compile(r"gsk_[A-Za-z0-9_-]+"), "[REDACTED]"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._-]+", re.IGNORECASE), r"\1[REDACTED]"),
)


@dataclass(slots=True)
class Settings:
    """Configuration parameters loaded from the environment and the `.env` file."""

    llm_base_url: str = _DEFAULT_LLM_BASE_URL
    llm_api_key: str = ""
    llm_model: str = _DEFAULT_LLM_MODEL
    host: str = _DEFAULT_HOST
    port: int = _DEFAULT_PORT
    max_short_term_messages: int = _DEFAULT_MAX_SHORT_TERM_MESSAGES
    max_user_facts: int = _DEFAULT_MAX_USER_FACTS
    db_path: Path = _DEFAULT_DB_PATH
    https_port: int = _DEFAULT_HTTPS_PORT
    cert_file: Path = _DEFAULT_CERT_FILE
    key_file: Path = _DEFAULT_KEY_FILE
    stt_model: str = _DEFAULT_STT_MODEL
    stt_language: str = _DEFAULT_STT_LANGUAGE
    tts_voice: str = _DEFAULT_TTS_VOICE
    tts_voice_en: str = _DEFAULT_TTS_VOICE_EN
    # Lupin's voice is Kokoro; `say` is the fallback. TTS_KOKORO=0 forces `say`.
    tts_kokoro: bool = True
    # Seconds without a first token from a local model before Lupin says it is slow (0 = never).
    local_llm_slow_after_s: float = _DEFAULT_LOCAL_LLM_SLOW_AFTER_S
    weather_latitude: float = _DEFAULT_WEATHER_LATITUDE
    weather_longitude: float = _DEFAULT_WEATHER_LONGITUDE
    weather_city: str = _DEFAULT_WEATHER_CITY
    cowork_workspace_path: Path = _DEFAULT_COWORK_WORKSPACE_PATH
    desk_access_token: str = ""
    # Development only: turns off the access token for LAN clients.
    desk_dev_no_token: bool = False


def _parse_int(raw: str | None, default: int) -> int:
    """Parse an integer environment variable, falling back safely to the default."""
    if raw is None:
        return default
    cleaned = raw.strip()
    if not cleaned:
        return default
    try:
        return int(cleaned)
    except ValueError:
        return default


def _parse_bool(raw: str | None) -> bool:
    """Enabled only by an explicit value (1, true, sim, yes, on); anything else is off."""
    return (raw or "").strip().lower() in {"1", "true", "sim", "yes", "on"}


def _parse_float(raw: str | None, default: float) -> float:
    """Parse a float environment variable, falling back safely to the default."""
    if raw is None:
        return default
    cleaned = raw.strip()
    if not cleaned:
        return default
    try:
        return float(cleaned)
    except ValueError:
        return default


def _resolve_path(raw: str | None, default: Path) -> Path:
    """Resolve a path relative to `BASE_DIR` when it is not absolute."""
    if raw is None or not raw.strip():
        return default
    candidate = Path(raw.strip()).expanduser()
    if not candidate.is_absolute():
        return (BASE_DIR / candidate).resolve()
    return candidate


def _resolve_db_path(raw: str | None) -> Path:
    """Resolve the SQLite database path relative to `BASE_DIR` when it is not absolute."""
    return _resolve_path(raw, _DEFAULT_DB_PATH)


def load_settings(env_path: Path | None = None) -> Settings:
    """Load variables from `.env` (at `BASE_DIR / '.env'`) and build a `Settings`."""
    dotenv_target = env_path if env_path is not None else BASE_DIR / ".env"
    if dotenv_target.exists():
        load_dotenv(dotenv_path=dotenv_target, override=False)

    base_url = os.getenv("LLM_BASE_URL", _DEFAULT_LLM_BASE_URL).strip().rstrip("/")
    if not base_url:
        base_url = _DEFAULT_LLM_BASE_URL

    api_key = os.getenv("LLM_API_KEY", "").strip()
    model = os.getenv("LLM_MODEL", _DEFAULT_LLM_MODEL).strip() or _DEFAULT_LLM_MODEL
    host = os.getenv("HOST", _DEFAULT_HOST).strip() or _DEFAULT_HOST
    port = _parse_int(os.getenv("PORT"), _DEFAULT_PORT)
    https_port = _parse_int(os.getenv("HTTPS_PORT"), _DEFAULT_HTTPS_PORT)
    if https_port <= 0:
        https_port = _DEFAULT_HTTPS_PORT
    cert_file = _resolve_path(os.getenv("CERT_FILE"), _DEFAULT_CERT_FILE)
    key_file = _resolve_path(os.getenv("KEY_FILE"), _DEFAULT_KEY_FILE)
    stt_model = os.getenv("STT_MODEL", _DEFAULT_STT_MODEL).strip() or _DEFAULT_STT_MODEL
    stt_language = os.getenv("STT_LANGUAGE", _DEFAULT_STT_LANGUAGE).strip() or _DEFAULT_STT_LANGUAGE
    tts_voice = os.getenv("TTS_VOICE", _DEFAULT_TTS_VOICE).strip() or _DEFAULT_TTS_VOICE
    tts_voice_en = os.getenv("TTS_VOICE_EN", _DEFAULT_TTS_VOICE_EN).strip() or _DEFAULT_TTS_VOICE_EN
    tts_kokoro = os.getenv("TTS_KOKORO", "1").strip().lower() not in {"0", "false", "no", "off"}
    local_llm_slow_after_s = max(
        0.0, _parse_float(os.getenv("LOCAL_LLM_SLOW_AFTER_S"), _DEFAULT_LOCAL_LLM_SLOW_AFTER_S)
    )
    weather_latitude = _parse_float(os.getenv("WEATHER_LATITUDE"), _DEFAULT_WEATHER_LATITUDE)
    weather_longitude = _parse_float(os.getenv("WEATHER_LONGITUDE"), _DEFAULT_WEATHER_LONGITUDE)
    weather_city = os.getenv("WEATHER_CITY", _DEFAULT_WEATHER_CITY).strip() or _DEFAULT_WEATHER_CITY
    max_short_term = max(
        1,
        _parse_int(os.getenv("MAX_SHORT_TERM_MESSAGES"), _DEFAULT_MAX_SHORT_TERM_MESSAGES),
    )
    max_facts = max(
        1,
        _parse_int(os.getenv("MAX_USER_FACTS"), _DEFAULT_MAX_USER_FACTS),
    )
    db_path = _resolve_db_path(os.getenv("DB_PATH"))
    cowork_workspace_path = _resolve_path(
        os.getenv("COWORK_WORKSPACE_PATH"), _DEFAULT_COWORK_WORKSPACE_PATH
    )
    desk_access_token = os.getenv("DESK_ACCESS_TOKEN", "").strip()
    # DESK_DEV_SEM_TOKEN is the legacy name, honoured only when the new one is unset.
    dev_no_token_raw = os.getenv("DESK_DEV_NO_TOKEN")
    if dev_no_token_raw is None:
        dev_no_token_raw = os.getenv("DESK_DEV_SEM_TOKEN")
    desk_dev_no_token = _parse_bool(dev_no_token_raw)

    return Settings(
        llm_base_url=base_url,
        llm_api_key=api_key,
        llm_model=model,
        host=host,
        port=port,
        max_short_term_messages=max_short_term,
        max_user_facts=max_facts,
        db_path=db_path,
        https_port=https_port,
        cert_file=cert_file,
        key_file=key_file,
        stt_model=stt_model,
        stt_language=stt_language,
        tts_voice=tts_voice,
        tts_voice_en=tts_voice_en,
        tts_kokoro=tts_kokoro,
        local_llm_slow_after_s=local_llm_slow_after_s,
        weather_latitude=weather_latitude,
        weather_longitude=weather_longitude,
        weather_city=weather_city,
        cowork_workspace_path=cowork_workspace_path,
        desk_access_token=desk_access_token,
        desk_dev_no_token=desk_dev_no_token,
    )


def resolve_runtime_access_token(settings: Settings) -> tuple[str, bool]:
    """Return `(token, auto_generated)` used to authenticate non-loopback clients."""
    if settings.desk_dev_no_token:
        return "", False
    configured = (settings.desk_access_token or "").strip()
    if configured:
        return configured, False
    if settings.host.strip().lower() in {"127.0.0.1", "::1", "localhost"}:
        return "", False
    return secrets.token_urlsafe(12), True


class SecretRedactingFilter(logging.Filter):
    """Logging filter that masks API keys and sensitive tokens with `[REDACTED]`."""

    def __init__(self, secret: str = "") -> None:
        super().__init__()
        self._secret = secret.strip()
        self._formatter = logging.Formatter()

    def redact(self, text: str) -> str:
        """Replace the configured secret and known key patterns with `[REDACTED]`."""
        if not text:
            return text
        sanitized = text
        if self._secret:
            sanitized = sanitized.replace(self._secret, "[REDACTED]")
        for pattern, replacement in _SECRET_PATTERNS:
            sanitized = pattern.sub(replacement, sanitized)
        return sanitized

    def filter(self, record: logging.LogRecord) -> bool:
        """Sanitize the formatted message and any traceback before emitting the record."""
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = str(record.msg)
        record.msg = self.redact(rendered)
        record.args = None

        if record.exc_info and not record.exc_text:
            record.exc_text = self._formatter.formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = self.redact(record.exc_text)
        return True


def _strip_existing_redactors(target: logging.Filterer) -> None:
    """Remove earlier `SecretRedactingFilter` instances to avoid duplicates."""
    for existing in list(target.filters):
        if isinstance(existing, SecretRedactingFilter):
            target.removeFilter(existing)


def configure_logging(secret: str = "", level: int = logging.INFO) -> SecretRedactingFilter:
    """Configure application logging, ensuring secret redaction on every handler."""
    redactor = SecretRedactingFilter(secret=secret)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Ensure at least one default StreamHandler exists when there is no output handler yet.
    has_stream_handler = any(
        isinstance(handler, logging.StreamHandler) for handler in root_logger.handlers
    )
    if not has_stream_handler:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        root_logger.addHandler(stream_handler)

    # Apply the filter to every root logger handler (including caplog in tests).
    _strip_existing_redactors(root_logger)
    root_logger.addFilter(redactor)
    for handler in root_logger.handlers:
        _strip_existing_redactors(handler)
        handler.addFilter(redactor)

    # Quiet down HTTP libraries and apply redaction to their specific loggers.
    for lib_name in ("httpx", "httpcore", "uvicorn.access"):
        lib_logger = logging.getLogger(lib_name)
        _strip_existing_redactors(lib_logger)
        lib_logger.addFilter(redactor)
        if lib_name in ("httpx", "httpcore") and lib_logger.level == logging.NOTSET:
            lib_logger.setLevel(logging.WARNING)

    return redactor
