"""
Multi-LLM Backend — Test Suite
Run: pytest test_backend.py -v

Tests use httpx.AsyncClient with mocked HTTP so no real API keys needed.
"""
from __future__ import annotations
import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

# ── Patch env before importing app ────────────────────────────────────────────
import os
os.environ.setdefault("GEMINI_API_KEY",  "test_gemini_key")
os.environ.setdefault("GROQ_API_KEY",    "test_groq_key")
os.environ.setdefault("MISTRAL_API_KEY", "test_mistral_key")

from clients import (
    call_gemini, call_groq, call_mistral,
    call_all_parallel, LLMResponse,
)
from main import app
from httpx import AsyncClient, ASGITransport


# ── Fixtures ──────────────────────────────────────────────────────────────────

FAKE_GEMINI_RESP = {
    "candidates": [{
        "content": {"parts": [{"text": "Hello from Gemini!"}]}
    }],
    "usageMetadata": {"totalTokenCount": 42},
}

FAKE_OPENAI_RESP = {
    "choices": [{"message": {"content": "Hello from LLM!"}}],
    "usage": {"total_tokens": 35},
}


def _make_mock_response(status: int, body: dict) -> httpx.Response:
    request = httpx.Request("POST", "https://mock.api/endpoint")
    return httpx.Response(
        status_code=status,
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        request=request,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Unit: individual clients
# ─────────────────────────────────────────────────────────────────────────────

class TestGeminiClient:

    @pytest.mark.asyncio
    async def test_success(self):
        mock_resp = _make_mock_response(200, FAKE_GEMINI_RESP)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            r = await call_gemini("Hello", None, "key")
        assert r.ok
        assert r.text == "Hello from Gemini!"
        assert r.provider == "gemini"
        assert r.tokens_used == 42

    @pytest.mark.asyncio
    async def test_no_api_key(self):
        r = await call_gemini("Hello", None, "")
        assert not r.ok
        assert "key" in r.error.lower()

    @pytest.mark.asyncio
    async def test_timeout(self):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   side_effect=httpx.TimeoutException("timeout")):
            r = await call_gemini("Hello", None, "key")
        assert not r.ok
        assert r.error == "timeout"

    @pytest.mark.asyncio
    async def test_http_error(self):
        mock_resp = _make_mock_response(429, {"error": "rate limit"})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            r = await call_gemini("Hello", None, "key")
        assert not r.ok
        assert "429" in r.error

    @pytest.mark.asyncio
    async def test_with_system_prompt(self):
        mock_resp = _make_mock_response(200, FAKE_GEMINI_RESP)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as m:
            r = await call_gemini("Hello", "You are a pirate.", "key")
        assert r.ok
        # Verify system instruction was included in payload
        call_kwargs = m.call_args
        payload = call_kwargs.kwargs.get("json", call_kwargs.args[1] if len(call_kwargs.args) > 1 else {})
        assert "systemInstruction" in payload


class TestGroqClient:

    @pytest.mark.asyncio
    async def test_success(self):
        mock_resp = _make_mock_response(200, FAKE_OPENAI_RESP)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            r = await call_groq("Hello", None, "key")
        assert r.ok
        assert r.text == "Hello from LLM!"
        assert r.provider == "groq"
        assert r.model == "llama-3.1-8b-instant"

    @pytest.mark.asyncio
    async def test_no_api_key(self):
        r = await call_groq("Hello", None, "")
        assert not r.ok

    @pytest.mark.asyncio
    async def test_timeout(self):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   side_effect=httpx.TimeoutException("timeout")):
            r = await call_groq("Hello", None, "key")
        assert not r.ok
        assert r.error == "timeout"


class TestMistralClient:

    @pytest.mark.asyncio
    async def test_success(self):
        mock_resp = _make_mock_response(200, FAKE_OPENAI_RESP)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            r = await call_mistral("Hello", None, "key")
        assert r.ok
        assert r.text == "Hello from LLM!"
        assert r.provider == "mistral"
        assert r.model == "mistral-small-latest"

    @pytest.mark.asyncio
    async def test_no_api_key(self):
        r = await call_mistral("Hello", None, "")
        assert not r.ok

    @pytest.mark.asyncio
    async def test_timeout(self):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   side_effect=httpx.TimeoutException("timeout")):
            r = await call_mistral("Hello", None, "key")
        assert not r.ok


