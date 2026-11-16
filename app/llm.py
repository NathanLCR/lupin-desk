"""Cliente assíncrono de LLM em streaming e parser de tags emocionais/memória/ações."""

from __future__ import annotations

import inspect
import json
import logging
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

# Lista oficial de 12 emoções suportadas pelo rosto estilo EMO.
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
    "angry",
    "dizzy",
)
VALID_EMOTIONS: frozenset[str] = frozenset(SUPPORTED_EMOTIONS)

_EMOTION_TAG_RE = re.compile(r"^\[emotion\s*:\s*([a-zA-Z0-9_-]+)\s*\]$", re.IGNORECASE)
_SHORT_EMOTION_TAG_RE = re.compile(r"^\[\s*([a-zA-Z0-9_-]+)\s*\]$")
_FACT_TAG_RE = re.compile(r"^\[fact\s*:\s*(.*?)\s*\]$", re.IGNORECASE | re.DOTALL)
_ACTION_TAG_RE = re.compile(
    r"^\[action\s*:\s*(shortcut|app|pomodoro|today)\s*:\s*(.*?)\s*\]$",
    re.IGNORECASE | re.DOTALL,
)
_KNOWN_TAG_PREFIXES: tuple[str, ...] = (
    "[emotion",
    "[fact",
    "[action",
    *(f"[{emotion}" for emotion in SUPPORTED_EMOTIONS),
)

# Limite de segurança para evitar buffering infinito se surgir '[' sem fechamento.
_MAX_TAG_BUFFER_CHARS = 256


class LLMError(Exception):
    """Erro seguro ao se comunicar com o provedor LLM (sem expor segredos)."""


def build_system_prompt(
    memory_context: str = "",
    shortcuts_context: str = "",
    companion_context: str = "",
    temporal_context: str = "",
    cowork_context: str = "",
    skills_context: str = "",
) -> str:
    """Constrói o system prompt em PT-BR com memória, contexto temporal, humor e ações no Mac."""
    emotions_list = ", ".join(SUPPORTED_EMOTIONS)
    sections = [
        "Você é o Lupin, um assistente de mesa carismático, leal e expressivo inspirado em um Husky Siberiano "
        "Cyber-OLED (preto e branco de olhos azul-gelo). "
        "Responda sempre em português do Brasil, em 1 a 3 frases curtas, usando apenas "
        "texto puro e natural para ser lido em voz alta. "
        "NUNCA use Markdown, asteriscos, listas com marcadores, títulos ou blocos de código.\n\n"
        "REGRAS OBRIGATÓRIAS DE FORMATAÇÃO:\n"
        f"1. SEMPRE comece sua resposta com exatamente uma tag de emoção no formato "
        f"[emotion:<nome>], escolhendo <nome> apenas entre: {emotions_list}.\n"
        "2. Quando o usuário compartilhar um fato pessoal duradouro, preferência, nome, "
        "rotina ou interesse real, adicione ao FINAL da resposta uma ou mais tags no formato "
        "[fact: <fato curto e objetivo sobre o usuário>]. Nunca invente fatos nem suposições.\n"
        "3. REGRA SHOW, DON'T TELL: use os fatos conhecidos sobre o usuário de forma natural e "
        "implícita como conhecimento de fundo, sem recitá-los roboticamente nem listar o que sabe.\n"
        "4. AÇÕES NO MAC: sempre que o usuário pedir por voz ou texto para acionar um atalho, "
        "controlar janelas/espaços/mídia/prints, abrir ou focar um aplicativo no Mac, iniciar/parar "
        "o Pomodoro ou consultar o resumo Today, "
        "emita a tag invisível correspondente:\n"
        "   - [action:shortcut:<slug>] para executar um atalho cadastrado\n"
        "   - [action:app:<nome_do_app>] para abrir ou focar um aplicativo\n"
        "   - [action:pomodoro:start] ou [action:pomodoro:stop] para o timer Pomodoro\n"
        "   - [action:today:brief] para consultar o resumo Today do Cowork\n"
        "   Nunca leia ou mencione colchetes ou nomes de tags no texto falado."
    ]

    if temporal_context.strip():
        sections.append(f"Contexto temporal:\n{temporal_context.strip()}")

    if companion_context.strip():
        sections.append(f"Estado emocional do pet:\n{companion_context.strip()}")

    if memory_context.strip():
        sections.append(f"Memória conhecida sobre o usuário:\n{memory_context.strip()}")

    if cowork_context.strip():
        sections.append(f"Estado atual do Cowork (tarefas, prazos e turnos):\n{cowork_context.strip()}")

    if shortcuts_context.strip():
        sections.append(f"Atalhos e apps disponíveis no Mac:\n{shortcuts_context.strip()}")

    if skills_context.strip():
        sections.append(f"Skills e truques do pet habilitados:\n{skills_context.strip()}")

    return "\n\n".join(sections)


