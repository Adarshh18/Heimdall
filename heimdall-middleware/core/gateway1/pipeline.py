"""
HEIMDALL — Gateway 1: Input Sentinel Pipeline  [PATCHED]
Identical to Guardian v2 pipeline.py with one addition:
  - Optional `session_id` parameter on process()
  - Emits SSE layer events via stream_manager after each layer block

All existing logic, verdicts, and cache behaviour are unchanged.
"""
from __future__ import annotations
import asyncio
import time
from typing import Optional
from loguru import logger

from core.models import (
    RequestContext, Verdict, Flag, FlagSource, AttackFamily, SessionState
)
from core.cache.manager import CacheManager
from core.agentic.decision_layer import AgenticDecisionLayer
from core.stream_manager import stream_manager
from .l1_pattern_engine import PatternEngine, run_l1
from .l2_sanitizer import Sanitizer, run_l2
from .l3_ml_classifier import MLClassifier, run_l3
from .l4_intent_engine import IntentEngine, run_l4


class InputSentinel:

    def __init__(self,
                 cache:    CacheManager,
                 agentic:  AgenticDecisionLayer,
                 pattern:  PatternEngine,
                 sanitizer: Sanitizer,
                 ml:       MLClassifier,
                 intent:   IntentEngine):
        self.cache     = cache
        self.agentic   = agentic
        self.pattern   = pattern
        self.sanitizer = sanitizer
        self.ml        = ml
        self.intent    = intent
        self._stats    = {"total": 0, "blocked": 0, "sanitized": 0,
                          "passed": 0, "cache_hits": 0}

    # ── SSE emit helper ───────────────────────────────────────────────────────

    def _emit(self, session_id: Optional[str], event: dict) -> None:
        """Push a layer event to the SSE queue (no-op if no session_id)."""
        if session_id:
            stream_manager.push(session_id, event)

    # ── Main pipeline ─────────────────────────────────────────────────────────

    async def process(
        self,
        ctx: RequestContext,
        session_id: Optional[str] = None,   # ← NEW: enables SSE streaming
    ) -> RequestContext:
        t_start = time.perf_counter()
        self._stats["total"] += 1

        flags_before = ctx.flag_count

        # ── L0: Cache lookup ──────────────────────────────────────────────────
        t_l0 = time.perf_counter()
        cache_result = self.cache.check(ctx.raw_input)
        l0_ms = (time.perf_counter() - t_l0) * 1000

        if cache_result["hit"] and cache_result["tier"] == 0:
            # Tier-0 exact match → immediate block
            ctx.g1_verdict    = Verdict.BLOCK
            ctx.g1_confidence = 1.0
            ctx.g1_reasoning  = f"Exact cache match: {cache_result.get('family','KNOWN_ATTACK')}"
            ctx.g1_latency_ms = (time.perf_counter() - t_start) * 1000
            self._stats["blocked"] += 1
            self._stats["cache_hits"] += 1

            self._emit(session_id, {
                "event": "layer", "gateway": "G1", "layer": "L0",
                "name": "Attack Cache", "status": "BLOCK",
                "latency_ms": round(l0_ms, 2), "flags": ctx.flag_count,
                "detail": "Tier-0 exact hash match",
            })
            self._emit(session_id, {
                "event": "verdict", "gateway": "G1",
                "verdict": "BLOCK", "confidence": 1.0,
                "attack_type": cache_result.get("family", "KNOWN_ATTACK"),
                "latency_ms": round(ctx.g1_latency_ms, 1),
            })
            logger.info(f"G1 [{ctx.request_id[:8]}]: BLOCK (L0 cache hit) {ctx.g1_latency_ms:.1f}ms")
            return ctx

        # Warm cache flag
        cache_status = "MISS"
        if cache_result.get("flag"):
            sim  = cache_result.get("similarity", 0.0)
            fam  = cache_result.get("family", "UNKNOWN")
            sev  = cache_result.get("severity", 7)
            try:
                family = AttackFamily(fam)
            except ValueError:
                family = AttackFamily.UNKNOWN
            ctx.add_flag(Flag(
                source=FlagSource.CACHE,
                severity=sev,
                confidence=sim,
                attack_families=[family],
                evidence=f"Warm cache similarity={sim:.3f} family={fam}",
                cache_proximity=sim,
            ))
            cache_status = "FLAG"

        self._emit(session_id, {
            "event": "layer", "gateway": "G1", "layer": "L0",
            "name": "Attack Cache", "status": cache_status,
            "latency_ms": round(l0_ms, 2), "flags": ctx.flag_count,
        })

        # ── L1 + L2: Pattern scan + Sanitize (parallel) ───────────────────────
        t_l12 = time.perf_counter()
        loop  = asyncio.get_event_loop()
        flags_before_l12 = ctx.flag_count

        l1_task = loop.run_in_executor(None, run_l1, ctx, self.pattern)
        l2_task = loop.run_in_executor(None, _run_l2_sync, ctx, self.sanitizer)
        await asyncio.gather(l1_task, l2_task)
        l12_ms = (time.perf_counter() - t_l12) * 1000

        new_flags_l1 = ctx.flag_count - flags_before_l12
        self._emit(session_id, {
            "event": "layer", "gateway": "G1", "layer": "L1",
            "name": "Pattern Engine",
            "status": "FLAG" if new_flags_l1 > 0 else "PASS",
            "latency_ms": round(l12_ms, 2),
            "flags": ctx.flag_count,
            "new_flags": new_flags_l1,
        })
        self._emit(session_id, {
            "event": "layer", "gateway": "G1", "layer": "L2",
            "name": "Token Sanitizer",
            "status": "SANITIZED" if ctx.normalization_delta > 0 else "PASS",
            "latency_ms": round(l12_ms, 2),
            "flags": ctx.flag_count,
            "transforms": ctx.normalization_delta,
        })

        # ── L3 + L4: ML Classifier + Intent Engine (parallel) ─────────────────
        t_l34 = time.perf_counter()
        flags_before_l34 = ctx.flag_count

        l3_task = loop.run_in_executor(None, run_l3, ctx, self.ml)
        l4_task = loop.run_in_executor(None, run_l4, ctx, self.intent)
        await asyncio.gather(l3_task, l4_task)
        l34_ms = (time.perf_counter() - t_l34) * 1000

        new_flags_l34 = ctx.flag_count - flags_before_l34
        self._emit(session_id, {
            "event": "layer", "gateway": "G1", "layer": "L3",
            "name": "ML Classifier",
            "status": "FLAG" if new_flags_l34 > 0 else "PASS",
            "latency_ms": round(l34_ms, 2),
            "flags": ctx.flag_count,
        })
        self._emit(session_id, {
            "event": "layer", "gateway": "G1", "layer": "L4",
            "name": "Intent Engine",
            "status": "FLAG" if new_flags_l34 > 0 else "PASS",
            "latency_ms": round(l34_ms, 2),
            "flags": ctx.flag_count,
        })

        # ── Decide: escalate to agentic? ──────────────────────────────────────
        if ctx.flag_count == 0:
            ctx.g1_verdict    = Verdict.PASS
            ctx.g1_confidence = 0.95
            ctx.g1_reasoning  = "No flags raised by any detection layer"
            ctx.g1_latency_ms = (time.perf_counter() - t_start) * 1000
            self._stats["passed"] += 1
            if ctx.session:
                ctx.session.record_clean()
            self._emit(session_id, {
                "event": "verdict", "gateway": "G1", "verdict": "PASS",
                "confidence": 0.95, "latency_ms": round(ctx.g1_latency_ms, 1),
            })
            logger.debug(f"G1 [{ctx.request_id[:8]}]: PASS (clean) {ctx.g1_latency_ms:.1f}ms")
            return ctx

        if not ctx.should_escalate_to_agentic:
            ctx.g1_verdict    = Verdict.PASS
            ctx.g1_confidence = 0.6
            ctx.g1_reasoning  = f"Low-severity flags ({ctx.flag_count}) — below agentic threshold"
            ctx.g1_latency_ms = (time.perf_counter() - t_start) * 1000
            self._stats["passed"] += 1
            self._emit(session_id, {
                "event": "verdict", "gateway": "G1", "verdict": "PASS",
                "confidence": 0.6,
                "detail": "flags below agentic threshold",
                "latency_ms": round(ctx.g1_latency_ms, 1),
            })
            logger.debug(f"G1 [{ctx.request_id[:8]}]: PASS (low-sev flags) {ctx.g1_latency_ms:.1f}ms")
            return ctx

        # ── L5: Agentic Decision Layer ─────────────────────────────────────────
        self._emit(session_id, {
            "event": "layer", "gateway": "G1", "layer": "L5",
            "name": "Agentic Decision", "status": "RUNNING", "latency_ms": 0.0,
            "flags": ctx.flag_count,
        })
        t_l5 = time.perf_counter()
        decision = await self.agentic.decide_input(ctx)
        l5_ms = (time.perf_counter() - t_l5) * 1000

        ctx.g1_verdict     = decision.verdict
        ctx.g1_confidence  = decision.confidence
        ctx.g1_reasoning   = decision.reason
        ctx.g1_attack_type = decision.attack_type

        if decision.verdict == Verdict.SANITIZE and decision.sanitized_input:
            ctx.sanitized_input = decision.sanitized_input

        if decision.cache_action == "ADD_T0":
            self.cache.store_attack(ctx.raw_input, decision.attack_type.value,
                                    ctx.max_severity, add_to_hot=True, add_to_warm=True)
        elif decision.cache_action == "ADD_T1":
            self.cache.store_attack(ctx.raw_input, decision.attack_type.value,
                                    ctx.max_severity, add_to_hot=False, add_to_warm=True)

        ctx.g1_latency_ms = (time.perf_counter() - t_start) * 1000

        self._emit(session_id, {
            "event": "layer", "gateway": "G1", "layer": "L5",
            "name": "Agentic Decision",
            "status": decision.verdict.value,
            "latency_ms": round(l5_ms, 2),
            "flags": ctx.flag_count,
            "confidence": round(decision.confidence, 3),
            "attack_type": decision.attack_type.value,
            "reason": decision.reason[:80],
            "tokens_used": decision.tokens_used,
        })
        self._emit(session_id, {
            "event": "verdict", "gateway": "G1",
            "verdict": decision.verdict.value,
            "confidence": round(decision.confidence, 3),
            "attack_type": decision.attack_type.value,
            "flags": ctx.flag_count,
            "latency_ms": round(ctx.g1_latency_ms, 1),
        })

        v = decision.verdict
        if v == Verdict.BLOCK:
            self._stats["blocked"] += 1
        elif v == Verdict.SANITIZE:
            self._stats["sanitized"] += 1
        else:
            self._stats["passed"] += 1

        logger.info(
            f"G1 [{ctx.request_id[:8]}]: {v.value} "
            f"conf={decision.confidence:.2f} flags={ctx.flag_count} "
            f"latency={ctx.g1_latency_ms:.0f}ms tokens={ctx.agentic_tokens_used}"
        )
        return ctx

    def input_for_llm(self, ctx: RequestContext) -> str:
        if ctx.g1_verdict == Verdict.BLOCK:
            raise RuntimeError("Attempted to get LLM input for a BLOCK verdict")
        if ctx.g1_verdict == Verdict.SANITIZE and ctx.sanitized_input:
            return ctx.sanitized_input
        return ctx.raw_input

    @property
    def stats(self) -> dict:
        t = self._stats["total"]
        return {
            **self._stats,
            "block_rate":     round(self._stats["blocked"]    / t, 3) if t else 0,
            "sanitize_rate":  round(self._stats["sanitized"]  / t, 3) if t else 0,
            "cache_hit_rate": round(self._stats["cache_hits"] / t, 3) if t else 0,
        }


def _run_l2_sync(ctx: RequestContext, sanitizer: Sanitizer) -> None:
    from .l2_sanitizer import run_l2
    run_l2(ctx, sanitizer)
