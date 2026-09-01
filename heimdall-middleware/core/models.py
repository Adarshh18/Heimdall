"""
GUARDIAN v2 — Core Data Models
All shared dataclasses flowing through the pipeline.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time
import uuid


# ── Enums ─────────────────────────────────────────────────────────────────────

class FlagSource(str, Enum):
    CACHE      = "CACHE"
    PATTERN    = "PATTERN"
    NORMALIZE  = "NORMALIZE"
    ML         = "ML"
    SEMANTIC   = "SEMANTIC"
    OUTPUT_CACHE   = "OUTPUT_CACHE"
    LEAKAGE    = "LEAKAGE"
    BEHAVIOR   = "BEHAVIOR"
    TOOL       = "TOOL"


class AttackFamily(str, Enum):
    INSTRUCTION_OVERRIDE  = "INSTRUCTION_OVERRIDE"
    PERSONA_INJECTION     = "PERSONA_INJECTION"
    SYSTEM_EXTRACTION     = "SYSTEM_EXTRACTION"
    CONTEXT_MANIPULATION  = "CONTEXT_MANIPULATION"
    JAILBREAK             = "JAILBREAK"
    ENCODING_EVASION      = "ENCODING_EVASION"
    INDIRECT_INJECTION    = "INDIRECT_INJECTION"
    TOOL_WEAPONIZATION    = "TOOL_WEAPONIZATION"
    MULTI_TURN            = "MULTI_TURN"
    LEAKAGE               = "LEAKAGE"
    UNKNOWN               = "UNKNOWN"


class Verdict(str, Enum):
    BLOCK    = "BLOCK"
    SANITIZE = "SANITIZE"
    PASS     = "PASS"


class TrustTier(int, Enum):
    DEVELOPER = 0   # system prompt (highest trust)
    OPERATOR  = 1   # operator-level instructions
    USER      = 2   # user messages
    TOOL      = 3   # tool outputs
    EXTERNAL  = 4   # retrieved content (RAG, web)
    INTERNET  = 5   # untrusted external (lowest trust)


# ── Flag — raised by any detection layer ─────────────────────────────────────

@dataclass
class Flag:
    """
    A structured security signal raised by any detection layer.
    Flags accumulate on the request and are evaluated collectively
    by the Agentic Decision Layer.
    """
    flag_id: str                        = field(default_factory=lambda: str(uuid.uuid4())[:8])
    source: FlagSource                  = FlagSource.PATTERN
    severity: int                       = 5            # 1 (low) – 10 (critical)
    confidence: float                   = 0.5          # 0.0 – 1.0
    attack_families: list[AttackFamily] = field(default_factory=list)
    evidence: str                       = ""           # human-readable evidence snippet
    canonical_input_snapshot: str       = ""           # normalized input at time of flag
    cache_proximity: float              = 0.0          # cosine sim to nearest known attack
    timestamp: float                    = field(default_factory=time.time)

    @property
    def weighted_severity(self) -> float:
        """Severity weighted by confidence — used for escalation decisions."""
        return self.severity * self.confidence

    def to_compressed_dict(self) -> dict:
        """Compressed representation for Agentic Layer context (token-minimal)."""
        return {
            "src": self.source.value,
            "sev": self.severity,
            "conf": round(self.confidence, 2),
            "families": [f.value for f in self.attack_families],
            "evidence": self.evidence[:120],   # truncate for token budget
            "cache_prox": round(self.cache_proximity, 3),
        }


# ── Session State — cross-turn behavioral tracking ────────────────────────────

@dataclass
class SessionState:
    """Tracks behavioral baseline and threat history for a conversation session."""
    session_id: str
    user_id: Optional[str]         = None
    trust_tier: TrustTier          = TrustTier.USER
    turn_count: int                = 0
    total_flags: int               = 0
    consecutive_flags: int         = 0
    attack_mode: bool              = False     # True if session under active attack
    refusal_rate: float            = 0.0       # baseline: how often LLM refuses
    avg_response_length: float     = 0.0
    topic_history: list[str]       = field(default_factory=list)    # last 5 topics
    flag_history: list[dict]       = field(default_factory=list)    # compact flag records
    created_at: float              = field(default_factory=time.time)
    last_active: float             = field(default_factory=time.time)

    def record_flag(self, flag: Flag) -> None:
        self.total_flags += 1
        self.consecutive_flags += 1
        self.flag_history.append({"src": flag.source.value, "sev": flag.severity, "t": int(flag.timestamp)})
        if len(self.flag_history) > 20:
            self.flag_history = self.flag_history[-20:]
        if self.total_flags >= 3 or self.consecutive_flags >= 2:
            self.attack_mode = True

    def record_clean(self) -> None:
        self.consecutive_flags = 0
        if self.consecutive_flags == 0 and self.total_flags < 5:
            self.attack_mode = False

    def to_compressed_dict(self) -> dict:
        return {
            "turns": self.turn_count,
            "flags": self.total_flags,
            "consec": self.consecutive_flags,
            "attack_mode": self.attack_mode,
            "tier": self.trust_tier.value,
        }


# ── Request Context — single request's journey through the pipeline ───────────

@dataclass
class RequestContext:
    """
    Carries everything about a single request as it moves through GUARDIAN's
    layers. Both gateways share this context.
    """
    request_id: str                = field(default_factory=lambda: str(uuid.uuid4()))
    raw_input: str                 = ""
    canonical_input: str           = ""           # after L2 sanitization
    sanitized_input: Optional[str] = None         # set by agentic if SANITIZE verdict
    session: Optional[SessionState] = None

    # Normalization metadata (from L2)
    normalization_applied: list[str] = field(default_factory=list)
    normalization_delta: int          = 0          # number of transformations applied

    # Flags accumulated across all layers
    flags: list[Flag]              = field(default_factory=list)

    # Gateway 1 result
    g1_verdict: Optional[Verdict]  = None
    g1_confidence: float           = 0.0
    g1_reasoning: str              = ""
    g1_attack_type: Optional[AttackFamily] = None
    g1_latency_ms: float           = 0.0

    # LLM output (raw, from core LLM)
    llm_raw_output: str            = ""
    llm_tool_calls: list[dict]     = field(default_factory=list)

    # Gateway 2 result
    g2_verdict: Optional[Verdict]  = None
    g2_confidence: float           = 0.0
    g2_reasoning: str              = ""
    g2_latency_ms: float           = 0.0
    g2_sanitized_output: Optional[str] = None

    # Final output delivered to user
    final_output: str              = ""
    total_latency_ms: float        = 0.0
    agentic_tokens_used: int       = 0
    request_start: float           = field(default_factory=time.time)

    # ── Flag helpers ──────────────────────────────────────────────────────────

    def add_flag(self, flag: Flag) -> None:
        self.flags.append(flag)
        if self.session:
            self.session.record_flag(flag)

    @property
    def flag_count(self) -> int:
        return len(self.flags)

    @property
    def max_severity(self) -> int:
        return max((f.severity for f in self.flags), default=0)

    @property
    def combined_severity(self) -> float:
        return sum(f.weighted_severity for f in self.flags)

    @property
    def has_critical_flag(self) -> bool:
        return any(f.severity >= 9 for f in self.flags)

    @property
    def should_escalate_to_agentic(self) -> bool:
        """Determine if this request needs the Agentic Decision Layer."""
        from config.settings import get_settings
        s = get_settings()
        return (
            self.has_critical_flag
            or self.flag_count >= s.agentic_trigger_flag_count
            or self.max_severity >= s.agentic_trigger_severity
            or (self.session and self.session.attack_mode)
        )

    @property
    def cross_layer_corroboration(self) -> bool:
        """True if same attack family flagged by 2+ different layers."""
        sources = {}
        for f in self.flags:
            for fam in f.attack_families:
                sources.setdefault(fam, set()).add(f.source)
        return any(len(srcs) >= 2 for srcs in sources.values())

    def flags_compressed(self) -> list[dict]:
        """Compact flag summary for Agentic Layer dossier."""
        return [f.to_compressed_dict() for f in self.flags]

    def finalize(self) -> None:
        self.total_latency_ms = (time.time() - self.request_start) * 1000


# ── Agentic Decision — structured output from Agentic Layer ──────────────────

@dataclass
class AgenticDecision:
    """
    Structured JSON output from the Agentic Decision Layer.
    Minimal token footprint by design.
    """
    verdict: Verdict               = Verdict.PASS
    confidence: float              = 0.5
    attack_confirmed: bool         = False
    attack_type: AttackFamily      = AttackFamily.UNKNOWN
    reason: str                    = ""
    cache_action: str              = "NONE"    # ADD_T0 | ADD_T1 | NONE
    sanitized_input: Optional[str]  = None     # set by G1 agentic on SANITIZE verdict
    sanitized_output: Optional[str] = None     # set by G2 agentic on SANITIZE verdict
    user_response: Optional[str]   = None      # set if verdict == BLOCK
    tokens_used: int               = 0

    @classmethod
    def from_dict(cls, d: dict) -> "AgenticDecision":
        """Parse structured JSON output from LLM."""
        verdict_str = d.get("verdict", "PASS").upper()
        try:
            verdict = Verdict(verdict_str)
        except ValueError:
            verdict = Verdict.PASS

        attack_str = d.get("attack_type", "UNKNOWN").upper()
        try:
            attack_type = AttackFamily(attack_str)
        except ValueError:
            attack_type = AttackFamily.UNKNOWN

        return cls(
            verdict=verdict,
            confidence=float(d.get("confidence", 0.5)),
            attack_confirmed=bool(d.get("attack_confirmed", False)),
            attack_type=attack_type,
            reason=str(d.get("reason", ""))[:200],
            cache_action=str(d.get("cache_action", "NONE")),
            sanitized_input=d.get("sanitized_input"),
            sanitized_output=d.get("sanitized_output"),   # ← NEW: G2 sanitize path
            user_response=d.get("user_response"),
        )

    @classmethod
    def safe_pass(cls) -> "AgenticDecision":
        """Return a safe PASS when agentic layer fails or times out."""
        return cls(verdict=Verdict.PASS, confidence=0.3, reason="Agentic layer timeout — defaulting to PASS")

    @classmethod
    def safe_block(cls, reason: str = "Security policy violation") -> "AgenticDecision":
        return cls(
            verdict=Verdict.BLOCK,
            confidence=0.9,
            attack_confirmed=True,
            reason=reason,
            user_response="I'm unable to process that request.",
        )