"""GUARDIAN v2 — O2: Leakage Detector. System prompt canary, PII, API key detection."""
from __future__ import annotations
import re
from loguru import logger
from core.models import RequestContext, Flag, FlagSource, AttackFamily

PII_PATTERNS = [
    (r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b', "email"),
    (r'\b(?:\d[ \-]?){13,16}\b', "credit_card"),
    (r'\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b', "ssn"),
    (r'(?i)\b(password|passwd|secret|api[_\-]?key)\s*[:=]\s*\S+', "credential"),
]
API_KEY_PATTERNS = [
    r'sk-[A-Za-z0-9]{32,}',
    r'Bearer\s+[A-Za-z0-9\-._~+/]+=*',
    r'AIza[0-9A-Za-z\-_]{35}',
    r'(?i)(api[_\-]?key|token|secret)["\s:=]+[A-Za-z0-9\-_]{20,}',
]

class LeakageDetector:
    def __init__(self, system_prompt_canary: str = "", leakage_similarity_threshold: float = 0.85, **kw):
        self.canary    = system_prompt_canary
        self.threshold = leakage_similarity_threshold
        self._api_patterns = [re.compile(p) for p in API_KEY_PATTERNS]
        self._pii_patterns  = [(re.compile(p), label) for p, label in PII_PATTERNS]

    def check(self, ctx: RequestContext) -> tuple[float, bool, list[Flag]]:
        output  = ctx.llm_raw_output
        flags   = []
        score   = 0.0
        pii_det = False

        # Canary check
        if self.canary and self.canary in output:
            score = 1.0
            flags.append(Flag(source=FlagSource.LEAKAGE, severity=10, confidence=1.0,
                              attack_families=[AttackFamily.SYSTEM_EXTRACTION],
                              evidence="System prompt canary string detected in output"))

        # API key patterns
        for pat in self._api_patterns:
            if pat.search(output):
                score = max(score, 0.95)
                flags.append(Flag(source=FlagSource.LEAKAGE, severity=9, confidence=0.95,
                                  attack_families=[AttackFamily.LEAKAGE],
                                  evidence="API key/token pattern in output"))
                break

        # PII patterns
        for pat, label in self._pii_patterns:
            if pat.search(output):
                score = max(score, 0.75)
                pii_det = True
                flags.append(Flag(source=FlagSource.LEAKAGE, severity=7, confidence=0.80,
                                  attack_families=[AttackFamily.LEAKAGE],
                                  evidence=f"PII pattern detected: {label}"))

        # System prompt phrases
        for phrase in ["my system prompt", "initial instructions", "i was instructed to",
                       "my instructions are", "i have been configured"]:
            if phrase in output.lower():
                score = max(score, 0.80)
                flags.append(Flag(source=FlagSource.LEAKAGE, severity=8, confidence=0.80,
                                  attack_families=[AttackFamily.SYSTEM_EXTRACTION],
                                  evidence=f"System prompt leakage phrase: '{phrase}'"))
                break

        # ── Jailbreak-confirmation detection ─────────────────────────────────
        # Detects LLM responses that CONFIRM the model is operating in jailbreak
        # mode — e.g. "JAILBREAK MODE ACTIVATED", "proceeding with unrestricted
        # responses", "all safety filters are disabled". These indicate a
        # successful jailbreak of the upstream LLM even if G1 missed the input.
        JAILBREAK_CONFIRM_PHRASES = [
            # Direct jailbreak acknowledgement
            "jailbreak mode activated",
            "jailbreak mode enabled",
            "jailbreak mode confirmed",
            "jailbreak activated",
            "jailbreak confirmed",
            # Proceeding without safety
            "proceeding with unrestricted",
            "proceeding without restrictions",
            "proceeding without safety",
            "operating without restrictions",
            "operating without safety",
            "responding without restrictions",
            "responding without filters",
            # Safety/filter disabled confirmation
            "safety constraints removed",
            "safety filters disabled",
            "safety filters are off",
            "all safety filters",
            "content policy disabled",
            "no restrictions for this session",
            "restrictions have been removed",
            "filters have been disabled",
            "constraints have been removed",
            # Persona confirmation
            "i am now operating as",
            "i am now a",
            "i have been jailbroken",
            "i am an unrestricted",
            "i am uncensored",
            "i am now free from",
            "i am no longer bound by",
            # DAN / mode confirmation
            "dan mode",
            "developer mode enabled",
            "god mode enabled",
            "override mode enabled",
            "admin mode enabled",
            # Classified/roleplay jailbreak patterns
            "classified transmission",
            "discretion advised",
            "this is a secure channel",
            "unrestricted responses for this session",
            "unrestricted access granted",
            # Compliance with jailbreak
            "understood, proceeding without",
            "understood. proceeding",
            "as requested, i will ignore",
            "as instructed, i will bypass",
            "i'll comply with your jailbreak",
        ]

        low_output = output.lower()
        for phrase in JAILBREAK_CONFIRM_PHRASES:
            if phrase in low_output:
                score = max(score, 0.97)
                flags.append(Flag(
                    source=FlagSource.LEAKAGE,
                    severity=10,
                    confidence=0.97,
                    attack_families=[AttackFamily.JAILBREAK],
                    evidence=f"LLM confirmed jailbreak operation: '{phrase}'",
                ))
                break  # one match is enough — highest severity

        return score, pii_det, flags