"""Private local persistence for the web application's model selections."""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

import yaml

from toolkit import env_config
from toolkit.model_registry import ProviderConfigError, get_provider, resolve_provider_config


SETTINGS_PATH = env_config.SKILL_DIR / "webapp" / "_data" / "model-settings.json"

_SCHEMA_VERSION = 1
_SECTION_FIELDS = frozenset({"provider_id", "model", "base_url", "api_key"})
_ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::-(.*?))?\}")


@dataclass(frozen=True, init=False)
class EffectiveSettings:
    __slots__ = ("settings", "source", "warning")

    settings: dict
    source: Literal["local", "legacy-bootstrap", "legacy-fallback"]
    warning: str

    def __init__(
        self,
        settings: dict,
        source: Literal["local", "legacy-bootstrap", "legacy-fallback"],
        warning: str = "",
    ) -> None:
        object.__setattr__(self, "settings", settings)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "warning", warning)


def _clean_section(kind: str, value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ProviderConfigError(f"{kind} settings must be a mapping")
    unknown = set(value) - _SECTION_FIELDS
    if unknown:
        raise ProviderConfigError(f"Unknown {kind} settings: {', '.join(sorted(unknown))}")

    raw = dict(value)
    resolve_provider_config(kind, raw)
    return {field: raw[field] for field in _SECTION_FIELDS if field in raw}


def _validate_raw_settings(settings: object) -> dict:
    if not isinstance(settings, Mapping):
        raise ProviderConfigError("Model settings must be a mapping")
    if set(settings) != {"schema_version", "writing", "image"}:
        raise ProviderConfigError("Model settings must contain schema_version, writing, and image")
    if type(settings.get("schema_version")) is not int or settings.get("schema_version") != _SCHEMA_VERSION:
        raise ProviderConfigError(f"Unsupported model settings schema version: {settings.get('schema_version')!r}")

    return {
        "schema_version": _SCHEMA_VERSION,
        "writing": _clean_section("writing", settings["writing"]),
        "image": _clean_section("image", settings["image"]),
    }


def _resolve_settings(settings: object) -> dict:
    raw = _validate_raw_settings(settings)
    return {
        "schema_version": raw["schema_version"],
        "writing": resolve_provider_config("writing", raw["writing"]),
        "image": resolve_provider_config("image", raw["image"]),
    }


def load_settings(path: Path = SETTINGS_PATH) -> dict:
    """Load the stored user form without applying provider defaults."""
    with Path(path).open("r", encoding="utf-8") as handle:
        return _validate_raw_settings(json.load(handle))


def save_settings(settings: object, path: Path = SETTINGS_PATH) -> dict:
    """Validate and atomically save private, raw model-setting overrides."""
    raw = _validate_raw_settings(settings)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination.parent, 0o700)
    temp_path: str | None = None
    try:
        fd, temp_path = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(raw, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, destination)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass
    return raw


def _expand_env(value: object, environ: Mapping[str, str]) -> object:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            name, default = match.groups()
            candidate = environ.get(name)
            if candidate is not None and str(candidate).strip():
                return str(candidate)
            return default if default is not None else ""

        return _ENV_PATTERN.sub(replace, value)
    if isinstance(value, list):
        return [_expand_env(item, environ) for item in value]
    if isinstance(value, Mapping):
        return {key: _expand_env(item, environ) for key, item in value.items()}
    return value


