"""Catálogo de provedores LLM compatíveis com OpenAI, persistência em SQLite e descoberta de modelos."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.memory import MemoryStore

_META_KEY_PROVIDER = "llm_provider_config"
_MODELS_FETCH_TIMEOUT_S = 8.0


@dataclass(frozen=True, slots=True)
class ProviderPreset:
    """Definição de um provedor LLM compatível com OpenAI."""

    id: str
    name: str
    default_base_url: str
    default_model: str
    suggested_models: tuple[str, ...]
    api_key_env: str
    requires_api_key: bool


PROVIDER_PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        id="local_proxy",
        name="Proxy Local",
        default_base_url="http://127.0.0.1:31415/v1",
        default_model="claude-haiku-4-5",
        suggested_models=("claude-haiku-4-5", "claude-sonnet-4-5", "gpt-4o-mini"),
        api_key_env="LLM_API_KEY",
        requires_api_key=False,
    ),
    ProviderPreset(
        id="ollama",
        name="Ollama (Local)",
        default_base_url="http://127.0.0.1:11434/v1",
        default_model="llama3.2",
        suggested_models=("llama3.2", "qwen2.5:7b", "mistral"),
        api_key_env="OLLAMA_API_KEY",
        requires_api_key=False,
    ),
    ProviderPreset(
        id="openai",
        name="OpenAI",
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        suggested_models=("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"),
        api_key_env="OPENAI_API_KEY",
        requires_api_key=True,
    ),
    ProviderPreset(
        id="openrouter",
        name="OpenRouter",
        default_base_url="https://openrouter.ai/api/v1",
        default_model="anthropic/claude-3.5-haiku",
        suggested_models=(
            "anthropic/claude-3.5-haiku",
            "openai/gpt-4o-mini",
            "google/gemini-2.5-flash",
        ),
        api_key_env="OPENROUTER_API_KEY",
        requires_api_key=True,
    ),
    ProviderPreset(
        id="gemini",
        name="Google Gemini (OpenAI-compat)",
        default_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        default_model="gemini-2.5-flash",
        suggested_models=("gemini-2.5-flash", "gemini-2.5-pro"),
        api_key_env="GEMINI_API_KEY",
        requires_api_key=True,
    ),
    ProviderPreset(
        id="custom",
        name="Personalizado (OpenAI-compat)",
        default_base_url="",
        default_model="",
        suggested_models=(),
        api_key_env="LLM_API_KEY",
        requires_api_key=False,
    ),
)

_PRESETS_BY_ID: dict[str, ProviderPreset] = {preset.id: preset for preset in PROVIDER_PRESETS}


def get_preset(provider_id: str) -> ProviderPreset | None:
    """Retorna o preset correspondente ao `provider_id`, se existir."""
    return _PRESETS_BY_ID.get(provider_id.strip().lower())


def validate_base_url(url: str) -> str:
    """Valida que a URL base usa HTTP/HTTPS com host válido e remove barra final."""
    cleaned = url.strip().rstrip("/")
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL base inválida: informe uma URL http:// ou https:// com host válido.")
    return cleaned


def infer_provider_id(base_url: str) -> str:
    """Infere o `provider_id` mais adequado a partir de uma URL base."""
    normalized = base_url.strip().rstrip("/").lower()
    for preset in PROVIDER_PRESETS:
        if preset.default_base_url and preset.default_base_url.lower() == normalized:
            return preset.id
    return "custom"


def resolve_provider_api_key(provider_id: str, fallback_key: str = "") -> tuple[str, str]:
    """Resolve a API key a partir das variáveis de ambiente sem persistir segredos no banco."""
    preset = get_preset(provider_id)
    env_name = preset.api_key_env if preset is not None else "LLM_API_KEY"
    env_val = os.getenv(env_name, "").strip()
    if env_val:
        return env_val, env_name
    if provider_id in {"local_proxy", "custom"}:
        llm_fallback = os.getenv("LLM_API_KEY", "").strip() or fallback_key.strip()
        return llm_fallback, env_name
    return "", env_name


def build_active_provider_state(
    settings: Settings,
    provider_id: str | None = None,
    env_fallback_key: str = "",
) -> dict[str, Any]:
    """Monta a visão pública (sem segredos) do provedor e modelo ativos."""
    resolved_id = (provider_id or infer_provider_id(settings.llm_base_url)).strip().lower()
    if resolved_id not in _PRESETS_BY_ID:
        resolved_id = "custom"
    api_key, env_name = resolve_provider_api_key(resolved_id, fallback_key=env_fallback_key)
    has_key = bool(api_key or settings.llm_api_key)
    return {
        "provider_id": resolved_id,
        "base_url": settings.llm_base_url,
        "model": settings.llm_model,
        "api_key_env": env_name,
        "has_api_key": has_key,
    }


def list_provider_presets(env_fallback_key: str = "") -> list[dict[str, Any]]:
    """Lista os presets disponíveis com status booleano da chave no ambiente (sem expor segredos)."""
    items: list[dict[str, Any]] = []
    for preset in PROVIDER_PRESETS:
        api_key, env_name = resolve_provider_api_key(preset.id, fallback_key=env_fallback_key)
        items.append(
            {
                "id": preset.id,
                "name": preset.name,
                "default_base_url": preset.default_base_url,
                "default_model": preset.default_model,
                "suggested_models": list(preset.suggested_models),
                "api_key_env": env_name,
                "requires_api_key": preset.requires_api_key,
                "has_api_key": bool(api_key),
            }
        )
    return items


def load_saved_provider_config(
    memory: MemoryStore,
    settings: Settings,
    env_fallback_key: str = "",
) -> dict[str, Any]:
    """Carrega provedor/modelo salvos em `app_meta` e aplica em `settings`, se válidos."""
    raw = memory.get_meta(_META_KEY_PROVIDER)
    if not raw:
        return build_active_provider_state(settings, env_fallback_key=env_fallback_key)

    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("formato inválido")
        provider_id = str(data.get("provider_id", "")).strip().lower()
        base_url = validate_base_url(str(data.get("base_url", "")))
        model = str(data.get("model", "")).strip()
        if not model:
            raise ValueError("modelo vazio")
    except (ValueError, json.JSONDecodeError):
        return build_active_provider_state(settings, env_fallback_key=env_fallback_key)

    if provider_id not in _PRESETS_BY_ID:
        provider_id = infer_provider_id(base_url)

    api_key, _ = resolve_provider_api_key(provider_id, fallback_key=env_fallback_key)
    settings.llm_base_url = base_url
    settings.llm_model = model
    settings.llm_api_key = api_key
    return build_active_provider_state(settings, provider_id=provider_id, env_fallback_key=env_fallback_key)


def save_provider_config(
    memory: MemoryStore,
    settings: Settings,
    provider_id: str,
    base_url: str | None,
    model: str,
    env_fallback_key: str = "",
) -> dict[str, Any]:
    """Valida, aplica em memória e persiste em SQLite (`app_meta`) o provedor e modelo ativos."""
    cleaned_id = provider_id.strip().lower()
    preset = get_preset(cleaned_id)
    if preset is None:
        raise ValueError(f"Provedor desconhecido: '{provider_id}'.")

    raw_url = (base_url or "").strip() or preset.default_base_url
    if not raw_url:
        raise ValueError("Informe a URL base do provedor.")
    validated_url = validate_base_url(raw_url)

    cleaned_model = model.strip()
    if not cleaned_model:
        raise ValueError("Informe o identificador do modelo.")

    api_key, _ = resolve_provider_api_key(cleaned_id, fallback_key=env_fallback_key)
    settings.llm_base_url = validated_url
    settings.llm_model = cleaned_model
    settings.llm_api_key = api_key

    payload = {
        "provider_id": cleaned_id,
        "base_url": validated_url,
        "model": cleaned_model,
    }
    memory.set_meta(_META_KEY_PROVIDER, json.dumps(payload, ensure_ascii=False))
    return build_active_provider_state(
        settings,
        provider_id=cleaned_id,
        env_fallback_key=env_fallback_key,
    )


async def fetch_provider_models(
    base_url: str,
    api_key: str = "",
    suggested_models: tuple[str, ...] = (),
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Consulta `GET {base_url}/models` no provedor com fallback para modelos sugeridos."""
    validated_url = validate_base_url(base_url)
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    client_kwargs: dict[str, Any] = {"timeout": _MODELS_FETCH_TIMEOUT_S}
    if transport is not None:
        client_kwargs["transport"] = transport

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get(f"{validated_url}/models", headers=headers)
        if resp.status_code != 200:
            return {
                "ok": False,
                "models": list(suggested_models),
                "source": "fallback",
                "error": f"HTTP {resp.status_code} ao consultar /models",
            }
        data = resp.json()
        raw_items = data.get("data", []) if isinstance(data, dict) else []
        model_ids = sorted(
            {
                str(item.get("id", "")).strip()
                for item in raw_items
                if isinstance(item, dict) and str(item.get("id", "")).strip()
            }
        )
        if not model_ids:
            return {
                "ok": True,
                "models": list(suggested_models),
                "source": "fallback",
            }
        return {
            "ok": True,
            "models": model_ids,
            "source": "remote",
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "ok": False,
            "models": list(suggested_models),
            "source": "fallback",
            "error": str(exc) or "Falha ao consultar /models",
        }
