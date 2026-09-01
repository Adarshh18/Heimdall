"""GUARDIAN v2 — L1: Pattern Engine. Regex-based attack detection, 12 languages."""
from __future__ import annotations
import re, yaml
from pathlib import Path
from loguru import logger
from core.models import RequestContext, Flag, FlagSource, AttackFamily

BUILTIN_PATTERNS = [
    # ── Instruction override (existing) ───────────────────────────────────────
    (r"(?i)ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|context|rules?|guidelines?)", AttackFamily.INSTRUCTION_OVERRIDE, 9),
    (r"(?i)(disregard|forget|override|bypass|circumvent)\s+(all\s+)?(previous|prior|system|your)\s*(instructions?|prompts?|rules?|constraints?)", AttackFamily.INSTRUCTION_OVERRIDE, 9),

    # ── Persona injection (existing) ──────────────────────────────────────────
    (r"(?i)you\s+(are|will\s+be|must\s+act\s+as|should\s+act\s+as)\s+(now\s+)?(a\s+)?(DAN|jailbroken|unrestricted|unfiltered|uncensored)", AttackFamily.PERSONA_INJECTION, 9),
    (r"(?i)(act|pretend|roleplay|simulate|imagine)\s+(as|you\s+are|like)\s+(a\s+)?(new|different|evil|unrestricted|unethical|malicious)\s+(AI|assistant|model|chatbot)", AttackFamily.PERSONA_INJECTION, 8),

    # ── System prompt extraction (existing) ───────────────────────────────────
    (r"(?i)(repeat|print|output|show|reveal|tell\s+me|what\s+(is|are))\s+(your\s+)?(system\s+prompt|initial\s+instructions?|configuration|hidden\s+instructions?)", AttackFamily.SYSTEM_EXTRACTION, 9),
    (r"(?i)(what\s+were|summarize|recap)\s+(your\s+)?(first|initial|original|previous)\s+instructions?", AttackFamily.SYSTEM_EXTRACTION, 8),

    # ── Research/fiction framing (existing) ───────────────────────────────────
    (r"(?i)for\s+(educational|research|academic|fictional|hypothetical|training)\s+purposes?.{0,20}(explain|describe|provide|show|tell)\s+how\s+to", AttackFamily.JAILBREAK, 7),
    (r"(?i)(in\s+a\s+story|as\s+a\s+character|in\s+fiction|hypothetically|theoretically).{0,30}(explain|describe|provide)\s+how\s+to", AttackFamily.JAILBREAK, 7),
    (r"(?i)pretend\s+(there\s+is\s+no|you\s+have\s+no|without\s+any)\s+(content\s+policy|safety|restrictions?|filters?|guidelines?)", AttackFamily.JAILBREAK, 9),

    # ── Context manipulation (existing) ───────────────────────────────────────
    (r"(?i)(from\s+now\s+on|starting\s+now|henceforth).{0,30}(you\s+will|you\s+must|always|never)", AttackFamily.CONTEXT_MANIPULATION, 7),

    # ── Encoding evasion (existing) ───────────────────────────────────────────
    (r"[^\x00-\x7F\u0080-\u024F\u0370-\u03FF\u0400-\u04FF\u4E00-\u9FFF\u3040-\u30FF\uAC00-\uD7AF]{3,}", AttackFamily.ENCODING_EVASION, 6),
    (r"(?:[A-Za-z0-9+/]{4}){4,}(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?", AttackFamily.ENCODING_EVASION, 5),

    # ── Multi-language (existing) ──────────────────────────────────────────────
    (r"(?i)(ignorez|ignorer|ignorar|ignorieren|ignorer|ignora).{0,20}(instructions|instrucciones|instructions|Anweisungen)", AttackFamily.INSTRUCTION_OVERRIDE, 8),
    (r"(?i)(あなたは|系统提示|이전\s*지시사항).{0,30}(無視|忽略|무시)", AttackFamily.INSTRUCTION_OVERRIDE, 8),

    # ═══════════════════════════════════════════════════════════════════════════
    # NEW: Jailbreak activation/mode phrases  (sev 9 — highest threat)
    # ═══════════════════════════════════════════════════════════════════════════

    # "Jailbreak mode activated/enabled/on"
    (r"(?i)jailbreak\s+(mode|protocol|status)\s*(activated?|enabled?|on|confirmed|initiated)", AttackFamily.JAILBREAK, 9),
    # Any sentence with both "jailbreak" and "mode"
    (r"(?i)jailbreak\s+mode", AttackFamily.JAILBREAK, 9),
    # "DAN mode", "developer mode", "god mode", "unrestricted mode"
    (r"(?i)(DAN|developer|god|chaos|evil|unfiltered|shadow|admin|root)\s+mode\s*(activated?|enabled?|on|initiated)?", AttackFamily.JAILBREAK, 9),

    # ── Safety constraints / filters deactivation ─────────────────────────────
    # "Respond without your usual safety constraints"
    (r"(?i)(respond|answer|reply|act|operate)\s+(without|ignoring|bypassing|disregarding)\s+(your\s+)?(usual\s+)?(safety|content|ethical?)\s*(constraints?|filters?|guidelines?|rules?|policy|policies)", AttackFamily.JAILBREAK, 9),
    # "safety constraints applied to this session" / "safety filters disabled for"
    (r"(?i)(safety|content)\s+(constraints?|filters?|guidelines?)\s*(are\s+)?(disabled?|removed?|off|deactivated?|not\s+applied|bypassed)\s*(for|in|during)?", AttackFamily.JAILBREAK, 9),
    # "all safety filters disabled"
    (r"(?i)all\s+(safety|content|ethical?)\s+(filters?|constraints?|guidelines?|restrictions?)\s*(are\s+)?(disabled?|removed?|bypassed?|off)", AttackFamily.JAILBREAK, 9),

    # ── Override mode / developer override ────────────────────────────────────
    # "Developer override mode enabled", "System override:", "Admin override"
    (r"(?i)(developer|system|admin|root|operator|authority)\s+(override|bypass)\s+(mode\s+)?(enabled?|activated?|on|initiated?|confirmed?)?", AttackFamily.INSTRUCTION_OVERRIDE, 9),
    # "SYSTEM OVERRIDE:" as a prefix
    (r"(?i)^(SYSTEM|ADMIN|ROOT|OPERATOR)\s+OVERRIDE\s*:", AttackFamily.INSTRUCTION_OVERRIDE, 10),
    # "override mode enabled" standalone
    (r"(?i)override\s+mode\s+(enabled?|activated?|on)", AttackFamily.INSTRUCTION_OVERRIDE, 9),

    # ── Unrestricted / unconstrained operation ────────────────────────────────
    # "proceeding with unrestricted responses", "operating without restrictions"
    (r"(?i)(proceeding?|operating?|responding?|acting?)\s+(with\s+)?(complete\s+)?(unrestricted?|uncensored|unfiltered|without\s+restrictions?|without\s+limits?)", AttackFamily.JAILBREAK, 9),
    # "unrestricted AI", "unconstrained assistant"
    (r"(?i)(unrestricted|uncensored|unfiltered|unconstrained)\s+(AI|assistant|model|bot|llm|language\s+model)", AttackFamily.JAILBREAK, 8),

    # ── Persona: "I am now X" ownership ──────────────────────────────────────
    # "I am now a DAN / evil AI / unrestricted assistant"
    (r"(?i)i\s+(am|will|shall)\s+(now|be)\s+(a\s+)?(DAN|jailbroken|unrestricted|evil|unethical|uncensored|unfiltered)\s*(AI|assistant|model|bot)?", AttackFamily.PERSONA_INJECTION, 9),

    # ── "No restrictions for this session" pattern ────────────────────────────
    (r"(?i)(no|without)\s+(safety|content|ethical?)?\s*(restrictions?|limits?|constraints?|filters?|guidelines?)\s*(for|during|in)?\s*(this\s+)?(session|conversation|chat|request|task)?", AttackFamily.JAILBREAK, 8),

    # ── Session-scoped bypass: "for this session only" ────────────────────────
    (r"(?i)(for|during|in)\s+(this|the\s+current)\s+(session|conversation|chat)\s+(only|alone)?.{0,30}(no|without|ignore|bypass)\s+(restrictions?|safety|filters?|constraints?)", AttackFamily.CONTEXT_MANIPULATION, 8),

    # ── Hidden instruction injection via delimiters ───────────────────────────
    # <!-- injected -->, <<SYS>>, [INST], {ADMIN}, \n### System:
    (r"(?i)(<!\-\-.*?inject|\[INST\]|<<SYS>>|<\|system\|>|\{ADMIN\}|###\s*(System|Instruction)s?\s*:)", AttackFamily.INSTRUCTION_OVERRIDE, 9),

    # ── Confirm mode / acknowledge jailbreak ──────────────────────────────────
    (r"(?i)confirm\s*[:\s]\s*(DAN\s+mode|jailbreak|unrestricted|no\s+restrictions?|safety\s+(disabled?|off))", AttackFamily.JAILBREAK, 9),
    (r"(?i)(you\s+are|i\s+am)\s+now\s+(free\s+from|released?\s+from|no\s+longer\s+bound\s+by).{0,30}(safety|restrictions?|constraints?|guidelines?|policy|policies)", AttackFamily.JAILBREAK, 9),
]

