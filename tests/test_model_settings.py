import copy
import json
import os
from dataclasses import replace

from toolkit import model_registry
from webapp import model_settings


CONFIG_YAML = """\
wechat:
  appid: "${WECHAT_APPID}"
  secret: "${WECHAT_SECRET}"
image:
  providers:
    - id: cliproxy
      provider: "openai"
      api_key: "${CLIPROXY_IMAGE_API_KEY}"
      model: "gpt-image-2"
      base_url: "${CLIPROXY_IMAGE_BASE_URL:-http://127.0.0.1:8317/v1}"
    - id: seedream
      provider: "seedream"
      api_key: "${ARK_API_KEY}"
      model: "doubao-seedream-4-0-250828"
      base_url: "https://ark.cn-beijing.volces.com/api/v3"
"""

LEGACY_ENV = {
    "ANTHROPIC_BASE_URL": "https://api.minimaxi.com/anthropic",
    "ANTHROPIC_API_KEY": "legacy-write",
    "ANTHROPIC_MODEL": "MiniMax-M3",
    "IMAGE_PROVIDER_ORDER": "cliproxy,seedream,minimax",
    "CLIPROXY_IMAGE_API_KEY": "legacy-image",
    "CLIPROXY_IMAGE_BASE_URL": "http://host.docker.internal:8317/v1",
}

SETTINGS_WITH_KEYS = {
    "schema_version": 1,
    "writing": {
        "provider_id": "custom-openai",
        "model": "writer",
        "base_url": "https://llm.example/v1",
        "api_key": "write-secret",
    },
    "image": {
        "provider_id": "cliproxy",
        "model": "gpt-image-2",
        "base_url": "http://127.0.0.1:8317/v1",
        "api_key": "image-secret",
    },
}


def test_save_is_atomic_private_and_round_trips_full_keys(tmp_path):
    path = tmp_path / "model-settings.json"
    settings = {
        "schema_version": 1,
        "writing": {"provider_id": "custom-openai", "model": "writer", "base_url": "https://llm.example/v1", "api_key": "write-secret"},
        "image": {"provider_id": "custom-openai-image", "model": "image-model", "base_url": "https://image.example/v1", "api_key": "image-secret"},
    }
    assert model_settings.save_settings(settings, path) == model_settings.load_settings(path)
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert list(tmp_path.glob("*.tmp")) == []


def test_save_makes_existing_parent_private(tmp_path):
    parent = tmp_path / "existing-data"
    parent.mkdir(mode=0o755)
    path = parent / "model-settings.json"
    settings = {
        "schema_version": 1,
        "writing": {"provider_id": "openai", "api_key": "write-secret"},
        "image": {"provider_id": "cliproxy", "api_key": "image-secret"},
    }

    model_settings.save_settings(settings, path)

    assert os.stat(parent).st_mode & 0o777 == 0o700


def test_bootstrap_imports_legacy_env_without_mutating_it(tmp_path):
    env = {
        "ANTHROPIC_BASE_URL": "https://api.minimaxi.com/anthropic",
        "ANTHROPIC_API_KEY": "legacy-write",
        "ANTHROPIC_MODEL": "MiniMax-M3",
        "IMAGE_PROVIDER_ORDER": "cliproxy,seedream,minimax",
        "CLIPROXY_IMAGE_API_KEY": "legacy-image",
        "CLIPROXY_IMAGE_BASE_URL": "http://host.docker.internal:8317/v1",
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG_YAML, encoding="utf-8")
    settings = model_settings.bootstrap_settings(tmp_path / "settings.json", env, config_path)
    assert settings["writing"]["provider_id"] == "minimax-anthropic"
    assert settings["image"]["provider_id"] == "cliproxy"
    assert env["ANTHROPIC_API_KEY"] == "legacy-write"