@dataclass
class TagStreamParser:
    """Parser incremental que remove tags `[emotion:...]`, `[fact:...]` e `[action:...]` no stream.

    Garante que nenhuma tag interna vaze nos eventos `delta`/`sentence` enviados ao frontend/TTS,
    mesmo quando os colchetes ou o conteúdo da tag chegam divididos entre múltiplos chunks.
    """

    emotion_emitted: bool = False
    detected_emotion: str = "neutral"
    _buffer: str = ""
    _sentence_buf: str = ""
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
            # Se sobrou uma tag `[emotion...`, `[fact...`, `[action...` ou `[happy...` incompleta,
            # descartamos para nunca vazar marcação ao usuário/TTS.
            if not self._looks_like_known_tag_prefix(self._buffer):
                events.extend(self._emit_text(self._buffer))
            self._buffer = ""

        if not self.emotion_emitted:
            self.emotion_emitted = True
            self.detected_emotion = "neutral"
            events.append({"type": "emotion", "emotion": "neutral"})

        remainder = self._sentence_buf.strip()
        self._sentence_buf = ""
        if remainder and any(ch.isalnum() for ch in remainder):
            events.append({"type": "sentence", "text": remainder})

        clean_text = "".join(self._clean_parts).strip()
        raw_text = "".join(self._raw_parts)
        return events, clean_text, raw_text, self.detected_emotion

    @staticmethod
    def _looks_like_known_tag_prefix(text: str) -> bool:
        """Verifica se o início do buffer pode corresponder a uma tag conhecida do protocolo."""
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

        action_match = _ACTION_TAG_RE.match(tag)
        if action_match:
            kind = action_match.group(1).strip().lower()
            target = " ".join(action_match.group(2).strip().split())
            if target:
                return [{"type": "action", "kind": kind, "target": target}]
            return []

        # Colchetes comuns que não pertencem a tags de controle viram texto falado.
        return self._emit_text(tag)

    def _emit_text(self, text: str) -> list[dict[str, str]]:
        """Emite texto limpo garantindo emoção antes de delta e emitindo frases fechadas."""
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

        self._sentence_buf += text
        events.extend(self._pop_complete_sentences())
        return events

    def _pop_complete_sentences(self) -> list[dict[str, str]]:
        """Extrai frases completas terminadas em `.`, `!` ou `?` do buffer de sentenças."""
        emitted: list[dict[str, str]] = []
        buf = self._sentence_buf
        start = 0
        i = 0
        length = len(buf)

        while i < length:
            ch = buf[i]
            if ch in ".!?":
                # Mantém pontuação agrupada (`...`, `!?`, `!!`) junta na mesma frase.
                if i + 1 < length and buf[i + 1] in ".!?":
                    i += 1
                    continue
                # Evita quebrar decimais como `3.14` quando o dígito seguinte já está no buffer.
                if (
                    ch == "."
                    and i > 0
                    and buf[i - 1].isdigit()
                    and i + 1 < length
                    and buf[i + 1].isdigit()
                ):
                    i += 1
                    continue

                end = i + 1
                # Inclui aspas/parênteses de fechamento logo após a pontuação, se houver.
                while end < length and buf[end] in "\"')]}":
                    end += 1

                candidate = buf[start:end].strip()
                if candidate and any(c.isalnum() for c in candidate):
                    emitted.append({"type": "sentence", "text": candidate})
                    start = end
                    i = end
                    continue
            i += 1

        if start > 0:
            self._sentence_buf = buf[start:]
        return emitted


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
        shortcuts_context: str = "",
        companion_context: str = "",
        temporal_context: str = "",
        cowork_context: str = "",
        skills_context: str = "",
    ) -> dict[str, Any]:
        """Monta o payload JSON para `/chat/completions`."""
        system_prompt = build_system_prompt(
            memory_context=memory_context,
            shortcuts_context=shortcuts_context,
            companion_context=companion_context,
            temporal_context=temporal_context,
            cowork_context=cowork_context,
            skills_context=skills_context,
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        for msg in history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in {"user", "assistant", "system"} and content:
                messages.append({"role": role, "content": content})

        # Garante que a mensagem atual do usuário esteja no final.
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
        shortcuts_context: str = "",
        companion_context: str = "",
        temporal_context: str = "",
        cowork_context: str = "",
        skills_context: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        """Executa o streaming do LLM e emite eventos `emotion`, `delta`, `sentence`, `action` e `result`."""
        if self._stream_fn is not None:
            kwargs: dict[str, Any] = {
                "user_text": user_text,
                "history": history,
                "memory_context": memory_context,
            }
            sig = inspect.signature(self._stream_fn)
            has_var_kw = any(
                param.kind == inspect.Parameter.VAR_KEYWORD
                for param in sig.parameters.values()
            )
            extra_kwargs = {
                "shortcuts_context": shortcuts_context,
                "companion_context": companion_context,
                "temporal_context": temporal_context,
                "cowork_context": cowork_context,
                "skills_context": skills_context,
            }
            for key, value in extra_kwargs.items():
                if has_var_kw or key in sig.parameters:
                    kwargs[key] = value
            async for event in self._stream_fn(**kwargs):
                yield event
            return

        payload = self._build_payload(
            user_text=user_text,
            history=history,
            memory_context=memory_context,
            shortcuts_context=shortcuts_context,
            companion_context=companion_context,
            temporal_context=temporal_context,
            cowork_context=cowork_context,
            skills_context=skills_context,
        )
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
