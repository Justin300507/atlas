from __future__ import annotations

import logging
import os
import re
from typing import Mapping

_ORIGIN_RE = re.compile(r"^https?://[^/\s*]+$")

_DEFAULT_DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]


class ConfigError(Exception):
    pass


def _parse_origins(raw: str) -> list[str]:
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _validate_origins(origins: list[str]) -> None:
    invalid = [origin for origin in origins if not _ORIGIN_RE.match(origin)]
    if invalid:
        raise ConfigError(
            "ATLAS_ALLOWED_ORIGINS contains invalid origin(s) "
            f"{invalid!r}; expected 'scheme://host[:port]' with no path or "
            "trailing slash."
        )


def resolve_cors_origins(env: Mapping[str, str] | None = None) -> list[str]:
    env = os.environ if env is None else env
    atlas_env = env.get("ATLAS_ENV", "development").strip().lower()
    configured = _parse_origins(env.get("ATLAS_ALLOWED_ORIGINS", ""))

    if atlas_env == "production":
        if not configured:
            raise ConfigError(
                "ATLAS_ENV=production requires ATLAS_ALLOWED_ORIGINS to be set "
                "to a comma-separated list of allowed origins -- refusing to "
                "start rather than fall back to an insecure default."
            )
        if "*" in configured:
            raise ConfigError(
                "ATLAS_ALLOWED_ORIGINS may not contain '*' when ATLAS_ENV=production."
            )
        _validate_origins(configured)
        return configured

    if atlas_env != "development":
        raise ConfigError(
            f"Unknown ATLAS_ENV={atlas_env!r}; expected 'development' or 'production'."
        )

    if configured:
        _validate_origins(configured)
        return configured
    return list(_DEFAULT_DEV_ORIGINS)


def resolve_log_level(env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    raw = env.get("ATLAS_LOG_LEVEL", "INFO").strip().upper()
    level = logging.getLevelName(raw)
    if not isinstance(level, int):
        raise ConfigError(
            f"Unknown ATLAS_LOG_LEVEL={raw!r}; expected one of DEBUG, INFO, "
            "WARNING, ERROR, CRITICAL."
        )
    return level
