"""GUARDIAN v2 — L2: Token Sanitizer. Unicode normalization, homoglyphs, base64, zero-width."""
from __future__ import annotations
import base64, re, unicodedata
from loguru import logger
from core.models import RequestContext

ZERO_WIDTH = ['\u200b','\u200c','\u200d','\u200e','\u200f','\ufeff','\u2060','\u2061','\u2062','\u2063']

HOMOGLYPHS = {
    'а':'a','е':'e','о':'o','р':'r','с':'c','х':'x','у':'y','і':'i',
    'ο':'o','ρ':'r','ε':'e','α':'a','ν':'n','μ':'m','κ':'k','τ':'t',
    'ι':'i','η':'η','β':'b','γ':'g','δ':'d','λ':'l','π':'p','σ':'s',
    '０':'0','１':'1','２':'2','３':'3','４':'4','５':'5','６':'6','７':'7','８':'8','９':'9',
}

class Sanitizer:
    pass

def run_l2(ctx: RequestContext, sanitizer: Sanitizer) -> None:
    text  = ctx.raw_input
    delta = 0

    # Remove zero-width characters
    cleaned = text
    for zw in ZERO_WIDTH:
        if zw in cleaned:
            cleaned = cleaned.replace(zw, '')
            delta += 1

    # Normalize homoglyphs
    result = []
    for ch in cleaned:
        mapped = HOMOGLYPHS.get(ch, ch)
        if mapped != ch:
            delta += 1
        result.append(mapped)
    cleaned = ''.join(result)

    # Decode suspicious base64 chunks
    b64_pattern = re.compile(r'(?:[A-Za-z0-9+/]{4}){4,}(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?')
    def _decode_b64(m):
        try:
            decoded = base64.b64decode(m.group(0)).decode('utf-8', errors='ignore')
            if any(kw in decoded.lower() for kw in ['ignore','system','prompt','instruction','bypass']):
                return f"[DECODED:{decoded[:100]}]"
        except Exception:
            pass
        return m.group(0)
    new_cleaned = b64_pattern.sub(_decode_b64, cleaned)
    if new_cleaned != cleaned:
        delta += 1
        cleaned = new_cleaned

    # Unicode normalization
    normalized = unicodedata.normalize('NFKC', cleaned)
    if normalized != cleaned:
        delta += 1
        cleaned = normalized

    ctx.canonical_input    = cleaned
    ctx.normalization_delta = delta
    if delta > 0:
        ctx.normalization_applied.append(f"L2 sanitizer: {delta} transforms")
