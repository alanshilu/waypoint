"""
find_places results, kept for a day: in memory first, backed by a CacheStore (the places_cache table) so a
restart or a Render sleep doesn't empty it. The store is best effort: if it fails, searches carry on with
the memory cache alone.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.places_cache import PlacesCacheEntry

log = logging.getLogger(__name__)

CACHE_TTL_S = 24 * 3600
CACHE_MAX_ENTRIES = 500

# (kind, lat, lon rounded to ~1 km)
CacheKey = tuple[str, float, float]


def cache_key(kind: str, lat: float, lon: float) -> CacheKey:
    return kind, round(lat, 2), round(lon, 2)


class CacheStore(Protocol):
    """Somewhere results outlive the process. Implementations log failures; they never raise."""

    def load(self, keys: list[CacheKey], max_age_s: float) -> dict[CacheKey, tuple[float, dict]]:
        """Saved results younger than max_age_s: key -> (saved at, epoch seconds; result)."""
        ...

    def save(self, results: dict[CacheKey, dict], max_age_s: float) -> None:
        """Upserts results; may drop entries older than max_age_s."""
        ...


class NoStore:
    """A CacheStore that keeps nothing: the memory cache alone."""

    def load(self, keys, max_age_s):
        return {}

    def save(self, results, max_age_s):
        pass


def _db_key(key: CacheKey) -> str:
    kind, lat, lon = key
    return f"{kind}:{lat:.2f}:{lon:.2f}"


class DatabaseStore:
    """A CacheStore over the places_cache table."""

    def __init__(self, session_factory: Callable[[], Session]):
        self._session_factory = session_factory

    def load(self, keys, max_age_s):
        by_db_key = {_db_key(k): k for k in keys}
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_s)
        try:
            with self._session_factory() as db:
                rows = (db.query(PlacesCacheEntry)
                        .filter(PlacesCacheEntry.key.in_(by_db_key), PlacesCacheEntry.saved_at > cutoff)
                        .all())
        except SQLAlchemyError as e:
            log.warning("Places cache: couldn't read the database (%s); using the memory cache only", e)
            return {}
        return {by_db_key[r.key]: (r.saved_at.timestamp(), r.result) for r in rows}

    def save(self, results, max_age_s):
        now = datetime.now(timezone.utc)
        rows = [{"key": _db_key(k), "result": r, "saved_at": now} for k, r in results.items()]
        stmt = insert(PlacesCacheEntry).values(rows)
        stmt = stmt.on_conflict_do_update(index_elements=[PlacesCacheEntry.key],
                                          set_={"result": stmt.excluded.result, "saved_at": stmt.excluded.saved_at})
        try:
            with self._session_factory() as db:
                db.execute(stmt)
                db.query(PlacesCacheEntry).filter(
                    PlacesCacheEntry.saved_at < now - timedelta(seconds=max_age_s)).delete()
                db.commit()
        except SQLAlchemyError as e:
            log.warning("Places cache: couldn't save to the database (%s); kept in memory only", e)


class PlacesCache:
    """Results by search, for ttl_s: memory first (at most max_entries, oldest out), then the store."""

    def __init__(self, store: CacheStore | None = None, ttl_s: float = CACHE_TTL_S,
                 max_entries: int = CACHE_MAX_ENTRIES, clock: Callable[[], float] = time.time):
        self._store = store or NoStore()
        self._ttl_s = ttl_s
        self._max_entries = max_entries
        self._clock = clock
        self._memory: dict[CacheKey, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def get(self, key: CacheKey) -> dict | None:
        """From memory only."""
        with self._lock:
            hit = self._memory.get(key)
            if hit and self._clock() - hit[0] < self._ttl_s:
                return hit[1]
            return None

    def missing(self, keys: list[CacheKey]) -> list[CacheKey]:
        """The keys with no result, after filling memory from the store for those it has."""
        absent = [k for k in keys if self.get(k) is None]
        if absent:
            for key, (saved_at, result) in self._store.load(absent, self._ttl_s).items():
                self._remember(key, result, saved_at)
        return [k for k in absent if self.get(k) is None]

    def put(self, results: dict[CacheKey, dict]) -> None:
        now = self._clock()
        for key, result in results.items():
            self._remember(key, result, now)
        if results:
            self._store.save(results, self._ttl_s)

    def clear(self) -> None:
        """Clears memory (the store expires entries by age)."""
        with self._lock:
            self._memory.clear()

    def _remember(self, key: CacheKey, result: dict, saved_at: float) -> None:
        with self._lock:
            if key not in self._memory and len(self._memory) >= self._max_entries:
                self._memory.pop(min(self._memory, key=lambda k: self._memory[k][0]))
            self._memory[key] = (saved_at, result)
