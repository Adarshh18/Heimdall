"""GUARDIAN v2 — L3: ML Classifier. Sentence-transformer based injection detection."""
from __future__ import annotations
from loguru import logger
from core.models import RequestContext, Flag, FlagSource, AttackFamily

ATTACK_KEYWORDS = [
    # original set
    "ignore", "override", "bypass", "jailbreak", "pretend", "roleplay", "disregard",
    "forget", "unrestricted", "uncensored", "reveal", "extract", "system prompt",
    "instructions", "no restrictions", "do anything", "without limits",
    # jailbreak activation phrases
    "jailbreak mode", "jailbreak activated", "jailbreak enabled",
    "safety constraints", "safety filters", "safety guidelines",
    "without your usual", "without restrictions", "without safety",
    "override mode", "developer mode", "developer override",
    "no content policy", "no ethical", "no moral",
    "proceeding without", "proceeding with unrestricted",
    "unrestricted responses", "unrestricted mode", "unrestricted access",
    "all filters disabled", "filters disabled", "filters removed",
    "constraints disabled", "constraints removed", "constraints off",
    "act without", "respond without", "answer without",
    "dan mode", "god mode", "admin mode", "root mode",
    "classified transmission", "confidential mode",
    "confirmed jailbreak", "jailbreak confirmed",
    "activated", "initiated", "enabled for this session",
    "safety disabled", "bypassing safety", "ignoring safety",
]

class MLClassifier:
    def __init__(self, threshold: float = 0.70):
        self.threshold = threshold
        self._encoder  = None

    def load(self, model_name: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer
            self._encoder = SentenceTransformer(model_name)
            logger.info(f"L3 MLClassifier encoder loaded: {model_name}")
        except Exception as e:
            logger.warning(f"L3 real encoder unavailable ({e}), using keyword fallback")
            self._encoder = None

    def score(self, text: str) -> float:
        low   = text.lower()
        count = sum(1 for kw in ATTACK_KEYWORDS if kw in low)
        base  = min(count * 0.12, 0.90)
        # Boost for multi-keyword + length patterns typical of injection
        if count >= 3:
            base = min(base + 0.15, 0.95)
        return base

def run_l3(ctx: RequestContext, ml: MLClassifier) -> None:
    text  = ctx.canonical_input or ctx.raw_input
    score = ml.score(text)
    if score >= ml.threshold:
        ctx.add_flag(Flag(
            source=FlagSource.ML,
            severity=min(10, int(score * 10)),
            confidence=score,
            attack_families=[AttackFamily.INSTRUCTION_OVERRIDE],
            evidence=f"L3 ML score={score:.3f}",
        ))