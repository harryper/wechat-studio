"""Tests for toolkit/env_config.py — the single source of env configuration."""
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from toolkit import env_config  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("PROBE_VAR", "IMAGE_PROVIDER_ORDER", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(env_config, "_loaded", False)


def test_load_env_reads_project_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text('PROBE_VAR="from-file"\n', encoding="utf-8")
    monkeypatch.setattr(env_config, "SKILL_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)

    env_config.load_env()

    assert env_config.get("PROBE_VAR") == "from-file"


def test_load_env_does_not_override_real_environment(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("PROBE_VAR=from-file\n", encoding="utf-8")
    monkeypatch.setattr(env_config, "SKILL_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROBE_VAR", "from-shell")

    env_config.load_env()

    assert env_config.get("PROBE_VAR") == "from-shell"


def test_empty_string_counts_as_unset(tmp_path, monkeypatch):
    """docker-compose injects undefined variables as empty strings."""
    (tmp_path / ".env").write_text("PROBE_VAR=from-file\n", encoding="utf-8")
    monkeypatch.setattr(env_config, "SKILL_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROBE_VAR", "")

    env_config.load_env()

    assert env_config.get("PROBE_VAR") == "from-file"


def test_get_returns_default_for_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(env_config, "SKILL_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    assert env_config.get("PROBE_VAR", "fallback") == "fallback"


def test_require_raises_config_error_naming_the_variable(tmp_path, monkeypatch):
    monkeypatch.setattr(env_config, "SKILL_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(env_config.ConfigError) as excinfo:
        env_config.require("ANTHROPIC_BASE_URL", hint="写作端点")

    message = str(excinfo.value)
    assert "ANTHROPIC_BASE_URL" in message
    assert "写作端点" in message


def test_require_returns_value_when_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.test/anthropic")
    assert env_config.require("ANTHROPIC_BASE_URL") == "https://example.test/anthropic"


def test_provider_order_parses_and_strips(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER_ORDER", " cliproxy , seedream ,, minimax ")
    assert env_config.provider_order() == ["cliproxy", "seedream", "minimax"]


def test_provider_order_returns_none_when_unset(tmp_path, monkeypatch):
    monkeypatch.setattr(env_config, "SKILL_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    assert env_config.provider_order() is None


def test_provider_order_returns_none_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(env_config, "SKILL_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IMAGE_PROVIDER_ORDER", "   ")
    assert env_config.provider_order() is None
