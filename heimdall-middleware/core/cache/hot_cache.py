"""GUARDIAN v2 — Hot Cache (Tier 0): SHA-256 exact hash matching via Redis/fakeredis."""
from __future__ import annotations
import hashlib, json
from loguru import logger

class HotCache:
    def __init__(self, use_fake: bool = True, redis_url: str = "redis://localhost:6379"):
        self.use_fake = use_fake
        self.redis_url = redis_url
        self._client = None
        self._local: dict = {}   # fallback in-memory

    def connect(self) -> None:
        try:
            if self.use_fake:
                import fakeredis
                self._client = fakeredis.FakeRedis(decode_responses=True)
            else:
                import redis
                self._client = redis.from_url(self.redis_url, decode_responses=True)
            logger.info(f"HotCache connected (fake={self.use_fake})")
        except Exception as e:
            logger.warning(f"HotCache redis unavailable ({e}), using in-memory fallback")
            self._client = None

    def _key(self, text: str) -> str:
        return "hc:" + hashlib.sha256(text.strip().lower().encode()).hexdigest()

    def check(self, text: str) -> dict | None:
        key = self._key(text)
        try:
            if self._client:
                val = self._client.get(key)
                return json.loads(val) if val else None
            return self._local.get(key)
        except Exception:
            return None

    def store(self, text: str, metadata: dict, ttl: int = 86400) -> None:
        key = self._key(text)
        try:
            if self._client:
                self._client.setex(key, ttl, json.dumps(metadata))
            else:
                self._local[key] = metadata
        except Exception as e:
            logger.warning(f"HotCache store error: {e}")

    def seed_from_patterns(self, signatures: list) -> None:
        for sig in signatures:
            if isinstance(sig, dict) and "text" in sig:
                self.store(sig["text"], {"family": sig.get("family","UNKNOWN"),
                                         "severity": sig.get("severity", 8)})

    @property
    def stats(self) -> dict:
        try:
            size = self._client.dbsize() if self._client else len(self._local)
        except Exception:
            size = 0
        return {"type": "redis" if not self.use_fake else "fakeredis", "size": size}
