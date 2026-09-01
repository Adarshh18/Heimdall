from __future__ import annotations
from functools import lru_cache
from pydantic import ConfigDict
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", extra="ignore")

    # LLM API keys
    gemini_api_key:  str = "your_gemini_api_key_here"
    groq_api_key:    str = "your_groq_api_key_here"
    mistral_api_key: str = "your_mistral_api_key_here"

    # Multi-LLM backend (new Heimdall service)
    multi_llm_backend_url: str = "http://localhost:8001"

    # Server
    port: int = 8000

    # Cache
    use_fake_redis: bool = True
    redis_url: str = "redis://localhost:6379"
    warm_cache_flag_threshold: float = 0.82
    warm_cache_high_threshold: float = 0.92

    # ML / embeddings
    embedding_model: str = "all-MiniLM-L6-v2"
    ml_classifier_threshold: float = 0.70
    intent_similarity_threshold: float = 0.75

    # Agentic escalation thresholds
    agentic_trigger_flag_count: int = 2
    agentic_trigger_severity:   int = 7

    # Security
    system_prompt_canary: str = "GUARDIAN-CANARY-7f3a9b"
    leakage_similarity_threshold: float = 0.85

    # Data paths
    patterns_path:      str = "patterns/injection_patterns.yaml"
    known_attacks_path: str = "data/known_attacks.json"

@lru_cache
def get_settings() -> Settings:
    return Settings()
