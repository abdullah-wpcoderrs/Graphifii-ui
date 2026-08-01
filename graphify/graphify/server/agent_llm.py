"""Streaming LLM calls for the agent, and the parser that splits their output.

Two pieces:

  * `stream_completion` — an async generator of raw text deltas from
    OpenAI-compatible or Anthropic streaming endpoints, plus the token usage
    the provider reports at the end. Called over httpx directly rather than
    through graphify/llm.py: that module's call functions are synchronous,
    non-streaming, and read their API key from the process environment,
    while this path needs async streaming with a key decrypted per request.
    Pricing still comes from llm.py via usage.py, so cost accounting stays
    in one place even though the transport does not.

  * `StreamDemultiplexer` — the reason the UI can stream prose and file
    diffs at the same time from a single call. The model is prompted to wrap
    proposed file bodies in explicit markers; this consumes the token stream
    incrementally and routes each fragment to either the message bubble or a
    specific file's editor pane, as it arrives.

The demultiplexer is careful about one thing that is easy to get wrong: a
marker can be split across two chunks ("<<<FI" then "LE: x>>>"). Emitting
eagerly would leak marker fragments into the visible answer, so a suffix
that could still become a marker is held back until the next chunk resolves
it.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger("graphify.server.agent_llm")

_TIMEOUT = httpx.Timeout(120.0, connect=10.0)

FILE_START_PREFIX = "<<<FILE:"
FILE_START_SUFFIX = ">>>"
FILE_END_MARKER = "<<<END FILE>>>"


class AgentLLMError(Exception):
    """The provider call failed in a way the user should be told about."""


@dataclass
class StreamUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class TextDelta:
    text: str


@dataclass
class FileStart:
    path: str


@dataclass
class FileDelta:
    path: str
    text: str


@dataclass
class FileEnd:
    path: str


StreamEvent = TextDelta | FileStart | FileDelta | FileEnd


def _longest_marker_prefix_suffix(buffer: str, marker: str) -> int:
    """Length of the longest buffer-suffix that is a prefix of `marker`.

    That suffix might be the start of a marker whose remainder has not
    arrived yet, so it must not be emitted as visible text.
    """
    limit = min(len(buffer), len(marker) - 1)
    for size in range(limit, 0, -1):
        if buffer.endswith(marker[:size]):
            return size
    return 0


@dataclass
class StreamDemultiplexer:
    """Splits a raw token stream into prose events and per-file content events."""

    _buffer: str = ""
    _current_path: str | None = None
    # True right after a FileStart, until the syntax newline that follows the
    # opening marker has been resolved — set here rather than stripped
    # in-place because that newline can legitimately arrive in the *next*
    # feed() call, after the marker itself already closed.
    _swallow_leading_newline: bool = False
    # Paths in the order the model produced them, for the caller to persist.
    paths: list[str] = field(default_factory=list)

    def feed(self, chunk: str) -> list[StreamEvent]:
        self._buffer += chunk
        return self._drain(final=False)

    def finish(self) -> list[StreamEvent]:
        """Flush whatever is buffered once the provider stops sending.

        A truncated response can leave an unterminated file block; that file
        is still closed so the caller always sees a matching FileEnd and can
        persist what did arrive.
        """
        events = self._drain(final=True)
        if self._buffer:
            events.extend(self._emit(self._buffer, final=True))
            self._buffer = ""
        if self._current_path is not None:
            events.append(FileEnd(path=self._current_path))
            self._current_path = None
        return events

    def _emit(self, text: str, *, final: bool = False) -> list[StreamEvent]:
        if not text:
            return []
        if self._current_path is not None:
            return [FileDelta(path=self._current_path, text=text)]
        return [TextDelta(text=text)]

    def _drain(self, *, final: bool) -> list[StreamEvent]:
        events: list[StreamEvent] = []

        while True:
            if self._current_path is None:
                index = self._buffer.find(FILE_START_PREFIX)
                if index == -1:
                    hold = 0 if final else _longest_marker_prefix_suffix(
                        self._buffer, FILE_START_PREFIX
                    )
                    emit_upto = len(self._buffer) - hold
                    if emit_upto > 0:
                        events.extend(self._emit(self._buffer[:emit_upto]))
                        self._buffer = self._buffer[emit_upto:]
                    return events

                # Everything before the marker is ordinary prose.
                if index > 0:
                    events.extend(self._emit(self._buffer[:index]))
                    self._buffer = self._buffer[index:]

                close = self._buffer.find(FILE_START_SUFFIX, len(FILE_START_PREFIX))
                if close == -1:
                    # The path is still arriving.
                    return events

                path = self._buffer[len(FILE_START_PREFIX) : close].strip()
                self._buffer = self._buffer[close + len(FILE_START_SUFFIX) :]

                if not path:
                    # Malformed marker — treat it as prose rather than
                    # opening a file block with no name.
                    events.append(TextDelta(text=FILE_START_PREFIX + FILE_START_SUFFIX))
                    continue

                self._current_path = path
                # The model reliably puts a newline after the marker; that
                # newline is syntax, not the first line of the file. It may
                # not have arrived yet (the marker just closed at the very
                # end of this buffer), so the swallow is deferred rather
                # than attempted against a buffer that is still empty.
                self._swallow_leading_newline = True
                if path not in self.paths:
                    self.paths.append(path)
                events.append(FileStart(path=path))
                continue

            if self._swallow_leading_newline:
                if self._buffer.startswith("\n"):
                    self._buffer = self._buffer[1:]
                    self._swallow_leading_newline = False
                elif self._buffer:
                    # First body character has arrived and it is not a
                    # newline — nothing to swallow.
                    self._swallow_leading_newline = False
                elif final:
                    self._swallow_leading_newline = False
                else:
                    # Buffer is empty and more may still arrive; wait rather
                    # than guessing.
                    return events

            index = self._buffer.find(FILE_END_MARKER)
            if index == -1:
                if final:
                    hold = 0
                else:
                    # Held back against two patterns, not one: the bare
                    # marker, and the marker with its required preceding
                    # newline. A lone "\n" at the buffer's end is always
                    # ambiguous mid-stream — it might be ordinary content, or
                    # it might be the syntax newline right before
                    # "<<<END FILE>>>", which must never reach the caller.
                    # Holding against the newline-prefixed pattern too is
                    # what keeps that "\n" back until the following
                    # character resolves which case it is.
                    hold = max(
                        _longest_marker_prefix_suffix(self._buffer, FILE_END_MARKER),
                        _longest_marker_prefix_suffix(self._buffer, "\n" + FILE_END_MARKER),
                    )
                emit_upto = len(self._buffer) - hold
                if emit_upto > 0:
                    events.extend(self._emit(self._buffer[:emit_upto]))
                    self._buffer = self._buffer[emit_upto:]
                return events

            body = self._buffer[:index]
            # Drop the newline that precedes the closing marker — it is part
            # of the syntax, not file content. Safe to check directly here:
            # the holdback above guarantees a genuine trailing newline was
            # never flushed out in an earlier chunk.
            if body.endswith("\n"):
                body = body[:-1]
            events.extend(self._emit(body))
            events.append(FileEnd(path=self._current_path))
            self._buffer = self._buffer[index + len(FILE_END_MARKER) :]
            self._current_path = None


async def _stream_openai_compat(
    *, base_url: str, model: str, api_key: str, system: str, messages: list[dict], usage: StreamUsage
) -> AsyncIterator[str]:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, *messages],
        "stream": True,
        # Without this the streaming response carries no usage at all and
        # every agent call would record as costing nothing.
        "stream_options": {"include_usage": True},
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        async with client.stream(
            "POST",
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        ) as response:
            if response.status_code != 200:
                await response.aread()
                raise AgentLLMError(_provider_error_message(response.status_code))

            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    parsed = json.loads(data)
                except json.JSONDecodeError:
                    continue

                if parsed.get("usage"):
                    usage.prompt_tokens = parsed["usage"].get("prompt_tokens", 0)
                    usage.completion_tokens = parsed["usage"].get("completion_tokens", 0)

                for choice in parsed.get("choices", []):
                    text = (choice.get("delta") or {}).get("content")
                    if text:
                        yield text


async def _stream_anthropic(
    *, model: str, api_key: str, system: str, messages: list[dict], usage: StreamUsage
) -> AsyncIterator[str]:
    payload = {
        "model": model,
        "max_tokens": 8192,
        "system": system,
        "messages": messages,
        "stream": True,
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        async with client.stream(
            "POST",
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            json=payload,
        ) as response:
            if response.status_code != 200:
                await response.aread()
                raise AgentLLMError(_provider_error_message(response.status_code))

            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if not data:
                    continue
                try:
                    parsed = json.loads(data)
                except json.JSONDecodeError:
                    continue

                event_type = parsed.get("type")
                if event_type == "message_start":
                    # Anthropic reports input tokens up front and output
                    # tokens in the closing delta — neither alone is enough.
                    usage.prompt_tokens = (
                        parsed.get("message", {}).get("usage", {}).get("input_tokens", 0)
                    )
                elif event_type == "content_block_delta":
                    text = (parsed.get("delta") or {}).get("text")
                    if text:
                        yield text
                elif event_type == "message_delta":
                    usage.completion_tokens = parsed.get("usage", {}).get("output_tokens", 0)


def _provider_error_message(status_code: int) -> str:
    """Translate a provider status into copy that leaks nothing.

    Mirrors routes/admin.py's verify handler: the user gets a cause they can
    act on, never the provider's raw body (which can echo the API key back).
    """
    if status_code in (401, 403):
        return "The configured AI provider key was rejected — an administrator needs to update it."
    if status_code == 429:
        return "The AI provider is rate-limiting requests right now. Try again in a moment."
    if status_code >= 500:
        return "The AI provider is temporarily unavailable. Try again in a moment."
    return f"The AI provider rejected the request ({status_code})."


async def stream_completion(
    *,
    provider: str,
    base_url: str,
    model: str,
    api_key: str,
    system: str,
    messages: list[dict],
    usage: StreamUsage,
) -> AsyncIterator[str]:
    """Yield text deltas from the provider, filling `usage` as it goes.

    `usage` is mutated rather than returned because the caller needs the
    token counts after the generator is exhausted, and an async generator
    cannot return a value to an `async for`.
    """
    try:
        if provider == "anthropic":
            async for chunk in _stream_anthropic(
                model=model, api_key=api_key, system=system, messages=messages, usage=usage
            ):
                yield chunk
        else:
            async for chunk in _stream_openai_compat(
                base_url=base_url,
                model=model,
                api_key=api_key,
                system=system,
                messages=messages,
                usage=usage,
            ):
                yield chunk
    except httpx.HTTPError as exc:
        logger.error("agent stream failed for provider=%s: %s", provider, exc)
        raise AgentLLMError("Could not reach the AI provider. Try again in a moment.") from exc
