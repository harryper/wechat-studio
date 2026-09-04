"""Single entry point for machine-specific configuration.

Every base_url, API key and provider priority comes from the environment
(optionally seeded by an uncommitted .env), never from committed files.
"""

from __future__ import annotations

import os
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent

_loaded = False


class ConfigError(RuntimeError):
    """Raised when a required environment variable is missing."""


def _is_set(value) -> bool:
    # docker-compose injects undefined variables as empty strings.
    return bool(value and value.strip())


def load_env() -> None:
    """Seed os.environ from .env so cron and subagents work without a shell profile."""
    global _loaded
    if _loaded:
        return
    for env_path in (SKILL_DIR / ".env", Path.cwd() / ".env"):
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and not _is_set(os.environ.get(key)):
                os.environ[key] = value
    _loaded = True


def get(name: str, default: str | None = None) -> str | None:
    load_env()
    value = os.environ.get(name)
    return value.strip() if _is_set(value) else default


def require(name: str, hint: str = "") -> str:
    value = get(name)
    if value is None:
        suffix = f"（{hint}）" if hint else ""
        raise ConfigError(
            f"{name} 未设置{suffix} — 请在 .env 中配置，参考 .env.example。"
        )
    return value


def provider_order() -> list[str] | None:
    """Ordered image provider ids from IMAGE_PROVIDER_ORDER, or None if unset."""
    raw = get("IMAGE_PROVIDER_ORDER")
    if raw is None:
        return None
    ids = [part.strip() for part in raw.split(",") if part.strip()]
    return ids or None
