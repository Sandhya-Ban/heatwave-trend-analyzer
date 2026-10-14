"""Runtime configuration, read once from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    mongodb_uri: str = ""            # empty -> in-memory mongomock (dev/tests only)
    mongodb_db: str = "climate_hazards"
    cors_origins: tuple = ()
    cache_ttl_days: int = 30
    fresh_data_ttl_hours: int = 24   # TTL when the requested range includes the current year
    rate_limit_general: int = 120    # requests / window / IP
    rate_limit_heavy: int = 20       # analysis + export requests / window / IP
    rate_window_s: int = 60
    trust_proxy: bool = False        # honour X-Forwarded-For (set true behind Render/Cloud Run)
    provider_timeout_s: float = 60.0
    provider_retries: int = 3
    max_concurrent_fetches: int = 2
    frontend_dist: str = ""
    synthetic: bool = False          # offline demo mode: generated (NOT real) data

    @classmethod
    def from_env(cls) -> "Settings":
        origins = tuple(o.strip().rstrip("/") for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip())
        return cls(
            mongodb_uri=os.environ.get("MONGODB_URI", ""),
            mongodb_db=os.environ.get("MONGODB_DB", "climate_hazards"),
            cors_origins=origins,
            cache_ttl_days=_int("CACHE_TTL_DAYS", 30),
            fresh_data_ttl_hours=_int("FRESH_DATA_TTL_HOURS", 24),
            rate_limit_general=_int("RATE_LIMIT_GENERAL", 120),
            rate_limit_heavy=_int("RATE_LIMIT_HEAVY", 20),
            rate_window_s=_int("RATE_WINDOW_S", 60),
            trust_proxy=_bool("TRUST_PROXY"),
            provider_timeout_s=float(os.environ.get("PROVIDER_TIMEOUT_S", 60)),
            provider_retries=_int("PROVIDER_RETRIES", 3),
            max_concurrent_fetches=_int("MAX_CONCURRENT_FETCHES", 2),
            frontend_dist=os.environ.get(
                "FRONTEND_DIST",
                str(Path(__file__).resolve().parent.parent.parent / "frontend" / "dist")
                if (Path(__file__).resolve().parent.parent.parent / "frontend" / "dist").is_dir()
                else ""
            ),
            synthetic=_bool("DEMO_SYNTHETIC"),
        )
