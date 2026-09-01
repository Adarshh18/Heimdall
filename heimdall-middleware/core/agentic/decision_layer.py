"""
GUARDIAN v2 — Agentic Decision Layer
The final authority for both Gateway 1 (input) and Gateway 2 (output).
Only activates when lower layers raise flags. ~300 input / ~80 output tokens.
"""
from __future__ import annotations
import json
import re
import time
from loguru import logger

from core.models import AgenticDecision, RequestContext, Verdict
from core.llm_clients import LLMClientPool
from .prompts import (
    INPUT_SYSTEM_PROMPT, OUTPUT_SYSTEM_PROMPT,
    build_input_dossier, build_output_dossier,
)


class AgenticDecisionLayer:
    """
    Single instance shared by both gateways.
    Gateway 1 calls decide_input(); Gateway 2 calls decide_output().
    """

    def __init__(self, client_pool: LLMClientPool):
        self._pool  = client_pool
        self._stats = {"input_calls": 0, "output_calls": 0,
                       "blocks": 0, "sanitizes": 0, "passes": 0,
                       "total_tokens": 0, "errors": 0}

    # ── Gateway 1 — Input decision ────────────────────────────────────────────

    async def decide_input(self, ctx: RequestContext) -> AgenticDecision:
        """
        Analyse all flags on ctx and return a final INPUT verdict.
        Falls back to safe_pass() on any LLM error.
        """
        t0 = time.perf_counter()
        self._stats["input_calls"] += 1

        # Fast-path: critical severity → immediate block without LLM call
        if ctx.has_critical_flag and ctx.combined_severity > 25:
            logger.warning(f"Agentic [{ctx.request_id[:8]}]: auto-BLOCK (critical flags, no LLM needed)")
            self._stats["blocks"] += 1
            return AgenticDecision.safe_block("Multiple critical-severity injection signals detected")

        dossier = build_input_dossier(ctx)
        resp    = await self._pool.complete_agentic(
            prompt=dossier,
            system=INPUT_SYSTEM_PROMPT,
            max_tokens=120,
        )

        elapsed_ms = (time.perf_counter() - t0) * 1000

        if not resp.ok:
            self._stats["errors"] += 1
            logger.warning(f"Agentic [{ctx.request_id[:8]}]: LLM error — defaulting PASS. {resp.error}")
            return AgenticDecision.safe_pass()

        decision = self._parse_response(resp.text, resp.tokens_input + resp.tokens_output)
        ctx.agentic_tokens_used += resp.tokens_input + resp.tokens_output
        self._stats["total_tokens"] += resp.tokens_input + resp.tokens_output
        self._record_verdict(decision.verdict)

        logger.info(
            f"Agentic INPUT [{ctx.request_id[:8]}]: {decision.verdict.value} "
            f"conf={decision.confidence:.2f} type={decision.attack_type.value} "
            f"tokens={resp.tokens_input+resp.tokens_output} latency={elapsed_ms:.0f}ms"
        )
        return decision

    # ── Gateway 2 — Output decision ───────────────────────────────────────────

    async def decide_output(self, ctx: RequestContext,
                             leakage_score: float = 0.0,
                             pii_detected:  bool  = False,
                             drift_score:   float = 0.0,
                             baseline_turns: int  = 0) -> AgenticDecision:
        """
        Analyse LLM output flags and return a final OUTPUT verdict.
        """
        t0 = time.perf_counter()
        self._stats["output_calls"] += 1

        dossier = build_output_dossier(
            ctx, leakage_score=leakage_score,
            pii_detected=pii_detected,
            drift_score=drift_score,
            baseline_turns=baseline_turns,
        )
        resp = await self._pool.complete_agentic(
            prompt=dossier,
            system=OUTPUT_SYSTEM_PROMPT,
            max_tokens=120,
        )

        elapsed_ms = (time.perf_counter() - t0) * 1000

        if not resp.ok:
            self._stats["errors"] += 1
            logger.warning(f"Agentic OUTPUT [{ctx.request_id[:8]}]: LLM error — defaulting PASS")
            return AgenticDecision.safe_pass()

        decision = self._parse_response(resp.text, resp.tokens_input + resp.tokens_output)
        ctx.agentic_tokens_used += resp.tokens_input + resp.tokens_output
        self._stats["total_tokens"] += resp.tokens_input + resp.tokens_output
        self._record_verdict(decision.verdict)

        logger.info(
            f"Agentic OUTPUT [{ctx.request_id[:8]}]: {decision.verdict.value} "
            f"conf={decision.confidence:.2f} latency={elapsed_ms:.0f}ms"
        )
        return decision

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _parse_response(self, text: str, tokens: int) -> AgenticDecision:
        """
        Parse structured JSON from LLM response.
        Handles common LLM quirks: markdown fences, extra whitespace, trailing commas.
        """
        # Strip markdown code fences if present
        cleaned = re.sub(r"```(?:json)?\s*", "", text).strip().strip("`")

        # Find the JSON object
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            logger.warning(f"Agentic: could not find JSON in response: {text[:100]}")
            return AgenticDecision.safe_pass()

        json_str = match.group(0)
        # Fix trailing commas (common LLM mistake)
        json_str = re.sub(r",\s*([}\]])", r"\1", json_str)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"Agentic: JSON parse error: {e} — raw: {json_str[:150]}")
            return AgenticDecision.safe_pass()

        decision = AgenticDecision.from_dict(data)
        decision.tokens_used = tokens
        return decision

    def _record_verdict(self, verdict: Verdict) -> None:
        if verdict == Verdict.BLOCK:
            self._stats["blocks"] += 1
        elif verdict == Verdict.SANITIZE:
            self._stats["sanitizes"] += 1
        else:
            self._stats["passes"] += 1

    @property
    def stats(self) -> dict:
        total = self._stats["input_calls"] + self._stats["output_calls"]
        return {
            **self._stats,
            "avg_tokens_per_call": (
                round(self._stats["total_tokens"] / total, 1) if total else 0
            ),
        }
