"""Aplicação FastAPI principal, endpoints HTTP, Dock/Atalhos Mac, STT/TTS e WebSocket."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import json
import logging
import uuid
from contextlib import asynccontextmanager
from email.parser import BytesParser
from email.policy import default as email_default_policy
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import BASE_DIR, Settings, configure_logging, load_settings, resolve_runtime_access_token
from app.cowork import CoworkStore, get_git_sync_status
from app.llm import LLMClient, LLMError
from app.mac_control import MacController
from app.memory import MemoryStore
from app.providers import (
    build_active_provider_state,
    fetch_provider_models,
    get_preset,
    list_provider_presets,
    load_saved_provider_config,
    resolve_provider_api_key,
    save_provider_config,
)
from app.shortcuts import ShortcutStore
from app.skills import (
    build_skills_prompt,
    get_trick,
    list_skills_payload,
    load_enabled_skills,
    set_skill_enabled,
)
from app.stt import LocalSTT
from app.today import FirstWakeTracker, TodayEngine
from app.tts import ServerTTS

logger = logging.getLogger(__name__)

_FRIENDLY_LLM_ERROR = "Não consegui falar com o modelo agora. Verifique se a API local está rodando."
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})
_BASE_URL_OVERRIDE_PROVIDERS = frozenset({"local_proxy", "ollama", "custom"})


def _is_loopback_host(host: str | None) -> bool:
    """Retorna True quando o cliente conecta a partir de loopback local."""
    normalized = (host or "").strip().lower()
    return normalized in _LOOPBACK_HOSTS


def _extract_access_token(headers: Any, query_token: str | None = None) -> str:
    """Extrai token Bearer/X-Desk-Token ou query param `token`."""
    auth_header = (headers.get("authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    desk_header = (headers.get("x-desk-token") or "").strip()
    if desk_header:
        return desk_header
    return (query_token or "").strip()


class FactCreateRequest(BaseModel):
    """Payload para criação manual de fato de memória de longo prazo."""

    fact: str = ""
    category: str = "general"
    pinned: bool | None = None
    importance: int | None = None


class LLMProviderUpdateRequest(BaseModel):
    """Payload para atualização do provedor e modelo LLM ativos."""

    provider_id: str
    base_url: str | None = None
    model: str


class SkillToggleRequest(BaseModel):
    """Payload para ativar ou desativar uma skill do pet."""

    enabled: bool


class FactPatchRequest(BaseModel):
    """Payload para atualizar fixação (`pinned`) ou importância de um fato."""

    pinned: bool | None = None
    importance: int | None = None


class ClearMemoryRequest(BaseModel):
    """Payload opcional para limpeza da memória."""

    include_facts: bool = False


class ShortcutPayloadRequest(BaseModel):
    """Payload flexível para criação e edição de atalhos."""

    slug: str | None = None
    title: str | None = None
    icon: str | None = None
    category: str | None = None
    action_type: str | None = None
    payload: dict[str, Any] | str | None = None
    voice_triggers: str | None = None
    color: str | None = None
    pinned_on_deck: bool | None = None
    sort_order: int | None = None
    requires_confirmation: bool | None = None


class ShortcutReorderRequest(BaseModel):
    """Payload para reordenação dos tiles do Stream Deck."""

    ordered_ids: list[int | str] = Field(default_factory=list)
    ids: list[int | str] = Field(default_factory=list)


class AppActivateRequest(BaseModel):
    """Payload para ativar/abrir um aplicativo no macOS."""

    app: str = ""
    name: str = ""


# Protocolo Brain<->Body (docs/protocolo-cerebro-corpo.md).
PROTOCOL_VERSION = 1
_AUDIO_CHUNK_BYTES = 24 * 1024
# Prioridade para escolher o Active Body; tipos fora da tabela valem 1.
_BODY_RANK = {"esp32": 3, "rg406h-web": 2}


class TTSRequest(BaseModel):
    """Payload para síntese de voz offline no servidor Mac."""

    text: str = ""
    voice: str | None = None
    format: str | None = None
    output_format: str | None = None


def _decode_base64_audio(raw_data: str) -> bytes:
    """Decodifica string base64 (com ou sem prefixo data URL) para bytes."""
    cleaned = (raw_data or "").strip()
    if not cleaned:
        return b""
    if cleaned.startswith("data:") and "," in cleaned:
        cleaned = cleaned.split(",", 1)[1].strip()
    try:
        return base64.b64decode(cleaned, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Áudio base64 inválido.") from exc


def _parse_multipart_pure_python(content_type: str, body: bytes) -> tuple[bytes, str, str | None]:
    """Extrai arquivo de áudio, MIME e idioma de `multipart/form-data` sem exigir python-multipart."""
    raw_msg = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("latin-1") + body
    msg = BytesParser(policy=email_default_policy).parsebytes(raw_msg)
    if not msg.is_multipart():
        raise ValueError("Corpo multipart inválido.")

    audio_bytes = b""
    mime_type = "audio/webm"
    language: str | None = None

    for part in msg.iter_parts():
        disp_name = part.get_param("name", header="content-disposition")
        payload = part.get_payload(decode=True) or b""
        if disp_name in {"file", "audio", "recording"}:
            audio_bytes = payload
            part_ct = part.get_content_type()
            if part_ct and part_ct != "application/octet-stream":
                mime_type = part_ct
        elif disp_name == "mime_type":
            val = payload.decode("utf-8", errors="ignore").strip()
            if val:
                mime_type = val
        elif disp_name == "language":
            val = payload.decode("utf-8", errors="ignore").strip()
            if val:
                language = val

    return audio_bytes, mime_type, language


async def _extract_stt_request(request: Request, default_language: str) -> tuple[bytes, str, str]:
    """Lê bytes de áudio, mime_type e language de JSON base64, multipart ou binário direto."""
    content_type = (request.headers.get("content-type") or "").strip()
    lower_ct = content_type.lower()

    if "application/json" in lower_ct or not lower_ct:
        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payload JSON inválido para STT.",
            ) from exc
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payload STT deve ser um objeto JSON.",
            )
        raw_b64 = str(payload.get("data") or payload.get("audio") or "")
        try:
            audio_bytes = _decode_base64_audio(raw_b64)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        mime_type = str(payload.get("mime_type") or "audio/webm").strip() or "audio/webm"
        language = str(payload.get("language") or default_language).strip() or default_language
        return audio_bytes, mime_type, language

    if "multipart/form-data" in lower_ct:
        raw_body = await request.body()
        try:
            audio_bytes, mime_type, lang = _parse_multipart_pure_python(content_type, raw_body)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return audio_bytes, mime_type, lang or default_language

    raw_body = await request.body()
    mime_type = content_type.split(";", 1)[0].strip() or "audio/webm"
    return raw_body, mime_type, default_language


def create_app(
    settings: Settings | None = None,
    memory_store: MemoryStore | None = None,
    llm_client: LLMClient | None = None,
    shortcut_store: ShortcutStore | None = None,
    mac_controller: MacController | None = None,
    stt_engine: LocalSTT | None = None,
    tts_engine: ServerTTS | None = None,
    cowork_store: CoworkStore | None = None,
    today_engine: TodayEngine | None = None,
) -> FastAPI:
    """Cria e configura a instância FastAPI com memória, atalhos, Mac, voz e WebSocket."""
    resolved_settings = settings or load_settings()
    env_llm_api_key = resolved_settings.llm_api_key
    configure_logging(secret=env_llm_api_key)
    runtime_access_token, token_generated = resolve_runtime_access_token(resolved_settings)
    if resolved_settings.desk_dev_sem_token:
        logger.warning(
            "DESK_DEV_SEM_TOKEN ligado: qualquer aparelho da rede acessa /api e /ws sem token. "
            "Use só em desenvolvimento."
        )
    if token_generated:
        logger.warning(
            "DESK_ACCESS_TOKEN não definido no .env; token efêmero gerado para clientes não-loopback: %s",
            runtime_access_token,
        )

    own_memory = memory_store is None
    resolved_memory = memory_store or MemoryStore(
        db_path=resolved_settings.db_path,
        max_short_term_messages=resolved_settings.max_short_term_messages,
        max_user_facts=resolved_settings.max_user_facts,
    )
    active_provider_state = load_saved_provider_config(
        resolved_memory,
        resolved_settings,
        env_fallback_key=env_llm_api_key,
    )
    enabled_skill_ids = load_enabled_skills(resolved_memory)

    own_shortcuts = shortcut_store is None
    resolved_shortcuts = shortcut_store or ShortcutStore(db_path=resolved_settings.db_path)

    resolved_llm = llm_client or LLMClient(resolved_settings)
    resolved_mac = mac_controller or MacController()
    resolved_stt = stt_engine or LocalSTT(
        model_name=resolved_settings.stt_model,
        language=resolved_settings.stt_language,
    )
    resolved_tts = tts_engine or ServerTTS(default_voice=resolved_settings.tts_voice)
    resolved_cowork = cowork_store or CoworkStore(resolved_settings.cowork_workspace_path)
    resolved_today = today_engine or TodayEngine(resolved_settings, resolved_cowork)
    resolved_first_wake = FirstWakeTracker(resolved_memory)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            if own_shortcuts:
                resolved_shortcuts.close()
            if own_memory:
                resolved_memory.close()

    fastapi_app = FastAPI(
        title="Desk Assistant",
        description="Assistente de mesa estilo EMO com memória cognitiva, Dock/Atalhos Mac e voz.",
        version="0.2.0",
        lifespan=lifespan,
    )
    fastapi_app.state.settings = resolved_settings
    fastapi_app.state.memory = resolved_memory
    fastapi_app.state.shortcuts = resolved_shortcuts
    fastapi_app.state.mac = resolved_mac
    fastapi_app.state.llm = resolved_llm
    fastapi_app.state.stt = resolved_stt
    fastapi_app.state.tts = resolved_tts
    fastapi_app.state.cowork = resolved_cowork
    fastapi_app.state.today = resolved_today
    fastapi_app.state.first_wake = resolved_first_wake
    fastapi_app.state.access_token = runtime_access_token

    @fastapi_app.middleware("http")
    async def lan_access_auth_middleware(request: Request, call_next: Any) -> Response:
        """Exige DESK_ACCESS_TOKEN em rotas /api/* para clientes não-loopback."""
        if runtime_access_token and request.url.path.startswith("/api/"):
            client_host = request.client.host if request.client else None
            if not _is_loopback_host(client_host):
                provided = _extract_access_token(
                    request.headers,
                    query_token=request.query_params.get("token"),
                )
                if not provided or not hmac.compare_digest(provided, runtime_access_token):
                    return JSONResponse(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        content={"detail": "Token de acesso inválido ou ausente."},
                    )
        return await call_next(request)

    static_dir = BASE_DIR / "static"
    if static_dir.exists():
        fastapi_app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @fastapi_app.get("/")
    async def index() -> FileResponse:
        """Serve a interface web principal."""
        index_path = static_dir / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=404, detail="Interface não encontrada.")
        return FileResponse(index_path)

    @fastapi_app.get("/manifest.json")
    async def manifest() -> FileResponse:
        """Serve o manifesto PWA para instalação no Android e iPhone."""
        manifest_path = static_dir / "manifest.json"
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail="Manifesto PWA não encontrado.")
        return FileResponse(manifest_path, media_type="application/manifest+json")

    @fastapi_app.get("/health")
    async def health() -> dict[str, str]:
        """Endpoint simples de verificação de saúde do serviço."""
        return {"status": "ok", "model": resolved_settings.llm_model}

    # ------------------------------------------------------------------
    # Memória Cognitiva & Estado Emocional do Pet
    # ------------------------------------------------------------------

    @fastapi_app.get("/api/memory")
    async def get_memory() -> dict[str, Any]:
        """Retorna os fatos persistidos e a quantidade de mensagens recentes."""
        return {
            "facts": resolved_memory.get_facts(),
            "recent_messages_count": resolved_memory.get_recent_messages_count(),
        }

    @fastapi_app.get("/api/memory/state")
    async def get_memory_state() -> dict[str, Any]:
        """Retorna estado emocional do pet, contexto temporal e resumo contínuo."""
        companion = resolved_memory.get_companion_state()
        return {
            "companion": companion,
            **companion,
            "temporal": resolved_memory.get_temporal_context(),
            "rolling_summary": resolved_memory.get_rolling_summary(),
            "facts_count": len(resolved_memory.get_facts()),
            "recent_messages_count": resolved_memory.get_recent_messages_count(),
        }

    @fastapi_app.post("/api/memory/facts", status_code=status.HTTP_201_CREATED)
    async def create_fact(payload: FactCreateRequest) -> dict[str, Any]:
        """Adiciona ou atualiza um fato de longo prazo sobre o usuário."""
        fact_text = payload.fact.strip()
        if not fact_text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="O campo 'fact' não pode ser vazio.",
            )
        category = payload.category.strip() or "general"
        return resolved_memory.add_fact(
            fact_text,
            category=category,
            pinned=payload.pinned,
            importance=payload.importance,
        )

    @fastapi_app.patch("/api/memory/facts/{fact_id}")
    async def patch_fact(fact_id: int, payload: FactPatchRequest) -> dict[str, Any]:
        """Atualiza fixação (`pinned`) ou importância (`1..10`) de um fato existente."""
        if payload.pinned is None and payload.importance is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Informe 'pinned' ou 'importance' para atualizar o fato.",
            )

        updated: dict[str, Any] | None = None
        if payload.pinned is not None:
            updated = resolved_memory.set_fact_pinned(fact_id, payload.pinned)
            if updated is None:
                raise HTTPException(status_code=404, detail="Fato não encontrado.")
        if payload.importance is not None:
            updated = resolved_memory.update_fact_importance(fact_id, payload.importance)
            if updated is None:
                raise HTTPException(status_code=404, detail="Fato não encontrado.")
        assert updated is not None
        return updated

    @fastapi_app.delete("/api/memory/facts/{fact_id}")
    async def delete_fact(fact_id: int) -> dict[str, Any]:
        """Remove um fato de longo prazo pelo identificador."""
        deleted = resolved_memory.delete_fact(fact_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fato não encontrado.",
            )
        return {"deleted": True, "id": fact_id}

    @fastapi_app.post("/api/memory/consolidate")
    async def consolidate_memory() -> dict[str, Any]:
        """Executa consolidação de fatos duplicados/contraditórios."""
        consolidated = resolved_memory.consolidate_facts()
        return {
            "consolidated": consolidated,
            "facts": resolved_memory.get_facts(),
        }

    @fastapi_app.post("/api/memory/clear")
    async def clear_memory(
        payload: ClearMemoryRequest | None = Body(default=None),
    ) -> dict[str, Any]:
        """Limpa a conversa recente e, opcionalmente, também todos os fatos aprendidos."""
        if payload is not None and payload.include_facts:
            resolved_memory.clear_all()
        else:
            resolved_memory.clear_short_term()
        return {
            "facts": resolved_memory.get_facts(),
            "recent_messages_count": resolved_memory.get_recent_messages_count(),
        }

    # ------------------------------------------------------------------
    # Stream Deck & Atalhos Configuráveis
    # ------------------------------------------------------------------

    @fastapi_app.get("/api/shortcuts")
    async def list_shortcuts(category: str | None = Query(default=None)) -> dict[str, Any]:
        """Lista os atalhos cadastrados no SQLite (opcionalmente filtrados por categoria)."""
        return {"shortcuts": resolved_shortcuts.list_shortcuts(category=category)}

    @fastapi_app.post("/api/shortcuts", status_code=status.HTTP_201_CREATED)
    async def create_shortcut(payload: ShortcutPayloadRequest) -> dict[str, Any]:
        """Cria um novo atalho configurável no Stream Deck."""
        data = payload.model_dump(exclude_none=True)
        try:
            return resolved_shortcuts.create_shortcut(data)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @fastapi_app.post("/api/shortcuts/reorder")
    async def reorder_shortcuts(payload: ShortcutReorderRequest) -> dict[str, Any]:
        """Reordena os atalhos do Stream Deck conforme lista de IDs/slugs."""
        order = payload.ordered_ids or payload.ids
        return {"shortcuts": resolved_shortcuts.reorder_shortcuts(order)}

    @fastapi_app.post("/api/shortcuts/reset-defaults")
    async def reset_default_shortcuts() -> dict[str, Any]:
        """Restaura o catálogo padrão completo de atalhos do Mac."""
        return {"shortcuts": resolved_shortcuts.reset_defaults()}

    @fastapi_app.put("/api/shortcuts/{shortcut_id}")
    async def update_shortcut(
        shortcut_id: str,
        payload: ShortcutPayloadRequest,
    ) -> dict[str, Any]:
        """Atualiza um atalho existente identificado por `id` ou `slug`."""
        data = payload.model_dump(exclude_unset=True)
        try:
            updated = resolved_shortcuts.update_shortcut(shortcut_id, data)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Atalho não encontrado.")
        return updated

    @fastapi_app.delete("/api/shortcuts/{shortcut_id}")
    async def delete_shortcut(shortcut_id: str) -> dict[str, Any]:
        """Remove um atalho pelo `id` ou `slug`."""
        deleted = resolved_shortcuts.delete_shortcut(shortcut_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Atalho não encontrado.")
        return {"deleted": True, "id": shortcut_id}

    @fastapi_app.post("/api/shortcuts/{shortcut_id}/run")
    async def run_shortcut(shortcut_id: str) -> dict[str, Any]:
        """Executa imediatamente um atalho cadastrado no macOS."""
        shortcut = resolved_shortcuts.get_shortcut(shortcut_id)
        if shortcut is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Atalho não encontrado.")
        if shortcut.get("requires_confirmation"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "approval_required",
                    "message": "Este atalho exige confirmação. Execute-o pelo WebSocket para aprová-lo.",
                },
            )
        result = await asyncio.to_thread(resolved_mac.run_shortcut, shortcut)
        return {"shortcut": shortcut, "result": result, **result}

    # ------------------------------------------------------------------
    # Dock Viva do macOS, Status & Clima
    # ------------------------------------------------------------------

    @fastapi_app.get("/api/mac/apps")
    async def get_mac_apps() -> dict[str, Any]:
        """Lista aplicativos abertos no Mac (com foco atual) e favoritos."""
        apps = await asyncio.to_thread(resolved_mac.list_running_apps)
        return {"apps": apps}

    @fastapi_app.post("/api/mac/apps/activate")
    async def activate_mac_app(payload: AppActivateRequest) -> JSONResponse:
        """Valida o nome e traz o aplicativo do macOS para o primeiro plano."""
        target = (payload.app or payload.name).strip()
        if not target or resolved_mac.validate_app_name(target) is None:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "ok": False,
                    "app": target,
                    "error": "Nome de aplicativo inválido ou não permitido.",
                    "detail": "Nome de aplicativo inválido ou não permitido.",
                },
            )
        result = await asyncio.to_thread(resolved_mac.activate_app, target)
        return JSONResponse(status_code=status.HTTP_200_OK, content=result)

    @fastapi_app.get("/api/mac/status")
    async def get_mac_status() -> dict[str, Any]:
        """Retorna telemetria leve do Mac (app ativo, bateria, volume e mídia)."""
        return await asyncio.to_thread(resolved_mac.get_mac_status)

    @fastapi_app.get("/api/weather")
    async def get_weather(
        lat: float | None = Query(default=None),
        lon: float | None = Query(default=None),
        city: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Retorna clima atual via Open-Meteo (com cache e fallback offline)."""
        resolved_lat = resolved_settings.weather_latitude if lat is None else lat
        resolved_lon = resolved_settings.weather_longitude if lon is None else lon
        resolved_city = (city or resolved_settings.weather_city).strip() or resolved_settings.weather_city
        return await asyncio.to_thread(
            resolved_mac.get_weather,
            resolved_lat,
            resolved_lon,
            resolved_city,
        )

    # ------------------------------------------------------------------
    # Voz (TTS Servidor Mac + STT Local) & Diagnóstico
    # ------------------------------------------------------------------

    @fastapi_app.post("/api/tts")
    async def synthesize_tts(payload: TTSRequest) -> Response:
        """Gera áudio offline via `/usr/bin/say` + `/usr/bin/afconvert` (m4a ou wav)."""
        fmt = (payload.format or payload.output_format or "m4a").strip().lower()
        try:
            audio_bytes, media_type = await resolved_tts.synthesize_async(
                text=payload.text,
                voice=payload.voice,
                output_format=fmt,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc
        return Response(content=audio_bytes, media_type=media_type)

    @fastapi_app.get("/api/tts/voices")
    async def list_tts_voices() -> dict[str, Any]:
        """Lista as vozes offline disponíveis no servidor macOS."""
        raw_voices = await asyncio.to_thread(resolved_tts.list_voices)
        voices = [
            {
                **item,
                "lang": item.get("lang") or item.get("locale", ""),
            }
            for item in raw_voices
        ]
        return {
            "voices": voices,
            "default_voice": resolved_settings.tts_voice,
        }

    @fastapi_app.post("/api/stt")
    async def transcribe_stt(request: Request) -> dict[str, Any]:
        """Transcreve áudio recebido via JSON base64, multipart ou binário direto."""
        audio_bytes, mime_type, language = await _extract_stt_request(
            request,
            default_language=resolved_settings.stt_language,
        )
        return await resolved_stt.transcribe_bytes(
            audio_bytes=audio_bytes,
            mime_type=mime_type,
            language=language,
        )

    @fastapi_app.get("/api/diagnostics")
    async def get_diagnostics() -> dict[str, Any]:
        """Retorna estado operacional do servidor, STT, TTS e HTTPS sem expor segredos."""
        stt_status = resolved_stt.status()
        tts_available = resolved_tts.is_available()
        provider_state = build_active_provider_state(
            resolved_settings,
            provider_id=active_provider_state.get("provider_id"),
            env_fallback_key=env_llm_api_key,
        )
        return {
            "status": "ok",
            "model": resolved_settings.llm_model,
            "llm_model": resolved_settings.llm_model,
            "llm_base_url": resolved_settings.llm_base_url,
            "llm_provider_id": provider_state["provider_id"],
            "llm_has_api_key": provider_state["has_api_key"],
            "https_port": resolved_settings.https_port,
            "certs_ready": (
                resolved_settings.cert_file.exists() and resolved_settings.key_file.exists()
            ),
            "stt": stt_status,
            "stt_available": stt_status["available"],
            "stt_engine": stt_status["engine"],
            "tts": {
                "available": tts_available,
                "default_voice": resolved_settings.tts_voice,
            },
            "tts_available": tts_available,
        }

    @fastapi_app.get("/api/llm/providers")
    async def get_llm_providers() -> dict[str, Any]:
        """Lista os provedores compatíveis com OpenAI e retorna o provedor/modelo ativo (sem segredos)."""
        active = build_active_provider_state(
            resolved_settings,
            provider_id=active_provider_state.get("provider_id"),
            env_fallback_key=env_llm_api_key,
        )
        return {
            "active": active,
            "presets": list_provider_presets(env_fallback_key=env_llm_api_key),
        }

    @fastapi_app.get("/api/llm/models")
    async def get_llm_models(
        provider_id: str | None = Query(default=None),
        base_url: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Consulta os modelos disponíveis no endpoint `/models` do provedor selecionado."""
        target_id = (provider_id or active_provider_state.get("provider_id") or "custom").strip().lower()
        preset = get_preset(target_id)
        requested_url = (base_url or "").strip().rstrip("/")
        default_url = (
            preset.default_base_url if preset and preset.default_base_url else resolved_settings.llm_base_url
        ).rstrip("/")

        if requested_url and requested_url != default_url and target_id not in _BASE_URL_OVERRIDE_PROVIDERS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Override de base_url não permitido para este provedor.",
            )

        target_url = requested_url or default_url
        api_key, _ = resolve_provider_api_key(target_id, fallback_key=env_llm_api_key)
        # Nunca envia chave de ambiente para um base_url arbitrário diferente do configurado.
        if requested_url and requested_url != resolved_settings.llm_base_url.rstrip("/") and target_id == "custom":
            api_key = ""
        suggested = preset.suggested_models if preset is not None else ()
        try:
            return await fetch_provider_models(
                base_url=target_url,
                api_key=api_key,
                suggested_models=suggested,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    @fastapi_app.put("/api/llm/provider")
    async def update_llm_provider(body: LLMProviderUpdateRequest) -> dict[str, Any]:
        """Atualiza em tempo real e persiste em SQLite o provedor e modelo LLM ativos."""
        try:
            updated = save_provider_config(
                memory=resolved_memory,
                settings=resolved_settings,
                provider_id=body.provider_id,
                base_url=body.base_url,
                model=body.model,
                env_fallback_key=env_llm_api_key,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        active_provider_state.clear()
        active_provider_state.update(updated)
        return {"ok": True, "active": updated}

    @fastapi_app.get("/api/skills")
    async def get_pet_skills() -> dict[str, Any]:
        """Lista os pacotes de skills configuráveis e truques interativos do pet."""
        return list_skills_payload(enabled_skill_ids)

    @fastapi_app.put("/api/skills/{skill_id}")
    async def toggle_pet_skill(skill_id: str, body: SkillToggleRequest) -> dict[str, Any]:
        """Ativa ou desativa uma skill e persiste no SQLite (`app_meta`)."""
        try:
            updated_ids = set_skill_enabled(resolved_memory, skill_id, body.enabled)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        enabled_skill_ids.clear()
        enabled_skill_ids.extend(updated_ids)
        return {"ok": True, **list_skills_payload(enabled_skill_ids)}

    @fastapi_app.post("/api/skills/tricks/{trick_id}")
    async def trigger_pet_trick(trick_id: str) -> dict[str, Any]:
        """Valida e registra a execução de um truque interativo do pet."""
        trick = get_trick(trick_id)
        if trick is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Truque '{trick_id}' não encontrado.",
            )
        companion = resolved_memory.record_interaction(sentiment_delta=0.05)
        return {
            "ok": True,
            "trick": {
                "id": trick.id,
                "icon": trick.icon,
                "name": trick.name,
                "emotion": trick.emotion,
                "duration_ms": trick.duration_ms,
            },
            "companion": companion,
        }

    # ------------------------------------------------------------------
    # Cowork (somente leitura: State, Today, Sync) & First Wake
    # ------------------------------------------------------------------

    @fastapi_app.get("/api/cowork/state")
    async def get_cowork_state() -> dict[str, Any]:
        """Retorna o estado atual de `Cowork/state/*.yaml` e o status de sincronização."""
        state = await asyncio.to_thread(resolved_cowork.load_state)
        state["cowork_available"] = bool(state.get("workspace_exists", False))
        return state

    @fastapi_app.get("/api/cowork/today")
    async def get_cowork_today() -> dict[str, Any]:
        """Gera o resumo Today validado contra alucinações via roteador unificado."""
        return await resolved_today.generate_today()

    @fastapi_app.get("/api/cowork/sync")
    async def get_cowork_sync() -> dict[str, Any]:
        """Retorna status Git + saúde do estado Cowork para o LED da barra de menus."""
        state = await asyncio.to_thread(resolved_cowork.load_state)
        git_info = await asyncio.to_thread(get_git_sync_status, resolved_settings.cowork_workspace_path)
        combined = "red"
        if state.get("sync_status") == "green" and git_info.get("sync_status") == "green":
            combined = "green"
        elif state.get("sync_status") != "red" and git_info.get("sync_status") != "red":
            combined = "yellow"
        return {
            "cowork_available": bool(state.get("workspace_exists", False)),
            "sync_status": combined,
            "state_status": state.get("sync_status"),
            "state_message": state.get("sync_message"),
            "git": git_info,
        }

    @fastapi_app.get("/api/first-wake")
    async def check_first_wake(mark: bool = Query(default=True)) -> dict[str, Any]:
        """Verifica se é a primeira interação do dia e retorna o card silencioso do Today."""
        should_brief = resolved_first_wake.should_trigger_today()
        if not should_brief:
            return {"should_brief": False}
        today_res = await resolved_today.generate_today()
        if mark:
            resolved_first_wake.mark_triggered()
        return {
            "should_brief": True,
            "today": today_res,
        }

    # ------------------------------------------------------------------
    # WebSocket Bidirecional (Streaming LLM, Barge-in, Ações, Voz e Pet)
    # ------------------------------------------------------------------

    # Active Body (ADR 0001): Lupin vive em um Body por vez. ESP32 vence o RG406H,
    # que vence os outros (navegador do Mac, iPhone); no mesmo tipo, o último hello vence.
    bodies: list[dict[str, Any]] = []
    body_seq = [0]

    def current_active_body() -> dict[str, Any] | None:
        if not bodies:
            return None
        return max(bodies, key=lambda b: (_BODY_RANK.get(b["body"], 1), b["seq"]))

    async def announce_active_body(previous: dict[str, Any] | None, skip: dict[str, Any] | None) -> None:
        """Avisa os Bodies (menos `skip`) quando o Active Body muda."""
        active = current_active_body()
        if active is previous or active is None:
            return
        for entry in list(bodies):
            if entry is skip:
                continue
            try:
                await entry["send"](
                    {"type": "active_body", "active_body": active["body"], "active": entry is active}
                )
            except Exception:
                logger.info("Body %s não recebeu o aviso de Active Body.", entry["body"])

    @fastapi_app.websocket("/ws")
    async def websocket_chat(websocket: WebSocket) -> None:
        """Canal WebSocket concorrente com streaming frase-a-frase, barge-in e ações."""
        if runtime_access_token:
            client_host = websocket.client.host if websocket.client else None
            if not _is_loopback_host(client_host):
                provided = _extract_access_token(
                    websocket.headers,
                    query_token=websocket.query_params.get("token"),
                )
                if not provided or not hmac.compare_digest(provided, runtime_access_token):
                    await websocket.close(code=4401)
                    return
        await websocket.accept()
        send_lock = asyncio.Lock()
        active_turn_task: asyncio.Task[None] | None = None
        pending_approvals: dict[str, dict[str, Any]] = {}
        # Protocolo Brain<->Body v1: o Body declara em `hello` se quer áudio do servidor.
        body_info: dict[str, Any] = {"body": None, "wants_audio": False, "entry": None}

        def is_active_body() -> bool:
            return body_info["entry"] is not None and current_active_body() is body_info["entry"]

        async def safe_send(payload: dict[str, Any]) -> None:
            async with send_lock:
                await websocket.send_json(payload)

        async def request_shortcut_approval(shortcut: dict[str, Any]) -> None:
            approval_id = uuid.uuid4().hex[:10]
            pending_approvals[approval_id] = {
                "kind": "shortcut",
                "shortcut": shortcut,
            }
            await safe_send(
                {
                    "type": "tool_approval_request",
                    "approval_id": approval_id,
                    "kind": "shortcut",
                    "target": shortcut["slug"],
                    "title": shortcut["title"],
                    "message": f"Autorizar execução de '{shortcut['title']}'?",
                }
            )

        async def execute_action_item(kind: str, target: str) -> None:
            if kind == "shortcut":
                shortcut = resolved_shortcuts.get_shortcut(target)
                if shortcut is None:
                    shortcut = resolved_shortcuts.find_by_trigger(target)
                if shortcut is None:
                    await safe_send(
                        {
                            "type": "action_executed",
                            "kind": "shortcut",
                            "target": target,
                            "ok": False,
                            "error": f"Atalho '{target}' não encontrado.",
                        }
                    )
                    return

                if shortcut.get("requires_confirmation"):
                    await request_shortcut_approval(shortcut)
                    return

                res = await asyncio.to_thread(resolved_mac.run_shortcut, shortcut)
                await safe_send(
                    {
                        "type": "action_executed",
                        "kind": "shortcut",
                        "target": shortcut["slug"],
                        "title": shortcut["title"],
                        "ok": bool(res.get("ok")),
                        "result": res,
                        "error": res.get("error"),
                    }
                )
                return

            if kind == "app":
                approval_id = uuid.uuid4().hex[:10]
                pending_approvals[approval_id] = {
                    "kind": "mac_app",
                    "app": target,
                }
                await safe_send(
                    {
                        "type": "tool_approval_request",
                        "approval_id": approval_id,
                        "kind": "mac_app",
                        "risk": "write",
                        "target": target,
                        "title": f"Abrir aplicativo {target}",
                        "message": f"Permitir que o assistente abra '{target}' no Mac?",
                    }
                )
                return

            if kind == "pomodoro":
                cmd = (
                    "pomodoro_stop"
                    if target.strip().lower() in {"stop", "parar", "cancel", "off"}
                    else "pomodoro_start"
                )
                res = await asyncio.to_thread(resolved_mac.execute_mac_command, cmd)
                await safe_send(
                    {
                        "type": "action_executed",
                        "kind": "pomodoro",
                        "target": target,
                        "command": cmd,
                        "ok": bool(res.get("ok")),
                        "result": res,
                        "error": res.get("error"),
                    }
                )
                return

            if kind == "today":
                today_res = await resolved_today.generate_today()
                await safe_send(
                    {
                        "type": "action_executed",
                        "kind": "today",
                        "target": "brief",
                        "title": "Resumo Today",
                        "ok": bool(today_res.get("ok")),
                        "result": today_res,
                    }
                )
                return

            if kind == "pet":
                trick = get_trick(target)
                if trick is None:
                    await safe_send(
                        {
                            "type": "action_executed",
                            "kind": "pet",
                            "target": target,
                            "ok": False,
                            "error": f"Truque '{target}' não encontrado.",
                        }
                    )
                    return
                resolved_memory.record_interaction(sentiment_delta=0.04)
                await safe_send(
                    {
                        "type": "action_executed",
                        "kind": "pet",
                        "target": trick.id,
                        "title": trick.name,
                        "ok": True,
                        "trick": {
                            "id": trick.id,
                            "icon": trick.icon,
                            "name": trick.name,
                            "emotion": trick.emotion,
                            "duration_ms": trick.duration_ms,
                        },
                    }
                )

        async def audio_worker(queue: asyncio.Queue[str | None]) -> None:
            """Sintetiza cada frase da fila e envia `audio` em chunks. Falha de TTS só pula o áudio."""
            index = 0
            while True:
                sentence_text = await queue.get()
                if sentence_text is None:
                    return
                sentence_index = index
                index += 1
                try:
                    audio_bytes, _mime = await resolved_tts.synthesize_async(
                        text=sentence_text, voice=None, output_format="m4a"
                    )
                except Exception as exc:
                    logger.warning("TTS falhou para frase de áudio (%s); áudio pulado.", type(exc).__name__)
                    continue
                total = max(1, -(-len(audio_bytes) // _AUDIO_CHUNK_BYTES))
                for seq in range(total):
                    chunk = audio_bytes[seq * _AUDIO_CHUNK_BYTES : (seq + 1) * _AUDIO_CHUNK_BYTES]
                    await safe_send(
                        {
                            "type": "audio",
                            "sentence": sentence_index,
                            "seq": seq,
                            "last": seq == total - 1,
                            "mime": "audio/mp4",
                            "data": base64.b64encode(chunk).decode("ascii"),
                        }
                    )

        async def run_llm_turn(user_text: str) -> None:
            clean_text = ""
            raw_text = ""
            emotion = "neutral"
            audio_queue: asyncio.Queue[str | None] | None = None
            audio_task: asyncio.Task[None] | None = None
            if body_info["wants_audio"] and is_active_body() and resolved_tts.is_available():
                audio_queue = asyncio.Queue()
                audio_task = asyncio.create_task(audio_worker(audio_queue))

            try:
                await safe_send({"type": "state", "state": "thinking"})

                history = resolved_memory.get_recent_messages()
                memory_context = resolved_memory.build_memory_context(query=user_text)
                temporal_context = resolved_memory.get_temporal_context()
                companion_context = resolved_memory.get_companion_prompt_line()
                running_apps = await asyncio.to_thread(resolved_mac.list_running_apps)
                shortcuts_context = resolved_shortcuts.build_agent_shortcuts_prompt(
                    running_apps=running_apps
                )
                cowork_context = await asyncio.to_thread(resolved_cowork.build_prompt_context)
                skills_context = build_skills_prompt(enabled_skill_ids)

                resolved_memory.add_message("user", user_text)

                async for event in resolved_llm.stream_chat(
                    user_text=user_text,
                    history=history,
                    memory_context=memory_context,
                    shortcuts_context=shortcuts_context,
                    companion_context=companion_context,
                    temporal_context=temporal_context,
                    cowork_context=cowork_context,
                    skills_context=skills_context,
                ):
                    event_type = event.get("type")
                    if event_type == "emotion":
                        emotion = str(event.get("emotion") or "neutral")
                        await safe_send({"type": "emotion", "emotion": emotion})
                    elif event_type == "delta":
                        delta_text = str(event.get("text") or "")
                        if delta_text:
                            await safe_send({"type": "delta", "text": delta_text})
                    elif event_type == "sentence":
                        sentence_text = str(event.get("text") or "")
                        if sentence_text:
                            await safe_send({"type": "sentence", "text": sentence_text})
                            if audio_queue is not None:
                                audio_queue.put_nowait(sentence_text)
                    elif event_type == "action":
                        kind = str(event.get("kind") or "")
                        target = str(event.get("target") or "")
                        if kind and target:
                            await execute_action_item(kind, target)
                    elif event_type == "result":
                        clean_text = str(event.get("text") or "")
                        raw_text = str(event.get("raw_text") or "")
                        emotion = str(event.get("emotion") or emotion)

                resolved_memory.add_message("assistant", clean_text, emotion=emotion)
                new_facts = resolved_memory.extract_and_store_facts(user_text, raw_text)
                companion_state = resolved_memory.record_interaction()

                await safe_send(
                    {
                        "type": "done",
                        "text": clean_text,
                        "emotion": emotion,
                        "facts": new_facts,
                        "companion": companion_state,
                    }
                )
                await safe_send(
                    {
                        "type": "memory_updated",
                        "facts": resolved_memory.get_facts(),
                        "recent_messages_count": resolved_memory.get_recent_messages_count(),
                        "companion": companion_state,
                    }
                )
                if audio_queue is not None and audio_task is not None:
                    audio_queue.put_nowait(None)
                    await audio_task
            except asyncio.CancelledError:
                logger.info("Turno LLM interrompido por barge-in.")
                raise
            except WebSocketDisconnect:
                raise
            except LLMError as exc:
                logger.error("Falha ao processar mensagem via LLM: %s", exc)
                await safe_send({"type": "state", "state": "error"})
                await safe_send({"type": "error", "message": _FRIENDLY_LLM_ERROR})
            except Exception as exc:
                logger.error(
                    "Erro inesperado durante o streaming WebSocket (%s)",
                    type(exc).__name__,
                )
                await safe_send({"type": "state", "state": "error"})
                await safe_send({"type": "error", "message": _FRIENDLY_LLM_ERROR})
            finally:
                if audio_task is not None and not audio_task.done():
                    audio_task.cancel()
                    try:
                        await audio_task
                    except BaseException:
                        pass

        async def run_audio_turn(audio_bytes: bytes, mime_type: str, language: str) -> None:
            try:
                await safe_send({"type": "state", "state": "thinking"})
                stt_res = await resolved_stt.transcribe_bytes(
                    audio_bytes=audio_bytes,
                    mime_type=mime_type,
                    language=language,
                )
                if asyncio.current_task() is not active_turn_task:
                    return
                transcript = str(stt_res.get("text") or "").strip()
                if not transcript:
                    err_msg = stt_res.get("error") or "Não foi possível entender o áudio."
                    await safe_send({"type": "error", "message": str(err_msg)})
                    await safe_send({"type": "state", "state": "idle"})
                    return

                await safe_send(
                    {
                        "type": "transcript",
                        "text": transcript,
                        "engine": stt_res.get("engine"),
                    }
                )
                await run_llm_turn(transcript)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Erro inesperado durante a transcrição WebSocket (%s)", type(exc).__name__)
                if asyncio.current_task() is active_turn_task:
                    await safe_send({"type": "state", "state": "error"})
                    await safe_send({"type": "error", "message": "Falha ao transcrever áudio recebido."})

        async def cancel_active_turn(notify: bool) -> None:
            nonlocal active_turn_task
            if active_turn_task is not None and not active_turn_task.done():
                active_turn_task.cancel()
                try:
                    await active_turn_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
            active_turn_task = None
            if notify:
                await safe_send({"type": "interrupted"})
                await safe_send({"type": "state", "state": "idle"})

        def start_llm_turn(user_text: str) -> None:
            nonlocal active_turn_task
            active_turn_task = asyncio.create_task(run_llm_turn(user_text))

        def start_audio_turn(audio_bytes: bytes, mime_type: str, language: str) -> None:
            nonlocal active_turn_task
            active_turn_task = asyncio.create_task(run_audio_turn(audio_bytes, mime_type, language))

        try:
            while True:
                raw_message = await websocket.receive_text()
                try:
                    data = json.loads(raw_message)
                except json.JSONDecodeError:
                    await safe_send({"type": "error", "message": "Formato de mensagem inválido."})
                    continue

                if not isinstance(data, dict):
                    await safe_send(
                        {"type": "error", "message": "Payload WebSocket deve ser um objeto JSON."}
                    )
                    continue

                msg_type = data.get("type")

                if msg_type == "hello":
                    audio_formats = data.get("audio")
                    body_info["body"] = str(data.get("body") or "unknown")
                    body_info["wants_audio"] = isinstance(audio_formats, list) and len(audio_formats) > 0
                    previous = current_active_body()
                    if body_info["entry"] is not None:
                        bodies.remove(body_info["entry"])
                    body_seq[0] += 1
                    body_info["entry"] = {"body": body_info["body"], "seq": body_seq[0], "send": safe_send}
                    bodies.append(body_info["entry"])
                    active = current_active_body()
                    await safe_send(
                        {
                            "type": "welcome",
                            "protocol": PROTOCOL_VERSION,
                            "active_body": active["body"] if active else body_info["body"],
                            "active": active is body_info["entry"],
                        }
                    )
                    await announce_active_body(previous, skip=body_info["entry"])
                    continue

                if msg_type == "typing":
                    active = bool(data.get("active", False))
                    await safe_send({"type": "state", "state": "listening" if active else "idle"})
                    continue

                if msg_type == "interrupt":
                    await cancel_active_turn(notify=True)
                    continue

                if msg_type == "clear_history":
                    await cancel_active_turn(notify=False)
                    resolved_memory.clear_short_term()
                    await safe_send(
                        {
                            "type": "memory_updated",
                            "facts": resolved_memory.get_facts(),
                            "recent_messages_count": resolved_memory.get_recent_messages_count(),
                            "companion": resolved_memory.get_companion_state(),
                        }
                    )
                    continue

                if msg_type == "touch":
                    kind = str(data.get("kind") or "pet").strip().lower()
                    if kind == "pet":
                        intensity = float(data.get("intensity") or 1.0)
                        companion = resolved_memory.record_pet(intensity=intensity)
                    else:
                        companion = resolved_memory.record_interaction(sentiment_delta=-0.02)
                    await safe_send(
                        {
                            "type": "mood",
                            "kind": kind,
                            "companion": companion,
                            **companion,
                        }
                    )
                    continue

                if msg_type == "run_shortcut":
                    identifier = data.get("id") if data.get("id") is not None else data.get("slug")
                    if identifier is None:
                        await safe_send({"type": "error", "message": "ID do atalho não informado."})
                        continue
                    shortcut = resolved_shortcuts.get_shortcut(identifier)
                    if shortcut is None:
                        await safe_send(
                            {
                                "type": "action_executed",
                                "kind": "shortcut",
                                "target": str(identifier),
                                "ok": False,
                                "error": "Atalho não encontrado.",
                            }
                        )
                        continue
                    if shortcut.get("requires_confirmation"):
                        await request_shortcut_approval(shortcut)
                        continue
                    if shortcut.get("action_type") == "agent_prompt":
                        prompt_text = str((shortcut.get("payload") or {}).get("prompt") or "").strip()
                        if prompt_text:
                            await cancel_active_turn(notify=False)
                            start_llm_turn(prompt_text)
                        continue
                    res = await asyncio.to_thread(resolved_mac.run_shortcut, shortcut)
                    await safe_send(
                        {
                            "type": "action_executed",
                            "kind": "shortcut",
                            "target": shortcut["slug"],
                            "title": shortcut["title"],
                            "ok": bool(res.get("ok")),
                            "result": res,
                            "error": res.get("error"),
                        }
                    )
                    continue

                if msg_type == "activate_app":
                    app_name = str(data.get("app") or "").strip()
                    res = await asyncio.to_thread(resolved_mac.activate_app, app_name)
                    await safe_send(
                        {
                            "type": "action_executed",
                            "kind": "app",
                            "target": app_name,
                            "title": app_name,
                            "ok": bool(res.get("ok")),
                            "result": res,
                            "error": res.get("error"),
                        }
                    )
                    continue

                if msg_type == "confirm_action":
                    approval_id = str(data.get("approval_id") or "").strip()
                    approved = bool(data.get("approved", False))
                    pending = pending_approvals.pop(approval_id, None)
                    if pending is None:
                        await safe_send(
                            {
                                "type": "error",
                                "message": "Solicitação de aprovação expirada ou desconhecida.",
                            }
                        )
                        continue
                    pending_kind = pending.get("kind", "shortcut")
                    if pending_kind == "mac_app":
                        app_name = str(pending.get("app") or "")
                        if not approved:
                            await safe_send(
                                {
                                    "type": "action_executed",
                                    "approval_id": approval_id,
                                    "kind": "app",
                                    "target": app_name,
                                    "title": app_name,
                                    "ok": False,
                                    "cancelled": True,
                                    "error": "Abertura de aplicativo recusada pelo usuário.",
                                }
                            )
                            continue
                        res = await asyncio.to_thread(resolved_mac.activate_app, app_name)
                        await safe_send(
                            {
                                "type": "action_executed",
                                "approval_id": approval_id,
                                "kind": "app",
                                "target": app_name,
                                "title": app_name,
                                "ok": bool(res.get("ok")),
                                "result": res,
                                "error": res.get("error"),
                            }
                        )
                        continue

                    shortcut = pending["shortcut"]
                    if not approved:
                        await safe_send(
                            {
                                "type": "action_executed",
                                "approval_id": approval_id,
                                "kind": "shortcut",
                                "target": shortcut["slug"],
                                "title": shortcut["title"],
                                "ok": False,
                                "cancelled": True,
                                "error": "Execução recusada pelo usuário.",
                            }
                        )
                        continue
                    if shortcut.get("action_type") == "agent_prompt":
                        prompt_text = str((shortcut.get("payload") or {}).get("prompt") or "").strip()
                        if not prompt_text:
                            await safe_send(
                                {
                                    "type": "action_executed",
                                    "approval_id": approval_id,
                                    "kind": "shortcut",
                                    "target": shortcut["slug"],
                                    "title": shortcut["title"],
                                    "ok": False,
                                    "error": "O prompt do atalho está vazio.",
                                }
                            )
                            continue
                        await cancel_active_turn(notify=False)
                        await safe_send(
                            {
                                "type": "action_executed",
                                "approval_id": approval_id,
                                "kind": "shortcut",
                                "target": shortcut["slug"],
                                "title": shortcut["title"],
                                "ok": True,
                            }
                        )
                        start_llm_turn(prompt_text)
                        continue
                    res = await asyncio.to_thread(resolved_mac.run_shortcut, shortcut)
                    await safe_send(
                        {
                            "type": "action_executed",
                            "approval_id": approval_id,
                            "kind": "shortcut",
                            "target": shortcut["slug"],
                            "title": shortcut["title"],
                            "ok": bool(res.get("ok")),
                            "result": res,
                            "error": res.get("error"),
                        }
                    )
                    continue

                if msg_type == "audio":
                    await cancel_active_turn(notify=False)
                    raw_b64 = str(data.get("data") or data.get("audio") or "")
                    mime_type = str(data.get("mime_type") or "audio/webm")
                    language = str(data.get("language") or resolved_settings.stt_language)
                    try:
                        audio_bytes = _decode_base64_audio(raw_b64)
                    except ValueError as exc:
                        await safe_send({"type": "error", "message": str(exc)})
                        await safe_send({"type": "state", "state": "idle"})
                        continue

                    start_audio_turn(audio_bytes, mime_type, language)
                    continue

                if msg_type == "text":
                    user_text = str(data.get("text") or "").strip()
                    if not user_text:
                        await safe_send(
                            {"type": "error", "message": "Digite uma mensagem para conversar."}
                        )
                        continue

                    await cancel_active_turn(notify=False)
                    start_llm_turn(user_text)
                    continue

                await safe_send({"type": "error", "message": "Tipo de evento não suportado."})
        except WebSocketDisconnect:
            logger.info("Cliente WebSocket desconectado.")
        finally:
            if body_info["entry"] is not None and body_info["entry"] in bodies:
                previous = current_active_body()
                bodies.remove(body_info["entry"])
                await announce_active_body(previous, skip=None)
            if active_turn_task is not None and not active_turn_task.done():
                active_turn_task.cancel()
                try:
                    await active_turn_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

    return fastapi_app


_cached_app: FastAPI | None = None


def __getattr__(name: str) -> Any:
    """Inicializa `app` sob demanda para evitar abertura de SQLite no import do módulo."""
    if name == "app":
        global _cached_app
        if _cached_app is None:
            _cached_app = create_app()
        return _cached_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
