"""
GUARDIAN v2 — Cache Manager
Unified interface for all cache tiers. Called by L0 and agentic layer.
"""
from __future__ import annotations
from loguru import logger
from .hot_cache import HotCache
from .warm_cache import WarmCache


class CacheManager:
    """
    Unified cache interface.
    Tier 0 (hot) → exact hash — sub-ms
    Tier 1 (warm) → semantic similarity — 5-20ms
    """

    def __init__(self, settings=None):
        if settings is None:
            from config.settings import get_settings
            settings = get_settings()
        self.s = settings
        self.hot = HotCache(
            use_fake=settings.use_fake_redis,
            redis_url=settings.redis_url,
        )
        self.warm = WarmCache(
            flag_threshold=settings.warm_cache_flag_threshold,
            high_threshold=settings.warm_cache_high_threshold,
        )
        self._initialized = False

    def initialize(self) -> None:
        """Connect caches and seed from known attack data."""
        if self._initialized:
            return
        # Connect hot cache
        self.hot.connect()

        # Load encoder for warm cache
        self.warm.load_encoder(self.s.embedding_model)

        # Seed both caches from patterns and data files
        self._seed_caches()
        self._initialized = True
        logger.info(f"CacheManager ready — hot: {self.hot.stats}, warm size: {self.warm.size}")

    def _seed_caches(self) -> None:
        """Load known attack data into caches."""
        import yaml
        from pathlib import Path

        # Seed hot cache from YAML exact signatures
        pattern_path = Path(self.s.patterns_path)
        if pattern_path.exists():
            data = yaml.safe_load(pattern_path.read_text())
            sigs = data.get("known_exact_signatures", [])
            self.hot.seed_from_patterns(sigs)

        # Seed warm cache from data file
        self.warm.seed_from_file(self.s.known_attacks_path)

    def check(self, text: str) -> dict:
        """
        Full cache check: hot first, then warm.
        Returns result dict with 'tier', 'hit', and match metadata.
        """
        # Tier 0: exact hash
        hot_result = self.hot.check(text)
        if hot_result:
            return {
                "tier": 0,
                "hit": True,
                "is_high": True,
                "similarity": 1.0,
                **hot_result,
            }

        # Tier 1: semantic similarity
        warm_result = self.warm.check(text)
        if warm_result:
            return {
                "tier": 1,
                "hit": warm_result["is_high"],   # hit only if above high threshold
                "flag": True,                     # always flag warm cache matches
                **warm_result,
            }

        return {"tier": -1, "hit": False, "flag": False}

    def store_attack(self, text: str, family: str, severity: int,
                     add_to_hot: bool = True, add_to_warm: bool = True) -> None:
        """Store a confirmed attack in appropriate cache tiers."""
        metadata = {"family": family, "severity": severity, "source": "local"}
        if add_to_hot:
            self.hot.store(text, metadata)
        if add_to_warm:
            self.warm.store(text, family=family, severity=severity, source="local")

    def stats(self) -> dict:
        return {
            "hot": self.hot.stats,
            "warm": self.warm.stats,
        }
