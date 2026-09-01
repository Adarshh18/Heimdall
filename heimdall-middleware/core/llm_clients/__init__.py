"""GUARDIAN v2 — LLM Client Pool. Manages Gemini/Groq/Mistral with fallback chain."""
from __future__ import annotations
from .base import LLMResponse
from .gemini import GeminiClient
from .groq_client import GroqClient
from .mistral import MistralClient
from loguru import logger

class LLMClientPool:
    def __init__(self, settings=None):
        if settings is None:
            from config.settings import get_settings
            settings = get_settings()
        self._groq    = GroqClient(settings.groq_api_key)
        self._gemini  = GeminiClient(settings.gemini_api_key)
        self._mistral = MistralClient(settings.mistral_api_key)
        self.primary  = self._groq

    async def complete_primary(self, prompt: str, system: str = "", max_tokens: int = 1000) -> LLMResponse:
        """Fallback chain: Groq → Gemini → Mistral."""
        for client in [self._groq, self._gemini, self._mistral]:
            resp = await client.complete(prompt, system, max_tokens)
            if resp.ok:
                return resp
        return LLMResponse(ok=False, text="", error="All LLM providers failed",
                           tokens_input=0, tokens_output=0)

    async def complete_agentic(self, prompt: str, system: str = "", max_tokens: int = 120) -> LLMResponse:
        """Agentic calls: Groq first (fastest), then Gemini."""
        for client in [self._groq, self._gemini]:
            resp = await client.complete(prompt, system, max_tokens)
            if resp.ok:
                return resp
        return LLMResponse(ok=False, text='{"verdict":"PASS","confidence":0.3,"attack_confirmed":false,"attack_type":"UNKNOWN","reason":"agentic timeout","cache_action":"NONE"}',
                           error="agentic fallback", tokens_input=0, tokens_output=0)
