"""NoSQL persistence (MongoDB). Two collections:
  weather_raw : cleaned-nothing, as-fetched daily Tmax per (location, years)  -> avoids refetching
  analyses    : computed hazard analysis document per (location, years, definition params)
Both carry `fetched_at`/`computed_at` and a TTL index. With no MONGODB_URI we fall back to an
in-memory mongomock database so the app runs locally with zero setup (data is lost on restart)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from .errors import StorageError

log = logging.getLogger("store")


def _naive_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


class Store:
    def __init__(self, uri: str, db_name: str, ttl_days: int = 30, client=None):
        try:
            if client is None:
                if uri:
                    from pymongo import MongoClient
                    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
                else:
                    import mongomock
                    log.warning("MONGODB_URI not set: using in-memory mongomock (dev only, non-persistent)")
                    client = mongomock.MongoClient()
            self.client = client
            self.db = client[db_name]
            ttl = int(ttl_days * 86400)
            self.db.weather_raw.create_index("fetched_at", expireAfterSeconds=ttl)
            self.db.analyses.create_index("computed_at", expireAfterSeconds=ttl)
        except Exception as exc:
            raise StorageError(f"cannot initialise database: {type(exc).__name__}") from exc

    def _wrap(self, fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as exc:
            log.exception("database error")
            raise StorageError(f"database error: {type(exc).__name__}") from exc

    def ping(self) -> bool:
        try:
            self.client.admin.command("ping")
            return True
        except Exception:
            return False

    @staticmethod
    def _fresh(doc, field: str, max_age: timedelta, now: datetime | None = None) -> bool:
        if not doc or field not in doc:
            return False
        now = now or datetime.now(timezone.utc).replace(tzinfo=None)
        return now - _naive_utc(doc[field]) <= max_age

    def get_raw(self, key: str, max_age: timedelta):
        doc = self._wrap(self.db.weather_raw.find_one, {"_id": key})
        return doc if self._fresh(doc, "fetched_at", max_age) else None

    def put_raw(self, key: str, doc: dict) -> None:
        doc = {**doc, "_id": key, "fetched_at": datetime.now(timezone.utc).replace(tzinfo=None)}
        self._wrap(self.db.weather_raw.replace_one, {"_id": key}, doc, upsert=True)

    def get_analysis(self, key: str, max_age: timedelta, algo_version: str):
        doc = self._wrap(self.db.analyses.find_one, {"_id": key})
        if doc and doc.get("algo_version") == algo_version and self._fresh(doc, "computed_at", max_age):
            return doc
        return None

    def put_analysis(self, key: str, doc: dict, algo_version: str) -> None:
        rec = {"_id": key, "algo_version": algo_version, "analysis": doc,
               "computed_at": datetime.now(timezone.utc).replace(tzinfo=None)}
        self._wrap(self.db.analyses.replace_one, {"_id": key}, rec, upsert=True)
