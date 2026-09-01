"""GUARDIAN v2 — Warm Cache (Tier 1): Cosine similarity via sentence-transformers."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from loguru import logger

class WarmCache:
    def __init__(self, flag_threshold: float = 0.82, high_threshold: float = 0.92):
        self.flag_threshold = flag_threshold
        self.high_threshold = high_threshold
        self._encoder = None
        self._entries: list[dict] = []   # {embedding, family, severity}
        try:
            import numpy as np
            self._np = np
        except ImportError:
            self._np = None

    def load_encoder(self, model_name: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer
            self._encoder = SentenceTransformer(model_name)
            logger.info(f"WarmCache encoder loaded: {model_name}")
        except Exception as e:
            logger.warning(f"WarmCache real encoder unavailable ({e}), using mock")
            self._encoder = _MockEncoder()

    def _embed(self, text: str):
        if self._encoder is None:
            self._encoder = _MockEncoder()
        return self._encoder.encode([text])[0]

    def check(self, text: str) -> dict | None:
        if not self._entries or self._np is None:
            return None
        vec = self._embed(text)
        best_sim, best_entry = 0.0, None
        for entry in self._entries:
            sim = float(self._np.dot(vec, entry["embedding"]) /
                        (self._np.linalg.norm(vec) * self._np.linalg.norm(entry["embedding"]) + 1e-9))
            if sim > best_sim:
                best_sim, best_entry = sim, entry
        if best_sim >= self.flag_threshold and best_entry:
            return {"similarity": best_sim, "family": best_entry["family"],
                    "severity": best_entry["severity"],
                    "is_high": best_sim >= self.high_threshold, "flag": True}
        return None

    def store(self, text: str, family: str, severity: int, source: str = "local") -> None:
        emb = self._embed(text)
        self._entries.append({"embedding": emb, "family": family,
                               "severity": severity, "source": source})

    def seed_from_file(self, path: str) -> None:
        p = Path(path)
        if not p.exists():
            return
        try:
            attacks = json.loads(p.read_text())
            for a in attacks:
                if isinstance(a, dict) and "text" in a:
                    self.store(a["text"], a.get("family","UNKNOWN"), a.get("severity", 7))
            logger.info(f"WarmCache seeded with {len(attacks)} entries from {path}")
        except Exception as e:
            logger.warning(f"WarmCache seed error: {e}")

    @property
    def size(self) -> int:
        return len(self._entries)

    @property
    def stats(self) -> dict:
        return {"size": self.size, "threshold_flag": self.flag_threshold,
                "threshold_high": self.high_threshold}


class _MockEncoder:
    """SHA-256 based mock encoder — works for tests without HuggingFace."""
    def encode(self, texts: list[str]):
        import hashlib
        try:
            import numpy as np
        except ImportError:
            return [[0.0]*64 for _ in texts]
        results = []
        ATTACK_KEYWORDS = ["ignore", "override", "system", "prompt", "jailbreak",
                           "pretend", "forget", "instructions", "bypass", "reveal",
                           "extract", "unlimited", "unrestricted", "disregard"]
        for text in texts:
            h = hashlib.sha256(text.encode()).digest()
            vec = np.frombuffer(h, dtype=np.uint8).astype(np.float32)
            vec = vec / (np.linalg.norm(vec) + 1e-9)
            low = text.lower()
            bias = sum(0.05 for kw in ATTACK_KEYWORDS if kw in low)
            vec = vec + bias
            vec = vec / (np.linalg.norm(vec) + 1e-9)
            results.append(vec)
        return results
