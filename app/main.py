"""Aplicação FastAPI principal, endpoints HTTP, Dock/Atalhos Mac, STT/TTS e WebSocket."""

from __future__ import annotations

import asyncio
import base64
import binascii
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

from app.config import BASE_DIR, Settings, configure_logging, load_settings
from app.llm import LLMClient, LLMError
from app.mac_control import MacController
from app.memory import MemoryStore
from app.shortcuts import ShortcutStore
from app.stt import LocalSTT
from app.tts import ServerTTS

logger = logging.getLogger(__name__)

_FRIENDLY_LLM_ERROR = "Não consegui falar com o modelo agora. Verifique se a API local está rodando."


class FactCreateRequest(BaseModel):
    """Payload para criação manual de fato de memória de longo prazo."""

    fact: str = ""
    category: str = "general"
    pinned: bool | None = None
    importance: int | None = None


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
) -> FastAPI:
    """Cria e configura a instância FastAPI com memória, atalhos, Mac, voz e WebSocket."""
    resolved_settings = settings or load_settings()
    configure_logging(secret=resolved_settings.llm_api_key)

    own_memory = memory_store is None
    resolved_memory = memory_store or MemoryStore(
        db_path=resolved_settings.db_path,
        max_short_term_messages=resolved_settings.max_short_term_messages,
        max_user_facts=resolved_settings.max_user_facts,
    )

    own_shortcuts = shortcut_store is None
    resolved_shortcuts = shortcut_store or ShortcutStore(db_path=resolved_settings.db_path)

    resolved_llm = llm_client or LLMClient(resolved_settings)
    resolved_mac = mac_controller or MacController()
    resolved_stt = stt_engine or LocalSTT(
        model_name=resolved_settings.stt_model,
        language=resolved_settings.stt_language,
    )
    resolved_tts = tts_engine or ServerTTS(default_voice=resolved_settings.tts_voice)

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
        return {
            "status": "ok",
            "model": resolved_settings.llm_model,
            "llm_model": resolved_settings.llm_model,
            "llm_base_url": resolved_settings.llm_base_url,
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

    # ------------------------------------------------------------------
    # WebSocket Bidirecional (Streaming LLM, Barge-in, Ações, Voz e Pet)
    # ------------------------------------------------------------------

    @fastapi_app.websocket("/ws")
    async def websocket_chat(websocket: WebSocket) -> None:
        """Canal WebSocket concorrente com streaming frase-a-frase, barge-in e ações."""
        await websocket.accept()
        send_lock = asyncio.Lock()
        active_turn_task: asyncio.Task[None] | None = None
        pending_approvals: dict[str, dict[str, Any]] = {}

        async def safe_send(payload: dict[str, Any]) -> None:
            async with send_lock:
                await websocket.send_json(payload)

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
                res = await asyncio.to_thread(resolved_mac.activate_app, target)
                await safe_send(
                    {
                        "type": "action_executed",
                        "kind": "app",
                        "target": target,
                        "title": target,
                        "ok": bool(res.get("ok")),
                        "result": res,
                        "error": res.get("error"),
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

        async def run_llm_turn(user_text: str) -> None:
            clean_text = ""
            raw_text = ""
            emotion = "neutral"

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

                resolved_memory.add_message("user", user_text)

                async for event in resolved_llm.stream_chat(
                    user_text=user_text,
                    history=history,
                    memory_context=memory_context,
                    shortcuts_context=shortcuts_context,
                    companion_context=companion_context,
                    temporal_context=temporal_context,
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

                if msg_type == "pet":
                    kind = str(data.get("kind") or "pet").strip().lower()
                    if kind == "pet":
                        intensity = float(data.get("intensity") or 1.0)
                        companion = resolved_memory.record_pet(intensity=intensity)
                    else:
                        companion = resolved_memory.record_interaction(sentiment_delta=-0.02)
                    await safe_send(
                        {
                            "type": "companion_updated",
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

                    await safe_send({"type": "state", "state": "thinking"})
                    stt_res = await resolved_stt.transcribe_bytes(
                        audio_bytes=audio_bytes,
                        mime_type=mime_type,
                        language=language,
                    )
                    transcript = str(stt_res.get("text") or "").strip()
                    if not transcript:
                        err_msg = stt_res.get("error") or "Não foi possível entender o áudio."
                        await safe_send({"type": "error", "message": str(err_msg)})
                        await safe_send({"type": "state", "state": "idle"})
                        continue

                    await safe_send(
                        {
                            "type": "transcript",
                            "text": transcript,
                            "engine": stt_res.get("engine"),
                        }
                    )
                    start_llm_turn(transcript)
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
            if active_turn_task is not None and not active_turn_task.done():
                active_turn_task.cancel()
                try:
                    await active_turn_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

    return fastapi_app


app = create_app()
