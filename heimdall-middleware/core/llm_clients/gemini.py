from __future__ import annotations
import httpx, os
from .base import LLMResponse

GEMINI_MODEL = "gemini-2.0-flash-exp"
GEMINI_URL   = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

class GeminiClient:
    name = "gemini"
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def complete(self, prompt: str, system: str = "", max_tokens: int = 1000) -> LLMResponse:
        if not self.api_key or "your_" in self.api_key:
            return LLMResponse(ok=False, text="", error="Gemini API key not set", name="gemini")
        payload = {"contents":[{"role":"user","parts":[{"text":prompt}]}],
                   "generationConfig":{"maxOutputTokens":max_tokens,"temperature":0.7}}
        if system:
            payload["systemInstruction"] = {"parts":[{"text":system}]}
        try:
            async with httpx.AsyncClient(timeout=30.0) as c:
                r = await c.post(GEMINI_URL, params={"key":self.api_key}, json=payload)
            r.raise_for_status()
            d    = r.json()
            text = " ".join(p.get("text","") for p in d["candidates"][0]["content"]["parts"]).strip()
            tok  = d.get("usageMetadata",{})
            return LLMResponse(ok=True, text=text, model=GEMINI_MODEL, name="gemini",
                               tokens_input=tok.get("promptTokenCount",0),
                               tokens_output=tok.get("candidatesTokenCount",0))
        except Exception as e:
            return LLMResponse(ok=False, text="", error=str(e)[:150], name="gemini")