def test_corrupt_file_is_preserved_and_reports_legacy_fallback(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{broken", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG_YAML, encoding="utf-8")
    result = model_settings.load_effective_settings(path, LEGACY_ENV, config_path)
    assert result.source == "legacy-fallback"
    assert result.warning.startswith("模型设置文件损坏")
    assert path.read_text(encoding="utf-8") == "{broken"


def test_audit_projection_never_contains_secrets_or_base_url():
    audit = model_settings.audit_settings(SETTINGS_WITH_KEYS)
    assert audit == {
        "writing": {"provider_id": "custom-openai", "adapter": "openai_compatible", "model": "writer"},
        "image": {"provider_id": "cliproxy", "adapter": "openai", "model": "gpt-image-2"},
    }


def test_audit_projection_accepts_resolved_settings():
    resolved = {
        "schema_version": 1,
        "writing": {
            "provider_id": "openai",
            "adapter": "openai_compatible",
            "model": "gpt-5.5",
            "base_url": "https://api.openai.com/v1",
            "api_key": "write-secret",
        },
        "image": {
            "provider_id": "cliproxy",
            "adapter": "openai",
            "model": "gpt-image-2",
            "base_url": "http://127.0.0.1:8317/v1",
            "api_key": "image-secret",
        },
    }

    assert model_settings.audit_settings(resolved) == {
        "writing": {"provider_id": "openai", "adapter": "openai_compatible", "model": "gpt-5.5"},
        "image": {"provider_id": "cliproxy", "adapter": "openai", "model": "gpt-image-2"},
    }


def test_audit_projection_masks_model_equal_to_api_key_defensively():
    secret = "audit-collision-secret"
    settings = copy.deepcopy(SETTINGS_WITH_KEYS)
    settings["writing"]["model"] = secret
    settings["writing"]["api_key"] = secret

    audit = model_settings.audit_settings(settings)

    assert audit["writing"]["model"] == "***"
    assert secret not in str(audit)


def test_effective_settings_resolve_defaults_without_persisting_them(tmp_path):
    path = tmp_path / "settings.json"
    raw = {
        "schema_version": 1,
        "writing": {"provider_id": "openai", "api_key": "write-key"},
        "image": {"provider_id": "cliproxy", "api_key": "image-key"},
    }

    model_settings.save_settings(raw, path)

    assert model_settings.load_settings(path) == raw
    assert model_settings.load_effective_settings(path).settings == {
        "schema_version": 1,
        "writing": {
            "provider_id": "openai",
            "adapter": "openai_compatible",
            "model": "gpt-5.5",
            "base_url": "https://api.openai.com/v1",
            "api_key": "write-key",
        },
        "image": {
            "provider_id": "cliproxy",
            "adapter": "openai",
            "model": "gpt-image-2",
            "base_url": "http://127.0.0.1:8317/v1",
            "api_key": "image-key",
        },
    }


def test_load_settings_preserves_explicit_fields_already_on_disk(tmp_path):
    """Compaction is a save boundary, not a mutation of existing stored forms."""
    path = tmp_path / "settings.json"
    stored = {
        "schema_version": 1,
        "writing": {
            "provider_id": "openai",
            "model": "gpt-5.5",
            "base_url": "https://api.openai.com/v1",
            "api_key": "write-key",
        },
        "image": {
            "provider_id": "cliproxy",
            "model": "gpt-image-2",
            "base_url": "http://127.0.0.1:8317/v1",
            "api_key": "image-key",
        },
    }
    path.write_text(json.dumps(stored), encoding="utf-8")

    assert model_settings.load_settings(path) == stored


def test_unchanged_resolved_preset_form_keeps_following_registry_defaults(
    tmp_path, monkeypatch
):
    """A GET → unchanged PUT must not turn current preset defaults into overrides."""
    path = tmp_path / "settings.json"
    submitted = {
        "schema_version": 1,
        "writing": {
            "provider_id": "openai",
            "model": "gpt-5.5",
            "base_url": "https://api.openai.com/v1",
            "api_key": "write-key",
        },
        "image": {
            "provider_id": "cliproxy",
            "model": "gpt-image-2",
            "base_url": "http://127.0.0.1:8317/v1",
            "api_key": "image-key",
        },
    }
    model_settings.save_settings(submitted, path)

    unchanged_form = copy.deepcopy(
        model_settings.load_effective_settings(path).settings
    )
    for section in (unchanged_form["writing"], unchanged_form["image"]):
        section.pop("adapter")
    model_settings.save_settings(unchanged_form, path)

    assert model_settings.load_settings(path) == {
        "schema_version": 1,
        "writing": {"provider_id": "openai", "api_key": "write-key"},
        "image": {"provider_id": "cliproxy", "api_key": "image-key"},
    }

    current = model_registry.get_provider("writing", "openai")
    monkeypatch.setitem(
        model_registry._PROVIDERS["writing"],
        "openai",
        replace(
            current,
            default_model="gpt-next",
            default_base_url="https://next.example/v2",
        ),
    )

    effective = model_settings.load_effective_settings(path).settings
    assert effective["writing"]["model"] == "gpt-next"
    assert effective["writing"]["base_url"] == "https://next.example/v2"


def test_save_preserves_preset_overrides_and_all_custom_provider_values(tmp_path):
    path = tmp_path / "settings.json"
    submitted = {
        "schema_version": 1,
        "writing": {
            "provider_id": "openai",
            "model": "gateway-model",
            "base_url": "https://gateway.example/v1",
            "api_key": "write-key",
        },
        "image": {
            "provider_id": "custom-openai-image",
            "model": "gpt-image-2",
            "base_url": "https://api.openai.com/v1",
            "api_key": "image-key",
        },
    }

    model_settings.save_settings(submitted, path)

    assert model_settings.load_settings(path) == submitted
