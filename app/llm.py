"""Async streaming LLM client and parser for emotion/memory/action tags."""

from __future__ import annotations

import inspect
import json
import logging
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app import speech
from app.config import Settings

logger = logging.getLogger(__name__)

# Official list of the 12 emotions supported by the EMO-style face.
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
    r"^\[action\s*:\s*(shortcut|app|pomodoro|today|task|note|habit|mcp|search)\s*:\s*(.*?)\s*\]$",
    re.IGNORECASE | re.DOTALL,
)
_KNOWN_TAG_PREFIXES: tuple[str, ...] = (
    "[emotion",
    "[fact",
    "[action",
    *(f"[{emotion}" for emotion in SUPPORTED_EMOTIONS),
)

# Safety limit to avoid unbounded buffering when a '[' is never closed.
_MAX_TAG_BUFFER_CHARS = 256


class LLMError(Exception):
    """Safe error raised when talking to the LLM provider (never exposes secrets)."""


def build_system_prompt(
    memory_context: str = "",
    shortcuts_context: str = "",
    companion_context: str = "",
    temporal_context: str = "",
    cowork_context: str = "",
    skills_context: str = "",
    personal_context: str = "",
) -> str:
    """Build the system prompt (in Lupin's current language) with memory, temporal context, mood and Mac actions."""
    emotions_list = ", ".join(SUPPORTED_EMOTIONS)
    sections = [speech.persona_prompt(emotions_list)]

    if temporal_context.strip():
        sections.append(speech.TEMPORAL_SECTION.format(content=temporal_context.strip()))

    if companion_context.strip():
        sections.append(speech.COMPANION_SECTION.format(content=companion_context.strip()))

    if memory_context.strip():
        sections.append(speech.MEMORY_SECTION.format(content=memory_context.strip()))

    if cowork_context.strip():
        sections.append(speech.COWORK_SECTION.format(content=cowork_context.strip()))

    if shortcuts_context.strip():
        sections.append(speech.SHORTCUTS_SECTION.format(content=shortcuts_context.strip()))

    if skills_context.strip():
        sections.append(speech.SKILLS_SECTION.format(content=skills_context.strip()))

    if personal_context.strip():
        sections.append(speech.PERSONAL_SECTION.format(content=personal_context.strip()))

    return "\n\n".join(sections)


@dataclass
class TagStreamParser:
    """Incremental parser that strips `[emotion:...]`, `[fact:...]` and `[action:...]` tags from the stream.

    Guarantees that no internal tag leaks into the `delta`/`sentence` events sent to the frontend/TTS,
    even when the brackets or the tag content arrive split across several chunks.
    """

    emotion_emitted: bool = False
    detected_emotion: str = "neutral"
    _buffer: str = ""
    _sentence_buf: str = ""
    _raw_parts: list[str] = field(default_factory=list)
    _clean_parts: list[str] = field(default_factory=list)
    _has_emitted_text: bool = False

    def feed(self, chunk: str) -> list[dict[str, str]]:
        """Process a `delta.content` chunk and return ready-to-send structured events."""
        if not chunk:
            return []

        self._raw_parts.append(chunk)
        self._buffer += chunk
        events: list[dict[str, str]] = []

        while self._buffer:
            if not self._has_emitted_text and not self._buffer.startswith("["):
                # Drop leading whitespace before the first tag or the first useful text.
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

                # Still waiting for the closing ']' of the tag.
                if len(self._buffer) > _MAX_TAG_BUFFER_CHARS and not self._looks_like_known_tag_prefix(
                    self._buffer
                ):
                    # Does not look like one of our tags; release it as plain text so the stream does not stall.
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
        """Finish the stream, drain the safe remainder of the buffer and return the full result.

        Returns `(final_events, clean_text, raw_text, emotion)`.
        """
        events: list[dict[str, str]] = []

        if self._buffer:
            # If an incomplete `[emotion...`, `[fact...`, `[action...` or `[happy...` tag is left over,
            # discard it so markup never leaks to the user/TTS.
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
        """Check whether the start of the buffer may match a known protocol tag."""
        lower = text.lstrip().lower()
        for prefix in _KNOWN_TAG_PREFIXES:
            if lower.startswith(prefix) or prefix.startswith(lower):
                return True
        return False

    def _handle_closed_tag(self, tag: str) -> list[dict[str, str]]:
        """Interpret a complete `[...]` tag and return the matching events."""
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
            # Fact tags stay only in raw_text, for extraction by the memory layer.
            return []

        action_match = _ACTION_TAG_RE.match(tag)
        if action_match:
            kind = action_match.group(1).strip().lower()
            target = " ".join(action_match.group(2).strip().split())
            if target:
                return [{"type": "action", "kind": kind, "target": target}]
            return []

        # Ordinary brackets that are not control tags become spoken text.
        return self._emit_text(tag)

    def _emit_text(self, text: str) -> list[dict[str, str]]:
        """Emit clean text, guaranteeing an emotion before the first delta, plus any completed sentences."""
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
        """Extract complete sentences ending in `.`, `!` or `?` from the sentence buffer."""
        emitted: list[dict[str, str]] = []
        buf = self._sentence_buf
        start = 0
        i = 0
        length = len(buf)

        while i < length:
            ch = buf[i]
            if ch in ".!?":
                # Keep grouped punctuation (`...`, `!?`, `!!`) together in the same sentence.
                if i + 1 < length and buf[i + 1] in ".!?":
                    i += 1
                    continue
                # Do not split decimals such as `3.14` when the next digit is already in the buffer.
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
                # Include closing quotes/brackets right after the punctuation, if any.
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
    """Async client for OpenAI-compatible streaming chat completions."""

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
        personal_context: str = "",
    ) -> dict[str, Any]:
        """Build the JSON payload for `/chat/completions`."""
        system_prompt = build_system_prompt(
            memory_context=memory_context,
            shortcuts_context=shortcuts_context,
            companion_context=companion_context,
            temporal_context=temporal_context,
            cowork_context=cowork_context,
            skills_context=skills_context,
            personal_context=personal_context,
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        for msg in history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in {"user", "assistant", "system"} and content:
                messages.append({"role": role, "content": content})

        # Make sure the user's current message is last.
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
        """Return the full URL of the chat completions endpoint."""
        return f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"

    def _headers(self) -> dict[str, str]:
        """Build the request HTTP headers without logging secrets."""
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
        personal_context: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream the LLM response and emit `emotion`, `delta`, `sentence`, `action` and `result` events."""
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
                "personal_context": personal_context,
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
            personal_context=personal_context,
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
                        "LLM provider HTTP error: status=%s model=%s",
                        response.status_code,
                        self.settings.llm_model,
                    )
                    raise LLMError("Failed to query the LLM model.")

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
                        logger.warning("Ignored an invalid SSE line from the LLM stream.")
                        continue

                    choices = chunk_data.get("choices") or []
                    if not choices:
                        continue

                    delta = choices[0].get("delta") or {}
                    # Local API quirk: reasoning tokens arrive in `delta.reasoning`
                    # before `delta.content` and must NEVER reach the user or TTS.
                    content = delta.get("content")
                    if not content:
                        continue

                    for event in parser.feed(content):
                        yield event

            tail_events, clean_text, raw_text, emotion = parser.finish()
            for event in tail_events:
                yield event

            logger.info(
                "LLM response finished: model=%s emotion=%s length_chars=%d",
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
                "Network error calling the LLM (%s) model=%s",
                type(exc).__name__,
                self.settings.llm_model,
            )
            raise LLMError("Could not connect to the LLM model.") from exc
        finally:
            if own_client:
                await client.aclose()
