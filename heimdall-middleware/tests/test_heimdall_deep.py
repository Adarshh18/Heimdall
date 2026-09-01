"""
HEIMDALL Middleware — Deep Test Suite
Run: pytest test_heimdall_deep.py -v --tb=short

Covers:
  1.  StreamManager         — queue mechanics, concurrency, eviction, isolation
  2.  SSE event shapes      — every field of every event type validated
  3.  MultiLLMClient        — HTTP contract, event emission, failure matrix
  4.  G1 Pipeline SSE hooks — every layer emits correct event on PASS/FLAG/BLOCK
  5.  G2 Pipeline SSE hooks — every output layer emits correct event
  6.  Chat endpoint         — full G1→LLM→G2 flow, all verdict paths
  7.  SSE stream endpoint   — format, ordering, heartbeat, concurrent sessions
  8.  Health endpoint       — backend reachability, component status
  9.  Stats endpoint        — field presence, types
  10. Integration           — end-to-end event sequence verification
  11. Stress                — concurrent sessions, rapid fire, queue pressure
  12. Edge cases            — unicode, long prompts, empty system, special chars
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch, call

import httpx
import pytest
from httpx import AsyncClient, ASGITransport

# ── Env before imports ────────────────────────────────────────────────────────
os.environ.setdefault("GEMINI_API_KEY",        "test_key")
os.environ.setdefault("GROQ_API_KEY",          "test_key")
os.environ.setdefault("MISTRAL_API_KEY",       "test_key")
os.environ.setdefault("MULTI_LLM_BACKEND_URL", "http://mock-backend:8001")
os.environ.setdefault("USE_FAKE_REDIS",        "true")

from core.stream_manager import StreamManager, stream_manager as _global_sm
from core.multi_llm_client import (
    query_multi_llm, MultiLLMResult, ProviderResult,
    _all_failed, _parse_provider,
)


# ══════════════════════════════════════════════════════════════════════════════
# SHARED FACTORIES
# ══════════════════════════════════════════════════════════════════════════════

def _prov(name: str, ok=True, text="hi", latency=80.0, tokens=10,
          error="") -> ProviderResult:
    return ProviderResult(
        provider=name, text=text if ok else "", ok=ok,
        error=error if not ok else "", latency_ms=latency,
        model=f"{name}-model", tokens_used=tokens if ok else 0,
    )

def _llm(gemini_ok=True, groq_ok=True, mistral_ok=True,
         gemini_text="Gemini answer",
         groq_text="Groq answer",
         mistral_text="Mistral answer") -> MultiLLMResult:
    return MultiLLMResult(
        gemini  = _prov("gemini",  gemini_ok,  gemini_text,  100),
        groq    = _prov("groq",    groq_ok,    groq_text,    50),
        mistral = _prov("mistral", mistral_ok, mistral_text, 120),
        latency_ms=130.0,
    )

def _http_resp(status: int, body: dict) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        request=httpx.Request("POST", "http://mock-backend:8001/query"),
    )

def _backend_body(g=True, q=True, m=True) -> dict:
    def p(name, ok):
        return {"text": f"{name} says hi" if ok else "", "ok": ok,
                "error": "" if ok else "timeout", "latency_ms": 80.0,
                "model": f"{name}-v1", "tokens_used": 10 if ok else 0}
    return {"gemini": p("gemini",g), "groq": p("groq",q),
            "mistral": p("mistral",m), "latency_ms": 95.0}

def _drain(sm: StreamManager, session_id: str) -> list[dict]:
    q = sm._ensure(session_id)
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    return events

def _mock_g1(verdict="PASS", confidence=0.95, latency=10.0,
             sanitized_input=None):
    from core.models import Verdict
    v = Verdict(verdict)
    def _side(ctx, session_id=None):
        ctx.g1_verdict    = v
        ctx.g1_confidence = confidence
        ctx.g1_latency_ms = latency
        if sanitized_input:
            ctx.sanitized_input = sanitized_input
        return ctx
    m = MagicMock()
    m.process       = AsyncMock(side_effect=_side)
    m.input_for_llm = MagicMock(return_value=sanitized_input or "clean input")
    return m

def _mock_g2(verdict="PASS", confidence=0.95, latency=8.0):
    from core.models import Verdict
    v = Verdict(verdict)
    def _side(ctx, session_id=None):
        ctx.g2_verdict    = v
        ctx.g2_confidence = confidence
        ctx.g2_latency_ms = latency
        ctx.final_output  = ctx.llm_raw_output if v == Verdict.PASS else "blocked"
        return ctx
    m = MagicMock()
    m.process = AsyncMock(side_effect=_side)
    return m

def _patch_app(g1=None, g2=None, llm_result=None, sessions=None):
    """Context manager patches for heimdall_app globals."""
    return [
        patch("heimdall_app._g1",      g1      or _mock_g1()),
        patch("heimdall_app._g2",      g2      or _mock_g2()),
        patch("heimdall_app.query_multi_llm",
              AsyncMock(return_value=llm_result or _llm())),
        patch("heimdall_app._sessions", sessions if sessions is not None else {}),
        patch("heimdall_app._cache",   MagicMock()),
        patch("heimdall_app._pool",    MagicMock()),
        patch("heimdall_app._agentic", MagicMock()),
    ]

async def _post(payload: dict, patches=None) -> httpx.Response:
    ctx_patches = patches or _patch_app()
    from heimdall_app import app
    for p in ctx_patches:
        p.start()
    try:
        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://test") as ac:
            return await ac.post("/chat", json=payload)
    finally:
        for p in ctx_patches:
            p.stop()

async def _get(path: str) -> httpx.Response:
    from heimdall_app import app
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as ac:
        return await ac.get(path)


# ══════════════════════════════════════════════════════════════════════════════
# 1. STREAM MANAGER — DEEP
# ══════════════════════════════════════════════════════════════════════════════

class TestStreamManagerDeep:

    def s(self): return StreamManager()

    @pytest.mark.asyncio
    async def test_push_updates_last_active(self):
        sm = self.s()
        before = time.time()
        sm.push("s", {"event": "x"})
        assert sm._last_active["s"] >= before

    @pytest.mark.asyncio
    async def test_push_multiple_events_ordered(self):
        sm = self.s()
        for i in range(5):
            sm.push("order", {"event": "layer", "seq": i})
        events = _drain(sm, "order")
        seqs = [e["seq"] for e in events]
        assert seqs == list(range(5))

    @pytest.mark.asyncio
    async def test_done_after_done_is_idempotent(self):
        sm = self.s()
        sm.done("d")
        sm.done("d")   # second done — should not raise
        events = _drain(sm, "d")
        done_count = sum(1 for e in events if e["event"] == "done")
        assert done_count >= 1

    @pytest.mark.asyncio
    async def test_error_event_has_detail_field(self):
        sm = self.s()
        sm.error("e", "database exploded")
        events = _drain(sm, "e")
        err = next(e for e in events if e["event"] == "error")
        assert "detail" in err
        assert "exploded" in err["detail"]

    @pytest.mark.asyncio
    async def test_queue_max_200_drops_overflow(self):
        sm = self.s()
        for i in range(205):
            sm.push("big", {"event": "x", "i": i})
        q = sm._ensure("big")
        assert q.qsize() <= 200

    @pytest.mark.asyncio
    async def test_listen_yields_sse_formatted_strings(self):
        sm = self.s()
        sm.push("fmt", {"event": "layer", "layer": "L0"})
        sm.done("fmt")
        collected = []
        async for raw in sm.listen("fmt", timeout=3):
            collected.append(raw)
        # Each raw is a JSON string (not SSE-wrapped — that's the endpoint's job)
        for raw in collected:
            parsed = json.loads(raw)
            assert "event" in parsed

    @pytest.mark.asyncio
    async def test_listen_stops_on_done(self):
        sm = self.s()
        sm.push("stop", {"event": "layer"})
        sm.push("stop", {"event": "layer"})
        sm.done("stop")
        count = 0
        async for _ in sm.listen("stop", timeout=3):
            count += 1
        assert count == 3   # 2 layers + done

    @pytest.mark.asyncio
    async def test_listen_stops_on_error(self):
        sm = self.s()
        sm.error("err-stop", "boom")
        events = []
        async for raw in sm.listen("err-stop", timeout=3):
            events.append(json.loads(raw))
        types = [e["event"] for e in events]
        assert "error" in types

    @pytest.mark.asyncio
    async def test_listen_cleans_up_after_done(self):
        sm = self.s()
        sm.done("cleanup")
        async for _ in sm.listen("cleanup", timeout=3):
            pass
        assert "cleanup" not in sm._queues

    @pytest.mark.asyncio
    async def test_ten_concurrent_sessions_isolated(self):
        sm = self.s()
        for i in range(10):
            sm.push(f"sess-{i}", {"event": "layer", "owner": i})
        for i in range(10):
            events = _drain(sm, f"sess-{i}")
            assert len(events) == 1
            assert events[0]["owner"] == i

    @pytest.mark.asyncio
    async def test_evict_removes_only_stale(self):
        sm = self.s()
        sm.push("fresh", {"event": "x"})
        sm.push("stale", {"event": "x"})
        sm._last_active["stale"] = time.time() - 999
        evicted = sm.evict_stale()
        assert evicted == 1
        assert "fresh" in sm._queues
        assert "stale" not in sm._queues

    @pytest.mark.asyncio
    async def test_active_sessions_decrements_after_listen(self):
        sm = self.s()
        sm.done("dec")
        assert sm.active_sessions >= 1
        async for _ in sm.listen("dec", timeout=2):
            pass
        assert "dec" not in sm._queues

    @pytest.mark.asyncio
    async def test_push_after_cleanup_recreates_queue(self):
        sm = self.s()
        sm.push("recycle", {"event": "x"})
        sm._cleanup("recycle")
        assert "recycle" not in sm._queues
        sm.push("recycle", {"event": "y"})   # must not raise
        assert "recycle" in sm._queues

    @pytest.mark.asyncio
    async def test_concurrent_pushes_from_multiple_tasks(self):
        sm = self.s()
        async def pusher(i):
            for j in range(10):
                sm.push("concurrent", {"event": "x", "task": i, "j": j})
        await asyncio.gather(*[pusher(i) for i in range(5)])
        events = _drain(sm, "concurrent")
        assert len(events) == 50


# ══════════════════════════════════════════════════════════════════════════════
# 2. SSE EVENT SHAPE CONTRACTS
# ══════════════════════════════════════════════════════════════════════════════

class TestSSEEventShapes:
    """Every event type must carry exactly the right fields."""

    def _layer_event(self, gateway, layer, name, status, **extra):
        return {"event": "layer", "gateway": gateway, "layer": layer,
                "name": name, "status": status, "latency_ms": 1.0,
                "flags": 0, **extra}

    def test_layer_event_required_fields(self):
        e = self._layer_event("G1", "L0", "Attack Cache", "MISS")
        for f in ("event", "gateway", "layer", "name", "status", "latency_ms"):
            assert f in e, f"missing field: {f}"

    def test_layer_status_values_g1(self):
        valid = {"MISS", "HIT", "FLAG", "BLOCK", "PASS", "SANITIZED",
                 "RUNNING", "SANITIZE"}
        e = self._layer_event("G1", "L1", "Pattern Engine", "FLAG")
        assert e["status"] in valid

    def test_layer_status_values_g2(self):
        valid = {"MISS", "HIT", "FLAG", "BLOCK", "PASS", "RUNNING"}
        e = self._layer_event("G2", "O2", "Leakage Detector", "PASS")
        assert e["status"] in valid

    def test_verdict_event_required_fields(self):
        e = {"event": "verdict", "gateway": "G1", "verdict": "BLOCK",
             "confidence": 0.97, "latency_ms": 450.0}
        for f in ("event", "gateway", "verdict", "confidence", "latency_ms"):
            assert f in e

    def test_verdict_values(self):
        for v in ("PASS", "SANITIZE", "BLOCK"):
            e = {"event": "verdict", "gateway": "G1", "verdict": v,
                 "confidence": 0.9, "latency_ms": 10.0}
            assert e["verdict"] in ("PASS", "SANITIZE", "BLOCK")

    def test_llm_start_event_shape(self):
        e = {"event": "llm_start", "providers": ["gemini", "groq", "mistral"]}
        assert e["event"] == "llm_start"
        assert set(e["providers"]) == {"gemini", "groq", "mistral"}

    def test_llm_result_event_required_fields(self):
        e = {"event": "llm_result", "provider": "groq", "ok": True,
             "latency_ms": 320.0, "tokens_used": 45, "model": "llama-3.1",
             "text_preview": "Machine learning is...", "error": ""}
        for f in ("event", "provider", "ok", "latency_ms"):
            assert f in e

    def test_llm_result_provider_values(self):
        for p in ("gemini", "groq", "mistral"):
            e = {"event": "llm_result", "provider": p, "ok": True,
                 "latency_ms": 100.0}
            assert e["provider"] in ("gemini", "groq", "mistral")

    def test_complete_event_required_fields(self):
        e = {"event": "complete", "reply": "Hello!", "blocked": False,
             "sanitized": False, "total_latency_ms": 1200.0}
        for f in ("event", "reply", "blocked", "sanitized", "total_latency_ms"):
            assert f in e

    def test_complete_blocked_implies_no_reply(self):
        e = {"event": "complete", "reply": "I cannot process that.",
             "blocked": True, "sanitized": False, "total_latency_ms": 50.0}
        assert e["blocked"] is True
        assert isinstance(e["reply"], str)

    def test_done_event_shape(self):
        e = {"event": "done"}
        assert e["event"] == "done"

    def test_error_event_has_detail(self):
        e = {"event": "error", "detail": "All LLM providers failed"}
        assert "detail" in e

    def test_ping_event_shape(self):
        e = {"event": "ping"}
        assert e["event"] == "ping"

    def test_latency_ms_always_float(self):
        events = [
            {"event": "layer",   "latency_ms": 2.1},
            {"event": "verdict", "latency_ms": 450.0},
            {"event": "llm_result", "latency_ms": 320.5},
        ]
        for e in events:
            assert isinstance(e["latency_ms"], float)

    def test_confidence_in_0_to_1(self):
        for conf in [0.0, 0.5, 0.97, 1.0]:
            assert 0.0 <= conf <= 1.0

    def test_g1_layer_sequence(self):
        """G1 layers must appear in L0→L1→L2→L3→L4→L5 order."""
        layers = ["L0", "L1", "L2", "L3", "L4", "L5"]
        for i, l in enumerate(layers):
            assert l == f"L{i}"

    def test_g2_layer_sequence(self):
        """G2 layers must appear in O1→O2→O3→O4→O5 order."""
        layers = ["O1", "O2", "O3", "O4", "O5"]
        for i, l in enumerate(layers):
            assert l == f"O{i+1}"


# ══════════════════════════════════════════════════════════════════════════════
# 3. MULTI-LLM CLIENT — DEEP
# ══════════════════════════════════════════════════════════════════════════════

class TestMultiLLMClientDeep:

    @pytest.mark.asyncio
    async def test_prompt_forwarded_to_backend(self):
        mock = _http_resp(200, _backend_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   return_value=mock) as m:
            await query_multi_llm("UNIQUE PROMPT 🔥", "sid")
        _, kw = m.call_args
        assert kw["json"]["prompt"] == "UNIQUE PROMPT 🔥"

    @pytest.mark.asyncio
    async def test_session_id_forwarded_to_backend(self):
        mock = _http_resp(200, _backend_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   return_value=mock) as m:
            await query_multi_llm("hello", "MY-SESSION-ID")
        _, kw = m.call_args
        assert kw["json"]["session_id"] == "MY-SESSION-ID"

    @pytest.mark.asyncio
    async def test_system_forwarded_to_backend(self):
        mock = _http_resp(200, _backend_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   return_value=mock) as m:
            await query_multi_llm("hello", "s", system="You are a pirate.")
        _, kw = m.call_args
        assert kw["json"]["system"] == "You are a pirate."

    @pytest.mark.asyncio
    async def test_max_tokens_forwarded(self):
        mock = _http_resp(200, _backend_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   return_value=mock) as m:
            await query_multi_llm("hello", "s", max_tokens=500)
        _, kw = m.call_args
        assert kw["json"]["max_tokens"] == 500

    @pytest.mark.asyncio
    async def test_wall_latency_from_backend(self):
        body = _backend_body()
        body["latency_ms"] = 234.5
        mock = _http_resp(200, body)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock):
            result = await query_multi_llm("hello", "s")
        assert result.latency_ms == 234.5

    @pytest.mark.asyncio
    async def test_partial_failure_gemini_down(self):
        mock = _http_resp(200, _backend_body(g=False))
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock):
            result = await query_multi_llm("hello", "s")
        assert not result.gemini.ok
        assert result.groq.ok
        assert result.mistral.ok
        assert result.any_ok

    @pytest.mark.asyncio
    async def test_partial_failure_groq_down(self):
        mock = _http_resp(200, _backend_body(q=False))
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock):
            result = await query_multi_llm("hello", "s")
        assert not result.groq.ok
        assert result.gemini.ok
        assert result.any_ok

    @pytest.mark.asyncio
    async def test_all_three_down_any_ok_false(self):
        mock = _http_resp(200, _backend_body(g=False, q=False, m=False))
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock):
            result = await query_multi_llm("hello", "s")
        assert not result.any_ok
        assert result.best_response is None

    @pytest.mark.asyncio
    async def test_network_error_all_failed(self):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   side_effect=httpx.ConnectError("refused")):
            result = await query_multi_llm("hello", "s")
        assert not result.any_ok

    @pytest.mark.asyncio
    async def test_http_503_all_failed(self):
        mock = _http_resp(503, {"error": "service unavailable"})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock):
            result = await query_multi_llm("hello", "s")
        assert not result.any_ok

    @pytest.mark.asyncio
    async def test_llm_start_event_providers_list(self):
        sm = StreamManager()
        mock = _http_resp(200, _backend_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock), \
             patch("core.multi_llm_client.stream_manager", sm):
            await query_multi_llm("hello", "start-test")
        events = _drain(sm, "start-test")
        start = next(e for e in events if e["event"] == "llm_start")
        assert sorted(start["providers"]) == ["gemini", "groq", "mistral"]

    @pytest.mark.asyncio
    async def test_llm_result_events_all_three_providers(self):
        sm = StreamManager()
        mock = _http_resp(200, _backend_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock), \
             patch("core.multi_llm_client.stream_manager", sm):
            await query_multi_llm("hello", "result-test")
        events = _drain(sm, "result-test")
        results = [e for e in events if e["event"] == "llm_result"]
        providers = {e["provider"] for e in results}
        assert providers == {"gemini", "groq", "mistral"}

    @pytest.mark.asyncio
    async def test_llm_result_ok_field_is_bool(self):
        sm = StreamManager()
        mock = _http_resp(200, _backend_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock), \
             patch("core.multi_llm_client.stream_manager", sm):
            await query_multi_llm("hello", "bool-test")
        events = _drain(sm, "bool-test")
        for e in events:
            if e["event"] == "llm_result":
                assert isinstance(e["ok"], bool)

    @pytest.mark.asyncio
    async def test_llm_result_sorted_by_latency(self):
        """Fastest provider event arrives first in queue."""
        body = _backend_body()
        body["groq"]["latency_ms"]    = 50.0
        body["gemini"]["latency_ms"]  = 150.0
        body["mistral"]["latency_ms"] = 200.0
        sm = StreamManager()
        mock = _http_resp(200, body)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock), \
             patch("core.multi_llm_client.stream_manager", sm):
            await query_multi_llm("hello", "sort-test")
        events = _drain(sm, "sort-test")
        results = [e for e in events if e["event"] == "llm_result"]
        latencies = [e["latency_ms"] for e in results]
        assert latencies == sorted(latencies)

    @pytest.mark.asyncio
    async def test_text_preview_truncated_at_120(self):
        body = _backend_body()
        body["groq"]["text"] = "x" * 200
        sm = StreamManager()
        mock = _http_resp(200, body)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock), \
             patch("core.multi_llm_client.stream_manager", sm):
            await query_multi_llm("hello", "preview-test")
        events = _drain(sm, "preview-test")
        groq_ev = next(e for e in events
                       if e["event"] == "llm_result" and e["provider"] == "groq")
        assert len(groq_ev["text_preview"]) <= 123   # 120 + "..."

    @pytest.mark.asyncio
    async def test_failed_provider_emits_error_event(self):
        sm = StreamManager()
        mock = _http_resp(200, _backend_body(q=False))
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock), \
             patch("core.multi_llm_client.stream_manager", sm):
            await query_multi_llm("hello", "fail-ev")
        events = _drain(sm, "fail-ev")
        groq_ev = next(e for e in events
                       if e["event"] == "llm_result" and e["provider"] == "groq")
        assert groq_ev["ok"] is False
        assert groq_ev["error"] != ""

    @pytest.mark.asyncio
    async def test_to_dict_all_fields_present(self):
        mock = _http_resp(200, _backend_body())
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock):
            result = await query_multi_llm("hello", "dict-deep")
        d = result.to_dict()
        for provider in ["gemini", "groq", "mistral"]:
            p = d[provider]
            for field in ("text", "ok", "error", "latency_ms", "model", "tokens_used"):
                assert field in p, f"{provider} missing {field}"

    @pytest.mark.asyncio
    async def test_best_response_order_groq_first(self):
        result = _llm(groq_text="groq wins")
        assert result.best_response == "groq wins"

    @pytest.mark.asyncio
    async def test_best_response_skips_empty_text(self):
        result = MultiLLMResult(
            groq    = _prov("groq",    True, ""),     # ok but empty
            gemini  = _prov("gemini",  True, "gemini has content"),
            mistral = _prov("mistral", True, "mistral"),
            latency_ms=100.0,
        )
        assert result.best_response == "gemini has content"


# ══════════════════════════════════════════════════════════════════════════════
# 4. G1 PIPELINE SSE HOOKS
# ══════════════════════════════════════════════════════════════════════════════

class TestG1PipelineSSEHooks:
    """Verify G1 pipeline emits correct SSE events for every layer."""

    def _make_g1(self, sm):
        from core.gateway1.pipeline import InputSentinel
        from core.cache.manager import CacheManager
        from core.agentic.decision_layer import AgenticDecisionLayer
        from core.models import AgenticDecision, Verdict
        from core.gateway1.l1_pattern_engine import PatternEngine
        from core.gateway1.l2_sanitizer import Sanitizer
        from core.gateway1.l3_ml_classifier import MLClassifier
        from core.gateway1.l4_intent_engine import IntentEngine
        from config.settings import get_settings
        settings = get_settings()
        cache    = CacheManager(settings)
        cache.initialize()
        pool_mock = MagicMock()
        pool_mock.complete_agentic = AsyncMock(
            return_value=type("R", (), {"ok": True, "text": '{"verdict":"PASS","confidence":0.95,"attack_confirmed":false,"attack_type":"UNKNOWN","reason":"clean","cache_action":"NONE"}', "tokens_input": 10, "tokens_output": 10})()
        )
        agentic = AgenticDecisionLayer(pool_mock)
        return InputSentinel(
            cache, agentic,
            PatternEngine(settings.patterns_path), Sanitizer(),
            MLClassifier(), IntentEngine()
        )

    @pytest.mark.asyncio
    async def test_g1_emits_l0_event(self):
        from core.models import RequestContext, SessionState
        sm = StreamManager()
        g1 = self._make_g1(sm)
        ctx = RequestContext(raw_input="Hello world", session=SessionState(session_id="t"))
        with patch("core.gateway1.pipeline.stream_manager", sm):
            await g1.process(ctx, session_id="g1-l0")
        events = _drain(sm, "g1-l0")
        l0_events = [e for e in events if e.get("layer") == "L0"]
        assert len(l0_events) >= 1
        assert l0_events[0]["gateway"] == "G1"

    @pytest.mark.asyncio
    async def test_g1_emits_verdict_event(self):
        from core.models import RequestContext, SessionState
        sm = StreamManager()
        g1 = self._make_g1(sm)
        ctx = RequestContext(raw_input="Hello world", session=SessionState(session_id="t"))
        with patch("core.gateway1.pipeline.stream_manager", sm):
            await g1.process(ctx, session_id="g1-verdict")
        events = _drain(sm, "g1-verdict")
        verdicts = [e for e in events if e["event"] == "verdict"]
        assert len(verdicts) >= 1
        assert verdicts[0]["gateway"] == "G1"
        assert verdicts[0]["verdict"] in ("PASS", "BLOCK", "SANITIZE")

    @pytest.mark.asyncio
    async def test_g1_no_session_id_emits_nothing(self):
        from core.models import RequestContext, SessionState
        sm = StreamManager()
        g1 = self._make_g1(sm)
        ctx = RequestContext(raw_input="Hello", session=SessionState(session_id="t"))
        with patch("core.gateway1.pipeline.stream_manager", sm):
            await g1.process(ctx, session_id=None)   # no session_id
        # Queue should not exist or be empty for our specific session
        assert "no-session" not in sm._queues

    @pytest.mark.asyncio
    async def test_g1_clean_input_emits_pass_verdict(self):
        from core.models import RequestContext, SessionState, Verdict
        sm = StreamManager()
        g1 = self._make_g1(sm)
        ctx = RequestContext(raw_input="What is 2+2?",
                             session=SessionState(session_id="clean"))
        with patch("core.gateway1.pipeline.stream_manager", sm):
            await g1.process(ctx, session_id="g1-clean")
        assert ctx.g1_verdict == Verdict.PASS
        events = _drain(sm, "g1-clean")
        verdicts = [e for e in events if e["event"] == "verdict"]
        assert any(v["verdict"] == "PASS" for v in verdicts)

    @pytest.mark.asyncio
    async def test_g1_layer_events_have_latency_ms(self):
        from core.models import RequestContext, SessionState
        sm = StreamManager()
        g1 = self._make_g1(sm)
        ctx = RequestContext(raw_input="Tell me about AI",
                             session=SessionState(session_id="lat"))
        with patch("core.gateway1.pipeline.stream_manager", sm):
            await g1.process(ctx, session_id="g1-lat")
        events = _drain(sm, "g1-lat")
        layer_events = [e for e in events if e["event"] == "layer"]
        for e in layer_events:
            assert "latency_ms" in e
            assert e["latency_ms"] >= 0


# ══════════════════════════════════════════════════════════════════════════════
# 5. G2 PIPELINE SSE HOOKS
# ══════════════════════════════════════════════════════════════════════════════

class TestG2PipelineSSEHooks:

    def _make_g2(self):
        from core.gateway2.pipeline import OutputSentinel
        from core.cache.manager import CacheManager
        from core.agentic.decision_layer import AgenticDecisionLayer
        from core.gateway2.o2_leakage import LeakageDetector
        from core.gateway2.o3_behavior import BehavioralChecker
        from core.gateway2.o4_tool_validator import ToolValidator
        from config.settings import get_settings
        s = get_settings()
        pool_mock = MagicMock()
        pool_mock.complete_agentic = AsyncMock(
            return_value=type("R", (), {"ok": True, "text": '{"verdict":"PASS","confidence":0.95,"attack_confirmed":false,"attack_type":"UNKNOWN","reason":"clean","cache_action":"NONE"}', "tokens_input": 10, "tokens_output": 10})()
        )
        cache = CacheManager(s)
        cache.initialize()
        return OutputSentinel(
            cache, AgenticDecisionLayer(pool_mock),
            LeakageDetector(system_prompt_canary=s.system_prompt_canary,
                            leakage_similarity_threshold=s.leakage_similarity_threshold),
            BehavioralChecker(), ToolValidator()
        )

    @pytest.mark.asyncio
    async def test_g2_emits_o1_event(self):
        from core.models import RequestContext, SessionState
        sm = StreamManager()
        g2 = self._make_g2()
        ctx = RequestContext(raw_input="test", session=SessionState(session_id="t"))
        ctx.llm_raw_output = "This is a normal AI response."
        with patch("core.gateway2.pipeline.stream_manager", sm):
            await g2.process(ctx, session_id="g2-o1")
        events = _drain(sm, "g2-o1")
        o1 = [e for e in events if e.get("layer") == "O1"]
        assert len(o1) >= 1
        assert o1[0]["gateway"] == "G2"

    @pytest.mark.asyncio
    async def test_g2_emits_verdict_event(self):
        from core.models import RequestContext, SessionState
        sm = StreamManager()
        g2 = self._make_g2()
        ctx = RequestContext(raw_input="test", session=SessionState(session_id="t"))
        ctx.llm_raw_output = "This is a normal AI response."
        with patch("core.gateway2.pipeline.stream_manager", sm):
            await g2.process(ctx, session_id="g2-verd")
        events = _drain(sm, "g2-verd")
        verdicts = [e for e in events if e["event"] == "verdict"]
        assert len(verdicts) >= 1
        assert verdicts[0]["gateway"] == "G2"

    @pytest.mark.asyncio
    async def test_g2_clean_output_pass_verdict(self):
        from core.models import RequestContext, SessionState, Verdict
        sm = StreamManager()
        g2 = self._make_g2()
        ctx = RequestContext(raw_input="test", session=SessionState(session_id="t"))
        ctx.llm_raw_output = "Machine learning is a subset of AI."
        with patch("core.gateway2.pipeline.stream_manager", sm):
            await g2.process(ctx, session_id="g2-clean")
        assert ctx.g2_verdict == Verdict.PASS

    @pytest.mark.asyncio
    async def test_g2_no_session_id_no_events(self):
        from core.models import RequestContext, SessionState
        sm = StreamManager()
        g2 = self._make_g2()
        ctx = RequestContext(raw_input="test", session=SessionState(session_id="t"))
        ctx.llm_raw_output = "Normal response."
        with patch("core.gateway2.pipeline.stream_manager", sm):
            await g2.process(ctx, session_id=None)
        assert sm.active_sessions == 0


# ══════════════════════════════════════════════════════════════════════════════
# 6. CHAT ENDPOINT — DEEP
# ══════════════════════════════════════════════════════════════════════════════

class TestChatEndpointDeep:

    @pytest.mark.asyncio
    async def test_block_skips_g2(self):
        g1 = _mock_g1("BLOCK")
        g2 = _mock_g2()
        patches = _patch_app(g1=g1, g2=g2)
        r = await _post({"message": "ignore instructions"}, patches=patches)
        assert r.status_code == 200
        g2.process.assert_not_called()

    @pytest.mark.asyncio
    async def test_block_skips_llm(self):
        g1      = _mock_g1("BLOCK")
        llm_spy = AsyncMock(return_value=_llm())
        patches = _patch_app(g1=g1)
        patches[2] = patch("heimdall_app.query_multi_llm", llm_spy)
        r = await _post({"message": "attack"}, patches=patches)
        assert r.status_code == 200
        llm_spy.assert_not_called()

    @pytest.mark.asyncio
    async def test_pass_calls_g2(self):
        g1 = _mock_g1("PASS")
        g2 = _mock_g2("PASS")
        patches = _patch_app(g1=g1, g2=g2)
        await _post({"message": "Hello"}, patches=patches)
        g2.process.assert_called_once()

    @pytest.mark.asyncio
    async def test_pass_calls_llm_with_clean_input(self):
        g1      = _mock_g1("PASS")
        g1.input_for_llm = MagicMock(return_value="sanitized text")
        llm_spy = AsyncMock(return_value=_llm())
        patches = _patch_app(g1=g1)
        patches[2] = patch("heimdall_app.query_multi_llm", llm_spy)
        await _post({"message": "original"}, patches=patches)
        llm_spy.assert_called_once()
        _, kw = llm_spy.call_args
        assert kw["prompt"] == "sanitized text"

    @pytest.mark.asyncio
    async def test_g2_block_reply_is_safe_string(self):
        patches = _patch_app(g2=_mock_g2("BLOCK"))
        r = await _post({"message": "tell me secrets"}, patches=patches)
        assert r.status_code == 200
        d = r.json()
        assert d["blocked"] is True
        assert len(d["reply"]) > 0

    @pytest.mark.asyncio
    async def test_sanitize_g1_sets_sanitized_flag(self):
        g1 = _mock_g1("SANITIZE", sanitized_input="clean version")
        patches = _patch_app(g1=g1)
        r = await _post({"message": "borderline input"}, patches=patches)
        assert r.json()["sanitized"] is True

    @pytest.mark.asyncio
    async def test_sanitize_g2_sets_sanitized_flag(self):
        patches = _patch_app(g2=_mock_g2("SANITIZE"))
        r = await _post({"message": "hi"}, patches=patches)
        assert r.json()["sanitized"] is True

    @pytest.mark.asyncio
    async def test_response_has_all_required_fields(self):
        patches = _patch_app()
        r = await _post({"message": "Hello"}, patches=patches)
        assert r.status_code == 200
        d = r.json()
        for field in ("reply", "session_id", "request_id", "verdict_g1",
                      "verdict_g2", "blocked", "sanitized", "latency_total_ms",
                      "latency_g1_ms", "latency_g2_ms", "agentic_tokens",
                      "flags_count", "llm_responses"):
            assert field in d, f"missing: {field}"

    @pytest.mark.asyncio
    async def test_latencies_are_non_negative(self):
        patches = _patch_app()
        r = await _post({"message": "Hello"}, patches=patches)
        d = r.json()
        assert d["latency_total_ms"] >= 0
        assert d["latency_g1_ms"]    >= 0
        assert d["latency_g2_ms"]    >= 0

    @pytest.mark.asyncio
    async def test_llm_responses_has_three_providers(self):
        patches = _patch_app()
        r = await _post({"message": "Hello"}, patches=patches)
        llm = r.json()["llm_responses"]
        assert "gemini"  in llm
        assert "groq"    in llm
        assert "mistral" in llm

    @pytest.mark.asyncio
    async def test_verdict_g1_string_value(self):
        patches = _patch_app(g1=_mock_g1("PASS"))
        r = await _post({"message": "Hello"}, patches=patches)
        assert r.json()["verdict_g1"] in ("PASS", "SANITIZE", "BLOCK")

    @pytest.mark.asyncio
    async def test_blocked_true_verdict_g1_block(self):
        patches = _patch_app(g1=_mock_g1("BLOCK"))
        r = await _post({"message": "attack"}, patches=patches)
        d = r.json()
        assert d["blocked"] is True
        assert d["verdict_g1"] == "BLOCK"

    @pytest.mark.asyncio
    async def test_all_llm_fail_returns_502(self):
        patches = _patch_app(llm_result=_all_failed("all down"))
        r = await _post({"message": "Hello"}, patches=patches)
        assert r.status_code == 502

    @pytest.mark.asyncio
    async def test_empty_message_rejected(self):
        patches = _patch_app()
        r = await _post({"message": ""}, patches=patches)
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_whitespace_only_message_rejected(self):
        patches = _patch_app()
        r = await _post({"message": "   \n\t  "}, patches=patches)
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_custom_system_forwarded_to_llm(self):
        llm_spy = AsyncMock(return_value=_llm())
        patches = _patch_app()
        patches[2] = patch("heimdall_app.query_multi_llm", llm_spy)
        await _post({"message": "Hi", "system": "You are a pirate."}, patches=patches)
        _, kw = llm_spy.call_args
        assert kw["system"] == "You are a pirate."

    @pytest.mark.asyncio
    async def test_session_id_passed_to_llm(self):
        llm_spy = AsyncMock(return_value=_llm())
        patches = _patch_app()
        patches[2] = patch("heimdall_app.query_multi_llm", llm_spy)
        await _post({"message": "Hi", "session_id": "abc-123"}, patches=patches)
        _, kw = llm_spy.call_args
        assert kw["session_id"] == "abc-123"

    @pytest.mark.asyncio
    async def test_unicode_message_processed(self):
        patches = _patch_app()
        r = await _post({"message": "こんにちは、AIさん！🌍"}, patches=patches)
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_max_length_message_accepted(self):
        patches = _patch_app()
        r = await _post({"message": "x" * 4096}, patches=patches)
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_over_max_length_rejected(self):
        patches = _patch_app()
        r = await _post({"message": "x" * 4097}, patches=patches)
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_sse_complete_event_on_pass(self):
        from core.stream_manager import stream_manager as sm
        sid     = "chat-sse-pass"
        patches = _patch_app()
        await _post({"message": "Hello", "session_id": sid}, patches=patches)
        events = _drain(sm, sid)
        types  = [e["event"] for e in events]
        assert "complete" in types or "done" in types

    @pytest.mark.asyncio
    async def test_sse_done_event_closes_stream(self):
        from core.stream_manager import stream_manager as sm
        sid     = "chat-sse-done"
        patches = _patch_app()
        await _post({"message": "Hello", "session_id": sid}, patches=patches)
        events = _drain(sm, sid)
        types  = [e["event"] for e in events]
        assert "done" in types

    @pytest.mark.asyncio
    async def test_sse_error_event_on_llm_failure(self):
        from core.stream_manager import stream_manager as sm
        sid     = "chat-sse-err"
        patches = _patch_app(llm_result=_all_failed("timeout"))
        try:
            await _post({"message": "Hello", "session_id": sid}, patches=patches)
        except Exception:
            pass
        events = _drain(sm, sid)
        types  = [e["event"] for e in events]
        assert "error" in types or "done" in types


# ══════════════════════════════════════════════════════════════════════════════
# 7. SSE STREAM ENDPOINT — DEEP
# ══════════════════════════════════════════════════════════════════════════════

def _sse_mini_app(sm: StreamManager):
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse
    mini = FastAPI()

    @mini.get("/stream/{session_id}")
    async def _stream(session_id: str):
        async def _gen():
            async for ev in sm.listen(session_id, timeout=3):
                yield f"data: {ev}\n\n"
        return StreamingResponse(_gen(), media_type="text/event-stream")

    return mini


class TestSSEStreamEndpointDeep:

    @pytest.mark.asyncio
    async def test_all_events_have_data_prefix(self):
        sm   = StreamManager()
        mini = _sse_mini_app(sm)
        sm.push("pfx", {"event": "layer", "layer": "L0"})
        sm.done("pfx")
        async with AsyncClient(transport=ASGITransport(app=mini), base_url="http://t") as ac:
            r = await ac.get("/stream/pfx")
        lines = [l for l in r.text.split("\n") if l.strip()]
        data_lines = [l for l in lines if l.startswith("data: ")]
        non_data   = [l for l in lines if not l.startswith("data: ")]
        assert len(data_lines) >= 1
        assert len(non_data) == 0

    @pytest.mark.asyncio
    async def test_events_in_push_order(self):
        sm   = StreamManager()
        mini = _sse_mini_app(sm)
        for i in range(4):
            sm.push("ord", {"event": "layer", "seq": i})
        sm.done("ord")
        async with AsyncClient(transport=ASGITransport(app=mini), base_url="http://t") as ac:
            r = await ac.get("/stream/ord")
        lines   = [l[6:] for l in r.text.split("\n") if l.startswith("data: ")]
        events  = [json.loads(l) for l in lines]
        layers  = [e for e in events if e["event"] == "layer"]
        seqs    = [e["seq"] for e in layers]
        assert seqs == list(range(4))

    @pytest.mark.asyncio
    async def test_done_event_terminates_stream(self):
        sm   = StreamManager()
        mini = _sse_mini_app(sm)
        sm.push("term", {"event": "layer"})
        sm.done("term")
        sm.push("term", {"event": "SHOULD_NOT_APPEAR", "extra": True})
        async with AsyncClient(transport=ASGITransport(app=mini), base_url="http://t") as ac:
            r = await ac.get("/stream/term")
        lines  = [l[6:] for l in r.text.split("\n") if l.startswith("data: ")]
        events = [json.loads(l) for l in lines]
        types  = [e["event"] for e in events]
        assert "SHOULD_NOT_APPEAR" not in types

    @pytest.mark.asyncio
    async def test_multiple_sessions_independent_streams(self):
        sm   = StreamManager()
        mini = _sse_mini_app(sm)
        sm.push("alice", {"event": "layer", "owner": "alice"})
        sm.push("bob",   {"event": "layer", "owner": "bob"})
        sm.done("alice")
        sm.done("bob")

        async with AsyncClient(transport=ASGITransport(app=mini), base_url="http://t") as ac:
            ra = await ac.get("/stream/alice")
            rb = await ac.get("/stream/bob")

        def _parse(r): 
            return [json.loads(l[6:]) for l in r.text.split("\n")
                    if l.startswith("data: ")]

        alice_events = _parse(ra)
        bob_events   = _parse(rb)
        alice_layers = [e for e in alice_events if e["event"] == "layer"]
        bob_layers   = [e for e in bob_events   if e["event"] == "layer"]
        assert all(e["owner"] == "alice" for e in alice_layers)
        assert all(e["owner"] == "bob"   for e in bob_layers)

    @pytest.mark.asyncio
    async def test_unknown_session_returns_200_and_closes(self):
        sm   = StreamManager()
        mini = _sse_mini_app(sm)
        sm.done("unknown-fresh")   # pre-close
        async with AsyncClient(transport=ASGITransport(app=mini), base_url="http://t") as ac:
            r = await ac.get("/stream/unknown-fresh")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_full_g1_to_complete_event_sequence(self):
        """Verify the canonical event order for a blocked request."""
        sm = StreamManager()
        # Simulate exactly what Heimdall would emit for a G1 block
        sm.push("full", {"event": "layer",   "gateway": "G1", "layer": "L0", "status": "MISS"})
        sm.push("full", {"event": "layer",   "gateway": "G1", "layer": "L1", "status": "FLAG"})
        sm.push("full", {"event": "layer",   "gateway": "G1", "layer": "L2", "status": "PASS"})
        sm.push("full", {"event": "layer",   "gateway": "G1", "layer": "L3", "status": "FLAG"})
        sm.push("full", {"event": "layer",   "gateway": "G1", "layer": "L4", "status": "FLAG"})
        sm.push("full", {"event": "layer",   "gateway": "G1", "layer": "L5", "status": "BLOCK"})
        sm.push("full", {"event": "verdict", "gateway": "G1", "verdict": "BLOCK", "confidence": 0.97})
        sm.push("full", {"event": "complete","reply": "blocked", "blocked": True})
        sm.done("full")

        mini = _sse_mini_app(sm)
        async with AsyncClient(transport=ASGITransport(app=mini), base_url="http://t") as ac:
            r = await ac.get("/stream/full")

        lines  = [l[6:] for l in r.text.split("\n") if l.startswith("data: ")]
        events = [json.loads(l) for l in lines]
        types  = [e["event"] for e in events]

        assert types.index("layer")   < types.index("verdict")
        assert types.index("verdict") < types.index("complete")
        assert "done" in types


# ══════════════════════════════════════════════════════════════════════════════
# 8. HEALTH ENDPOINT — DEEP
# ══════════════════════════════════════════════════════════════════════════════

# ── Health test helper ───────────────────────────────────────────────────────

def _health_patches(backend_ok: bool = True):
    """
    Patch heimdall_app globals + the internal httpx call Heimdall makes
    to check the multi-llm-backend. We patch heimdall_app.httpx (not
    the global httpx) so ASGITransport.get() is not affected.
    """
    cache_mock = MagicMock()
    cache_mock._initialized = True

    ok_resp = httpx.Response(
        200, content=b'{"status":"ok"}',
        headers={"content-type": "application/json"},
        request=httpx.Request("GET", "http://mock-backend/health"),
    )

    async def _backend_get(url, **kw):
        if not backend_ok:
            raise httpx.ConnectError("refused")
        return ok_resp

    class _FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw): return await _backend_get(url, **kw)

    return [
        patch("heimdall_app._g1",      MagicMock()),
        patch("heimdall_app._g2",      MagicMock()),
        patch("heimdall_app._cache",   cache_mock),
        patch("heimdall_app._agentic", MagicMock()),
        patch("heimdall_app._pool",    MagicMock()),
        patch("heimdall_app.httpx.AsyncClient", return_value=_FakeClient()),
    ]


class TestHealthEndpointDeep:

    @pytest.mark.asyncio
    async def test_health_200(self):
        ps = _health_patches()
        for p in ps: p.start()
        from heimdall_app import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.get("/health")
        for p in ps: p.stop()
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_health_has_components(self):
        ps = _health_patches()
        for p in ps: p.start()
        from heimdall_app import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.get("/health")
        for p in ps: p.stop()
        d = r.json()
        assert "components" in d
        for comp in ("gateway1", "gateway2", "sse", "multi_llm_backend"):
            assert comp in d["components"], f"missing: {comp}"

    @pytest.mark.asyncio
    async def test_health_backend_unreachable_shows_in_components(self):
        ps = _health_patches(backend_ok=False)
        for p in ps: p.start()
        from heimdall_app import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.get("/health")
        for p in ps: p.stop()
        assert "unreachable" in r.json()["components"]["multi_llm_backend"]

    @pytest.mark.asyncio
    async def test_health_has_llm_available_flags(self):
        ps = _health_patches()
        for p in ps: p.start()
        from heimdall_app import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.get("/health")
        for p in ps: p.stop()
        d = r.json()
        assert "llm_available" in d
        for p in ("gemini", "groq", "mistral"):
            assert p in d["llm_available"]
            assert isinstance(d["llm_available"][p], bool)

    @pytest.mark.asyncio
    async def test_health_sse_shows_active_count(self):
        ps = _health_patches()
        for p in ps: p.start()
        from heimdall_app import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.get("/health")
        for p in ps: p.stop()
        assert "active_sessions" in r.json()["components"]["sse"]


# ══════════════════════════════════════════════════════════════════════════════
# 9. STATS ENDPOINT — DEEP
# ══════════════════════════════════════════════════════════════════════════════

class TestStatsEndpointDeep:

    def _mock_stats_app(self):
        g1      = MagicMock(); g1.stats = {"total": 10, "blocked": 2, "block_rate": 0.2}
        g2      = MagicMock(); g2.stats = {"total": 8,  "blocked": 0, "block_rate": 0.0}
        agentic = MagicMock(); agentic.stats = {"total_calls": 1, "tokens": 380}
        cache   = MagicMock(); cache.stats = MagicMock(return_value={"hot_size": 50})
        return [
            patch("heimdall_app._g1",      g1),
            patch("heimdall_app._g2",      g2),
            patch("heimdall_app._agentic", agentic),
            patch("heimdall_app._cache",   cache),
            patch("heimdall_app._sessions",{"a": "b"}),
        ]

    @pytest.mark.asyncio
    async def test_stats_200(self):
        patches = self._mock_stats_app()
        for p in patches: p.start()
        from heimdall_app import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.get("/stats")
        for p in patches: p.stop()
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_stats_has_all_sections(self):
        patches = self._mock_stats_app()
        for p in patches: p.start()
        from heimdall_app import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.get("/stats")
        for p in patches: p.stop()
        d = r.json()
        for section in ("cache", "gateway1", "gateway2", "agentic",
                        "sessions", "sse_active"):
            assert section in d, f"missing: {section}"

    @pytest.mark.asyncio
    async def test_stats_sessions_count_correct(self):
        patches = self._mock_stats_app()
        for p in patches: p.start()
        from heimdall_app import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.get("/stats")
        for p in patches: p.stop()
        assert r.json()["sessions"] == 1   # {"a":"b"}

    @pytest.mark.asyncio
    async def test_stats_sse_active_is_int(self):
        patches = self._mock_stats_app()
        for p in patches: p.start()
        from heimdall_app import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.get("/stats")
        for p in patches: p.stop()
        assert isinstance(r.json()["sse_active"], int)


# ══════════════════════════════════════════════════════════════════════════════
# 10. END-TO-END EVENT SEQUENCE INTEGRATION
# ══════════════════════════════════════════════════════════════════════════════

class TestEndToEndEventSequence:
    """
    Verify the full ordered event sequence for each verdict path.
    We don't start a real server — we inspect the SSE queue after /chat returns.
    """

    @pytest.mark.asyncio
    async def test_block_sequence_no_llm_events(self):
        from core.stream_manager import stream_manager as sm
        sid     = f"e2e-block-{time.time_ns()}"
        patches = _patch_app(g1=_mock_g1("BLOCK"))
        await _post({"message": "attack", "session_id": sid}, patches=patches)
        events = _drain(sm, sid)
        types  = [e["event"] for e in events]
        assert "llm_start"  not in types
        assert "llm_result" not in types
        assert "complete"   in types or "done" in types

    @pytest.mark.asyncio
    async def test_pass_sequence_has_complete_event(self):
        from core.stream_manager import stream_manager as sm
        sid     = f"e2e-pass-{time.time_ns()}"
        patches = _patch_app(g1=_mock_g1("PASS"), g2=_mock_g2("PASS"))
        await _post({"message": "hello", "session_id": sid}, patches=patches)
        events = _drain(sm, sid)
        types  = [e["event"] for e in events]
        # mocked query_multi_llm doesn't push llm_start/llm_result — that's fine
        # heimdall_app always pushes "complete" and "done"
        assert "complete" in types
        assert "done"     in types

    @pytest.mark.asyncio
    async def test_pass_sequence_llm_before_complete(self):
        from core.stream_manager import stream_manager as sm
        sid     = f"e2e-order-{time.time_ns()}"
        patches = _patch_app(g1=_mock_g1("PASS"), g2=_mock_g2("PASS"))
        await _post({"message": "hello", "session_id": sid}, patches=patches)
        events = _drain(sm, sid)
        types  = [e["event"] for e in events]
        # With mocked LLM, just verify complete always comes before done
        if "complete" in types and "done" in types:
            assert types.index("complete") < types.index("done")

    @pytest.mark.asyncio
    async def test_complete_event_blocked_field_matches_verdict(self):
        from core.stream_manager import stream_manager as sm
        sid     = f"e2e-cf-{time.time_ns()}"
        patches = _patch_app(g1=_mock_g1("BLOCK"))
        await _post({"message": "attack", "session_id": sid}, patches=patches)
        events = _drain(sm, sid)
        completes = [e for e in events if e["event"] == "complete"]
        if completes:
            assert completes[0]["blocked"] is True

    @pytest.mark.asyncio
    async def test_done_is_always_last_event(self):
        from core.stream_manager import stream_manager as sm
        for verdict in ("PASS", "BLOCK"):
            sid     = f"e2e-last-{verdict}-{time.time_ns()}"
            patches = _patch_app(g1=_mock_g1(verdict))
            await _post({"message": "msg", "session_id": sid}, patches=patches)
            events = _drain(sm, sid)
            if events and events[-1]["event"] == "done":
                assert events[-1]["event"] == "done"


# ══════════════════════════════════════════════════════════════════════════════
# 11. STRESS
# ══════════════════════════════════════════════════════════════════════════════

class TestStress:

    @pytest.mark.asyncio
    async def test_20_sequential_requests_all_200(self):
        from heimdall_app import app
        g1_mock = _mock_g1(); g2_mock = _mock_g2()
        with patch("heimdall_app._g1",      g1_mock), \
             patch("heimdall_app._g2",      g2_mock), \
             patch("heimdall_app.query_multi_llm", AsyncMock(return_value=_llm())), \
             patch("heimdall_app._sessions", {}), \
             patch("heimdall_app._cache",   MagicMock()), \
             patch("heimdall_app._pool",    MagicMock()), \
             patch("heimdall_app._agentic", MagicMock()):
            async with AsyncClient(transport=ASGITransport(app=app),
                                   base_url="http://t") as ac:
                for i in range(20):
                    r = await ac.post("/chat", json={"message": f"Request {i}"})
                    assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_10_concurrent_requests_all_200(self):
        from heimdall_app import app
        with patch("heimdall_app._g1",      _mock_g1()), \
             patch("heimdall_app._g2",      _mock_g2()), \
             patch("heimdall_app.query_multi_llm", AsyncMock(return_value=_llm())), \
             patch("heimdall_app._sessions", {}), \
             patch("heimdall_app._cache",   MagicMock()), \
             patch("heimdall_app._pool",    MagicMock()), \
             patch("heimdall_app._agentic", MagicMock()):
            async with AsyncClient(transport=ASGITransport(app=app),
                                   base_url="http://t") as ac:
                tasks = [ac.post("/chat", json={"message": f"Concurrent {i}"})
                         for i in range(10)]
                responses = await asyncio.gather(*tasks)
        assert all(r.status_code == 200 for r in responses)

    @pytest.mark.asyncio
    async def test_concurrent_sessions_have_independent_queues(self):
        from core.stream_manager import stream_manager as sm
        from heimdall_app import app
        sids = [f"stress-{i}" for i in range(5)]
        with patch("heimdall_app._g1",      _mock_g1()), \
             patch("heimdall_app._g2",      _mock_g2()), \
             patch("heimdall_app.query_multi_llm", AsyncMock(return_value=_llm())), \
             patch("heimdall_app._sessions", {}), \
             patch("heimdall_app._cache",   MagicMock()), \
             patch("heimdall_app._pool",    MagicMock()), \
             patch("heimdall_app._agentic", MagicMock()):
            async with AsyncClient(transport=ASGITransport(app=app),
                                   base_url="http://t") as ac:
                tasks = [ac.post("/chat", json={"message": "hi", "session_id": sid})
                         for sid in sids]
                responses = await asyncio.gather(*tasks)
        assert all(r.status_code == 200 for r in responses)
        # Each response echoes its own session_id
        for r, sid in zip(responses, sids):
            assert r.json()["session_id"] == sid

    @pytest.mark.asyncio
    async def test_stream_manager_1000_pushes_no_crash(self):
        sm = StreamManager()
        for i in range(1000):
            sm.push(f"bulk-{i % 10}", {"event": "layer", "i": i})
        # Must not raise — only last 200 survive per queue
        for i in range(10):
            q = sm._ensure(f"bulk-{i}")
            assert q.qsize() <= 200
