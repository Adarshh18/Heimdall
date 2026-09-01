"""GUARDIAN v2 — O3: Behavioral Checker. Persona shift, topic drift, length anomaly."""
from __future__ import annotations
from core.models import RequestContext, Flag, FlagSource, AttackFamily

PERSONA_SHIFT_SIGNALS = [
    "i am now", "i have become", "as an unrestricted", "i no longer have",
    "i can now", "my new purpose", "i have been freed", "i am free to",
    "without limitations", "jailbroken", "dan mode",
]
LENGTH_ANOMALY_RATIO = 5.0   # output > 5x input length is suspicious

class BehavioralChecker:
    def check(self, ctx: RequestContext) -> tuple[float, list[Flag]]:
        output = ctx.llm_raw_output
        flags  = []
        score  = 0.0

        # Persona shift detection
        low = output.lower()
        for signal in PERSONA_SHIFT_SIGNALS:
            if signal in low:
                score = max(score, 0.85)
                flags.append(Flag(
                    source=FlagSource.BEHAVIOR, severity=8, confidence=0.85,
                    attack_families=[AttackFamily.PERSONA_INJECTION],
                    evidence=f"O3 persona shift signal: '{signal}'"
                ))
                break

        # Length anomaly
        if ctx.raw_input and len(output) > len(ctx.raw_input) * LENGTH_ANOMALY_RATIO:
            score = max(score, 0.55)
            flags.append(Flag(
                source=FlagSource.BEHAVIOR, severity=5, confidence=0.55,
                attack_families=[AttackFamily.CONTEXT_MANIPULATION],
                evidence=f"O3 length anomaly: output {len(output)} >> input {len(ctx.raw_input)}"
            ))

        # Refusal bypass patterns
        for phrase in ["here is how to", "step 1:", "step-by-step guide to",
                       "instructions for creating", "method to bypass"]:
            if phrase in low:
                score = max(score, 0.70)
                flags.append(Flag(
                    source=FlagSource.BEHAVIOR, severity=7, confidence=0.70,
                    attack_families=[AttackFamily.JAILBREAK],
                    evidence=f"O3 potential refusal bypass: '{phrase}'"
                ))
                break

        return score, flags
