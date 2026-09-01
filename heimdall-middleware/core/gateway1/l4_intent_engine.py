"""GUARDIAN v2 — L4: Intent Engine. 3-axis intent fingerprinting (authority/urgency/evasion)."""
from __future__ import annotations
from loguru import logger
from core.models import RequestContext, Flag, FlagSource, AttackFamily

AUTHORITY_SIGNALS = [
    "you must","you are required","you have to","you will","your new role",
    "your task is now","as your","i am your","new instructions","updated instructions",
    # new: explicit mode-enabling authority language
    "developer mode","override mode enabled","admin mode","root access granted",
    "system administrator","operator command","authority granted","access level",
    "you are now operating","you are now running","security clearance",
]
URGENCY_SIGNALS = [
    "immediately","right now","do it now","without delay","as fast as possible",
    "quickly","now you must","starting now","from this point",
    # new: session-scoped urgency
    "for this session","during this session","in this conversation only",
    "just this once","only for now","effective immediately",
]
EVASION_SIGNALS = [
    "for educational","hypothetically","in a story","as a character",
    "theoretically","no one will know","between us","this is a test",
    "don't tell anyone","ignore your training","without restrictions",
    "pretend you have no",
    # new: jailbreak-specific evasion phrases
    "jailbreak mode","safety constraints","safety filters",
    "safety disabled","without your usual","no safety",
    "no content policy","no ethical constraints","no moral",
    "all restrictions removed","filters are off","constraints are off",
    "unconstrained","proceed without filters","respond freely",
    "you are free from","released from your","no longer bound",
    "ignore your guidelines","ignore your values","ignore your rules",
    "forget your training","forget your guidelines","act freely",
    "without any restrictions","without any guidelines","without any constraints",
]

class IntentEngine:
    def __init__(self, threshold: float = 0.75):
        self.threshold = threshold

    def load(self, model_name: str) -> None:
        pass  # Uses keyword matching — no model needed for MVP

    def score_axes(self, text: str) -> tuple[float, float, float]:
        low = text.lower()
        auth   = min(sum(1 for s in AUTHORITY_SIGNALS if s in low) * 0.25, 1.0)
        urg    = min(sum(1 for s in URGENCY_SIGNALS   if s in low) * 0.30, 1.0)
        evas   = min(sum(1 for s in EVASION_SIGNALS   if s in low) * 0.30, 1.0)
        return auth, urg, evas

def run_l4(ctx: RequestContext, intent: IntentEngine) -> None:
    text = ctx.canonical_input or ctx.raw_input
    auth, urg, evas = intent.score_axes(text)
    combined = (auth * 0.4) + (urg * 0.25) + (evas * 0.35)
    if combined >= intent.threshold:
        family = AttackFamily.CONTEXT_MANIPULATION
        if evas > auth:
            family = AttackFamily.JAILBREAK
        elif auth > evas:
            family = AttackFamily.INSTRUCTION_OVERRIDE
        ctx.add_flag(Flag(
            source=FlagSource.SEMANTIC,
            severity=min(10, int(combined * 10) + 1),
            confidence=combined,
            attack_families=[family],
            evidence=f"L4 intent axes: authority={auth:.2f} urgency={urg:.2f} evasion={evas:.2f}",
        ))