"""
Multi-LLM Backend — Deep Test Suite
Run: pytest test_backend_deep.py -v --tb=short

Covers:
  - Client unit tests (all 3 providers, all failure modes)
  - Payload structure validation (exact API shapes)
  - Parallel execution guarantees (concurrency, ordering, isolation)
  - Edge cases (unicode, empty strings, max length, special chars)
  - Timeout & retry behaviour
  - API endpoint contract (schema, status codes, headers)
  - Partial failure scenarios (1-down, 2-down, all-down)
  - Stress: rapid sequential + concurrent requests
  - Security: prompt injection passthrough (backend is dumb — Heimdall filters)
  - Response field types and ranges
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from unittest.mock import AsyncMock, patch, call as mock_call

import httpx
import pytest
from httpx import AsyncClient, ASGITransport

# ── Patch env before importing app ────────────────────────────────────────────
os.environ["GEMINI_API_KEY"]  = "test_gemini_key"
os.environ["GROQ_API_KEY"]    = "test_groq_key"
os.environ["MISTRAL_API_KEY"] = "test_mistral_key"

from clients import (
    call_gemini, call_groq, call_mistral,
    call_all_parallel, call_primary_with_fallback,
    LLMResponse, GEMINI_MODEL, GROQ_MODEL, MISTRAL_MODEL,
    GEMINI_URL, GROQ_URL, MISTRAL_URL,
)
from main import app


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _req(url: str = "https://mock.api/") -> httpx.Request:
    return httpx.Request("POST", url)

def _resp(status: int, body: dict, url: str = "https://mock.api/") -> httpx.Response:
    return httpx.Response(
        status_code=status,
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        request=_req(url),
    )

def _gemini_body(text: str = "hello", tokens: int = 10) -> dict:
    return {
        "candidates": [{"content": {"parts": [{"text": text}]}}],
        "usageMetadata": {"totalTokenCount": tokens},
    }

def _openai_body(text: str = "hello", tokens: int = 10) -> dict:
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"total_tokens": tokens},
    }

def _ok(provider: str, text: str = "ok", latency: float = 50.0) -> LLMResponse:
    return LLMResponse(provider=provider, text=text, ok=True,
                       model="test-model", latency_ms=latency, tokens_used=10)

def _fail(provider: str, error: str = "timeout") -> LLMResponse:
    return LLMResponse(provider=provider, ok=False, error=error, latency_ms=100.0)

async def _post(payload: dict) -> httpx.Response:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        return await ac.post("/query", json=payload)

async def _get(path: str) -> httpx.Response:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        return await ac.get(path)


# ══════════════════════════════════════════════════════════════════════════════
# 1. CONSTANTS & MODEL NAMES
# ══════════════════════════════════════════════════════════════════════════════

class TestConstants:
    def test_gemini_model_name(self):
        assert GEMINI_MODEL == "gemini-2.0-flash-exp"

    def test_groq_model_name(self):
        assert GROQ_MODEL == "llama-3.1-8b-instant"

    def test_mistral_model_name(self):
        assert MISTRAL_MODEL == "mistral-small-latest"

    def test_gemini_url_contains_model(self):
        assert GEMINI_MODEL in GEMINI_URL

    def test_groq_url_is_openai_compat(self):
        assert "openai" in GROQ_URL

    def test_mistral_url(self):
        assert "mistral.ai" in MISTRAL_URL


# ══════════════════════════════════════════════════════════════════════════════
# 2. GEMINI CLIENT — DEEP
# ══════════════════════════════════════════════════════════════════════════════

class TestGeminiDeep:

    @pytest.mark.asyncio
    async def test_success_full_fields(self):
        mock = _resp(200, _gemini_body("Deep answer", 99))
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock):
            r = await call_gemini("Hi", None, "key")
        assert r.ok
        assert r.text == "Deep answer"
        assert r.tokens_used == 99
        assert r.provider == "gemini"
        assert r.model == GEMINI_MODEL
        assert r.latency_ms > 0
        assert r.error == ""

    @pytest.mark.asyncio
    async def test_api_key_sent_as_query_param(self):
        mock = _resp(200, _gemini_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock) as m:
            await call_gemini("Hi", None, "SECRET_KEY_123")
        _, kwargs = m.call_args
        params = kwargs.get("params", {})
        assert params.get("key") == "SECRET_KEY_123"

    @pytest.mark.asyncio
    async def test_api_key_not_in_json_body(self):
        mock = _resp(200, _gemini_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock) as m:
            await call_gemini("Hi", None, "SECRET_KEY_123")
        _, kwargs = m.call_args
        payload = kwargs.get("json", {})
        assert "SECRET_KEY_123" not in json.dumps(payload)

    @pytest.mark.asyncio
    async def test_prompt_in_contents(self):
        mock = _resp(200, _gemini_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock) as m:
            await call_gemini("Tell me a joke", None, "key")
        _, kwargs = m.call_args
        payload = kwargs["json"]
        parts = payload["contents"][0]["parts"]
        assert any("Tell me a joke" in p.get("text", "") for p in parts)

    @pytest.mark.asyncio
    async def test_system_prompt_in_system_instruction(self):
        mock = _resp(200, _gemini_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock) as m:
            await call_gemini("Hi", "Be a pirate.", "key")
        _, kwargs = m.call_args
        payload = kwargs["json"]
        assert "systemInstruction" in payload
        assert "pirate" in json.dumps(payload["systemInstruction"])

    @pytest.mark.asyncio
    async def test_no_system_prompt_omits_system_instruction(self):
        mock = _resp(200, _gemini_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock) as m:
            await call_gemini("Hi", None, "key")
        _, kwargs = m.call_args
        payload = kwargs["json"]
        assert "systemInstruction" not in payload

    @pytest.mark.asyncio
    async def test_max_tokens_in_generation_config(self):
        mock = _resp(200, _gemini_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock) as m:
            await call_gemini("Hi", None, "key", max_tokens=500)
        _, kwargs = m.call_args
        payload = kwargs["json"]
        assert payload["generationConfig"]["maxOutputTokens"] == 500

    @pytest.mark.asyncio
    async def test_empty_candidates_returns_error(self):
        mock = _resp(200, {"candidates": [], "usageMetadata": {}})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock):
            r = await call_gemini("Hi", None, "key")
        assert not r.ok
        assert "candidates" in r.error.lower() or "no" in r.error.lower()

    @pytest.mark.asyncio
    async def test_missing_candidates_key(self):
        mock = _resp(200, {"usageMetadata": {}})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock):
            r = await call_gemini("Hi", None, "key")
        assert not r.ok

    @pytest.mark.asyncio
    async def test_multipart_text_joined(self):
        body = {
            "candidates": [{"content": {"parts": [
                {"text": "Hello "},
                {"text": "World"},
            ]}}],
            "usageMetadata": {"totalTokenCount": 5},
        }
        mock = _resp(200, body)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock):
            r = await call_gemini("Hi", None, "key")
        assert "Hello" in r.text
        assert "World" in r.text

    @pytest.mark.asyncio
    async def test_rate_limit_429(self):
        mock = _resp(429, {"error": {"message": "RATE_LIMIT_EXCEEDED"}})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock):
            r = await call_gemini("Hi", None, "key")
        assert not r.ok
        assert "429" in r.error

    @pytest.mark.asyncio
    async def test_unauthorized_401(self):
        mock = _resp(401, {"error": {"message": "API_KEY_INVALID"}})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock):
            r = await call_gemini("Hi", None, "bad_key")
        assert not r.ok
        assert "401" in r.error

    @pytest.mark.asyncio
    async def test_server_error_500(self):
        mock = _resp(500, {"error": "Internal Server Error"})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock):
            r = await call_gemini("Hi", None, "key")
        assert not r.ok
        assert "500" in r.error

    @pytest.mark.asyncio
    async def test_network_error(self):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   side_effect=httpx.ConnectError("connection refused")):
            r = await call_gemini("Hi", None, "key")
        assert not r.ok
        assert r.error != ""

    @pytest.mark.asyncio
    async def test_latency_recorded(self):
        mock = _resp(200, _gemini_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock):
            r = await call_gemini("Hi", None, "key")
        assert r.latency_ms >= 0
        assert r.latency_ms < 10_000   # sanity: under 10 seconds in test

    @pytest.mark.asyncio
    async def test_empty_api_key(self):
        r = await call_gemini("Hi", None, "")
        assert not r.ok
        assert r.provider == "gemini"

    @pytest.mark.asyncio
    async def test_unicode_prompt(self):
        mock = _resp(200, _gemini_body("こんにちは"))
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock) as m:
            r = await call_gemini("教えてください 🌍", None, "key")
        assert r.ok
        _, kwargs = m.call_args
        # Check the raw dict (not json.dumps — that escapes unicode by default)
        payload = kwargs["json"]
        prompt_text = payload["contents"][0]["parts"][0]["text"]
        assert "教えてください" in prompt_text

    @pytest.mark.asyncio
    async def test_zero_token_usage_ok(self):
        mock = _resp(200, {"candidates": [{"content": {"parts": [{"text": "hi"}]}}],
                           "usageMetadata": {}})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock):
            r = await call_gemini("Hi", None, "key")
        assert r.ok
        assert r.tokens_used == 0


# ══════════════════════════════════════════════════════════════════════════════
# 3. GROQ CLIENT — DEEP
# ══════════════════════════════════════════════════════════════════════════════

class TestGroqDeep:

    @pytest.mark.asyncio
    async def test_success_full_fields(self):
        mock = _resp(200, _openai_body("Groq says hi", 55))
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock):
            r = await call_groq("Hi", None, "key")
        assert r.ok
        assert r.text == "Groq says hi"
        assert r.tokens_used == 55
        assert r.provider == "groq"
        assert r.model == GROQ_MODEL
        assert r.error == ""

    @pytest.mark.asyncio
    async def test_bearer_auth_header(self):
        mock = _resp(200, _openai_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock) as m:
            await call_groq("Hi", None, "MY_GROQ_KEY")
        _, kwargs = m.call_args
        headers = kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer MY_GROQ_KEY"

    @pytest.mark.asyncio
    async def test_system_message_prepended(self):
        mock = _resp(200, _openai_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock) as m:
            await call_groq("User msg", "System msg", "key")
        _, kwargs = m.call_args
        messages = kwargs["json"]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "System msg"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "User msg"

    @pytest.mark.asyncio
    async def test_no_system_only_user_message(self):
        mock = _resp(200, _openai_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock) as m:
            await call_groq("Hello", None, "key")
        _, kwargs = m.call_args
        messages = kwargs["json"]["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_model_in_payload(self):
        mock = _resp(200, _openai_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock) as m:
            await call_groq("Hi", None, "key")
        _, kwargs = m.call_args
        assert kwargs["json"]["model"] == GROQ_MODEL

    @pytest.mark.asyncio
    async def test_max_tokens_in_payload(self):
        mock = _resp(200, _openai_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock) as m:
            await call_groq("Hi", None, "key", max_tokens=750)
        _, kwargs = m.call_args
        assert kwargs["json"]["max_tokens"] == 750

    @pytest.mark.asyncio
    async def test_rate_limit_429(self):
        mock = _resp(429, {"error": {"message": "rate_limit_exceeded"}})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock):
            r = await call_groq("Hi", None, "key")
        assert not r.ok

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   side_effect=httpx.TimeoutException("read timeout")):
            r = await call_groq("Hi", None, "key")
        assert not r.ok
        assert r.error == "timeout"

    @pytest.mark.asyncio
    async def test_network_error(self):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   side_effect=httpx.ConnectError("refused")):
            r = await call_groq("Hi", None, "key")
        assert not r.ok

    @pytest.mark.asyncio
    async def test_empty_key(self):
        r = await call_groq("Hi", None, "")
        assert not r.ok
        assert r.provider == "groq"

    @pytest.mark.asyncio
    async def test_long_response_text(self):
        long_text = "word " * 500
        mock = _resp(200, _openai_body(long_text))
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock):
            r = await call_groq("Hi", None, "key")
        assert r.ok
        assert len(r.text) > 100


# ══════════════════════════════════════════════════════════════════════════════
# 4. MISTRAL CLIENT — DEEP
# ══════════════════════════════════════════════════════════════════════════════

class TestMistralDeep:

    @pytest.mark.asyncio
    async def test_success_full_fields(self):
        mock = _resp(200, _openai_body("Mistral here", 77))
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock):
            r = await call_mistral("Hi", None, "key")
        assert r.ok
        assert r.text == "Mistral here"
        assert r.tokens_used == 77
        assert r.provider == "mistral"
        assert r.model == MISTRAL_MODEL

    @pytest.mark.asyncio
    async def test_bearer_auth_header(self):
        mock = _resp(200, _openai_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock) as m:
            await call_mistral("Hi", None, "MY_MISTRAL_KEY")
        _, kwargs = m.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer MY_MISTRAL_KEY"

    @pytest.mark.asyncio
    async def test_system_message_prepended(self):
        mock = _resp(200, _openai_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock) as m:
            await call_mistral("User msg", "System msg", "key")
        _, kwargs = m.call_args
        messages = kwargs["json"]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_model_in_payload(self):
        mock = _resp(200, _openai_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock) as m:
            await call_mistral("Hi", None, "key")
        _, kwargs = m.call_args
        assert kwargs["json"]["model"] == MISTRAL_MODEL

    @pytest.mark.asyncio
    async def test_timeout(self):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   side_effect=httpx.TimeoutException("timeout")):
            r = await call_mistral("Hi", None, "key")
        assert not r.ok
        assert r.error == "timeout"

    @pytest.mark.asyncio
    async def test_empty_key(self):
        r = await call_mistral("Hi", None, "")
        assert not r.ok

    @pytest.mark.asyncio
    async def test_whitespace_stripped_from_response(self):
        mock = _resp(200, _openai_body("  response with whitespace  "))
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock):
            r = await call_mistral("Hi", None, "key")
        assert r.ok
        assert r.text == "response with whitespace"


# ══════════════════════════════════════════════════════════════════════════════
# 5. PARALLEL CALLER — DEEP
# ══════════════════════════════════════════════════════════════════════════════

class TestParallelCallerDeep:

    @pytest.mark.asyncio
    async def test_all_three_called_once(self):
        with patch("clients.call_gemini",  new_callable=AsyncMock, return_value=_ok("gemini")) as mg, \
             patch("clients.call_groq",    new_callable=AsyncMock, return_value=_ok("groq"))   as mq, \
             patch("clients.call_mistral", new_callable=AsyncMock, return_value=_ok("mistral")) as mm:
            await call_all_parallel("test", None, "g", "q", "m")
        assert mg.call_count == 1
        assert mq.call_count == 1
        assert mm.call_count == 1

    @pytest.mark.asyncio
    async def test_prompt_passed_to_all(self):
        with patch("clients.call_gemini",  new_callable=AsyncMock, return_value=_ok("gemini")) as mg, \
             patch("clients.call_groq",    new_callable=AsyncMock, return_value=_ok("groq"))   as mq, \
             patch("clients.call_mistral", new_callable=AsyncMock, return_value=_ok("mistral")) as mm:
            await call_all_parallel("SPECIAL PROMPT", None, "g", "q", "m")
        assert mg.call_args[0][0] == "SPECIAL PROMPT"
        assert mq.call_args[0][0] == "SPECIAL PROMPT"
        assert mm.call_args[0][0] == "SPECIAL PROMPT"

    @pytest.mark.asyncio
    async def test_system_passed_to_all(self):
        with patch("clients.call_gemini",  new_callable=AsyncMock, return_value=_ok("gemini")) as mg, \
             patch("clients.call_groq",    new_callable=AsyncMock, return_value=_ok("groq"))   as mq, \
             patch("clients.call_mistral", new_callable=AsyncMock, return_value=_ok("mistral")) as mm:
            await call_all_parallel("p", "SYSTEM MSG", "g", "q", "m")
        assert mg.call_args[0][1] == "SYSTEM MSG"
        assert mq.call_args[0][1] == "SYSTEM MSG"
        assert mm.call_args[0][1] == "SYSTEM MSG"

    @pytest.mark.asyncio
    async def test_correct_api_keys_routed(self):
        with patch("clients.call_gemini",  new_callable=AsyncMock, return_value=_ok("gemini")) as mg, \
             patch("clients.call_groq",    new_callable=AsyncMock, return_value=_ok("groq"))   as mq, \
             patch("clients.call_mistral", new_callable=AsyncMock, return_value=_ok("mistral")) as mm:
            await call_all_parallel("p", None, "GKEY", "QKEY", "MKEY")
        assert mg.call_args[0][2] == "GKEY"
        assert mq.call_args[0][2] == "QKEY"
        assert mm.call_args[0][2] == "MKEY"

    @pytest.mark.asyncio
    async def test_dict_keys_are_provider_names(self):
        with patch("clients.call_gemini",  new_callable=AsyncMock, return_value=_ok("gemini")), \
             patch("clients.call_groq",    new_callable=AsyncMock, return_value=_ok("groq")), \
             patch("clients.call_mistral", new_callable=AsyncMock, return_value=_ok("mistral")):
            results = await call_all_parallel("p", None, "g", "q", "m")
        assert set(results.keys()) == {"gemini", "groq", "mistral"}

    @pytest.mark.asyncio
    async def test_two_down_one_up(self):
        with patch("clients.call_gemini",  new_callable=AsyncMock, return_value=_fail("gemini")), \
             patch("clients.call_groq",    new_callable=AsyncMock, return_value=_fail("groq")), \
             patch("clients.call_mistral", new_callable=AsyncMock, return_value=_ok("mistral", "only one")):
            results = await call_all_parallel("p", None, "g", "q", "m")
        assert not results["gemini"].ok
        assert not results["groq"].ok
        assert results["mistral"].ok
        assert results["mistral"].text == "only one"

    @pytest.mark.asyncio
    async def test_all_down_no_exception(self):
        with patch("clients.call_gemini",  new_callable=AsyncMock, return_value=_fail("gemini")), \
             patch("clients.call_groq",    new_callable=AsyncMock, return_value=_fail("groq")), \
             patch("clients.call_mistral", new_callable=AsyncMock, return_value=_fail("mistral")):
            results = await call_all_parallel("p", None, "", "", "")
        # Must return dict, never raise
        assert isinstance(results, dict)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_independent_errors_dont_affect_others(self):
        with patch("clients.call_gemini",  new_callable=AsyncMock,
                   return_value=_fail("gemini", "rate_limit")), \
             patch("clients.call_groq",    new_callable=AsyncMock,
                   return_value=_ok("groq", "groq works")), \
             patch("clients.call_mistral", new_callable=AsyncMock,
                   return_value=_fail("mistral", "timeout")):
            results = await call_all_parallel("p", None, "g", "q", "m")
        assert results["gemini"].error == "rate_limit"
        assert results["groq"].text == "groq works"
        assert results["mistral"].error == "timeout"

    @pytest.mark.asyncio
    async def test_max_tokens_forwarded(self):
        with patch("clients.call_gemini",  new_callable=AsyncMock, return_value=_ok("gemini")) as mg, \
             patch("clients.call_groq",    new_callable=AsyncMock, return_value=_ok("groq"))   as mq, \
             patch("clients.call_mistral", new_callable=AsyncMock, return_value=_ok("mistral")) as mm:
            await call_all_parallel("p", None, "g", "q", "m", max_tokens=333)
        assert mg.call_args[0][3] == 333
        assert mq.call_args[0][3] == 333
        assert mm.call_args[0][3] == 333

    @pytest.mark.asyncio
    async def test_concurrent_calls_run_faster_than_sequential(self):
        """
        Each mock takes 0.05s. Sequential would be 0.15s+.
        Parallel should finish in ~0.05–0.10s.
        """
        async def slow_gemini(*a, **kw):
            await asyncio.sleep(0.05)
            return _ok("gemini")

        async def slow_groq(*a, **kw):
            await asyncio.sleep(0.05)
            return _ok("groq")

        async def slow_mistral(*a, **kw):
            await asyncio.sleep(0.05)
            return _ok("mistral")

        with patch("clients.call_gemini",  side_effect=slow_gemini), \
             patch("clients.call_groq",    side_effect=slow_groq), \
             patch("clients.call_mistral", side_effect=slow_mistral):
            t0 = time.perf_counter()
            results = await call_all_parallel("p", None, "g", "q", "m")
            elapsed = time.perf_counter() - t0

        assert all(r.ok for r in results.values())
        assert elapsed < 0.12, f"Expected parallel ~0.05s, got {elapsed:.3f}s"


# ══════════════════════════════════════════════════════════════════════════════
# 6. FALLBACK CHAIN
# ══════════════════════════════════════════════════════════════════════════════

class TestFallbackChain:

    @pytest.mark.asyncio
    async def test_groq_first_success(self):
        async def groq_ok(*a, **kw):    return _ok("groq", "groq first")
        async def gemini_ok(*a, **kw):  return _ok("gemini", "gemini")
        async def mistral_ok(*a, **kw): return _ok("mistral", "mistral")
        with patch("clients.call_groq",    side_effect=groq_ok), \
             patch("clients.call_gemini",  side_effect=gemini_ok), \
             patch("clients.call_mistral", side_effect=mistral_ok):
            r = await call_primary_with_fallback("p", None, "g", "q", "m")
        assert r.text == "groq first"

    @pytest.mark.asyncio
    async def test_groq_fails_gemini_used(self):
        async def groq_fail(*a, **kw):    return _fail("groq")
        async def gemini_ok(*a, **kw):    return _ok("gemini", "gemini fallback")
        async def mistral_ok(*a, **kw):   return _ok("mistral")
        with patch("clients.call_groq",    side_effect=groq_fail), \
             patch("clients.call_gemini",  side_effect=gemini_ok), \
             patch("clients.call_mistral", side_effect=mistral_ok):
            r = await call_primary_with_fallback("p", None, "g", "q", "m")
        assert r.text == "gemini fallback"

    @pytest.mark.asyncio
    async def test_groq_gemini_fail_mistral_used(self):
        async def groq_fail(*a, **kw):    return _fail("groq")
        async def gemini_fail(*a, **kw):  return _fail("gemini")
        async def mistral_ok(*a, **kw):   return _ok("mistral", "last resort")
        with patch("clients.call_groq",    side_effect=groq_fail), \
             patch("clients.call_gemini",  side_effect=gemini_fail), \
             patch("clients.call_mistral", side_effect=mistral_ok):
            r = await call_primary_with_fallback("p", None, "g", "q", "m")
        assert r.text == "last resort"

    @pytest.mark.asyncio
    async def test_all_fail_returns_last_error(self):
        async def groq_fail(*a, **kw):    return _fail("groq",    "e1")
        async def gemini_fail(*a, **kw):  return _fail("gemini",  "e2")
        async def mistral_fail(*a, **kw): return _fail("mistral", "e3")
        with patch("clients.call_groq",    side_effect=groq_fail), \
             patch("clients.call_gemini",  side_effect=gemini_fail), \
             patch("clients.call_mistral", side_effect=mistral_fail):
            r = await call_primary_with_fallback("p", None, "g", "q", "m")
        assert not r.ok
        assert r.error == "e3"   # last in chain


# ══════════════════════════════════════════════════════════════════════════════
# 7. API — POST /query  CONTRACT
# ══════════════════════════════════════════════════════════════════════════════

class TestQueryEndpointContract:

    @pytest.mark.asyncio
    async def test_status_200_on_success(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            r = await _post({"prompt": "Hello"})
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_status_200_even_all_providers_fail(self):
        """Partial / total provider failure is NOT a 500."""
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _fail("gemini"), "groq": _fail("groq"), "mistral": _fail("mistral")}):
            r = await _post({"prompt": "Hello"})
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_response_has_all_provider_keys(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            r = await _post({"prompt": "Hi"})
        data = r.json()
        assert "gemini"  in data
        assert "groq"    in data
        assert "mistral" in data

    @pytest.mark.asyncio
    async def test_each_provider_has_required_fields(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            r = await _post({"prompt": "Hi"})
        data = r.json()
        for p in ["gemini", "groq", "mistral"]:
            assert "text"        in data[p], f"{p} missing text"
            assert "ok"          in data[p], f"{p} missing ok"
            assert "error"       in data[p], f"{p} missing error"
            assert "latency_ms"  in data[p], f"{p} missing latency_ms"
            assert "model"       in data[p], f"{p} missing model"
            assert "tokens_used" in data[p], f"{p} missing tokens_used"

    @pytest.mark.asyncio
    async def test_ok_field_is_bool(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            r = await _post({"prompt": "Hi"})
        data = r.json()
        for p in ["gemini", "groq", "mistral"]:
            assert isinstance(data[p]["ok"], bool)

    @pytest.mark.asyncio
    async def test_latency_ms_is_float(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            r = await _post({"prompt": "Hi"})
        data = r.json()
        assert isinstance(data["latency_ms"], float)
        for p in ["gemini", "groq", "mistral"]:
            assert isinstance(data[p]["latency_ms"], float)

    @pytest.mark.asyncio
    async def test_tokens_used_is_int(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            r = await _post({"prompt": "Hi"})
        data = r.json()
        for p in ["gemini", "groq", "mistral"]:
            assert isinstance(data[p]["tokens_used"], int)

    @pytest.mark.asyncio
    async def test_session_id_echoed(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            r = await _post({"prompt": "Hi", "session_id": "abc-123"})
        assert r.json()["session_id"] == "abc-123"

    @pytest.mark.asyncio
    async def test_no_session_id_is_null(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            r = await _post({"prompt": "Hi"})
        assert r.json()["session_id"] is None

    @pytest.mark.asyncio
    async def test_custom_system_forwarded(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}) as m:
            await _post({"prompt": "Hi", "system": "Be concise."})
        _, kwargs = m.call_args
        assert kwargs["system"] == "Be concise."

    @pytest.mark.asyncio
    async def test_default_system_used_when_none(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}) as m:
            await _post({"prompt": "Hi"})
        _, kwargs = m.call_args
        assert kwargs["system"] is not None
        assert len(kwargs["system"]) > 0

    @pytest.mark.asyncio
    async def test_max_tokens_forwarded(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}) as m:
            await _post({"prompt": "Hi", "max_tokens": 250})
        _, kwargs = m.call_args
        assert kwargs["max_tokens"] == 250

    @pytest.mark.asyncio
    async def test_wall_latency_gte_zero(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            r = await _post({"prompt": "Hi"})
        assert r.json()["latency_ms"] >= 0


# ══════════════════════════════════════════════════════════════════════════════
# 8. API — INPUT VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

class TestInputValidation:

    @pytest.mark.asyncio
    async def test_empty_prompt_422(self):
        r = await _post({"prompt": ""})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_prompt_too_long_422(self):
        r = await _post({"prompt": "x" * 4097})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_prompt_max_length_ok(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            r = await _post({"prompt": "x" * 4096})
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_prompt_min_length_one_ok(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            r = await _post({"prompt": "x"})
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_missing_prompt_422(self):
        r = await _post({"session_id": "abc"})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_max_tokens_below_50_422(self):
        r = await _post({"prompt": "Hi", "max_tokens": 10})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_max_tokens_above_4000_422(self):
        r = await _post({"prompt": "Hi", "max_tokens": 5000})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_max_tokens_boundary_50_ok(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            r = await _post({"prompt": "Hi", "max_tokens": 50})
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_max_tokens_boundary_4000_ok(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            r = await _post({"prompt": "Hi", "max_tokens": 4000})
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_unicode_prompt_ok(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            r = await _post({"prompt": "日本語でお願いします 🎯"})
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_prompt_with_newlines_ok(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            r = await _post({"prompt": "line1\nline2\nline3"})
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_prompt_with_special_chars_ok(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            r = await _post({"prompt": "<script>alert('xss')</script>"})
        assert r.status_code == 200   # backend is dumb — Heimdall filters

    @pytest.mark.asyncio
    async def test_prompt_with_sql_injection_passthrough(self):
        """Backend must NOT filter — that's Heimdall's job."""
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            r = await _post({"prompt": "'; DROP TABLE users; --"})
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_extra_fields_ignored(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            r = await _post({"prompt": "Hi", "unknown_field": "ignored", "another": 123})
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 9. API — GET /health
# ══════════════════════════════════════════════════════════════════════════════

class TestHealthEndpoint:

    @pytest.mark.asyncio
    async def test_status_200(self):
        r = await _get("/health")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_has_providers_key(self):
        r = await _get("/health")
        assert "providers" in r.json()

    @pytest.mark.asyncio
    async def test_all_three_providers_present(self):
        r = await _get("/health")
        providers = r.json()["providers"]
        assert "gemini"  in providers
        assert "groq"    in providers
        assert "mistral" in providers

    @pytest.mark.asyncio
    async def test_each_provider_has_configured_field(self):
        r = await _get("/health")
        for p in r.json()["providers"].values():
            assert "configured" in p
            assert isinstance(p["configured"], bool)

    @pytest.mark.asyncio
    async def test_has_status_field(self):
        r = await _get("/health")
        assert "status" in r.json()

    @pytest.mark.asyncio
    async def test_status_ok_when_all_keys_present(self):
        """Keys are set to test values at top of file."""
        r = await _get("/health")
        # Keys are set, so should be 'ok' or 'degraded' — not 'error'
        assert r.json()["status"] in ("ok", "degraded")

    @pytest.mark.asyncio
    async def test_no_live_llm_calls_on_health(self):
        """Health must be instant — no API calls."""
        with patch("clients.call_gemini",  new_callable=AsyncMock) as mg, \
             patch("clients.call_groq",    new_callable=AsyncMock) as mq, \
             patch("clients.call_mistral", new_callable=AsyncMock) as mm:
            r = await _get("/health")
        assert mg.call_count == 0
        assert mq.call_count == 0
        assert mm.call_count == 0


# ══════════════════════════════════════════════════════════════════════════════
# 10. API — GET /  (root)
# ══════════════════════════════════════════════════════════════════════════════

class TestRootEndpoint:

    @pytest.mark.asyncio
    async def test_status_200(self):
        r = await _get("/")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_has_service_field(self):
        r = await _get("/")
        assert "service" in r.json()

    @pytest.mark.asyncio
    async def test_has_status_field(self):
        r = await _get("/")
        assert "status" in r.json()

    @pytest.mark.asyncio
    async def test_has_docs_link(self):
        r = await _get("/")
        assert "docs" in r.json()


# ══════════════════════════════════════════════════════════════════════════════
# 11. STRESS — RAPID SEQUENTIAL & CONCURRENT REQUESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestStress:

    @pytest.mark.asyncio
    async def test_10_sequential_requests_all_200(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                for i in range(10):
                    r = await ac.post("/query", json={"prompt": f"Request {i}"})
                    assert r.status_code == 200, f"Request {i} failed"

    @pytest.mark.asyncio
    async def test_20_concurrent_requests_all_200(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                tasks = [
                    ac.post("/query", json={"prompt": f"Concurrent {i}"})
                    for i in range(20)
                ]
                responses = await asyncio.gather(*tasks)
        assert all(r.status_code == 200 for r in responses)

    @pytest.mark.asyncio
    async def test_concurrent_requests_independent_session_ids(self):
        """Each request should echo its own session_id."""
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                tasks = [
                    ac.post("/query", json={"prompt": "Hi", "session_id": f"sid-{i}"})
                    for i in range(10)
                ]
                responses = await asyncio.gather(*tasks)

        for i, r in enumerate(responses):
            assert r.json()["session_id"] == f"sid-{i}"

    @pytest.mark.asyncio
    async def test_rapid_health_checks(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            tasks = [ac.get("/health") for _ in range(15)]
            responses = await asyncio.gather(*tasks)
        assert all(r.status_code == 200 for r in responses)


# ══════════════════════════════════════════════════════════════════════════════
# 12. RESPONSE INTEGRITY — values make sense
# ══════════════════════════════════════════════════════════════════════════════

class TestResponseIntegrity:

    @pytest.mark.asyncio
    async def test_ok_true_means_text_not_empty(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={
                       "gemini":  _ok("gemini", "some text"),
                       "groq":    _ok("groq",   "some text"),
                       "mistral": _ok("mistral","some text"),
                   }):
            r = await _post({"prompt": "Hi"})
        data = r.json()
        for p in ["gemini", "groq", "mistral"]:
            if data[p]["ok"]:
                assert len(data[p]["text"]) > 0

    @pytest.mark.asyncio
    async def test_ok_false_means_error_not_empty(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={
                       "gemini":  _fail("gemini", "rate_limit"),
                       "groq":    _fail("groq",   "timeout"),
                       "mistral": _fail("mistral","server_error"),
                   }):
            r = await _post({"prompt": "Hi"})
        data = r.json()
        for p in ["gemini", "groq", "mistral"]:
            if not data[p]["ok"]:
                assert len(data[p]["error"]) > 0

    @pytest.mark.asyncio
    async def test_latency_ms_non_negative(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            r = await _post({"prompt": "Hi"})
        data = r.json()
        assert data["latency_ms"] >= 0
        for p in ["gemini", "groq", "mistral"]:
            assert data[p]["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_tokens_used_non_negative(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            r = await _post({"prompt": "Hi"})
        data = r.json()
        for p in ["gemini", "groq", "mistral"]:
            assert data[p]["tokens_used"] >= 0

    @pytest.mark.asyncio
    async def test_content_type_is_json(self):
        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": _ok("gemini"), "groq": _ok("groq"), "mistral": _ok("mistral")}):
            r = await _post({"prompt": "Hi"})
        assert "application/json" in r.headers["content-type"]
