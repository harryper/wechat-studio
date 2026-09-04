"""The stable provider catalogue used by model settings consumers."""

from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping

from toolkit.model_security import validate_base_url


class ProviderConfigError(ValueError):
    """Raised when a provider selection or its settings are invalid."""


@dataclass(frozen=True, init=False)
class ProviderSpec:
    __slots__ = (
        "provider_id", "label", "kind", "adapter", "default_model",
        "default_base_url", "requires_api_key", "requires_base_url",
        "supports_connection_test", "test_size",
    )

    provider_id: str
    label: str
    kind: Literal["writing", "image"]
    adapter: str
    default_model: str
    default_base_url: str
    requires_api_key: bool
    requires_base_url: bool
    supports_connection_test: bool
    test_size: str

    def __init__(
        self,
        provider_id: str,
        label: str,
        kind: Literal["writing", "image"],
        adapter: str,
        default_model: str,
        default_base_url: str,
        requires_api_key: bool = True,
        requires_base_url: bool = True,
        supports_connection_test: bool = True,
        test_size: str = "",
    ) -> None:
        for field, value in locals().items():
            if field != "self":
                object.__setattr__(self, field, value)


WRITING_PROVIDERS = (
    ProviderSpec("minimax-anthropic", "MiniMax · Anthropic", "writing", "anthropic_messages", "MiniMax-M3", "https://api.minimaxi.com/anthropic"),
    ProviderSpec("openai", "OpenAI", "writing", "openai_compatible", "gpt-5.5", "https://api.openai.com/v1"),
    ProviderSpec("anthropic", "Anthropic", "writing", "anthropic_messages", "claude-sonnet-5", "https://api.anthropic.com"),
    ProviderSpec("kimi", "Kimi / Moonshot", "writing", "openai_compatible", "kimi-k3", "https://api.moonshot.cn/v1"),
    ProviderSpec("deepseek", "DeepSeek", "writing", "openai_compatible", "deepseek-v4-pro", "https://api.deepseek.com"),
    ProviderSpec("volcengine", "豆包 / 火山方舟", "writing", "openai_compatible", "doubao-seed-2-1-turbo-260628", "https://ark.cn-beijing.volces.com/api/v3"),
    ProviderSpec("custom-openai", "自定义 OpenAI-compatible", "writing", "openai_compatible", "", ""),
    ProviderSpec("custom-anthropic", "自定义 Anthropic Messages", "writing", "anthropic_messages", "", ""),
)

IMAGE_PROVIDERS = (
    ProviderSpec("cliproxy", "CLIProxy", "image", "openai", "gpt-image-2", "http://127.0.0.1:8317/v1", test_size="1024x1024"),
    ProviderSpec("seedream", "豆包 Seedream", "image", "seedream", "doubao-seedream-4-0-250828", "https://ark.cn-beijing.volces.com/api/v3", test_size="1024x1024"),
    ProviderSpec("minimax", "MiniMax", "image", "minimax", "image-01", "https://api.minimaxi.com/v1", test_size="1024x1024"),
    ProviderSpec("openai", "OpenAI", "image", "openai", "gpt-image-2", "https://api.openai.com/v1", test_size="1024x1024"),
    ProviderSpec("custom-openai-image", "自定义 OpenAI Image-compatible", "image", "openai", "", "", test_size="1024x1024"),
)

_ALLOWED_ADAPTERS = {
    "writing": {"openai_compatible", "anthropic_messages"},
    "image": {"openai", "seedream", "minimax"},
}


def _build_provider_index() -> dict[str, dict[str, ProviderSpec]]:
    index: dict[str, dict[str, ProviderSpec]] = {"writing": {}, "image": {}}
    for spec in (*WRITING_PROVIDERS, *IMAGE_PROVIDERS):
        if spec.kind not in _ALLOWED_ADAPTERS:
            raise ValueError(f"Unknown provider kind: {spec.kind}")
        if spec.adapter not in _ALLOWED_ADAPTERS[spec.kind]:
            raise ValueError(f"Unsupported adapter {spec.adapter!r} for {spec.kind}")
        if not spec.provider_id or spec.provider_id in index[spec.kind]:
            raise ValueError(f"Duplicate or empty provider id: {spec.provider_id!r}")
        index[spec.kind][spec.provider_id] = spec
    return index


_PROVIDERS = _build_provider_index()


def _require_kind(kind: str) -> None:
    if kind not in _PROVIDERS:
        raise ProviderConfigError(f"Unknown provider kind: {kind!r}")


def get_provider(kind: str, provider_id: str) -> ProviderSpec:
    """Find a provider by its ID within its writing or image kind."""
    _require_kind(kind)
    try:
        return _PROVIDERS[kind][provider_id]
    except KeyError as exc:
        raise ProviderConfigError(f"Unknown {kind} provider: {provider_id!r}") from exc


def registry_payload() -> dict[str, list[dict[str, Any]]]:
    """Return serializable registry data suitable for settings clients."""
    return {
        kind: [asdict(spec) for spec in providers.values()]
        for kind, providers in _PROVIDERS.items()
    }


def _required_text(field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderConfigError(f"{field} is required")
    return value


def resolve_provider_config(kind: str, raw: Mapping[str, object]) -> dict[str, str]:
    """Apply a provider's defaults, then validate the resolved configuration."""
    if not isinstance(raw, Mapping):
        raise ProviderConfigError("Provider configuration must be a mapping")
    provider_id = _required_text("provider_id", raw.get("provider_id"))
    spec = get_provider(kind, provider_id)

    model = raw.get("model", spec.default_model)
    base_url = raw.get("base_url", spec.default_base_url)
    api_key = raw.get("api_key", "")
    model = _required_text("model", model)
    if spec.requires_base_url:
        base_url = _required_text("base_url", base_url)
        try:
            validate_base_url(base_url)
        except ValueError as exc:
            raise ProviderConfigError(str(exc)) from exc
    elif not isinstance(base_url, str):
        raise ProviderConfigError("base_url must be a string")
    if spec.requires_api_key:
        api_key = _required_text("api_key", api_key)
    elif not isinstance(api_key, str):
        raise ProviderConfigError("api_key must be a string")

    return {
        "provider_id": spec.provider_id,
        "adapter": spec.adapter,
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
    }
