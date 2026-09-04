"""Protocol adapters for configurable writing-model providers."""

import logging
import time
from typing import Any, Mapping

import anthropic
import requests

from toolkit.model_security import redact_sensitive, safe_base_host


logger = logging.getLogger(__name__)

_RESPONSE_DETAIL_LIMIT = 512


def _response_detail(response: requests.Response, api_key: str) -> str:
    content = response.content[:_RESPONSE_DETAIL_LIMIT]
    if isinstance(content, bytes):
        detail = content.decode("utf-8", errors="replace")
    else:
        detail = str(content)
    return redact_sensitive(detail, secrets=(api_key,))


def extract_openai_text(payload: object, provider_id: str) -> str:
    """Extract the first Chat Completions message content from a response."""
    try:
        content = payload["choices"][0]["message"]["content"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"{provider_id} 返回为空") from exc
    if not isinstance(content, str) or not content:
        raise RuntimeError(f"{provider_id} 返回为空")
    return content


def _extract_anthropic_text(response: object, provider_id: str) -> str:
    content = getattr(response, "content", ())
    text = "".join(
        block_text
        for block in content
        if isinstance((block_text := getattr(block, "text", None)), str)
    )
    if not text:
        raise RuntimeError(f"{provider_id} 返回为空")
    return text


def _generate_openai_compatible(
    prompt: str,
    settings: Mapping[str, str],
    *,
    max_tokens: int,
    timeout: int,
) -> str:
    base_url = settings["base_url"]
    api_key = settings["api_key"]
    response = requests.post(
        base_url.rstrip("/") + "/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings["model"],
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=timeout,
    )
    if not 200 <= response.status_code < 300:
        detail = _response_detail(response, api_key)
        raise RuntimeError(
            f"{settings['provider_id']} 请求失败 (HTTP {response.status_code}): {detail}"
        )
    return extract_openai_text(response.json(), settings["provider_id"])


def _generate_anthropic_messages(
    prompt: str,
    settings: Mapping[str, str],
    *,
    max_tokens: int,
    timeout: int,
) -> str:
    client = anthropic.Anthropic(
        base_url=settings["base_url"],
        api_key=settings["api_key"],
    )
    response = client.messages.create(
        model=settings["model"],
        max_tokens=max_tokens,
        timeout=timeout,
        messages=[{"role": "user", "content": prompt}],
    )
    return _extract_anthropic_text(response, settings["provider_id"])


def generate_text(
    prompt: str,
    settings: Mapping[str, str],
    *,
    max_tokens: int = 4096,
    timeout: int = 240,
) -> str:
    """Generate writing text with a validated provider configuration."""
    provider_id = settings["provider_id"]
    model = settings["model"]
    api_key = settings["api_key"]
    adapter = settings["adapter"]
    started_at = time.monotonic()
    host = safe_base_host(settings["base_url"])
    logger.info(
        "Writing adapter request adapter=%s provider_id=%s model=%s host=%s phase=start",
        adapter,
        provider_id,
        model,
        host,
    )
    try:
        if adapter == "openai_compatible":
            return _generate_openai_compatible(
                prompt, settings, max_tokens=max_tokens, timeout=timeout
            )
        if adapter == "anthropic_messages":
            return _generate_anthropic_messages(
                prompt, settings, max_tokens=max_tokens, timeout=timeout
            )
        raise RuntimeError(f"{provider_id} 不支持适配器 {adapter}")
    except Exception as exc:
        raise RuntimeError(
            redact_sensitive(exc, secrets=(api_key,))
        ) from None
    finally:
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        logger.info(
            "Writing adapter request adapter=%s provider_id=%s model=%s host=%s phase=done elapsed_ms=%s",
            adapter,
            provider_id,
            model,
            host,
            elapsed_ms,
        )


def test_writing_connection(
    settings: Mapping[str, str], *, timeout: int = 30
) -> dict[str, Any]:
    """Try a small writing request and return a redacted status payload."""
    started_at = time.monotonic()
    provider_id = settings["provider_id"]
    model = settings["model"]
    try:
        text = generate_text("只回复 OK", settings, max_tokens=8, timeout=timeout)
    except Exception as exc:
        result: dict[str, Any] = {
            "ok": False,
            "provider_id": provider_id,
            "model": model,
            "elapsed_ms": int((time.monotonic() - started_at) * 1000),
            "error": redact_sensitive(exc, secrets=(settings["api_key"],)),
        }
    else:
        result = {
            "ok": True,
            "provider_id": provider_id,
            "model": model,
            "elapsed_ms": int((time.monotonic() - started_at) * 1000),
            "text": text,
        }
    return result
