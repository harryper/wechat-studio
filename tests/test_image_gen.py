"""Tests for toolkit/image_gen.py provider gating and fallback loop.

These guard the no-cost image pipeline: OpenAI stays off unless explicitly
opted in, providers are tried in order, and the first successful API
response is written unchanged (no OCR validator or quality retry).
"""
import inspect
import sys
from pathlib import Path

import pytest

TOOLKIT_DIR = Path(__file__).resolve().parent.parent / "toolkit"
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

import image_gen  # noqa: E402


def _config(*entries):
    return {"image": {"providers": list(entries)}}


# ── provider enable/disable gating ────────────────────────────────────
def test_disabled_provider_entry_is_skipped():
    chain = image_gen._build_provider_chain(_config(
        {"provider": "minimax", "api_key": "k1"},
        {"provider": "openai", "api_key": "k2", "enabled": False},
    ))
    assert [p.provider_key for p in chain] == ["minimax"]


def test_disabled_provider_flag_defaults_to_false_without_opt_in(monkeypatch):
    monkeypatch.delenv("OPENAI_IMAGE_ENABLED", raising=False)
    config = image_gen._expand_env(_config(
        {"provider": "minimax", "api_key": "k1"},
        {"provider": "openai", "api_key": "k2",
         "enabled": "${OPENAI_IMAGE_ENABLED:-false}"},
    ))
    chain = image_gen._build_provider_chain(config)
    assert [p.provider_key for p in chain] == ["minimax"]


def test_disabled_provider_flag_honours_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("OPENAI_IMAGE_ENABLED", "true")
    config = image_gen._expand_env(_config(
        {"provider": "minimax", "api_key": "k1"},
        {"provider": "openai", "api_key": "k2",
         "enabled": "${OPENAI_IMAGE_ENABLED:-false}"},
    ))
    chain = image_gen._build_provider_chain(config)
    assert [p.provider_key for p in chain] == ["minimax", "openai"]


@pytest.mark.parametrize("falsy", ["false", "False", "0", "no", "off", " off "])
def test_disabled_provider_accepts_falsy_strings(falsy):
    chain = image_gen._build_provider_chain(_config(
        {"provider": "minimax", "api_key": "k1"},
        {"provider": "openai", "api_key": "k2", "enabled": falsy},
    ))
    assert [p.provider_key for p in chain] == ["minimax"]


def test_disabled_provider_gating_leaves_entries_without_flag_enabled():
    chain = image_gen._build_provider_chain(_config(
        {"provider": "minimax", "api_key": "k1"},
        {"provider": "openai", "api_key": "k2", "enabled": True},
    ))
    assert [p.provider_key for p in chain] == ["minimax", "openai"]


# ── simple provider fallback loop ─────────────────────────────────────
class FakeProvider(image_gen.ImageProvider):
    """Provider returning a distinct payload per call, recording prompts."""

    def __init__(self, key, payloads):
        self._key = key
        self._payloads = list(payloads)
        self.prompts = []

    @property
    def provider_key(self):
        return self._key

    def resolve_size(self, preset):
        return "1792x1024"

    def generate(self, prompt, size):
        self.prompts.append(prompt)
        payload = self._payloads[min(len(self.prompts) - 1, len(self._payloads) - 1)]
        if isinstance(payload, Exception):
            raise payload
        return payload


@pytest.fixture
def fake_chain(monkeypatch):
    holder = {}

    def install(*providers):
        holder["providers"] = list(providers)
        monkeypatch.setattr(image_gen, "_build_provider_chain",
                            lambda config: list(holder["providers"]))
        return holder["providers"]

    return install


def test_generate_image_has_simple_public_signature():
    assert list(inspect.signature(image_gen.generate_image).parameters) == [
        "prompt", "output_path", "size", "config",
    ]


def test_generate_image_accepts_first_successful_provider_bytes(tmp_path, fake_chain):
    minimax = FakeProvider("minimax", [b"image-with-any-content"])
    fallback = FakeProvider("openai", [b"never"])
    fake_chain(minimax, fallback)
    out = tmp_path / "cover.jpg"

    image_gen.generate_image("prompt", str(out), config={})

    assert out.read_bytes() == b"image-with-any-content"
    assert fallback.prompts == []


def test_generate_image_falls_back_after_provider_exception(tmp_path, fake_chain):
    minimax = FakeProvider("minimax", [RuntimeError("quota")])
    fallback = FakeProvider("fallback", [b"clean"])
    fake_chain(minimax, fallback)
    out = tmp_path / "cover.jpg"

    image_gen.generate_image("prompt", str(out), config={})

    assert out.read_bytes() == b"clean"


def test_generate_image_raises_when_every_provider_fails(tmp_path, fake_chain):
    minimax = FakeProvider("minimax", [RuntimeError("quota")])
    fallback = FakeProvider("fallback", [RuntimeError("down")])
    fake_chain(minimax, fallback)

    with pytest.raises(ValueError, match="All providers failed"):
        image_gen.generate_image("prompt", str(tmp_path / "c.jpg"), config={})
    assert not (tmp_path / "c.jpg").exists()
