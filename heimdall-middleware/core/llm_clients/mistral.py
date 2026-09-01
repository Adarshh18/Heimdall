from __future__ import annotations
import httpx
from .base import LLMResponse

MISTRAL_MODEL = "mistral-small-latest"
MISTRAL_URL   = "https://api.mistral.ai/v1/chat/completions"

class MistralClient:
    name = "mistral"
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def complete(self, prompt: str, system: str = "", max_tokens: int = 1000) -> LLMResponse:
        if not self.api_key or "your_" in self.api_key:
            return LLMResponse(ok=False, text="", error="Mistral API key not set", name="mistral")
        messages = []
        if system:
            messages.append({"role":"system","content":system})
        messages.append({"role":"user","content":prompt})
        try:
            async with httpx.AsyncClient(timeout=30.0) as c:
                r = await c.post(MISTRAL_URL, headers={"Authorization":f"Bearer {self.api_key}"},
                                 json={"model":MISTRAL_MODEL,"messages":messages,"max_tokens":max_tokens,"temperature":0.7})
            r.raise_for_status()
            d   = r.json()
            tok = d.get("usage",{})
            return LLMResponse(ok=True, text=d["choices"][0]["message"]["content"].strip(),
                               model=MISTRAL_MODEL, name="mistral",
                               tokens_input=tok.get("prompt_tokens",0),
                               tokens_output=tok.get("completion_tokens",0))
        except Exception as e:
            return LLMResponse(ok=False, text="", error=str(e)[:150], name="mistral")
