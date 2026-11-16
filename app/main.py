"""Aplicação FastAPI principal, endpoints HTTP de memória e chat WebSocket."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import BASE_DIR, Settings, configure_logging, load_settings
from app.llm import LLMClient, LLMError
from app.memory import MemoryStore

logger = logging.getLogger(__name__)

_FRIENDLY_LLM_ERROR = "Não consegui falar com o modelo agora. Verifique se a API local está rodando."


class FactCreateRequest(BaseModel):
    """Payload para criação manual de fato de memória de longo prazo."""

    fact: str = ""
    category: str = "general"


class ClearMemoryRequest(BaseModel):
    """Payload opcional para limpeza da memória."""

    include_facts: bool = False


def create_app(
    settings: Settings | None = None,
    memory_store: MemoryStore | None = None,
    llm_client: LLMClient | None = None,
) -> FastAPI:
    """Cria e configura a instância FastAPI com memória, LLM e arquivos estáticos."""
    resolved_settings = settings or load_settings()
    configure_logging(secret=resolved_settings.llm_api_key)

    own_memory = memory_store is None
    resolved_memory = memory_store or MemoryStore(
        db_path=resolved_settings.db_path,
        max_short_term_messages=resolved_settings.max_short_term_messages,
        max_user_facts=resolved_settings.max_user_facts,
    )
    resolved_llm = llm_client or LLMClient(resolved_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            if own_memory:
                resolved_memory.close()

    fastapi_app = FastAPI(
        title="Desk Assistant",
        description="Assistente de mesa estilo EMO com memória em 2 camadas e streaming LLM.",
        version="0.1.0",
        lifespan=lifespan,
    )
    fastapi_app.state.settings = resolved_settings
    fastapi_app.state.memory = resolved_memory
    fastapi_app.state.llm = resolved_llm

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

    @fastapi_app.get("/health")
    async def health() -> dict[str, str]:
        """Endpoint simples de verificação de saúde do serviço."""
        return {"status": "ok", "model": resolved_settings.llm_model}

    @fastapi_app.get("/api/memory")
    async def get_memory() -> dict[str, Any]:
        """Retorna os fatos persistidos e a quantidade de mensagens recentes."""
        return {
            "facts": resolved_memory.get_facts(),
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
        return resolved_memory.add_fact(fact_text, category=category)

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

    @fastapi_app.websocket("/ws")
    async def websocket_chat(websocket: WebSocket) -> None:
        """Canal WebSocket bidirecional para estados do rosto, chat em streaming e memória."""
        await websocket.accept()
        try:
            while True:
                raw_message = await websocket.receive_text()
                try:
                    data = json.loads(raw_message)
                except json.JSONDecodeError:
                    await websocket.send_json(
                        {"type": "error", "message": "Formato de mensagem inválido."}
                    )
                    continue

                if not isinstance(data, dict):
                    await websocket.send_json(
                        {"type": "error", "message": "Payload WebSocket deve ser um objeto JSON."}
                    )
                    continue

                msg_type = data.get("type")

                if msg_type == "typing":
                    active = bool(data.get("active", False))
                    await websocket.send_json(
                        {"type": "state", "state": "listening" if active else "idle"}
                    )
                    continue

                if msg_type == "clear_history":
                    resolved_memory.clear_short_term()
                    await websocket.send_json(
                        {
                            "type": "memory_updated",
                            "facts": resolved_memory.get_facts(),
                            "recent_messages_count": resolved_memory.get_recent_messages_count(),
                        }
                    )
                    continue

                if msg_type == "text":
                    user_text = str(data.get("text") or "").strip()
                    if not user_text:
                        await websocket.send_json(
                            {"type": "error", "message": "Digite uma mensagem para conversar."}
                        )
                        continue

                    await websocket.send_json({"type": "state", "state": "thinking"})

                    history = resolved_memory.get_recent_messages()
                    memory_context = resolved_memory.build_memory_context()
                    resolved_memory.add_message("user", user_text)

                    clean_text = ""
                    raw_text = ""
                    emotion = "neutral"

                    try:
                        async for event in resolved_llm.stream_chat(
                            user_text=user_text,
                            history=history,
                            memory_context=memory_context,
                        ):
                            event_type = event.get("type")
                            if event_type == "emotion":
                                emotion = str(event.get("emotion") or "neutral")
                                await websocket.send_json({"type": "emotion", "emotion": emotion})
                            elif event_type == "delta":
                                delta_text = str(event.get("text") or "")
                                if delta_text:
                                    await websocket.send_json({"type": "delta", "text": delta_text})
                            elif event_type == "result":
                                clean_text = str(event.get("text") or "")
                                raw_text = str(event.get("raw_text") or "")
                                emotion = str(event.get("emotion") or emotion)

                        resolved_memory.add_message("assistant", clean_text, emotion=emotion)
                        new_facts = resolved_memory.extract_and_store_facts(user_text, raw_text)

                        await websocket.send_json(
                            {
                                "type": "done",
                                "text": clean_text,
                                "emotion": emotion,
                                "facts": new_facts,
                            }
                        )
                        await websocket.send_json(
                            {
                                "type": "memory_updated",
                                "facts": resolved_memory.get_facts(),
                                "recent_messages_count": resolved_memory.get_recent_messages_count(),
                            }
                        )
                    except WebSocketDisconnect:
                        raise
                    except LLMError as exc:
                        logger.error("Falha ao processar mensagem via LLM: %s", exc)
                        await websocket.send_json({"type": "state", "state": "error"})
                        await websocket.send_json(
                            {"type": "error", "message": _FRIENDLY_LLM_ERROR}
                        )
                    except Exception as exc:
                        logger.error(
                            "Erro inesperado durante o streaming WebSocket (%s)",
                            type(exc).__name__,
                        )
                        await websocket.send_json({"type": "state", "state": "error"})
                        await websocket.send_json(
                            {"type": "error", "message": _FRIENDLY_LLM_ERROR}
                        )
                    continue

                await websocket.send_json(
                    {"type": "error", "message": "Tipo de evento não suportado."}
                )
        except WebSocketDisconnect:
            logger.info("Cliente WebSocket desconectado.")

    return fastapi_app


app = create_app()
