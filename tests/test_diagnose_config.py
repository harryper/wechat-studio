import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from scripts import diagnose  # noqa: E402
from toolkit import env_config  # noqa: E402


def _write_config(tmp_path, *ids):
    entries = "\n".join(
        f'    - id: {i}\n      provider: "minimax"\n      api_key: "key"' for i in ids
    )
    (tmp_path / "config.yaml").write_text(
        f'wechat:\n  appid: "a"\n  secret: "s"\nimage:\n  providers:\n{entries}\n',
        encoding="utf-8",
    )


def test_provider_order_matching_config_passes(tmp_path, monkeypatch):
    _write_config(tmp_path, "cliproxy", "seedream")
    monkeypatch.setattr(diagnose, "SKILL_ROOT", tmp_path)
    monkeypatch.setattr(env_config, "_loaded", True)
    monkeypatch.setenv("IMAGE_PROVIDER_ORDER", "cliproxy,seedream")

    result = {c["name"]: c for c in diagnose.check_config()}

    assert result["image_providers"]["status"] == "pass"


def test_unknown_provider_id_fails(tmp_path, monkeypatch):
    _write_config(tmp_path, "cliproxy")
    monkeypatch.setattr(diagnose, "SKILL_ROOT", tmp_path)
    monkeypatch.setattr(env_config, "_loaded", True)
    monkeypatch.setenv("IMAGE_PROVIDER_ORDER", "cliproxy,typo")

    result = {c["name"]: c for c in diagnose.check_config()}

    assert result["image_providers"]["status"] == "fail"
    assert "typo" in result["image_providers"]["detail"]