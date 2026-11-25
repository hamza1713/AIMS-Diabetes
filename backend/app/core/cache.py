"""
TTL Search Result Cache
========================
In-memory cache for ColPali search results.

Why cache ColPali results?
- ColPali runs a deep neural forward pass for every query (PaliGemma 2 inference).
- This takes 1-5 seconds on CPU depending on hardware.
- Repeated or similar queries within a session hit the same evidence.
- A 5-minute TTL cache eliminates duplicate computation without staleness risk
  (the index only changes when ingest_papers.py is explicitly re-run).

Cache key: MD5(sorted(queries) + "|" + str(top_k))
  - Sorting queries means ["A", "B"] and ["B", "A"] share the same cache entry.
  - Including top_k ensures different result sizes don't collide.

Thread safety: RLock guards all reads/writes — safe under FastAPI thread-pool.
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.logger import get_logger

log = get_logger(__name__)


class SearchCache:
    """
    Thread-safe TTL cache for ColPali `search_enriched()` results.

    Attributes:
        ttl: Time-to-live in seconds. Entries older than this are considered stale.
        max_size: Maximum number of entries before the oldest are evicted.
    """

    def __init__(self, ttl_seconds: int = 300, max_size: int = 128) -> None:
        self.ttl = ttl_seconds
        self.max_size = max_size
        # {cache_key: (inserted_at: float, value: Any)}
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    # ── Key construction ───────────────────────────────────────────────────

    def _make_key(self, queries: List[str], top_k: int) -> str:
        raw = "|".join(sorted(q.lower().strip() for q in queries)) + f"|k={top_k}"
        return hashlib.md5(raw.encode()).hexdigest()

    # ── Public API ─────────────────────────────────────────────────────────

    def get(self, queries: List[str], top_k: int) -> Optional[Any]:
        """Return cached result, or None on miss / stale entry."""
        key = self._make_key(queries, top_k)
        now = time.monotonic()

        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None

            inserted_at, value = entry
            if now - inserted_at > self.ttl:
                del self._store[key]
                self._misses += 1
                log.debug("Cache STALE for key=%s…", key[:8])
                return None

            self._hits += 1
            log.debug("Cache HIT  for key=%s… (age=%.1fs)", key[:8], now - inserted_at)
            return value

    def set(self, queries: List[str], top_k: int, value: Any) -> None:
        """Store a result. Evicts oldest entry if max_size is reached."""
        key = self._make_key(queries, top_k)

        with self._lock:
            # Evict oldest entry when full
            if len(self._store) >= self.max_size:
                oldest_key = min(self._store, key=lambda k: self._store[k][0])
                del self._store[oldest_key]
                log.debug("Cache EVICT oldest entry to make room.")

            self._store[key] = (time.monotonic(), value)
            log.debug("Cache SET  for key=%s… (%d entries total)", key[:8], len(self._store))

    def invalidate(self) -> None:
        """Flush all entries (call after re-ingesting papers)."""
        with self._lock:
            count = len(self._store)
            self._store.clear()
            log.info("Search cache flushed (%d entries removed).", count)

    def stats(self) -> Dict[str, Any]:
        """Return cache health metrics for the /health endpoint."""
        with self._lock:
            total = self._hits + self._misses
            return {
                "entries": len(self._store),
                "max_size": self.max_size,
                "ttl_seconds": self.ttl,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate_pct": round(100 * self._hits / total, 1) if total else 0.0,
            }


# ── Module-level singleton ──────────────────────────────────────────────────
search_cache = SearchCache(ttl_seconds=300, max_size=128)