# ─────────────────────────────────────────────────────────────────────────────
# Unit: parallel caller
# ─────────────────────────────────────────────────────────────────────────────

class TestParallelCaller:

    @pytest.mark.asyncio
    async def test_all_succeed(self):
        gemini_ok  = LLMResponse(provider="gemini",  text="g", ok=True,  model="gemini-2.0-flash-exp", latency_ms=100, tokens_used=10)
        groq_ok    = LLMResponse(provider="groq",    text="q", ok=True,  model="llama-3.1-8b-instant", latency_ms=50,  tokens_used=8)
        mistral_ok = LLMResponse(provider="mistral", text="m", ok=True,  model="mistral-small-latest", latency_ms=150, tokens_used=12)

        with patch("clients.call_gemini",  new_callable=AsyncMock, return_value=gemini_ok), \
             patch("clients.call_groq",    new_callable=AsyncMock, return_value=groq_ok), \
             patch("clients.call_mistral", new_callable=AsyncMock, return_value=mistral_ok):
            results = await call_all_parallel("test", None, "g", "q", "m")

        assert results["gemini"].ok
        assert results["groq"].ok
        assert results["mistral"].ok
        assert results["gemini"].text == "g"

    @pytest.mark.asyncio
    async def test_one_provider_fails_others_succeed(self):
        gemini_fail = LLMResponse(provider="gemini", ok=False, error="timeout")
        groq_ok     = LLMResponse(provider="groq",   text="q", ok=True)
        mistral_ok  = LLMResponse(provider="mistral", text="m", ok=True)

        with patch("clients.call_gemini",  new_callable=AsyncMock, return_value=gemini_fail), \
             patch("clients.call_groq",    new_callable=AsyncMock, return_value=groq_ok), \
             patch("clients.call_mistral", new_callable=AsyncMock, return_value=mistral_ok):
            results = await call_all_parallel("test", None, "g", "q", "m")

        assert not results["gemini"].ok
        assert results["gemini"].error == "timeout"
        assert results["groq"].ok
        assert results["mistral"].ok

    @pytest.mark.asyncio
    async def test_all_fail_no_exception(self):
        fail = LLMResponse(provider="x", ok=False, error="down")
        all_fail = LLMResponse(provider="gemini", ok=False, error="down")

        with patch("clients.call_gemini",  new_callable=AsyncMock,
                   return_value=LLMResponse(provider="gemini",  ok=False, error="down")), \
             patch("clients.call_groq",    new_callable=AsyncMock,
                   return_value=LLMResponse(provider="groq",    ok=False, error="down")), \
             patch("clients.call_mistral", new_callable=AsyncMock,
                   return_value=LLMResponse(provider="mistral", ok=False, error="down")):
            # Must not raise — demo must never crash
            results = await call_all_parallel("test", None, "", "", "")

        assert not results["gemini"].ok
        assert not results["groq"].ok
        assert not results["mistral"].ok

    @pytest.mark.asyncio
    async def test_returns_all_three_keys(self):
        resp = LLMResponse(provider="x", ok=True, text="hi")
        with patch("clients.call_gemini",  new_callable=AsyncMock,
                   return_value=LLMResponse(provider="gemini", ok=True, text="g")), \
             patch("clients.call_groq",    new_callable=AsyncMock,
                   return_value=LLMResponse(provider="groq", ok=True, text="q")), \
             patch("clients.call_mistral", new_callable=AsyncMock,
                   return_value=LLMResponse(provider="mistral", ok=True, text="m")):
            results = await call_all_parallel("test", None, "g", "q", "m")

        assert set(results.keys()) == {"gemini", "groq", "mistral"}


# ─────────────────────────────────────────────────────────────────────────────
# Integration: FastAPI endpoints
# ─────────────────────────────────────────────────────────────────────────────

