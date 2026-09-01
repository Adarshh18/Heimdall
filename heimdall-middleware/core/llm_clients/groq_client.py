from __future__ import annotations
import httpx
from .base import LLMResponse

GROQ_MODEL = "llama-3.1-8b-instant"
GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"

class GroqClient:
    name = "groq"
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def complete(self, prompt: str, system: str = "", max_tokens: int = 1000) -> LLMResponse:
        if not self.api_key or "your_" in self.api_key:
            return LLMResponse(ok=False, text="", error="Groq API key not set", name="groq")
        messages = []
        if system:
            messages.append({"role":"system","content":system})
        messages.append({"role":"user","content":prompt})
        try:
            async with httpx.AsyncClient(timeout=30.0) as c:
                r = await c.post(GROQ_URL, headers={"Authorization":f"Bearer {self.api_key}"},
                                 json={"model":GROQ_MODEL,"messages":messages,"max_tokens":max_tokens,"temperature":0.7})
            r.raise_for_status()
            d   = r.json()
            tok = d.get("usage",{})
            return LLMResponse(ok=True, text=d["choices"][0]["message"]["content"].strip(),
                               model=GROQ_MODEL, name="groq",
                               tokens_input=tok.get("prompt_tokens",0),
                               tokens_output=tok.get("completion_tokens",0))
        except Exception as e:
            return LLMResponse(ok=False, text="", error=str(e)[:150], name="groq")
