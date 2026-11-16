"""Configuração do aplicativo e logging com redação automática de segredos."""

from __future__ import annotations

import logging
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Diretório raiz do projeto resolvido a partir deste arquivo para funcionar de qualquer cwd
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
_DEFAULT_WEATHER_LATITUDE = -23.5505
_DEFAULT_WEATHER_LONGITUDE = -46.6333
_DEFAULT_WEATHER_CITY = "São Paulo"
_DEFAULT_MAX_SHORT_TERM_MESSAGES = 10
_DEFAULT_MAX_USER_FACTS = 25
_DEFAULT_DB_PATH = BASE_DIR / "data" / "memory.db"
_DEFAULT_COWORK_WORKSPACE_PATH = Path("/Users/nathanlucio/Desktop/Cowork")
_DEFAULT_JARVIS_VISION_MAX_DIM = 1280

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"freellmapi-[A-Za-z0-9_-]+"), "[REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9_-]+"), "[REDACTED]"),
    (re.compile(r"AIza[A-Za-z0-9_-]+"), "[REDACTED]"),
    (re.compile(r"gsk_[A-Za-z0-9_-]+"), "[REDACTED]"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._-]+", re.IGNORECASE), r"\1[REDACTED]"),
)


@dataclass(slots=True)
class Settings:
    """Parâmetros de configuração carregados do ambiente e do arquivo `.env`."""

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
    weather_latitude: float = _DEFAULT_WEATHER_LATITUDE
    weather_longitude: float = _DEFAULT_WEATHER_LONGITUDE
    weather_city: str = _DEFAULT_WEATHER_CITY
    cowork_workspace_path: Path = _DEFAULT_COWORK_WORKSPACE_PATH
    jarvis_vision_max_dim: int = _DEFAULT_JARVIS_VISION_MAX_DIM
    desk_access_token: str = ""


def _parse_int(raw: str | None, default: int) -> int:
    """Converte variável de ambiente inteira com fallback seguro para o valor padrão."""
    if raw is None:
        return default
    cleaned = raw.strip()
    if not cleaned:
        return default
    try:
        return int(cleaned)
    except ValueError:
        return default


def _parse_float(raw: str | None, default: float) -> float:
    """Converte variável de ambiente em ponto flutuante com fallback seguro."""
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
    """Resolve caminho relativo ao `BASE_DIR` quando não for absoluto."""
    if raw is None or not raw.strip():
        return default
    candidate = Path(raw.strip()).expanduser()
    if not candidate.is_absolute():
        return (BASE_DIR / candidate).resolve()
    return candidate


def _resolve_db_path(raw: str | None) -> Path:
    """Resolve o caminho do banco SQLite relativo ao `BASE_DIR` quando não for absoluto."""
    return _resolve_path(raw, _DEFAULT_DB_PATH)


def load_settings(env_path: Path | None = None) -> Settings:
    """Carrega variáveis do `.env` (em `BASE_DIR / '.env'`) e monta um `Settings`."""
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
    jarvis_vision_max_dim = max(
        320,
        _parse_int(os.getenv("JARVIS_VISION_MAX_DIM"), _DEFAULT_JARVIS_VISION_MAX_DIM),
    )
    desk_access_token = os.getenv("DESK_ACCESS_TOKEN", "").strip()

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
        weather_latitude=weather_latitude,
        weather_longitude=weather_longitude,
        weather_city=weather_city,
        cowork_workspace_path=cowork_workspace_path,
        jarvis_vision_max_dim=jarvis_vision_max_dim,
        desk_access_token=desk_access_token,
    )


def resolve_runtime_access_token(settings: Settings) -> tuple[str, bool]:
    """Retorna `(token, gerado_automaticamente)` para autenticar clientes não-loopback."""
    configured = (settings.desk_access_token or "").strip()
    if configured:
        return configured, False
    if settings.host.strip().lower() in {"127.0.0.1", "::1", "localhost"}:
        return "", False
    return secrets.token_urlsafe(12), True


class SecretRedactingFilter(logging.Filter):
    """Filtro de logging que mascara chaves de API e tokens sensíveis com `[REDACTED]`."""

    def __init__(self, secret: str = "") -> None:
        super().__init__()
        self._secret = secret.strip()
        self._formatter = logging.Formatter()

    def redact(self, text: str) -> str:
        """Substitui o segredo configurado e padrões conhecidos de chave por `[REDACTED]`."""
        if not text:
            return text
        sanitized = text
        if self._secret:
            sanitized = sanitized.replace(self._secret, "[REDACTED]")
        for pattern, replacement in _SECRET_PATTERNS:
            sanitized = pattern.sub(replacement, sanitized)
        return sanitized

    def filter(self, record: logging.LogRecord) -> bool:
        """Sanitiza a mensagem formatada e eventual traceback antes de emitir o registro."""
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
    """Remove filtros anteriores do tipo `SecretRedactingFilter` para evitar duplicação."""
    for existing in list(target.filters):
        if isinstance(existing, SecretRedactingFilter):
            target.removeFilter(existing)


def configure_logging(secret: str = "", level: int = logging.INFO) -> SecretRedactingFilter:
    """Configura logging da aplicação garantindo redação de segredos em todos os handlers."""
    redactor = SecretRedactingFilter(secret=secret)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Garante ao menos um StreamHandler padrão caso ainda não exista handler de saída.
    has_stream_handler = any(
        isinstance(handler, logging.StreamHandler) for handler in root_logger.handlers
    )
    if not has_stream_handler:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        root_logger.addHandler(stream_handler)

    # Aplica o filtro em todos os handlers do logger raiz (incluindo caplog nos testes).
    _strip_existing_redactors(root_logger)
    root_logger.addFilter(redactor)
    for handler in root_logger.handlers:
        _strip_existing_redactors(handler)
        handler.addFilter(redactor)

    # Reduz verbosidade de bibliotecas HTTP e aplica redação em seus loggers específicos.
    for lib_name in ("httpx", "httpcore", "uvicorn.access"):
        lib_logger = logging.getLogger(lib_name)
        _strip_existing_redactors(lib_logger)
        lib_logger.addFilter(redactor)
        if lib_name in ("httpx", "httpcore") and lib_logger.level == logging.NOTSET:
            lib_logger.setLevel(logging.WARNING)

    return redactor