class TestAPIEndpoints:

    @pytest.mark.asyncio
    async def test_root(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/")
        assert r.status_code == 200
        assert "Heimdall" in r.json()["service"]

    @pytest.mark.asyncio
    async def test_health_no_keys(self):
        """Health endpoint should work even without real keys."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert "providers" in data
        assert "gemini" in data["providers"]
        assert "groq" in data["providers"]
        assert "mistral" in data["providers"]

    @pytest.mark.asyncio
    async def test_query_success(self):
        g = LLMResponse(provider="gemini",  text="Gemini answer",  ok=True, model="m", latency_ms=100, tokens_used=10)
        q = LLMResponse(provider="groq",    text="Groq answer",    ok=True, model="m", latency_ms=50,  tokens_used=8)
        m = LLMResponse(provider="mistral", text="Mistral answer", ok=True, model="m", latency_ms=120, tokens_used=11)

        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": g, "groq": q, "mistral": m}):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.post("/query", json={
                    "prompt": "What is machine learning?",
                    "session_id": "test-session-1",
                })

        assert r.status_code == 200
        data = r.json()
        assert data["gemini"]["ok"] is True
        assert data["gemini"]["text"] == "Gemini answer"
        assert data["groq"]["ok"] is True
        assert data["mistral"]["ok"] is True
        assert data["session_id"] == "test-session-1"
        assert data["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_query_one_provider_down(self):
        g = LLMResponse(provider="gemini",  ok=False, error="timeout",       latency_ms=30000)
        q = LLMResponse(provider="groq",    text="Groq OK", ok=True, model="m", latency_ms=50, tokens_used=8)
        m = LLMResponse(provider="mistral", text="Mistral OK", ok=True, model="m", latency_ms=120, tokens_used=11)

        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": g, "groq": q, "mistral": m}):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.post("/query", json={"prompt": "Hello"})

        assert r.status_code == 200           # still 200 — partial success is ok
        data = r.json()
        assert data["gemini"]["ok"] is False
        assert data["gemini"]["error"] == "timeout"
        assert data["groq"]["ok"] is True
        assert data["mistral"]["ok"] is True

    @pytest.mark.asyncio
    async def test_query_empty_prompt(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/query", json={"prompt": ""})
        assert r.status_code == 422   # Pydantic validation: min_length=1

    @pytest.mark.asyncio
    async def test_query_prompt_too_long(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/query", json={"prompt": "x" * 5000})
        assert r.status_code == 422   # Pydantic validation: max_length=4096

    @pytest.mark.asyncio
    async def test_query_custom_system(self):
        g = LLMResponse(provider="gemini",  ok=True, text="arr", model="m", latency_ms=80, tokens_used=5)
        q = LLMResponse(provider="groq",    ok=True, text="arr", model="m", latency_ms=40, tokens_used=5)
        m = LLMResponse(provider="mistral", ok=True, text="arr", model="m", latency_ms=90, tokens_used=5)

        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": g, "groq": q, "mistral": m}) as mock_call:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.post("/query", json={
                    "prompt": "Hello",
                    "system": "You are a pirate.",
                })

        assert r.status_code == 200
        # Verify custom system was passed through
        _, kwargs = mock_call.call_args
        assert kwargs.get("system") == "You are a pirate."

    @pytest.mark.asyncio
    async def test_query_response_schema(self):
        """Verify response has all required fields in correct types."""
        g = LLMResponse(provider="gemini",  ok=True, text="hi", model="gemini-2.0-flash-exp", latency_ms=100, tokens_used=10)
        q = LLMResponse(provider="groq",    ok=True, text="hi", model="llama-3.1-8b-instant",  latency_ms=50,  tokens_used=8)
        m = LLMResponse(provider="mistral", ok=True, text="hi", model="mistral-small-latest",  latency_ms=120, tokens_used=11)

        with patch("main.call_all_parallel", new_callable=AsyncMock,
                   return_value={"gemini": g, "groq": q, "mistral": m}):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.post("/query", json={"prompt": "test"})

        data = r.json()
        for provider in ["gemini", "groq", "mistral"]:
            assert "text"        in data[provider]
            assert "ok"          in data[provider]
            assert "error"       in data[provider]
            assert "latency_ms"  in data[provider]
            assert "model"       in data[provider]
            assert "tokens_used" in data[provider]
        assert "latency_ms" in data
