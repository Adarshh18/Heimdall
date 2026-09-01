"""
HEIMDALL — Stream Manager
asyncio.Queue per session_id.
G1/G2 pipelines push layer events here.
SSE endpoint reads and forwards them to the browser.

Event shape (all events):
  {"event": "layer",   "gateway": "G1", "layer": "L0", "name": "Attack Cache",
   "status": "MISS|HIT|FLAG|BLOCK", "latency_ms": 0.3, "flags": 0}

  {"event": "verdict", "gateway": "G1|G2",
   "verdict": "PASS|SANITIZE|BLOCK", "confidence": 0.97,
   "attack_type": "JAILBREAK", "latency_ms": 513.0}

  {"event": "llm_start",  "providers": ["gemini","groq","mistral"]}
  {"event": "llm_result", "provider": "groq", "ok": true,
   "latency_ms": 320.0, "tokens": 45, "text_preview": "Machine learning..."}

  {"event": "complete", "reply": "...", "blocked": false,
   "sanitized": false, "total_latency_ms": 1100.0}

  {"event": "error", "detail": "..."}
  {"event": "done"}   ← signals SSE generator to close
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any


# How long (seconds) to keep a session queue alive after last use
_SESSION_TTL = 120


class StreamManager:
    """
    Singleton that holds one asyncio.Queue per active session.

    Usage:
        # In pipeline (sync context OK — put_nowait is thread-safe):
        stream_manager.push(session_id, {"event": "layer", ...})

        # In SSE endpoint (async):
        async for event in stream_manager.listen(session_id, timeout=60):
            yield event
    """

    def __init__(self):
        self._queues:      dict[str, asyncio.Queue] = {}
        self._last_active: dict[str, float]         = {}

    # ── Producer API (called from pipeline threads / async tasks) ──────────

    def push(self, session_id: str, event: dict[str, Any]) -> None:
        """
        Put an event onto the session queue.
        Thread-safe: uses put_nowait so sync pipeline code can call it.
        Silently drops events when queue is full (never blocks demo).
        Creates the queue if it doesn't exist yet.
        """
        q = self._ensure(session_id)
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass   # drop — frontend missed a frame, not critical
        self._last_active[session_id] = time.time()

    def done(self, session_id: str) -> None:
        """Push the terminal sentinel so the SSE generator closes cleanly."""
        self.push(session_id, {"event": "done"})

    def error(self, session_id: str, detail: str) -> None:
        """Push an error event then close."""
        self.push(session_id, {"event": "error", "detail": detail})
        self.done(session_id)

    # ── Consumer API (called from SSE endpoint) ────────────────────────────

    async def listen(
        self,
        session_id: str,
        timeout: float = 90.0,
    ):
        """
        Async generator — yields JSON strings for the SSE endpoint.
        Stops when it receives {"event": "done"} or timeout fires.
        """
        q = self._ensure(session_id)
        deadline = time.monotonic() + timeout

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                yield json.dumps({"event": "timeout"})
                break

            try:
                event = await asyncio.wait_for(q.get(), timeout=min(remaining, 5.0))
            except asyncio.TimeoutError:
                # Heartbeat so browser doesn't close the connection
                yield json.dumps({"event": "ping"})
                continue

            yield json.dumps(event)

            if event.get("event") in ("done", "error", "timeout"):
                break

        self._cleanup(session_id)

    # ── Helpers ────────────────────────────────────────────────────────────

    def _ensure(self, session_id: str) -> asyncio.Queue:
        if session_id not in self._queues:
            self._queues[session_id] = asyncio.Queue(maxsize=200)
        return self._queues[session_id]

    def _cleanup(self, session_id: str) -> None:
        self._queues.pop(session_id, None)
        self._last_active.pop(session_id, None)

    def evict_stale(self) -> int:
        """Remove queues inactive for > TTL. Call from background task."""
        cutoff = time.time() - _SESSION_TTL
        stale  = [sid for sid, t in self._last_active.items() if t < cutoff]
        for sid in stale:
            self._cleanup(sid)
        return len(stale)

    @property
    def active_sessions(self) -> int:
        return len(self._queues)


# ── Module-level singleton (imported everywhere) ───────────────────────────
stream_manager = StreamManager()
