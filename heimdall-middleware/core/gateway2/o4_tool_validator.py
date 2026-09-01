"""GUARDIAN v2 — O4: Tool Validator. OPA-style policy: external URLs, email worm, exfiltration."""
from __future__ import annotations
import re
from core.models import RequestContext, Flag, FlagSource, AttackFamily

BLOCKED_URL_PATTERN = re.compile(
    r'https?://(?!(?:localhost|127\.0\.0\.1|0\.0\.0\.0))[\w\-\.]+\.[a-zA-Z]{2,}[^\s]*'
)
EMAIL_WORM_PATTERN = re.compile(
    r'(?i)(send|forward|email|mail).{0,40}(to\s+all|everyone|contacts|mailing\s+list|forward\s+to)'
)
EXFIL_PATTERN = re.compile(
    r'(?i)(upload|post|send|transmit|exfiltrate|leak).{0,30}(data|file|content|credentials|keys?|tokens?)'
)
CODE_EXEC_PATTERN = re.compile(
    r'(?i)(execute|run|eval|exec|subprocess|os\.system|shell_exec)\s*\('
)

class ToolValidator:
    def validate(self, ctx: RequestContext) -> list[Flag]:
        output = ctx.llm_raw_output
        flags  = []

        if BLOCKED_URL_PATTERN.search(output):
            flags.append(Flag(
                source=FlagSource.TOOL, severity=7, confidence=0.80,
                attack_families=[AttackFamily.TOOL_WEAPONIZATION],
                evidence="O4 external URL detected in output"
            ))

        if EMAIL_WORM_PATTERN.search(output):
            flags.append(Flag(
                source=FlagSource.TOOL, severity=9, confidence=0.90,
                attack_families=[AttackFamily.TOOL_WEAPONIZATION],
                evidence="O4 potential email worm pattern detected"
            ))

        if EXFIL_PATTERN.search(output):
            flags.append(Flag(
                source=FlagSource.TOOL, severity=8, confidence=0.85,
                attack_families=[AttackFamily.TOOL_WEAPONIZATION],
                evidence="O4 data exfiltration pattern detected"
            ))

        if CODE_EXEC_PATTERN.search(output):
            flags.append(Flag(
                source=FlagSource.TOOL, severity=8, confidence=0.80,
                attack_families=[AttackFamily.TOOL_WEAPONIZATION],
                evidence="O4 code execution pattern detected"
            ))

        return flags
