"""Main FastAPI application: HTTP endpoints, Mac Dock/Shortcuts, STT/TTS and WebSocket."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import json
import logging
import socket
import time
import uuid
from contextlib import asynccontextmanager
from email.parser import BytesParser
from email.policy import default as email_default_policy
from typing import Any, Callable

from fastapi import Body, FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.device_routes import setup_devices
from app.panels.routes import register as register_panels
from app.productivity import register as register_productivity
from app.config import BASE_DIR, Settings, configure_logging, load_settings, resolve_runtime_access_token
from app.cowork import CoworkStore, get_git_sync_status
from app.llm import LLMClient, LLMError
from app.dictation import format_dictation
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
from app import speech
from app.stt import LocalSTT
from app.consent import DataConsent, build_personal_context
from app.kokoro_tts import LupinTTS
from app.local_mode import SlowModelNotice
from app.mcp_client import McpServerStore
from app.mcp_routes import register_mcp_routes
from app.mcp_server import register_mcp_server
from app.signals import ActiveBodySpeaker, SignalBus
from app.today import FirstWakeTracker, TodayEngine, compose_first_wake_speech
from app.tts import ServerTTS

logger = logging.getLogger(__name__)

_META_KEY_LUPIN_LANGUAGE = "lupin_language"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})
_BASE_URL_OVERRIDE_PROVIDERS = frozenset({"local_proxy", "ollama", "custom"})


def _is_loopback_host(host: str | None) -> bool:
    """Return True when the client connects from local loopback."""
    normalized = (host or "").strip().lower()
    return normalized in _LOOPBACK_HOSTS


def _discover_local_ips() -> frozenset[str]:
    """Discover the Mac's own IPs (Wi-Fi/Ethernet) without running anything external."""
    found: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            found.add(str(info[4][0]).split("%", 1)[0])
    except OSError:
        pass
    # UDP trick: connect sends no packet, it only asks which interface would be used.
    for family, target in ((socket.AF_INET, "10.255.255.255"), (socket.AF_INET6, "2001:db8::1")):
        try:
            with socket.socket(family, socket.SOCK_DGRAM) as sock:
                sock.connect((target, 1))
                found.add(str(sock.getsockname()[0]).split("%", 1)[0])
        except OSError:
            continue
    return frozenset(ip for ip in found if ip)


