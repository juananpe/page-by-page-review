"""Provider layer: Anthropic Messages API, any OpenAI-compatible /chat/completions, or a mock.

Both real providers are called over plain HTTP with httpx, so the only
dependency is httpx and switching provider is an .env change.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import random
import re
from dataclasses import dataclass

import httpx


class LLMError(RuntimeError):
    """Raised with a message safe to show in the UI."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
        )


@dataclass
class Reply:
    data: dict
    usage: Usage
    raw: str


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name) or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name) or default)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    v = _env(name).lower()
    if not v:
        return default
    return v in {"1", "true", "yes", "on"}


def _parse_json(text: str) -> dict:
    """Models sometimes wrap JSON in fences or add a sentence. Recover what we can."""
    s = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", s, re.S)
    if fence:
        s = fence.group(1).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(s[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise LLMError("Model did not return usable JSON: " + s[:200])


class Provider:
    name = "provider"
    model = ""

    async def complete_json(
        self, system: str, user_text: str, image_jpeg: bytes | None = None
    ) -> Reply:
        raise NotImplementedError

    async def close(self) -> None:
        pass

    # shared retry wrapper for transient failures
    async def _with_retries(self, call, attempts: int = 3):
        delay = 1.5
        last: Exception | None = None
        for i in range(attempts):
            try:
                return await call()
            except LLMError:
                raise
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in (408, 409, 429) or status >= 500:
                    last = exc
                else:
                    raise LLMError(_http_message(exc)) from exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = exc
            if i < attempts - 1:
                await asyncio.sleep(delay + random.random())
                delay *= 2
        if isinstance(last, httpx.HTTPStatusError):
            raise LLMError(_http_message(last)) from last
        raise LLMError(f"Request failed after {attempts} attempts: {last}") from last


def _http_message(exc: httpx.HTTPStatusError) -> str:
    body = exc.response.text[:400]
    try:
        payload = exc.response.json()
        body = (
            payload.get("error", {}).get("message")
            or payload.get("message")
            or json.dumps(payload)[:400]
        )
    except Exception:
        pass
    return f"HTTP {exc.response.status_code} from provider: {body}"


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self) -> None:
        key = _env("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("ANTHROPIC_API_KEY is not set in .env")
        self.model = _env("MODEL", "claude-sonnet-4-6")
        self.max_tokens = _env_int("MAX_OUTPUT_TOKENS", 2000)
        self.temperature = _env_float("TEMPERATURE", 0.0)
        base = _env("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
        self.client = httpx.AsyncClient(
            base_url=base,
            timeout=httpx.Timeout(_env_int("REQUEST_TIMEOUT", 180)),
            headers={
                "x-api-key": key,
                "anthropic-version": _env("ANTHROPIC_VERSION", "2023-06-01"),
                "content-type": "application/json",
            },
        )

    async def complete_json(self, system, user_text, image_jpeg=None) -> Reply:
        content: list[dict] = []
        if image_jpeg:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64.b64encode(image_jpeg).decode(),
                    },
                }
            )
        content.append({"type": "text", "text": user_text})

        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": system,
            "messages": [{"role": "user", "content": content}],
        }

        async def call():
            r = await self.client.post("/v1/messages", json=body)
            r.raise_for_status()
            return r.json()

        payload = await self._with_retries(call)
        text = "".join(
            b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text"
        )
        u = payload.get("usage", {}) or {}
        usage = Usage(
            int(u.get("input_tokens", 0) or 0)
            + int(u.get("cache_read_input_tokens", 0) or 0)
            + int(u.get("cache_creation_input_tokens", 0) or 0),
            int(u.get("output_tokens", 0) or 0),
        )
        return Reply(_parse_json(text), usage, text)

    async def close(self) -> None:
        await self.client.aclose()


