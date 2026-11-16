"""Cliente assíncrono de LLM em streaming e parser de tags emocionais/memória."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

# Lista oficial de emoções suportadas pelo rosto estilo EMO.
SUPPORTED_EMOTIONS: tuple[str, ...] = (
    "neutral",
    "happy",
    "excited",
    "curious",
    "skeptical",
    "surprised",
    "sad",
    "wink",
    "love",
    "sleepy",
)
VALID_EMOTIONS: frozenset[str] = frozenset(SUPPORTED_EMOTIONS)

_EMOTION_TAG_RE = re.compile(r"^\[emotion\s*:\s*([a-zA-Z0-9_-]+)\s*\]$", re.IGNORECASE)
_SHORT_EMOTION_TAG_RE = re.compile(r"^\[\s*([a-zA-Z0-9_-]+)\s*\]$")
_FACT_TAG_RE = re.compile(r"^\[fact\s*:\s*(.*?)\s*\]$", re.IGNORECASE | re.DOTALL)
_KNOWN_TAG_PREFIXES: tuple[str, ...] = (
    "[emotion",
    "[fact",
    *(f"[{emotion}" for emotion in SUPPORTED_EMOTIONS),
)

# Limite de segurança para evitar buffering infinito se surgir '[' sem fechamento.
_MAX_TAG_BUFFER_CHARS = 256


class LLMError(Exception):
    """Erro seguro ao se comunicar com o provedor LLM (sem expor segredos)."""


def build_system_prompt(memory_context: str = "") -> str:
    """Constrói o system prompt em PT-BR para o assistente de mesa estilo EMO."""
    emotions_list = ", ".join(SUPPORTED_EMOTIONS)
    base_prompt = (
        "Você é um assistente de mesa carismático, amigável e expressivo no estilo EMO. "
        "Responda sempre em português do Brasil, em 1 a 3 frases curtas, usando apenas "
        "texto puro e natural para ser lido em voz alta. "
        "NUNCA use Markdown, asteriscos, listas com marcadores, títulos ou blocos de código.\n\n"
        "REGRAS OBRIGATÓRIAS DE FORMATAÇÃO:\n"
        f"1. SEMPRE comece sua resposta com exatamente uma tag de emoção no formato "
        f"[emotion:<nome>], escolhendo <nome> apenas entre: {emotions_list}.\n"
        "2. Quando o usuário compartilhar um fato pessoal duradouro, preferência, nome, "
        "rotina ou interesse real, adicione ao FINAL da resposta uma ou mais tags no formato "
        "[fact: <fato curto e objetivo sobre o usuário>]. Nunca invente fatos nem suposições."
    )
    context = memory_context.strip()
    if context:
        return f"{base_prompt}\n\nMemória conhecida sobre o usuário:\n{context}"
    return base_prompt


@dataclass
class TagStreamParser:
    """Parser incremental que remove tags `[emotion:...]`/`[<emocao>]` e `[fact:...]` no stream.

    Garante que nenhuma tag interna vaze nos eventos `delta` enviados ao frontend/TTS,
    mesmo quando os colchetes ou o conteúdo da tag chegam divididos entre múltiplos chunks.
    """

    emotion_emitted: bool = False
    detected_emotion: str = "neutral"
    _buffer: str = ""
    _raw_parts: list[str] = field(default_factory=list)
    _clean_parts: list[str] = field(default_factory=list)
    _has_emitted_text: bool = False

    def feed(self, chunk: str) -> list[dict[str, str]]:
        """Processa um trecho de `delta.content` e retorna eventos estruturados prontos."""
        if not chunk:
            return []

        self._raw_parts.append(chunk)
        self._buffer += chunk
        events: list[dict[str, str]] = []

        while self._buffer:
            if not self._has_emitted_text and not self._buffer.startswith("["):
                # Descarta espaços iniciais antes da primeira tag ou do primeiro texto útil.
                stripped = self._buffer.lstrip()
                if not stripped:
                    self._buffer = ""
                    break
                self._buffer = stripped

            if self._buffer.startswith("["):
                close_idx = self._buffer.find("]")
                if close_idx != -1:
                    tag = self._buffer[: close_idx + 1]
                    self._buffer = self._buffer[close_idx + 1 :]
                    events.extend(self._handle_closed_tag(tag))
                    continue

                # Ainda aguardando o ']' de fechamento da tag.
                if len(self._buffer) > _MAX_TAG_BUFFER_CHARS and not self._looks_like_known_tag_prefix(
                    self._buffer
                ):
                    # Não parece uma tag nossa; libera como texto comum para não travar o stream.
                    text = self._buffer
                    self._buffer = ""
                    events.extend(self._emit_text(text))
                break

            next_bracket = self._buffer.find("[")
            if next_bracket == -1:
                text = self._buffer
                self._buffer = ""
                events.extend(self._emit_text(text))
            else:
                text = self._buffer[:next_bracket]
                self._buffer = self._buffer[next_bracket:]
                events.extend(self._emit_text(text))

        return events

    def finish(self) -> tuple[list[dict[str, str]], str, str, str]:
        """Finaliza o stream, drena restos seguros do buffer e retorna resultado completo.

        Retorna `(eventos_finais, texto_limpo, texto_bruto, emocao)`.
        """
        events: list[dict[str, str]] = []

        if self._buffer:
            # Se sobrou uma tag `[emotion...`, `[happy...` ou `[fact...` incompleta no fim do stream,
            # descartamos para nunca vazar marcação ao usuário/TTS.
            if not self._looks_like_known_tag_prefix(self._buffer):
                events.extend(self._emit_text(self._buffer))
            self._buffer = ""

        if not self.emotion_emitted:
            self.emotion_emitted = True
            self.detected_emotion = "neutral"
            events.append({"type": "emotion", "emotion": "neutral"})

        clean_text = "".join(self._clean_parts).strip()
        raw_text = "".join(self._raw_parts)
        return events, clean_text, raw_text, self.detected_emotion

    @staticmethod
    def _looks_like_known_tag_prefix(text: str) -> bool:
        """Verifica se o início do buffer pode corresponder a `[emotion:`, `[fact:` ou `[<emoção>`."""
        lower = text.lstrip().lower()
        for prefix in _KNOWN_TAG_PREFIXES:
            if lower.startswith(prefix) or prefix.startswith(lower):
                return True
        return False

    def _handle_closed_tag(self, tag: str) -> list[dict[str, str]]:
        """Interpreta uma tag completa `[...]` e retorna eventos correspondentes."""
        emotion_match = _EMOTION_TAG_RE.match(tag)
        if emotion_match:
            candidate = emotion_match.group(1).strip().lower()
            valid_emotion = candidate if candidate in VALID_EMOTIONS else "neutral"
            if not self.emotion_emitted:
                self.emotion_emitted = True
                self.detected_emotion = valid_emotion
                return [{"type": "emotion", "emotion": valid_emotion}]
            return []

        short_match = _SHORT_EMOTION_TAG_RE.match(tag)
        if short_match:
            candidate = short_match.group(1).strip().lower()
            if candidate in VALID_EMOTIONS:
                if not self.emotion_emitted:
                    self.emotion_emitted = True
                    self.detected_emotion = candidate
                    return [{"type": "emotion", "emotion": candidate}]
                return []

        if _FACT_TAG_RE.match(tag):
            # Tag de fato fica apenas no raw_text para extração pela camada de memória.
            return []

        # Colchetes comuns que não pertencem a tags de controle viram texto falado.
        return self._emit_text(tag)

    def _emit_text(self, text: str) -> list[dict[str, str]]:
        """Emite texto limpo garantindo que o evento de emoção venha antes de qualquer delta."""
        events: list[dict[str, str]] = []
        if not self._has_emitted_text:
            text = text.lstrip()
            if not text:
                return events

        if not self.emotion_emitted:
            self.emotion_emitted = True
            self.detected_emotion = "neutral"
            events.append({"type": "emotion", "emotion": "neutral"})

        self._has_emitted_text = True
        self._clean_parts.append(text)
        events.append({"type": "delta", "text": text})
        return events


class LLMClient:
    """Cliente assíncrono para chat completions em streaming compatível com OpenAI."""

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        stream_fn: Callable[..., AsyncIterator[dict[str, Any]]] | None = None,
    ) -> None:
        self.settings = settings
        self._http_client = http_client
        self._transport = transport
        self._stream_fn = stream_fn

    def _build_payload(
        self,
        user_text: str,
        history: list[dict[str, str]],
        memory_context: str = "",
    ) -> dict[str, Any]:
        """Monta o payload JSON para `/chat/completions`."""
        messages: list[dict[str, str]] = [
            {"role": "system", "content": build_system_prompt(memory_context)}
        ]
        for msg in history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in {"user", "assistant", "system"} and content:
                messages.append({"role": role, "content": content})

        # Garante que a mensagem atual do usuário esteja no final se ainda não estiver no history.
        if not messages or messages[-1].get("role") != "user" or messages[-1].get("content") != user_text:
            messages.append({"role": "user", "content": user_text})

        return {
            "model": self.settings.llm_model,
            "messages": messages,
            "stream": True,
            "max_tokens": 500,
            "temperature": 0.7,
        }

    def _endpoint_url(self) -> str:
        """Retorna a URL completa do endpoint de chat completions."""
        return f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"

    def _headers(self) -> dict[str, str]:
        """Monta os headers HTTP da requisição sem registrar segredos em logs."""
        return {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }

    async def stream_chat(
        self,
        user_text: str,
        history: list[dict[str, str]],
        memory_context: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        """Executa o streaming do LLM e emite eventos `emotion`, `delta` e `result`."""
        if self._stream_fn is not None:
            async for event in self._stream_fn(
                user_text=user_text,
                history=history,
                memory_context=memory_context,
            ):
                yield event
            return

        payload = self._build_payload(user_text, history, memory_context)
        parser = TagStreamParser()

        own_client = self._http_client is None
        client = self._http_client
        if client is None:
            timeout = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
            client = httpx.AsyncClient(transport=self._transport, timeout=timeout)

        try:
            async with client.stream(
                "POST",
                self._endpoint_url(),
                headers=self._headers(),
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    logger.error(
                        "Erro HTTP do provedor LLM: status=%s modelo=%s",
                        response.status_code,
                        self.settings.llm_model,
                    )
                    raise LLMError("Falha ao consultar o modelo LLM.")

                async for raw_line in response.aiter_lines():
                    line = raw_line.strip()
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue

                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break

                    try:
                        chunk_data = json.loads(data_str)
                    except json.JSONDecodeError:
                        logger.warning("Linha SSE inválida ignorada do stream LLM.")
                        continue

                    choices = chunk_data.get("choices") or []
                    if not choices:
                        continue

                    delta = choices[0].get("delta") or {}
                    # Quirk da API local: tokens de raciocínio chegam em `delta.reasoning`
                    # antes de `delta.content` e NUNCA devem ir para o usuário ou TTS.
                    content = delta.get("content")
                    if not content:
                        continue

                    for event in parser.feed(content):
                        yield event

            tail_events, clean_text, raw_text, emotion = parser.finish()
            for event in tail_events:
                yield event

            logger.info(
                "Resposta LLM concluída: modelo=%s emocao=%s tamanho_chars=%d",
                self.settings.llm_model,
                emotion,
                len(clean_text),
            )
            yield {
                "type": "result",
                "text": clean_text,
                "raw_text": raw_text,
                "emotion": emotion,
            }
        except LLMError:
            raise
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError) as exc:
            logger.error(
                "Erro de rede ao acessar LLM (%s) modelo=%s",
                type(exc).__name__,
                self.settings.llm_model,
            )
            raise LLMError("Não foi possível conectar ao modelo LLM.") from exc
        finally:
            if own_client:
                await client.aclose()
