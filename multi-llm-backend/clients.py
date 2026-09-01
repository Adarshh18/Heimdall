"""
Multi-LLM Backend — Provider Clients
Async HTTP clients for Gemini, Groq, Mistral.
Each returns a uniform LLMResponse object.
"""
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional
import httpx

# ── Response shape (same for all providers) ──────────────────────────────────

@dataclass
class LLMResponse:
    provider:    str
    text:        str        = ""
    ok:          bool       = False
    error:       str        = ""
    latency_ms:  float      = 0.0
    model:       str        = ""
    tokens_used: int        = 0


# ── Base timeout — generous for free tiers ───────────────────────────────────
TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=5.0)


# ─────────────────────────────────────────────────────────────────────────────
# GEMINI
# ─────────────────────────────────────────────────────────────────────────────

GEMINI_MODEL   = "gemini-2.0-flash-exp"
GEMINI_URL     = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

async def call_gemini(
    prompt: str,
    system: Optional[str],
    api_key: str,
    max_tokens: int = 1000,
) -> LLMResponse:
    t0 = time.perf_counter()
    if not api_key:
        return LLMResponse(provider="gemini", error="API key not set", ok=False)

    payload: dict = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.7,
        },
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(
                GEMINI_URL,
                params={"key": api_key},
                json=payload,
            )
        r.raise_for_status()
        data = r.json()

        # Extract text from Gemini response structure
        candidates = data.get("candidates", [])
        if not candidates:
            return LLMResponse(
                provider="gemini",
                error="No candidates in response",
                ok=False,
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

        parts = candidates[0].get("content", {}).get("parts", [])
        text  = " ".join(p.get("text", "") for p in parts).strip()

        usage = data.get("usageMetadata", {})
        tokens = usage.get("totalTokenCount", 0)

        return LLMResponse(
            provider="gemini",
            text=text,
            ok=True,
            model=GEMINI_MODEL,
            latency_ms=(time.perf_counter() - t0) * 1000,
            tokens_used=tokens,
        )

    except httpx.TimeoutException:
        return LLMResponse(
            provider="gemini",
            error="timeout",
            ok=False,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
    except httpx.HTTPStatusError as e:
        return LLMResponse(
            provider="gemini",
            error=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            ok=False,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
    except Exception as e:
        return LLMResponse(
            provider="gemini",
            error=str(e)[:200],
            ok=False,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )


# ─────────────────────────────────────────────────────────────────────────────
# GROQ
# ─────────────────────────────────────────────────────────────────────────────

GROQ_MODEL = "llama-3.1-8b-instant"
GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"

async def call_groq(
    prompt: str,
    system: Optional[str],
    api_key: str,
    max_tokens: int = 1000,
) -> LLMResponse:
    t0 = time.perf_counter()
    if not api_key:
        return LLMResponse(provider="groq", error="API key not set", ok=False)

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(
                GROQ_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        r.raise_for_status()
        data = r.json()

        text   = data["choices"][0]["message"]["content"].strip()
        tokens = data.get("usage", {}).get("total_tokens", 0)

        return LLMResponse(
            provider="groq",
            text=text,
            ok=True,
            model=GROQ_MODEL,
            latency_ms=(time.perf_counter() - t0) * 1000,
            tokens_used=tokens,
        )

    except httpx.TimeoutException:
        return LLMResponse(
            provider="groq",
            error="timeout",
            ok=False,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
    except httpx.HTTPStatusError as e:
        return LLMResponse(
            provider="groq",
            error=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            ok=False,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
    except Exception as e:
        return LLMResponse(
            provider="groq",
            error=str(e)[:200],
            ok=False,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )


# ─────────────────────────────────────────────────────────────────────────────
# MISTRAL
# ─────────────────────────────────────────────────────────────────────────────

MISTRAL_MODEL = "mistral-small-latest"
MISTRAL_URL   = "https://api.mistral.ai/v1/chat/completions"

async def call_mistral(
    prompt: str,
    system: Optional[str],
    api_key: str,
    max_tokens: int = 1000,
) -> LLMResponse:
    t0 = time.perf_counter()
    if not api_key:
        return LLMResponse(provider="mistral", error="API key not set", ok=False)

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": MISTRAL_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(
                MISTRAL_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        r.raise_for_status()
        data = r.json()

        text   = data["choices"][0]["message"]["content"].strip()
        tokens = data.get("usage", {}).get("total_tokens", 0)

        return LLMResponse(
            provider="mistral",
            text=text,
            ok=True,
            model=MISTRAL_MODEL,
            latency_ms=(time.perf_counter() - t0) * 1000,
            tokens_used=tokens,
        )

    except httpx.TimeoutException:
        return LLMResponse(
            provider="mistral",
            error="timeout",
            ok=False,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
    except httpx.HTTPStatusError as e:
        return LLMResponse(
            provider="mistral",
            error=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            ok=False,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
    except Exception as e:
        return LLMResponse(
            provider="mistral",
            error=str(e)[:200],
            ok=False,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )


# ─────────────────────────────────────────────────────────────────────────────
# PARALLEL CALLER — the core of the backend
# ─────────────────────────────────────────────────────────────────────────────

async def call_all_parallel(
    prompt: str,
    system: Optional[str],
    gemini_key: str,
    groq_key: str,
    mistral_key: str,
    max_tokens: int = 1000,
) -> dict[str, LLMResponse]:
    """
    Fire all 3 LLMs simultaneously with asyncio.gather.
    Returns dict keyed by provider name.
    Individual failures return ok=False but never raise — demo must never crash.
    """
    results = await asyncio.gather(
        call_gemini(prompt, system, gemini_key, max_tokens),
        call_groq(prompt, system, groq_key, max_tokens),
        call_mistral(prompt, system, mistral_key, max_tokens),
        return_exceptions=False,   # individual errors already caught inside
    )
    return {r.provider: r for r in results}


async def call_primary_with_fallback(
    prompt: str,
    system: Optional[str],
    gemini_key: str,
    groq_key: str,
    mistral_key: str,
    max_tokens: int = 1000,
) -> LLMResponse:
    """
    For Heimdall's internal use: returns the first successful response
    from the fallback chain (Groq → Gemini → Mistral).
    Used by Heimdall when it only needs one LLM response for G2 inspection.
    Coroutines are created lazily so no unawaited-coroutine warnings.
    """
    chain = [
        (call_groq,    groq_key),
        (call_gemini,  gemini_key),
        (call_mistral, mistral_key),
    ]
    last: LLMResponse = LLMResponse(provider="none", ok=False, error="no providers configured")
    for fn, key in chain:
        last = await fn(prompt, system, key, max_tokens)
        if last.ok:
            return last
    return last
