"""Tests for LLM provider and model selection, SQLite persistence and key security."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import LLMClient
from app.main import create_app
from app.providers import fetch_provider_models


def _build_settings(tmp_path: Path, api_key: str = "sk-secret-test-key-12345") -> Settings:
    return Settings(
        llm_base_url="http://127.0.0.1:31415/v1",
        llm_api_key=api_key,
        llm_model="claude-haiku-4-5",
        db_path=tmp_path / "memory.db",
        cowork_workspace_path=tmp_path / "Cowork",
    )


def test_list_providers_never_exposes_api_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret_openai = "sk-openai-never-leak-999"
    monkeypatch.setenv("OPENAI_API_KEY", secret_openai)
    settings = _build_settings(tmp_path, api_key="freellmapi-secret-000")
    app = create_app(settings=settings)

    with TestClient(app) as client:
        resp = client.get("/api/llm/providers")
        assert resp.status_code == 200
        body_text = resp.text
        assert secret_openai not in body_text
        assert "freellmapi-secret-000" not in body_text

        data = resp.json()
        assert data["active"]["provider_id"] == "local_proxy"
        assert data["active"]["model"] == "claude-haiku-4-5"
        assert data["active"]["has_api_key"] is True

        openai_preset = next(p for p in data["presets"] if p["id"] == "openai")
        assert openai_preset["has_api_key"] is True
        assert openai_preset["api_key_env"] == "OPENAI_API_KEY"

        diag = client.get("/api/diagnostics")
        assert diag.status_code == 200
        assert secret_openai not in diag.text
        assert "freellmapi-secret-000" not in diag.text
        assert diag.json()["llm_provider_id"] == "local_proxy"


def test_update_provider_updates_runtime_and_persists_across_restarts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    settings1 = _build_settings(tmp_path)
    llm_client = LLMClient(settings1)
    app1 = create_app(settings=settings1, llm_client=llm_client)

    with TestClient(app1) as client:
        res = client.put(
            "/api/llm/provider",
            json={
                "provider_id": "openrouter",
                "model": "google/gemini-2.5-flash",
            },
        )
        assert res.status_code == 200
        payload = res.json()
        assert payload["ok"] is True
        assert payload["active"]["provider_id"] == "openrouter"
        assert payload["active"]["base_url"] == "https://openrouter.ai/api/v1"
        assert payload["active"]["model"] == "google/gemini-2.5-flash"
        assert "sk-or-test-key" not in res.text

        # The shared runtime is reflected immediately in LLMClient, /health and /api/diagnostics
        assert llm_client._endpoint_url() == "https://openrouter.ai/api/v1/chat/completions"
        assert llm_client._build_payload("oi", [])["model"] == "google/gemini-2.5-flash"
        assert client.get("/health").json()["model"] == "google/gemini-2.5-flash"
        diag = client.get("/api/diagnostics").json()
        assert diag["llm_provider_id"] == "openrouter"
        assert diag["llm_base_url"] == "https://openrouter.ai/api/v1"

    # A new instance pointing at the same SQLite restores the saved provider and model
    settings2 = _build_settings(tmp_path)
    app2 = create_app(settings=settings2)
    with TestClient(app2) as client2:
        providers = client2.get("/api/llm/providers").json()
        assert providers["active"]["provider_id"] == "openrouter"
        assert providers["active"]["base_url"] == "https://openrouter.ai/api/v1"
        assert providers["active"]["model"] == "google/gemini-2.5-flash"


def test_update_provider_validation_errors(tmp_path: Path) -> None:
    app = create_app(settings=_build_settings(tmp_path))
    with TestClient(app) as client:
        bad_provider = client.put(
            "/api/llm/provider",
            json={"provider_id": "invalid", "model": "gpt-4o"},
        )
        assert bad_provider.status_code == 400

        bad_url = client.put(
            "/api/llm/provider",
            json={"provider_id": "custom", "base_url": "file:///etc/passwd", "model": "gpt-4o"},
        )
        assert bad_url.status_code == 400

        empty_model = client.put(
            "/api/llm/provider",
            json={"provider_id": "ollama", "model": "   "},
        )
        assert empty_model.status_code == 400


@pytest.mark.asyncio
async def test_fetch_provider_models_remote_and_fallback() -> None:
    def ok_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        assert request.headers.get("Authorization") == "Bearer test-token"
        return httpx.Response(
            200,
            content=json.dumps({"data": [{"id": "zeta"}, {"id": "alpha"}]}),
        )

    ok_result = await fetch_provider_models(
        base_url="https://api.example.com/v1",
        api_key="test-token",
        suggested_models=("fallback-1",),
        transport=httpx.MockTransport(ok_handler),
    )
    assert ok_result == {"ok": True, "models": ["alpha", "zeta"], "source": "remote"}

    def fail_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    fallback_result = await fetch_provider_models(
        base_url="https://api.example.com/v1",
        api_key="",
        suggested_models=("fallback-1", "fallback-2"),
        transport=httpx.MockTransport(fail_handler),
    )
    assert fallback_result["ok"] is False
    assert fallback_result["source"] == "fallback"
    assert fallback_result["models"] == ["fallback-1", "fallback-2"]
