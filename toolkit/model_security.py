"""Validation and redaction helpers for model-provider settings."""

import re
from urllib.parse import urlsplit


_SENSITIVE_NAME = r"api_key|token|key|secret|password"
_QUERY_SENSITIVE = re.compile(
    rf"([?&]({_SENSITIVE_NAME})=)[^&#\s]*", re.IGNORECASE
)
_ASSIGNMENT_SENSITIVE = re.compile(
    rf"(\b(?:{_SENSITIVE_NAME})\b\s*=\s*)[^\s,&#]+", re.IGNORECASE
)
_QUOTED_MAPPING_SENSITIVE = re.compile(
    rf"((?:[\"'])(?:{_SENSITIVE_NAME}|authorization)(?:[\"'])\s*:\s*[\"'])[^\"']*([\"'])",
    re.IGNORECASE,
)
_AUTHORIZATION = re.compile(
    r"\bAuthorization\s*:\s*(?:Bearer\s+|Basic\s+)?[^\s,]+", re.IGNORECASE
)
_URL_USERINFO = re.compile(r"\b(https?://)[^\s/?#]*@", re.IGNORECASE)


def validate_base_url(value: str) -> str:
    """Return a validated HTTP(S) base URL without allowing userinfo."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Base URL is required")

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid base URL") from exc

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Base URL must use http or https and include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Base URL must not include userinfo")
    if port is not None and not 0 < port <= 65535:
        raise ValueError("Invalid base URL port")
    return value


def safe_base_host(value: str) -> str:
    """Return only a validated URL's host and optional port."""
    validate_base_url(value)
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{parsed.port}" if parsed.port is not None else host


def redact_sensitive(value: object, secrets: tuple[str, ...] = ()) -> str:
    """Redact configured secrets and credential-like values from text."""
    text = "" if value is None else str(value)
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        text = text.replace(secret, "***")
    text = _URL_USERINFO.sub(r"\1", text)
    text = _AUTHORIZATION.sub("Authorization: ***", text)
    text = _QUERY_SENSITIVE.sub(r"\1***", text)
    text = _QUOTED_MAPPING_SENSITIVE.sub(r"\1***\2", text)
    return _ASSIGNMENT_SENSITIVE.sub(r"\1***", text)
