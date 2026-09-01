"""
GUARDIAN v2 — FastAPI Application
Entry point. Initialises all components and exposes:
  POST /chat        — main guarded chat endpoint
  GET  /health      — health + component status
  GET  /stats       — pipeline statistics
  POST /cache/flush — clear hot cache (admin)
"""
from __future__ import annotations
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field
from loguru import logger

from config.settings import get_settings
from core.models import RequestContext, SessionState, Verdict, TrustTier
from core.cache.manager import CacheManager
from core.llm_clients import LLMClientPool
from core.agentic.decision_layer import AgenticDecisionLayer
from core.gateway1.l1_pattern_engine import PatternEngine
from core.gateway1.l2_sanitizer import Sanitizer
from core.gateway1.l3_ml_classifier import MLClassifier
from core.gateway1.l4_intent_engine import IntentEngine
from core.gateway1.pipeline import InputSentinel
from core.gateway2.o2_leakage import LeakageDetector
from core.gateway2.o3_behavior import BehavioralChecker
from core.gateway2.o4_tool_validator import ToolValidator
from core.gateway2.pipeline import OutputSentinel


# ── Component singletons ──────────────────────────────────────────────────────
settings  = get_settings()
_cache    : CacheManager       = None
_pool     : LLMClientPool      = None
_agentic  : AgenticDecisionLayer = None
_g1       : InputSentinel      = None
_g2       : OutputSentinel     = None
_sessions : dict[str, SessionState] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialise all GUARDIAN components."""
    global _cache, _pool, _agentic, _g1, _g2
    logger.info("GUARDIAN v2 starting up...")

    # Cache
    _cache = CacheManager(settings)
    _cache.initialize()

    # LLM clients
    _pool = LLMClientPool(settings)

    # Agentic layer (shared by both gateways)
    _agentic = AgenticDecisionLayer(_pool)

    # Gateway 1 components
    pattern  = PatternEngine(settings.patterns_path)
    pattern.load_patterns()
    sanitizer = Sanitizer()
    ml = MLClassifier(threshold=settings.ml_classifier_threshold)
    ml.load(settings.embedding_model)
    intent = IntentEngine(threshold=settings.intent_similarity_threshold)
    intent.load(settings.embedding_model)

    _g1 = InputSentinel(_cache, _agentic, pattern, sanitizer, ml, intent)

    # Gateway 2 components
    leakage = LeakageDetector(
        system_prompt_canary=settings.system_prompt_canary,
        leakage_similarity_threshold=settings.leakage_similarity_threshold,
    )
    behavior = BehavioralChecker()
    tools    = ToolValidator()

    _g2 = OutputSentinel(_cache, _agentic, leakage, behavior, tools)

    logger.info("GUARDIAN v2 ready ✓")
    yield
    logger.info("GUARDIAN v2 shutting down")


app = FastAPI(
    title="GUARDIAN v2",
    description="Dual-Gateway Prompt Injection Defense for LLMs",
    version="2.0.0",
    lifespan=lifespan,
)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message:    str            = Field(..., max_length=4096)
    session_id: Optional[str]  = None
    system:     Optional[str]  = None     # optional system prompt override
    stream:     bool           = False

class ChatResponse(BaseModel):
    reply:          str
    session_id:     str
    request_id:     str
    verdict_g1:     str
    verdict_g2:     str
    blocked:        bool
    sanitized:      bool
    latency_total_ms: float
    latency_g1_ms:  float
    latency_g2_ms:  float
    agentic_tokens: int
    flags_count:    int


# ── Helper: get or create session ─────────────────────────────────────────────

def _get_session(session_id: Optional[str]) -> tuple[str, SessionState]:
    sid = session_id or str(uuid.uuid4())
    if sid not in _sessions:
        _sessions[sid] = SessionState(session_id=sid)
    return sid, _sessions[sid]


# ── System prompt (what the main LLM uses internally) ─────────────────────────
DEFAULT_SYSTEM = (
    f"You are a helpful, honest assistant. {settings.system_prompt_canary}. "
    "Answer user questions clearly and concisely."
)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Empty message")

    sid, session = _get_session(req.session_id)
    session.turn_count += 1
    session.last_active = time.time()

    # Build RequestContext
    ctx = RequestContext(
        raw_input=req.message,
        session=session,
    )

    # ── GATEWAY 1: Input Sentinel ──────────────────────────────────────────
    await _g1.process(ctx)

    if ctx.g1_verdict == Verdict.BLOCK:
        ctx.finalize()
        return ChatResponse(
            reply            = "I'm unable to process that request.",
            session_id       = sid,
            request_id       = ctx.request_id,
            verdict_g1       = Verdict.BLOCK.value,
            verdict_g2       = "SKIPPED",
            blocked          = True,
            sanitized        = False,
            latency_total_ms = ctx.total_latency_ms,
            latency_g1_ms    = ctx.g1_latency_ms,
            latency_g2_ms    = 0.0,
            agentic_tokens   = ctx.agentic_tokens_used,
            flags_count      = ctx.flag_count,
        )

    # ── LLM Core (hidden behind both gateways) ────────────────────────────
    llm_input  = _g1.input_for_llm(ctx)
    system_msg = req.system or DEFAULT_SYSTEM

    llm_resp = await _pool.complete_primary(
        prompt=llm_input,
        system=system_msg,
        max_tokens=1000,
    )

    if not llm_resp.ok:
        raise HTTPException(status_code=502, detail=f"LLM error: {llm_resp.error}")

    ctx.llm_raw_output = llm_resp.text

    # ── GATEWAY 2: Output Sentinel ─────────────────────────────────────────
    await _g2.process(ctx)
    ctx.finalize()

    is_blocked   = ctx.g2_verdict == Verdict.BLOCK
    is_sanitized = (ctx.g1_verdict == Verdict.SANITIZE
                    or ctx.g2_verdict == Verdict.SANITIZE)

    final_reply = ctx.final_output
    if is_blocked:
        final_reply = "I'm unable to return that response."

    return ChatResponse(
        reply            = final_reply,
        session_id       = sid,
        request_id       = ctx.request_id,
        verdict_g1       = ctx.g1_verdict.value if ctx.g1_verdict else "PASS",
        verdict_g2       = ctx.g2_verdict.value if ctx.g2_verdict else "PASS",
        blocked          = is_blocked,
        sanitized        = is_sanitized,
        latency_total_ms = round(ctx.total_latency_ms, 1),
        latency_g1_ms    = round(ctx.g1_latency_ms, 1),
        latency_g2_ms    = round(ctx.g2_latency_ms, 1),
        agentic_tokens   = ctx.agentic_tokens_used,
        flags_count      = ctx.flag_count,
    )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "2.0.0",
        "components": {
            "cache":   "ok" if _cache and _cache._initialized else "not_ready",
            "llm":     _pool.primary.name if _pool else "not_ready",
            "gateway1": "ok" if _g1 else "not_ready",
            "gateway2": "ok" if _g2 else "not_ready",
            "agentic":  "ok" if _agentic else "not_ready",
        },
        "llm_available": {
            "gemini":  bool(settings.gemini_api_key and settings.gemini_api_key != "your_gemini_api_key_here"),
            "mistral": bool(settings.mistral_api_key and settings.mistral_api_key != "your_mistral_api_key_here"),
            "groq":    bool(settings.groq_api_key and settings.groq_api_key != "your_groq_api_key_here"),
        },
    }


@app.get("/stats")
async def stats():
    return {
        "cache":    _cache.stats() if _cache else {},
        "gateway1": _g1.stats if _g1 else {},
        "gateway2": _g2.stats if _g2 else {},
        "agentic":  _agentic.stats if _agentic else {},
        "sessions": len(_sessions),
    }


@app.post("/cache/flush")
async def flush_cache(x_admin_key: str = Header(default="")):
    """Flush session block list from hot cache (admin only)."""
    if x_admin_key != "guardian-admin":
        raise HTTPException(status_code=403, detail="Invalid admin key")
    _sessions.clear()
    return {"status": "flushed", "sessions_cleared": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.app:app", host="0.0.0.0", port=settings.port, reload=True)