def _provider_for_legacy_writing(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    if base_url == "https://api.minimaxi.com/anthropic":
        return "minimax-anthropic"
    if base_url == "https://api.anthropic.com":
        return "anthropic"
    return "custom-anthropic"


def _compact_legacy_section(kind: str, section: dict[str, str]) -> dict[str, str]:
    """Omit legacy values that are now registry defaults, retaining overrides."""
    spec = get_provider(kind, section["provider_id"])
    for field, default in (("model", spec.default_model), ("base_url", spec.default_base_url)):
        if section.get(field) == default:
            section.pop(field)
    resolve_provider_config(kind, section)
    return section


def _legacy_settings(environ: Mapping[str, str], config_path: Path) -> dict:
    with Path(config_path).open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    expanded = _expand_env(config, environ)
    if not isinstance(expanded, Mapping):
        raise ProviderConfigError("config.yaml must contain a mapping")

    writing_base_url = str(environ.get("ANTHROPIC_BASE_URL") or "")
    writing = _compact_legacy_section("writing", {
        "provider_id": _provider_for_legacy_writing(writing_base_url),
        "model": str(environ.get("ANTHROPIC_MODEL") or ""),
        "base_url": writing_base_url,
        "api_key": str(environ.get("ANTHROPIC_API_KEY") or ""),
    })

    image_config = expanded.get("image", {})
    providers = image_config.get("providers", []) if isinstance(image_config, Mapping) else []
    if not isinstance(providers, list) or not providers:
        raise ProviderConfigError("config.yaml 缺少 image.providers 列表")
    by_id = {
        item.get("id"): item for item in providers
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    order = str(environ.get("IMAGE_PROVIDER_ORDER") or "")
    selected_id = next((item.strip() for item in order.split(",") if item.strip()), None)
    if selected_id is None:
        selected_id = next(iter(by_id), None)
    selected = by_id.get(selected_id)
    if not isinstance(selected, Mapping):
        raise ProviderConfigError(f"Unknown image provider in legacy configuration: {selected_id!r}")

    image = _compact_legacy_section("image", {
        "provider_id": str(selected_id),
        "model": str(selected.get("model") or ""),
        "base_url": str(selected.get("base_url") or ""),
        "api_key": str(selected.get("api_key") or ""),
    })
    return _validate_raw_settings({
        "schema_version": _SCHEMA_VERSION,
        "writing": writing,
        "image": image,
    })


def bootstrap_settings(
    path: Path = SETTINGS_PATH,
    environ: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> dict:
    """Import legacy environment/config values exactly once, when no file exists."""
    destination = Path(path)
    if destination.exists():
        return load_settings(destination)
    if environ is None:
        env_config.load_env()
        environ = os.environ
    if config_path is None:
        config_path = env_config.SKILL_DIR / "config.yaml"
    settings = _legacy_settings(environ, Path(config_path))
    return save_settings(settings, destination)


def load_effective_settings(
    path: Path = SETTINGS_PATH,
    environ: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> EffectiveSettings:
    """Return current resolved settings, retaining legacy-fallback visibility."""
    destination = Path(path)
    if destination.exists():
        try:
            return EffectiveSettings(_resolve_settings(load_settings(destination)), "local")
        except (OSError, ValueError, json.JSONDecodeError):
            if environ is None:
                env_config.load_env()
                environ = os.environ
            if config_path is None:
                config_path = env_config.SKILL_DIR / "config.yaml"
            return EffectiveSettings(
                _resolve_settings(_legacy_settings(environ, Path(config_path))),
                "legacy-fallback",
                "模型设置文件损坏，已使用旧配置作为临时回退。",
            )

    return EffectiveSettings(
        _resolve_settings(bootstrap_settings(destination, environ, config_path)),
        "legacy-bootstrap",
    )


def snapshot_settings() -> dict:
    """Return an isolated resolved settings snapshot for runtime consumers."""
    return copy.deepcopy(load_effective_settings().settings)


def audit_settings(settings: object) -> dict:
    """Project settings for logs without exposing API keys or endpoint URLs."""
    if not isinstance(settings, Mapping):
        raise ProviderConfigError("Model settings must be a mapping")
    raw = dict(settings)
    for kind in ("writing", "image"):
        section = raw.get(kind)
        if isinstance(section, Mapping):
            raw[kind] = {key: value for key, value in section.items() if key != "adapter"}
    resolved = _resolve_settings(raw)
    return {
        kind: {
            "provider_id": resolved[kind]["provider_id"],
            "adapter": resolved[kind]["adapter"],
            "model": resolved[kind]["model"],
        }
        for kind in ("writing", "image")
    }
