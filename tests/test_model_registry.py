import pytest

from toolkit.model_registry import (
    ProviderConfigError,
    get_provider,
    registry_payload,
    resolve_provider_config,
)
from toolkit.model_security import redact_sensitive, safe_base_host, validate_base_url


def test_writing_registry_uses_only_two_protocols():
    protocols = {item["adapter"] for item in registry_payload()["writing"]}
    assert protocols == {"openai_compatible", "anthropic_messages"}


def test_resolve_provider_config_applies_defaults_without_hiding_overrides():
    resolved = resolve_provider_config("writing", {
        "provider_id": "openai",
        "model": "custom-model",
        "base_url": "https://gateway.example/v1",
        "api_key": "secret-key",
    })
    assert resolved == {
        "provider_id": "openai",
        "adapter": "openai_compatible",
        "model": "custom-model",
        "base_url": "https://gateway.example/v1",
        "api_key": "secret-key",
    }


def test_resolve_provider_config_uses_provider_defaults_for_omitted_values():
    assert resolve_provider_config("writing", {"provider_id": "openai", "api_key": "key"}) == {
        "provider_id": "openai",
        "adapter": "openai_compatible",
        "model": "gpt-5.5",
        "base_url": "https://api.openai.com/v1",
        "api_key": "key",
    }


def test_resolve_provider_config_rejects_unknown_provider_and_empty_required_fields():
    with pytest.raises(ProviderConfigError):
        resolve_provider_config("writing", {"provider_id": "unknown", "api_key": "key"})
    with pytest.raises(ProviderConfigError):
        resolve_provider_config("writing", {"provider_id": "openai", "api_key": ""})
    with pytest.raises(ProviderConfigError):
        resolve_provider_config("writing", {"provider_id": "custom-openai", "api_key": "key"})


def test_resolve_provider_config_rejects_model_equal_to_api_key_without_echoing_it():
    secret = "collision-secret-value"

    with pytest.raises(ProviderConfigError) as excinfo:
        resolve_provider_config(
            "writing",
            {
                "provider_id": "custom-openai",
                "model": secret,
                "base_url": "https://llm.example/v1",
                "api_key": secret,
            },
        )

    assert secret not in str(excinfo.value)
    assert "model" in str(excinfo.value)
    assert "api_key" in str(excinfo.value)


def test_get_provider_is_scoped_to_kind():
    assert get_provider("writing", "openai").kind == "writing"
    assert get_provider("image", "openai").kind == "image"
    with pytest.raises(ProviderConfigError):
        get_provider("unknown", "openai")


def test_image_registry_exposes_connection_test_metadata():
    image = {item["provider_id"]: item for item in registry_payload()["image"]}
    assert image["cliproxy"]["adapter"] == "openai"
    assert image["cliproxy"]["test_size"] == "1024x1024"
    assert image["custom-openai-image"]["supports_connection_test"] is True


def test_validate_base_url_rejects_userinfo_and_non_http_schemes():
    for value in ("file:///etc/passwd", "https://user:pass@example.com/v1"):
        try:
            validate_base_url(value)
        except ValueError:
            pass
        else:
            raise AssertionError(value)


def test_redact_sensitive_removes_keys_and_sensitive_query_values():
    message = "failed https://example.com/v1?api_key=abc token=xyz secret-key"
    assert redact_sensitive(message, secrets=("secret-key",)) == (
        "failed https://example.com/v1?api_key=*** token=*** ***"
    )
    assert safe_base_host("http://host.docker.internal:8317/v1") == "host.docker.internal:8317"


def test_redact_sensitive_removes_userinfo_and_authorization_values():
    message = "Authorization: Bearer private-token https://user:pass@example.com/v1?Key=value"
    assert redact_sensitive(message) == "Authorization: *** https://example.com/v1?Key=***"


def test_redact_sensitive_removes_quoted_mapping_values():
    message = '{"api_key":"abc"} {\'token\': \'xyz\'}'
    assert redact_sensitive(message) == '{"api_key":"***"} {\'token\': \'***\'}'


def test_redact_sensitive_removes_quoted_authorization_values():
    message = "{'Authorization': 'Bearer private-token'}"
    assert redact_sensitive(message) == "{'Authorization': '***'}"


def test_redact_sensitive_removes_userinfo_containing_at_signs():
    assert redact_sensitive("https://user:p@ss@example.com/") == "https://example.com/"