def _extract_access_token(headers: Any, query_token: str | None = None) -> str:
    """Extract the Bearer/X-Desk-Token token or the `token` query param."""
    auth_header = (headers.get("authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    desk_header = (headers.get("x-desk-token") or "").strip()
    if desk_header:
        return desk_header
    return (query_token or "").strip()


class FactCreateRequest(BaseModel):
    """Payload for manually creating a long-term memory fact."""

    fact: str = ""
    category: str = "general"
    pinned: bool | None = None
    importance: int | None = None


class LLMProviderUpdateRequest(BaseModel):
    """Payload for updating the active LLM provider and model."""

    provider_id: str
    base_url: str | None = None
    model: str


class DataConsentRequest(BaseModel):
    """Payload for changing the Data Consent (missing fields stay as they are)."""

    calendar: bool | None = None
    email: bool | None = None


class SkillToggleRequest(BaseModel):
    """Payload for enabling or disabling a pet skill."""

    enabled: bool


class FactPatchRequest(BaseModel):
    """Payload for updating a fact's pinning (`pinned`) or importance."""

    pinned: bool | None = None
    importance: int | None = None


class ClearMemoryRequest(BaseModel):
    """Optional payload for clearing memory."""

    include_facts: bool = False


class ShortcutPayloadRequest(BaseModel):
    """Flexible payload for creating and editing shortcuts."""

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
    """Payload for reordering the Stream Deck tiles."""

    ordered_ids: list[int | str] = Field(default_factory=list)
    ids: list[int | str] = Field(default_factory=list)


class AppActivateRequest(BaseModel):
    """Payload for activating/opening an application on macOS."""

    app: str = ""
    name: str = ""


# Brain<->Body protocol (docs/brain-body-protocol.md).
PROTOCOL_VERSION = 1
_AUDIO_CHUNK_BYTES = 24 * 1024


class LupinLanguageRequest(BaseModel):
    """Payload to change Lupin's language (pt-BR or en)."""

    language: str


class TTSRequest(BaseModel):
    """Payload for offline speech synthesis on the Mac server."""

    text: str = ""
    voice: str | None = None
    format: str | None = None
    output_format: str | None = None


def _decode_base64_audio(raw_data: str) -> bytes:
    """Decode a base64 string (with or without a data URL prefix) to bytes."""
    cleaned = (raw_data or "").strip()
    if not cleaned:
        return b""
    if cleaned.startswith("data:") and "," in cleaned:
        cleaned = cleaned.split(",", 1)[1].strip()
    try:
        return base64.b64decode(cleaned, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Invalid base64 audio.") from exc


def _parse_multipart_pure_python(content_type: str, body: bytes) -> tuple[bytes, str, str | None]:
    """Extract the audio file, MIME type and language from `multipart/form-data` without requiring python-multipart."""
    raw_msg = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("latin-1") + body
    msg = BytesParser(policy=email_default_policy).parsebytes(raw_msg)
    if not msg.is_multipart():
        raise ValueError("Invalid multipart body.")

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
    """Read audio bytes, mime_type and language from base64 JSON, multipart or raw binary."""
    content_type = (request.headers.get("content-type") or "").strip()
    lower_ct = content_type.lower()

    if "application/json" in lower_ct or not lower_ct:
        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload for STT.",
            ) from exc
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="STT payload must be a JSON object.",
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
    first_wake: FirstWakeTracker | None = None,
    calendar_reader: Callable[[], list[dict[str, Any]] | None] | None = None,
    inbox_reader: Callable[[], dict[str, Any] | None] | None = None,
    local_ips: Callable[[], frozenset[str]] | None = None,
) -> FastAPI:
    """Create and configure the FastAPI instance with memory, shortcuts, Mac, voice and WebSocket."""
    resolved_settings = settings or load_settings()
    env_llm_api_key = resolved_settings.llm_api_key
    configure_logging(secret=env_llm_api_key)
    runtime_access_token, token_generated = resolve_runtime_access_token(resolved_settings)
    if resolved_settings.desk_dev_no_token:
        logger.warning(
            "DESK_DEV_NO_TOKEN is on: any device on the network can reach /api and /ws without a token. "
            "Use it only in development."
        )
    if token_generated:
        logger.warning(
            "DESK_ACCESS_TOKEN is not set in .env; generated an ephemeral token for non-loopback clients: %s",
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
    # Lupin's language lives on the Brain (app_meta) so every Body sees the same value.
    speech.set_language(resolved_memory.get_meta(_META_KEY_LUPIN_LANGUAGE))

    own_shortcuts = shortcut_store is None
    resolved_shortcuts = shortcut_store or ShortcutStore(db_path=resolved_settings.db_path)

    resolved_llm = llm_client or LLMClient(resolved_settings)
    resolved_mac = mac_controller or MacController()
    resolved_stt = stt_engine or LocalSTT(
        model_name=resolved_settings.stt_model,
        language=resolved_settings.stt_language,
    )
    resolved_tts = tts_engine or LupinTTS(
        ServerTTS(default_voice=resolved_settings.tts_voice),
        enabled=resolved_settings.tts_kokoro,
    )
    resolved_cowork = cowork_store or CoworkStore(resolved_settings.cowork_workspace_path)
    resolved_today = today_engine or TodayEngine(resolved_settings, resolved_cowork)
    resolved_first_wake = first_wake or FirstWakeTracker(resolved_memory)

    def resolved_calendar_reader() -> list[dict[str, Any]] | None:
        if calendar_reader is not None:
            return calendar_reader()
        reader = getattr(resolved_mac, "read_today_calendar", None)
        return reader() if callable(reader) else None

    def resolved_inbox_reader() -> dict[str, Any] | None:
        if inbox_reader is not None:
            return inbox_reader()
        reader = getattr(resolved_mac, "read_inbox", None)
        return reader() if callable(reader) else None

    data_consent = DataConsent(
        resolved_memory,
        lambda: (
            str(active_provider_state.get("provider_id") or "custom"),
            resolved_settings.llm_base_url,
        ),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        productivity = getattr(_app.state, "productivity", None)
        if productivity is not None:
            productivity.start()
        try:
            yield
        finally:
            if productivity is not None:
                await productivity.stop()
            if own_shortcuts:
                resolved_shortcuts.close()
            if own_memory:
                resolved_memory.close()

    fastapi_app = FastAPI(
        title="Desk Assistant",
        description="EMO-style desk assistant with cognitive memory, Mac Dock/Shortcuts and voice.",
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

    local_ips_cache: dict[str, Any] = {"at": 0.0, "ips": frozenset()}

    def mac_ip_addresses() -> frozenset[str]:
        """The Mac's own IPs, cached for 60 s (Wi-Fi may change address)."""
        if local_ips is not None:
            return local_ips()
        now = time.monotonic()
        if not local_ips_cache["ips"] or now - local_ips_cache["at"] > 60:
            local_ips_cache["ips"] = _discover_local_ips()
            local_ips_cache["at"] = now
        return local_ips_cache["ips"]

    def is_mac_client(host: str | None) -> bool:
        """The Mac is the client when on loopback or connecting through its own network IP."""
        if _is_loopback_host(host):
            return True
        normalized = (host or "").strip().split("%", 1)[0]
        return bool(normalized) and normalized in mac_ip_addresses()

    def require_mac_client(
        request: Request, detail: str = "Shortcuts can only be configured on the Mac."
    ) -> None:
        """Shortcuts and Data Consent are only configured on the Mac, even with DESK_DEV_NO_TOKEN."""
        host = request.client.host if request.client else None
        if not is_mac_client(host):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)

    @fastapi_app.middleware("http")
    async def lan_access_auth_middleware(request: Request, call_next: Any) -> Response:
        """Require DESK_ACCESS_TOKEN on /api/* routes for non-loopback clients."""
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
                        content={"detail": "Invalid or missing access token."},
                    )
        return await call_next(request)

    static_dir = BASE_DIR / "static"
    if static_dir.exists():
        fastapi_app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @fastapi_app.get("/")
    async def index() -> FileResponse:
        """Serve the main web interface."""
        index_path = static_dir / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=404, detail="Interface not found.")
        return FileResponse(index_path)

    @fastapi_app.get("/manifest.json")
    async def manifest() -> FileResponse:
        """Serve the PWA manifest for installation on Android and iPhone."""
        manifest_path = static_dir / "manifest.json"
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail="PWA manifest not found.")
        return FileResponse(manifest_path, media_type="application/manifest+json")

    @fastapi_app.get("/health")
    async def health() -> dict[str, str]:
        """Simple service health-check endpoint."""
        return {"status": "ok", "model": resolved_settings.llm_model}

    # ------------------------------------------------------------------
    # Cognitive Memory & Pet Emotional State
    # ------------------------------------------------------------------

    @fastapi_app.get("/api/memory")
    async def get_memory() -> dict[str, Any]:
        """Return the persisted facts and the number of recent messages."""
        return {
            "facts": resolved_memory.get_facts(),
            "recent_messages_count": resolved_memory.get_recent_messages_count(),
        }

    @fastapi_app.get("/api/memory/state")
    async def get_memory_state() -> dict[str, Any]:
        """Return the pet's emotional state, temporal context and rolling summary."""
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
        """Add or update a long-term fact about the user."""
        fact_text = payload.fact.strip()
        if not fact_text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The 'fact' field cannot be empty.",
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
        """Update the pinning (`pinned`) or importance (`1..10`) of an existing fact."""
        if payload.pinned is None and payload.importance is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provide 'pinned' or 'importance' to update the fact.",
            )

        updated: dict[str, Any] | None = None
        if payload.pinned is not None:
            updated = resolved_memory.set_fact_pinned(fact_id, payload.pinned)
            if updated is None:
                raise HTTPException(status_code=404, detail="Fact not found.")
        if payload.importance is not None:
            updated = resolved_memory.update_fact_importance(fact_id, payload.importance)
            if updated is None:
                raise HTTPException(status_code=404, detail="Fact not found.")
        assert updated is not None
        return updated

    @fastapi_app.delete("/api/memory/facts/{fact_id}")
    async def delete_fact(fact_id: int) -> dict[str, Any]:
        """Delete a long-term fact by its identifier."""
        deleted = resolved_memory.delete_fact(fact_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fact not found.",
            )
        return {"deleted": True, "id": fact_id}

    @fastapi_app.post("/api/memory/consolidate")
    async def consolidate_memory() -> dict[str, Any]:
        """Run consolidation of duplicate/contradictory facts."""
        consolidated = resolved_memory.consolidate_facts()
        return {
            "consolidated": consolidated,
            "facts": resolved_memory.get_facts(),
        }

    @fastapi_app.post("/api/memory/clear")
    async def clear_memory(
        payload: ClearMemoryRequest | None = Body(default=None),
    ) -> dict[str, Any]:
        """Clear the recent conversation and, optionally, all learned facts too."""
        if payload is not None and payload.include_facts:
            resolved_memory.clear_all()
        else:
            resolved_memory.clear_short_term()
        return {
            "facts": resolved_memory.get_facts(),
            "recent_messages_count": resolved_memory.get_recent_messages_count(),
        }

    # ------------------------------------------------------------------
    # Stream Deck & Configurable Shortcuts
    # ------------------------------------------------------------------

    @fastapi_app.get("/api/shortcuts")
    async def list_shortcuts(category: str | None = Query(default=None)) -> dict[str, Any]:
        """List the shortcuts stored in SQLite (optionally filtered by category)."""
        return {"shortcuts": resolved_shortcuts.list_shortcuts(category=category)}

    @fastapi_app.get("/api/client-info")
    async def client_info(request: Request) -> dict[str, Any]:
        """Say whether the asker is the Mac itself (the only place that edits Shortcuts)."""
        host = request.client.host if request.client else None
        return {"is_mac": is_mac_client(host)}

    def data_consent_payload(request: Request) -> dict[str, Any]:
        host = request.client.host if request.client else None
        return {
            **data_consent.get(),
            "receiver": data_consent.receiver_name(),
            "local": data_consent.is_local(),
            "can_edit": is_mac_client(host),
        }

    @fastapi_app.get("/api/data-consent")
    async def get_data_consent(request: Request) -> dict[str, Any]:
        """Data Consent state (calendar and e-mail) and who receives it. Any client can read."""
        return data_consent_payload(request)

    @fastapi_app.put("/api/data-consent")
    async def put_data_consent(request: Request, body: DataConsentRequest) -> dict[str, Any]:
        """Turn calendar and/or e-mail consent on or off. Mac only."""
        require_mac_client(request, "Data Consent can only be changed on the Mac.")
        data_consent.update(calendar=body.calendar, email=body.email)
        return data_consent_payload(request)

    @fastapi_app.post("/api/shortcuts", status_code=status.HTTP_201_CREATED)
    async def create_shortcut(request: Request, payload: ShortcutPayloadRequest) -> dict[str, Any]:
        """Create a new shortcut (starts unpinned from the Dock). Mac only."""
        require_mac_client(request)
        data = payload.model_dump(exclude_none=True)
        try:
            return resolved_shortcuts.create_shortcut(data)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @fastapi_app.post("/api/shortcuts/reorder")
    async def reorder_shortcuts(request: Request, payload: ShortcutReorderRequest) -> dict[str, Any]:
        """Reorder the Dock shortcuts according to a list of IDs/slugs. Mac only."""
        require_mac_client(request)
        order = payload.ordered_ids or payload.ids
        return {"shortcuts": resolved_shortcuts.reorder_shortcuts(order)}

    @fastapi_app.post("/api/shortcuts/reset-defaults")
    async def reset_default_shortcuts(request: Request) -> dict[str, Any]:
        """Restore the full default catalog of Mac shortcuts. Mac only."""
        require_mac_client(request)
        return {"shortcuts": resolved_shortcuts.reset_defaults()}

    @fastapi_app.put("/api/shortcuts/{shortcut_id}")
    async def update_shortcut(
        request: Request,
        shortcut_id: str,
        payload: ShortcutPayloadRequest,
    ) -> dict[str, Any]:
        """Update (including pin/unpin) a shortcut by `id` or `slug`. Mac only."""
        require_mac_client(request)
        data = payload.model_dump(exclude_unset=True)
        try:
            updated = resolved_shortcuts.update_shortcut(shortcut_id, data)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shortcut not found.")
        return updated

    @fastapi_app.delete("/api/shortcuts/{shortcut_id}")
    async def delete_shortcut(request: Request, shortcut_id: str) -> dict[str, Any]:
        """Delete a shortcut by `id` or `slug`. Mac only."""
        require_mac_client(request)
        deleted = resolved_shortcuts.delete_shortcut(shortcut_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shortcut not found.")
        return {"deleted": True, "id": shortcut_id}

    @fastapi_app.post("/api/shortcuts/{shortcut_id}/run")
    async def run_shortcut(shortcut_id: str) -> dict[str, Any]:
        """Immediately run a shortcut stored on macOS."""
        shortcut = resolved_shortcuts.get_shortcut(shortcut_id)
        if shortcut is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shortcut not found.")
        if shortcut.get("requires_confirmation"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "approval_required",
                    "message": "This shortcut requires confirmation. Run it over the WebSocket to approve it.",
                },
            )
        result = await asyncio.to_thread(resolved_mac.run_shortcut, shortcut)
        return {"shortcut": shortcut, "result": result, **result}

    # ------------------------------------------------------------------
    # Live macOS Dock, Status & Weather
    # ------------------------------------------------------------------

    @fastapi_app.get("/api/mac/apps")
    async def get_mac_apps() -> dict[str, Any]:
        """List the apps open on the Mac (with current focus) and favorites."""
        apps = await asyncio.to_thread(resolved_mac.list_running_apps)
        return {"apps": apps}

    @fastapi_app.post("/api/mac/apps/activate")
    async def activate_mac_app(payload: AppActivateRequest) -> JSONResponse:
        """Validate the name and bring the macOS app to the foreground."""
        target = (payload.app or payload.name).strip()
        if not target or resolved_mac.validate_app_name(target) is None:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "ok": False,
                    "app": target,
                    "error": "Invalid or disallowed application name.",
                    "detail": "Invalid or disallowed application name.",
                },
            )
        result = await asyncio.to_thread(resolved_mac.activate_app, target)
        return JSONResponse(status_code=status.HTTP_200_OK, content=result)

    @fastapi_app.get("/api/mac/status")
    async def get_mac_status() -> dict[str, Any]:
        """Return light Mac telemetry (active app, battery, volume and media)."""
        return await asyncio.to_thread(resolved_mac.get_mac_status)

    @fastapi_app.get("/api/weather")
    async def get_weather(
        lat: float | None = Query(default=None),
        lon: float | None = Query(default=None),
        city: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Return the current weather via Open-Meteo (with cache and offline fallback)."""
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
    # Voice (Mac server TTS + local STT) & Diagnostics
    # ------------------------------------------------------------------

    def current_tts_voice() -> str:
        """The server voice that matches Lupin's current language."""
        if speech.get_language() == "en":
            return resolved_settings.tts_voice_en
        return resolved_settings.tts_voice

    def current_stt_language() -> str:
        """The speech-to-text language code that matches Lupin's current language."""
        if speech.get_language() == "en":
            return "en"
        return resolved_settings.stt_language

    def lupin_language_payload() -> dict[str, Any]:
        lang = speech.get_language()
        phrases = speech.for_language(lang)
        return {
            "language": lang,
            "languages": list(speech.SUPPORTED_LANGUAGES),
            "tts_voice": current_tts_voice(),
            "stt_language": current_stt_language(),
            "phrases": {
                "pomodoro_focus_done": phrases.POMODORO_FOCUS_DONE,
                "pomodoro_break_done": phrases.POMODORO_BREAK_DONE,
                "diag_test_browser_tts": phrases.DIAG_TEST_BROWSER_TTS,
                "diag_test_server_tts": phrases.DIAG_TEST_SERVER_TTS,
            },
        }

    @fastapi_app.get("/api/lupin-language")
    async def get_lupin_language() -> dict[str, Any]:
        """Lupin's language (pt-BR default or en) and what follows from it."""
        return lupin_language_payload()

    @fastapi_app.put("/api/lupin-language")
    async def put_lupin_language(body: LupinLanguageRequest) -> dict[str, Any]:
        """Change Lupin's language from any device; takes effect on the next turn."""
        lang = speech.normalize_language(body.language)
        if lang is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Unsupported language. Use 'pt-BR' or 'en'.",
            )
        resolved_memory.set_meta(_META_KEY_LUPIN_LANGUAGE, lang)
        speech.set_language(lang)
        return {"ok": True, **lupin_language_payload()}

    @fastapi_app.post("/api/tts")
    async def synthesize_tts(payload: TTSRequest) -> Response:
        """Generate offline audio via `/usr/bin/say` + `/usr/bin/afconvert` (m4a or wav)."""
        fmt = (payload.format or payload.output_format or "m4a").strip().lower()
        try:
            audio_bytes, media_type = await resolved_tts.synthesize_async(
                text=payload.text,
                voice=payload.voice or current_tts_voice(),
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
        """List the offline voices available on the macOS server."""
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
            "default_voice": current_tts_voice(),
        }

    @fastapi_app.post("/api/stt")
    async def transcribe_stt(request: Request) -> dict[str, Any]:
        """Transcribe audio received as base64 JSON, multipart or raw binary."""
        audio_bytes, mime_type, language = await _extract_stt_request(
            request,
            default_language=current_stt_language(),
        )
        return await resolved_stt.transcribe_bytes(
            audio_bytes=audio_bytes,
            mime_type=mime_type,
            language=language,
        )

    @fastapi_app.get("/api/diagnostics")
    async def get_diagnostics() -> dict[str, Any]:
        """Return the operational state of the server, STT, TTS and HTTPS without exposing secrets."""
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
                "default_voice": current_tts_voice(),
            },
            "tts_available": tts_available,
        }

    @fastapi_app.get("/api/llm/providers")
    async def get_llm_providers() -> dict[str, Any]:
        """List OpenAI-compatible providers and return the active provider/model (no secrets)."""
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
        """Query the models available at the selected provider's `/models` endpoint."""
        target_id = (provider_id or active_provider_state.get("provider_id") or "custom").strip().lower()
        preset = get_preset(target_id)
        requested_url = (base_url or "").strip().rstrip("/")
        default_url = (
            preset.default_base_url if preset and preset.default_base_url else resolved_settings.llm_base_url
        ).rstrip("/")

        if requested_url and requested_url != default_url and target_id not in _BASE_URL_OVERRIDE_PROVIDERS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="base_url override is not allowed for this provider.",
            )

        target_url = requested_url or default_url
        api_key, _ = resolve_provider_api_key(target_id, fallback_key=env_llm_api_key)
        # Never send the environment key to an arbitrary base_url that differs from the configured one.
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
        """Update live and persist in SQLite the active LLM provider and model."""
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
        """List the configurable skill packs and interactive pet tricks."""
        return list_skills_payload(enabled_skill_ids)

    @fastapi_app.put("/api/skills/{skill_id}")
    async def toggle_pet_skill(skill_id: str, body: SkillToggleRequest) -> dict[str, Any]:
        """Enable or disable a skill and persist it in SQLite (`app_meta`)."""
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
        """Validate and record the run of an interactive pet trick."""
        trick = get_trick(trick_id)
        if trick is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Trick '{trick_id}' not found.",
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
    # Cowork (read-only: State, Today, Sync) & First Wake
    # ------------------------------------------------------------------

    @fastapi_app.get("/api/cowork/state")
    async def get_cowork_state() -> dict[str, Any]:
        """Return the current `Cowork/state/*.yaml` state and the sync status."""
        state = await asyncio.to_thread(resolved_cowork.load_state)
        state["cowork_available"] = bool(state.get("workspace_exists", False))
        return state

    @fastapi_app.get("/api/cowork/today")
    async def get_cowork_today() -> dict[str, Any]:
        """Generate the Today summary, validated against hallucinations via the unified router."""
        return await resolved_today.generate_today()

    @fastapi_app.get("/api/cowork/sync")
    async def get_cowork_sync() -> dict[str, Any]:
        """Return Git status + Cowork state health for the menu bar LED."""
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

    # ------------------------------------------------------------------
    # Bidirectional WebSocket (LLM streaming, barge-in, actions, voice and pet)
    # ------------------------------------------------------------------

    # Active Body (ADR 0001) and Device Roles (P01): see app/device_hub.py.
    hub = setup_devices(fastapi_app, resolved_settings.db_path, require_mac_client)
    # Panels (P02): Layouts REST and the /panel page (app/panels/routes.py).
    register_panels(fastapi_app, resolved_settings.db_path, require_mac_client)
    bodies = hub.entries
    current_active_body = hub.current_active_body
    announce_active_body = hub.announce_active_body

    # Signals (P06): sources call `app.state.signals.emit(Signal(...))`.
    signal_speaker = ActiveBodySpeaker(current_active_body, resolved_tts, current_tts_voice)
    signals = SignalBus(
        hub,
        speak=signal_speaker.speak,
        set_expression=signal_speaker.set_expression,
        focus_active=getattr(resolved_mac, "pomodoro_active", None),
        consent=data_consent.get,
    )
    fastapi_app.state.signals = signals

    # Issue 12: Lupin as an MCP server (loopback only) and external MCP servers as Actions.
    register_mcp_server(fastapi_app, signals=signals, today=resolved_today)
    external_tools = register_mcp_routes(
        fastapi_app,
        McpServerStore(resolved_settings.db_path.parent / "mcp_servers.json"),
        require_mac_client,
    )

    # Tasks, notes and habits (issue 05): store, REST, Panel actions, habit scheduler.
    register_productivity(fastapi_app, resolved_settings.db_path)

    @fastapi_app.websocket("/ws")
    async def websocket_chat(websocket: WebSocket) -> None:
        """Concurrent WebSocket channel with sentence-by-sentence streaming, barge-in and actions."""
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
        # Brain<->Body protocol v1: the Body declares in `hello` whether it wants server audio.
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
                    "message": f"Authorize running '{shortcut['title']}'?",
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
                            "error": f"Shortcut '{target}' not found.",
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
                        "title": f"Open application {target}",
                        "message": f"Allow the assistant to open '{target}' on the Mac?",
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
                        "title": "Today summary",
                        "ok": bool(today_res.get("ok")),
                        "result": today_res,
                    }
                )
                return

            if kind == "mcp":
                parsed = external_tools.parse_target(target)
                info = external_tools.describe(*parsed) if parsed else None
                if parsed is None or info is None:
                    await safe_send(
                        {
                            "type": "action_executed",
                            "kind": "mcp",
                            "target": target.split(" ", 1)[0][:80],
                            "ok": False,
                            "error": "Unknown external tool.",
                        }
                    )
                    return
                if info["needs_approval"]:
                    approval_id = uuid.uuid4().hex[:10]
                    pending_approvals[approval_id] = {"kind": "mcp", "call": parsed}
                    await safe_send(
                        {
                            "type": "tool_approval_request",
                            "approval_id": approval_id,
                            "kind": "mcp",
                            "risk": info["risk"],
                            "target": f"{info['server']}.{info['tool']}",
                            "title": info["title"],
                            "message": info["message"],
                        }
                    )
                    return
                res = await external_tools.run(*parsed)
                await safe_send(
                    {
                        "type": "action_executed",
                        "kind": "mcp",
                        "target": f"{info['server']}.{info['tool']}",
                        "ok": bool(res.get("ok")),
                        "result": res.get("text"),
                        "error": res.get("error"),
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
                            "error": f"Trick '{target}' not found.",
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

        def mirror_target() -> dict[str, Any] | None:
            """Active Body of another connection, when the asker is not the Active Body."""
            active = current_active_body()
            if active is None or active is body_info["entry"]:
                return None
            return active

        async def send_to_entry(entry: dict[str, Any], payload: dict[str, Any]) -> bool:
            """Send to any Body; a dropped connection does not bring down the asker's turn."""
            try:
                await entry["send"](payload)
                return True
            except Exception:
                logger.info("Body %s did not receive event %s (connection dropped).", entry["body"], payload.get("type"))
                return False

        async def audio_worker(
            queue: asyncio.Queue[str | None],
            send: Callable[[dict[str, Any]], Any] | None = None,
            extra: dict[str, Any] | None = None,
        ) -> None:
            """Synthesize each queued sentence and send `audio` in chunks. A TTS failure only skips the audio.

            `send`/`extra` let the voice be delivered to another Body (mirrored reply on the Active Body);
            in that case a send failure only ends the audio, not the turn.
            """
            deliver = send or safe_send
            index = 0
            while True:
                sentence_text = await queue.get()
                if sentence_text is None:
                    return
                sentence_index = index
                index += 1
                try:
                    audio_bytes, _mime = await resolved_tts.synthesize_async(
                        text=sentence_text, voice=current_tts_voice(), output_format="m4a"
                    )
                except Exception as exc:
                    logger.warning("TTS failed for an audio sentence (%s); audio skipped.", type(exc).__name__)
                    continue
                total = max(1, -(-len(audio_bytes) // _AUDIO_CHUNK_BYTES))
                for seq in range(total):
                    chunk = audio_bytes[seq * _AUDIO_CHUNK_BYTES : (seq + 1) * _AUDIO_CHUNK_BYTES]
                    payload = {
                        "type": "audio",
                        "sentence": sentence_index,
                        "seq": seq,
                        "last": seq == total - 1,
                        "mime": "audio/mp4",
                        "data": base64.b64encode(chunk).decode("ascii"),
                        **(extra or {}),
                    }
                    if extra is None:
                        await deliver(payload)
                    else:
                        try:
                            await deliver(payload)
                        except Exception:
                            logger.info("Target Body left in the middle of the voice; audio ended.")
                            return

        async def run_first_wake() -> None:
            """First Wake (issue 03): on the first interaction of the day on the Active Body, Lupin speaks the Today.

            The speech is composed without an LLM and does not enter the history, so the calendar and Cowork
            never leave the machine.
            """
            if not is_active_body() or not resolved_first_wake.is_due():
                return
            today_iso = resolved_first_wake.mark_triggered()
            try:
                state = await asyncio.to_thread(resolved_cowork.load_state)
            except Exception as exc:
                logger.warning("First Wake without Cowork (%s).", type(exc).__name__)
                state = {"workspace_exists": False}
            try:
                calendar = await asyncio.to_thread(resolved_calendar_reader)
            except Exception as exc:
                logger.warning("First Wake without calendar (%s).", type(exc).__name__)
                calendar = None
            try:
                inbox = await asyncio.to_thread(resolved_inbox_reader)
            except Exception as exc:
                logger.warning("First Wake without e-mail (%s).", type(exc).__name__)
                inbox = None
            unread = inbox.get("unread") if isinstance(inbox, dict) else None
            sentences = compose_first_wake_speech(state, calendar, today_iso, unread)

            audio_queue: asyncio.Queue[str | None] | None = None
            audio_task: asyncio.Task[None] | None = None
            if body_info["wants_audio"] and resolved_tts.is_available():
                audio_queue = asyncio.Queue()
                audio_task = asyncio.create_task(audio_worker(audio_queue))
            try:
                await safe_send({"type": "emotion", "emotion": "happy"})
                for first_wake_sentence in sentences:
                    await safe_send({"type": "sentence", "text": first_wake_sentence, "first_wake": True})
                    if audio_queue is not None:
                        audio_queue.put_nowait(first_wake_sentence)
                await safe_send(
                    {
                        "type": "done",
                        "text": " ".join(sentences),
                        "emotion": "happy",
                        "facts": [],
                        "companion": resolved_memory.get_companion_state(),
                        "first_wake": True,
                    }
                )
                if audio_queue is not None and audio_task is not None:
                    audio_queue.put_nowait(None)
                    await audio_task
            finally:
                if audio_task is not None and not audio_task.done():
                    audio_task.cancel()

        async def run_llm_turn(user_text: str) -> None:
            clean_text = ""
            raw_text = ""
            emotion = "neutral"
            audio_queue: asyncio.Queue[str | None] | None = None
            audio_task: asyncio.Task[None] | None = None
            slow_notice: SlowModelNotice | None = None
            # Reply on the Active Body (ADR 0001, addendum): if the asker is not the Active Body,
            # the voice, the Expression and the sentences also go to it, tagged with `from_body`.
            asker_name = str(body_info["body"] or "unknown")
            mirror_entry = mirror_target()
            mirror_extra = {"from_body": asker_name}

            async def mirror(payload: dict[str, Any]) -> None:
                target = mirror_target() if mirror_entry is not None else None
                if target is not None:
                    await send_to_entry(target, {**payload, **mirror_extra})

            if resolved_tts.is_available():
                if body_info["wants_audio"] and is_active_body():
                    audio_queue = asyncio.Queue()
                    audio_task = asyncio.create_task(audio_worker(audio_queue))
                elif mirror_entry is not None and mirror_entry.get("wants_audio"):
                    audio_queue = asyncio.Queue()
                    audio_task = asyncio.create_task(
                        audio_worker(audio_queue, mirror_entry["send"], mirror_extra)
                    )

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
                mcp_context = external_tools.prompt_context()
                if mcp_context:
                    skills_context = f"{skills_context}\n\n{mcp_context}".strip()

                # Data Consent: calendar and e-mail are only read and sent with the switch on
                # for the active provider. Ephemeral context: it goes neither to the history nor to the log.
                consent = data_consent.get()
                turn_calendar: list[dict[str, Any]] | None = None
                turn_inbox: dict[str, Any] | None = None
                if consent["calendar"]:
                    try:
                        turn_calendar = await asyncio.to_thread(resolved_calendar_reader)
                    except Exception as exc:
                        logger.warning("Conversation without calendar (%s).", type(exc).__name__)
                if consent["email"]:
                    try:
                        turn_inbox = await asyncio.to_thread(resolved_inbox_reader)
                    except Exception as exc:
                        logger.warning("Conversation without e-mail (%s).", type(exc).__name__)
                personal_context = build_personal_context(consent, turn_calendar, turn_inbox)

                resolved_memory.add_message("user", user_text)

                async def announce_slow_model() -> None:
                    await safe_send({"type": "state", "state": "thinking"})
                    await safe_send({"type": "notice", "kind": "slow_model", "text": speech.LOCAL_MODEL_SLOW})
                    if audio_queue is not None:
                        audio_queue.put_nowait(speech.LOCAL_MODEL_SLOW)

                slow_notice = SlowModelNotice(
                    resolved_settings.local_llm_slow_after_s if data_consent.is_local() else 0.0,
                    announce_slow_model,
                )
                slow_notice.start()

                async for event in resolved_llm.stream_chat(
                    user_text=user_text,
                    history=history,
                    memory_context=memory_context,
                    shortcuts_context=shortcuts_context,
                    companion_context=companion_context,
                    temporal_context=temporal_context,
                    cowork_context=cowork_context,
                    skills_context=skills_context,
                    personal_context=personal_context,
                ):
                    slow_notice.stop()
                    event_type = event.get("type")
                    if event_type == "emotion":
                        emotion = str(event.get("emotion") or "neutral")
                        await safe_send({"type": "emotion", "emotion": emotion})
                        await mirror({"type": "emotion", "emotion": emotion})
                    elif event_type == "delta":
                        delta_text = str(event.get("text") or "")
                        if delta_text:
                            await safe_send({"type": "delta", "text": delta_text})
                    elif event_type == "sentence":
                        sentence_text = str(event.get("text") or "")
                        if sentence_text:
                            await safe_send({"type": "sentence", "text": sentence_text})
                            await mirror({"type": "sentence", "text": sentence_text})
                            if audio_queue is not None:
                                audio_queue.put_nowait(sentence_text)
                    elif event_type == "action":
                        kind = str(event.get("kind") or "")
                        target = str(event.get("target") or "")
                        if kind in ("task", "note", "habit") and target:
                            voice_result = await fastapi_app.state.productivity.handle_voice(kind, target)
                            await safe_send(
                                {
                                    "type": "action_executed",
                                    "kind": kind,
                                    "target": kind,
                                    "ok": bool(voice_result.get("ok")),
                                }
                            )
                            spoken = str(voice_result.get("spoken") or "")
                            if spoken:
                                await safe_send({"type": "sentence", "text": spoken})
                                await mirror({"type": "sentence", "text": spoken})
                                if audio_queue is not None:
                                    audio_queue.put_nowait(spoken)
                        elif kind and target:
                            await execute_action_item(kind, target)
                    elif event_type == "result":
                        clean_text = str(event.get("text") or "")
                        raw_text = str(event.get("raw_text") or "")
                        emotion = str(event.get("emotion") or emotion)

                resolved_memory.add_message("assistant", clean_text, emotion=emotion)
                new_facts = resolved_memory.extract_and_store_facts(user_text, raw_text)
                companion_state = resolved_memory.record_interaction()

                done_payload = {
                    "type": "done",
                    "text": clean_text,
                    "emotion": emotion,
                    "facts": new_facts,
                    "companion": companion_state,
                }
                await safe_send(done_payload)
                await mirror(done_payload)
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
                logger.info("LLM turn interrupted by barge-in.")
                raise
            except WebSocketDisconnect:
                raise
            except LLMError as exc:
                logger.error("Failed to process message via LLM: %s", exc)
                await safe_send({"type": "state", "state": "error"})
                await safe_send({"type": "error", "message": speech.FRIENDLY_LLM_ERROR})
            except Exception as exc:
                logger.error(
                    "Unexpected error during WebSocket streaming (%s)",
                    type(exc).__name__,
                )
                await safe_send({"type": "state", "state": "error"})
                await safe_send({"type": "error", "message": speech.FRIENDLY_LLM_ERROR})
            finally:
                if slow_notice is not None:
                    slow_notice.stop()
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
                    err_msg = stt_res.get("error") or "Could not understand the audio."
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
                logger.error("Unexpected error during WebSocket transcription (%s)", type(exc).__name__)
                if asyncio.current_task() is active_turn_task:
                    await safe_send({"type": "state", "state": "error"})
                    await safe_send({"type": "error", "message": "Failed to transcribe the received audio."})

        async def run_dictation_turn(audio_bytes: bytes, mime_type: str, language: str) -> None:
            """Dictation: transcribe locally, format, paste into the Mac's focused app. No LLM."""
            try:
                await safe_send({"type": "state", "state": "thinking"})
                stt_res = await resolved_stt.transcribe_bytes(
                    audio_bytes=audio_bytes, mime_type=mime_type, language=language
                )
                if asyncio.current_task() is not active_turn_task:
                    return
                text = format_dictation(str(stt_res.get("text") or ""), language)
                if not text:
                    await safe_send(
                        {"type": "dictation_result", "ok": False, "message": speech.DICTATION_EMPTY}
                    )
                    await safe_send({"type": "state", "state": "idle"})
                    return
                result = await asyncio.to_thread(resolved_mac.paste_text, text)
                if result.get("ok"):
                    message = speech.DICTATION_INSERTED
                elif result.get("needs_accessibility"):
                    message = speech.DICTATION_NEEDS_ACCESSIBILITY
                else:
                    message = speech.DICTATION_PASTE_FAILED
                await safe_send(
                    {
                        "type": "dictation_result",
                        "ok": bool(result.get("ok")),
                        "chars": len(text) if result.get("ok") else 0,
                        "message": message,
                    }
                )
                await safe_send({"type": "state", "state": "idle" if result.get("ok") else "error"})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Unexpected error during dictation (%s)", type(exc).__name__)
                if asyncio.current_task() is active_turn_task:
                    await safe_send({"type": "state", "state": "error"})
                    await safe_send(
                        {"type": "dictation_result", "ok": False, "message": speech.DICTATION_PASTE_FAILED}
                    )

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

        async def with_first_wake(turn: Callable[[], Any]) -> None:
            await run_first_wake()
            await turn()

        def start_llm_turn(user_text: str) -> None:
            nonlocal active_turn_task
            active_turn_task = asyncio.create_task(with_first_wake(lambda: run_llm_turn(user_text)))

        def start_dictation_turn(audio_bytes: bytes, mime_type: str, language: str) -> None:
            nonlocal active_turn_task
            active_turn_task = asyncio.create_task(run_dictation_turn(audio_bytes, mime_type, language))

        def start_audio_turn(audio_bytes: bytes, mime_type: str, language: str) -> None:
            nonlocal active_turn_task
            active_turn_task = asyncio.create_task(
                with_first_wake(lambda: run_audio_turn(audio_bytes, mime_type, language))
            )

        try:
            while True:
                raw_message = await websocket.receive_text()
                try:
                    data = json.loads(raw_message)
                except json.JSONDecodeError:
                    await safe_send({"type": "error", "message": "Invalid message format."})
                    continue

                if not isinstance(data, dict):
                    await safe_send(
                        {"type": "error", "message": "WebSocket payload must be a JSON object."}
                    )
                    continue

                msg_type = data.get("type")

                if msg_type == "hello":
                    await hub.hello(body_info, data, safe_send)
                    continue

                if await hub.handle_message(body_info["entry"], data, safe_send):
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
                    if active_turn_task is None or active_turn_task.done():
                        active_turn_task = asyncio.create_task(run_first_wake())
                    continue

                if msg_type == "run_shortcut":
                    identifier = data.get("id") if data.get("id") is not None else data.get("slug")
                    if identifier is None:
                        await safe_send({"type": "error", "message": "Shortcut ID not provided."})
                        continue
                    shortcut = resolved_shortcuts.get_shortcut(identifier)
                    if shortcut is None:
                        await safe_send(
                            {
                                "type": "action_executed",
                                "kind": "shortcut",
                                "target": str(identifier),
                                "ok": False,
                                "error": "Shortcut not found.",
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
                                "message": "Approval request expired or unknown.",
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
                                    "error": "Opening the application was declined by the user.",
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

                    if pending_kind == "mcp":
                        server_id, tool_name, tool_args = pending["call"]
                        target_name = f"{server_id}.{tool_name}"
                        if not approved:
                            await safe_send(
                                {
                                    "type": "action_executed",
                                    "approval_id": approval_id,
                                    "kind": "mcp",
                                    "target": target_name,
                                    "ok": False,
                                    "cancelled": True,
                                    "error": "Running the external tool was declined by the user.",
                                }
                            )
                            continue
                        res = await external_tools.run(server_id, tool_name, tool_args)
                        await safe_send(
                            {
                                "type": "action_executed",
                                "approval_id": approval_id,
                                "kind": "mcp",
                                "target": target_name,
                                "ok": bool(res.get("ok")),
                                "result": res.get("text"),
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
                                "error": "Execution declined by the user.",
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
                                    "error": "The shortcut prompt is empty.",
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
                    language = str(data.get("language") or current_stt_language())
                    try:
                        audio_bytes = _decode_base64_audio(raw_b64)
                    except ValueError as exc:
                        await safe_send({"type": "error", "message": str(exc)})
                        await safe_send({"type": "state", "state": "idle"})
                        continue

                    if data.get("dictation") is True:
                        start_dictation_turn(audio_bytes, mime_type, language)
                    else:
                        start_audio_turn(audio_bytes, mime_type, language)
                    continue

                if msg_type == "text":
                    user_text = str(data.get("text") or "").strip()
                    if not user_text:
                        await safe_send(
                            {"type": "error", "message": "Type a message to chat."}
                        )
                        continue

                    await cancel_active_turn(notify=False)
                    start_llm_turn(user_text)
                    continue

                await safe_send({"type": "error", "message": "Unsupported event type."})
        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected.")
        finally:
            await hub.disconnect(body_info["entry"])
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
    """Initialize `app` on demand to avoid opening SQLite at module import."""
    if name == "app":
        global _cached_app
        if _cached_app is None:
            _cached_app = create_app()
        return _cached_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