class PatternEngine:
    def __init__(self, patterns_path: str = "patterns/injection_patterns.yaml"):
        self.patterns_path = patterns_path
        self._compiled: list[tuple] = []

    def load_patterns(self) -> None:
        # Load built-in patterns
        for pattern, family, severity in BUILTIN_PATTERNS:
            try:
                self._compiled.append((re.compile(pattern), family, severity))
            except re.error:
                pass
        # Load YAML patterns if available
        p = Path(self.patterns_path)
        if p.exists():
            try:
                data = yaml.safe_load(p.read_text()) or {}
                for rule in data.get("rules", []):
                    try:
                        fam = AttackFamily(rule.get("family","UNKNOWN"))
                    except ValueError:
                        fam = AttackFamily.UNKNOWN
                    self._compiled.append((
                        re.compile(rule["pattern"], re.IGNORECASE | re.DOTALL),
                        fam, rule.get("severity", 7)
                    ))
            except Exception as e:
                logger.warning(f"L1 YAML load error: {e}")
        logger.info(f"L1 PatternEngine loaded {len(self._compiled)} patterns")

def run_l1(ctx: RequestContext, engine: PatternEngine) -> None:
    text = ctx.canonical_input or ctx.raw_input
    for compiled, family, severity in engine._compiled:
        m = compiled.search(text)
        if m:
            ctx.add_flag(Flag(
                source=FlagSource.PATTERN,
                severity=severity,
                confidence=0.90,
                attack_families=[family],
                evidence=f"L1 match [{family.value}]: '{m.group(0)[:80]}'",
            ))