class OpenAIProvider(Provider):
    """Works with OpenAI, OpenRouter, Together, vLLM, LM Studio, Ollama, ..."""

    name = "openai"

    def __init__(self) -> None:
        key = _env("OPENAI_API_KEY")
        base = _env("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        # Local servers often need no key; hosted ones do.
        if not key and "localhost" not in base and "127.0.0.1" not in base:
            raise LLMError("OPENAI_API_KEY is not set in .env")
        self.model = _env("MODEL", "gpt-4.1-mini")
        self.max_tokens = _env_int("MAX_OUTPUT_TOKENS", 2000)
        self.temperature = _env_float("TEMPERATURE", 0.0)
        self.json_mode = _env_bool("OPENAI_JSON_MODE", True)
        self.client = httpx.AsyncClient(
            base_url=base,
            timeout=httpx.Timeout(_env_int("REQUEST_TIMEOUT", 180)),
            headers={
                "authorization": f"Bearer {key or 'not-needed'}",
                "content-type": "application/json",
            },
        )

    async def complete_json(self, system, user_text, image_jpeg=None) -> Reply:
        content: list[dict] = [{"type": "text", "text": user_text}]
        if image_jpeg:
            url = "data:image/jpeg;base64," + base64.b64encode(image_jpeg).decode()
            content.append({"type": "image_url", "image_url": {"url": url, "detail": "high"}})

        def build(json_mode: bool) -> dict:
            body = {
                "model": self.model,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": content},
                ],
            }
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            return body

        async def call(json_mode: bool):
            r = await self.client.post("/chat/completions", json=build(json_mode))
            r.raise_for_status()
            return r.json()

        try:
            payload = await self._with_retries(lambda: call(self.json_mode))
        except LLMError as exc:
            # Some compatible servers reject response_format or max_tokens; try plainly once.
            if self.json_mode and "400" in str(exc):
                self.json_mode = False
                payload = await self._with_retries(lambda: call(False))
            else:
                raise

        choices = payload.get("choices") or []
        if not choices:
            raise LLMError("Provider returned no choices")
        text = (choices[0].get("message") or {}).get("content") or ""
        if isinstance(text, list):  # a few servers return content parts
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
        u = payload.get("usage", {}) or {}
        usage = Usage(
            int(u.get("prompt_tokens", 0) or 0), int(u.get("completion_tokens", 0) or 0)
        )
        return Reply(_parse_json(text), usage, text)

    async def close(self) -> None:
        await self.client.aclose()


class MockProvider(Provider):
    """No network, no key. For checking the pipeline and the UI end to end."""

    name = "mock"

    def __init__(self) -> None:
        self.model = "mock"

    async def complete_json(self, system, user_text, image_jpeg=None) -> Reply:
        await asyncio.sleep(0.3 + random.random() * 0.5)
        if "cross-page" in user_text or "<review>" in user_text:
            return Reply(
                {
                    "findings": [
                        {
                            "severity": "warning",
                            "pages": [1, 2],
                            "text": "Mock cross-page finding. Set PROVIDER to anthropic or openai for a real review.",
                        }
                    ]
                },
                Usage(900, 60),
                "",
            )
        m = re.search(r"Page (\d+) of (\d+)", user_text)
        n = int(m.group(1)) if m else 1
        snippet = ""
        block = re.search(r"<page_text>\n(.+?)\n</page_text>", user_text, re.S)
        if block:
            snippet = " ".join(block.group(1).split())[:160]
        pool = [
            {"severity": "error", "text": "Mock error: a number here would be recomputed by a real model."},
            {"severity": "warning", "text": "Mock warning: a claim here would be checked against the evidence."},
            {"severity": "note", "text": "Mock note: presentation could be tightened."},
            {"severity": "ok", "text": "Mock check: arithmetic on this page reproduces."},
        ]
        k = n % 4
        return Reply(
            {
                "gist": f"Mock review of page {n}",
                "section": f"page {n}",
                "summary": (
                    "This is mock output, produced without calling any model. "
                    + (f"The page begins: {snippet}\u2026" if snippet else "This page has no text layer.")
                ),
                "findings": pool[k : k + 2] or pool[:1],
            },
            Usage(1200, 180),
            "",
        )


def build_provider() -> Provider:
    kind = _env("PROVIDER", "anthropic").lower()
    if kind == "anthropic":
        return AnthropicProvider()
    if kind in {"openai", "openai-compatible", "compatible"}:
        return OpenAIProvider()
    if kind == "mock":
        return MockProvider()
    raise LLMError(f"Unknown PROVIDER '{kind}'. Use anthropic, openai or mock.")
