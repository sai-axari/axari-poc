"""
Short-lived TTL cache for tool results to avoid redundant API calls.

During a single conversation turn, the orchestrator or worker may call
the same tool with the same arguments multiple times (e.g., fetching
calendar events while reasoning about a meeting). This cache avoids
making duplicate external API calls by storing results with a short TTL.

The cache is shared across all requests (singleton in api/router.py),
and tenant isolation is implicit — tool arguments always include
tenant_id, so the cache key naturally scopes results per tenant.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import NamedTuple

from config.settings import TOOL_CACHE_TTL, TOOL_CACHE_MAX_ENTRIES

logger = logging.getLogger(__name__)

# Meta-tools (delegate_subtask) produce non-deterministic results
# that depend on conversation context, so they must never be cached.
META_TOOLS = frozenset({"delegate_subtask"})


class _CacheEntry(NamedTuple):
    """Internal cache entry holding the result string and its expiry time."""
    result: str
    expires_at: float  # Unix timestamp when this entry becomes stale


class ToolResultCache:
    """In-memory TTL cache keyed by (tool_name, args_hash).

    One instance is created as a module-level singleton in ``api/router.py``
    and shared across all requests.  The TTL (default 5 min) handles staleness;
    tenant isolation is implicit because tool args include ``tenant_id``.
    """

    def __init__(
        self,
        ttl_seconds: int = TOOL_CACHE_TTL,
        max_entries: int = TOOL_CACHE_MAX_ENTRIES,
    ) -> None:
        self._ttl = ttl_seconds       # How long a cached result is valid
        self._max = max_entries        # Maximum number of entries before eviction
        self._store: dict[str, _CacheEntry] = {}  # SHA-256 key -> cache entry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def _make_key(tool_name: str, tool_input: dict) -> str:
        """
        Create a deterministic cache key from tool name + arguments.

        Uses sort_keys=True in JSON serialization so that dict ordering
        doesn't affect the key, then hashes with SHA-256 for a fixed-length key.
        """
        raw = tool_name + json.dumps(tool_input, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, tool_name: str, tool_input: dict) -> str | None:
        """
        Return cached result or None if missing / expired.

        Meta-tools are always skipped (never cached).
        Expired entries are eagerly deleted on access.
        """
        if tool_name in META_TOOLS:
            return None
        key = self._make_key(tool_name, tool_input)
        entry = self._store.get(key)
        if entry is None:
            return None
        # Check if the entry has expired
        if time.time() > entry.expires_at:
            del self._store[key]
            return None
        return entry.result

    def put(self, tool_name: str, tool_input: dict, result: str) -> None:
        """
        Store a tool result with a TTL.

        Before inserting, runs lazy eviction of expired entries. If still
        at capacity after eviction, drops the entry expiring soonest (LRU-ish).
        """
        if tool_name in META_TOOLS:
            return
        self._evict_expired()
        # If still at capacity after evicting expired entries, drop the one
        # closest to expiry to make room
        if len(self._store) >= self._max:
            oldest_key = min(self._store, key=lambda k: self._store[k].expires_at)
            del self._store[oldest_key]
        key = self._make_key(tool_name, tool_input)
        self._store[key] = _CacheEntry(
            result=result,
            expires_at=time.time() + self._ttl,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evict_expired(self) -> None:
        """Remove all entries whose TTL has elapsed."""
        now = time.time()
        expired = [k for k, v in self._store.items() if now > v.expires_at]
        for k in expired:
            del self._store[k]
