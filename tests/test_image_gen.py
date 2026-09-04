"""Tests for toolkit/image_gen.py provider gating and fallback loop.

These guard the no-cost image pipeline: OpenAI stays off unless explicitly
opted in, providers are tried in order, and the first successful API
response is written unchanged (no OCR validator or quality retry).
"""
import base64
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


def test_seedream_provider_is_available_in_provider_chain():
    chain = image_gen._build_provider_chain(_config(
        {
            "provider": "seedream",
            "api_key": "ark-key",
            "model": "doubao-seedream-4-0-250828",
        },
    ))

    assert [p.provider_key for p in chain] == ["seedream"]


def test_seedream_provider_calls_ark_images_api_and_decodes_base64(monkeypatch):
    captured = {}
    expected = b"seedream-image"

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"data": [{"b64_json": base64.b64encode(expected).decode()}]}

    def fake_post(url, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return Response()

    monkeypatch.setattr(image_gen.requests, "post", fake_post)
    provider = image_gen.SeedreamProvider(
        api_key="ark-key",
        model="doubao-seedream-4-0-250828",
    )

    result = provider.generate("一张科普插画", "1792x1024")

    assert result == expected
    assert captured["url"] == (
        "https://ark.cn-beijing.volces.com/api/v3/images/generations"
    )
    assert captured["headers"]["Authorization"] == "Bearer ark-key"
    assert captured["json"] == {
        "model": "doubao-seedream-4-0-250828",
        "prompt": "一张科普插画",
        "size": "1792x1024",
        "response_format": "b64_json",
        "watermark": False,
    }


def test_gpt_image_provider_decodes_base64_response(monkeypatch):
    expected = b"gpt-image-output"

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"data": [{"b64_json": base64.b64encode(expected).decode()}]}

    monkeypatch.setattr(image_gen.requests, "post", lambda *args, **kwargs: Response())
    provider = image_gen.OpenAIProvider(
        api_key="proxy-key",
        model="gpt-image-2",
        base_url="http://127.0.0.1:8317/v1",
    )

    assert provider.generate("一张科普插画", "1536x1024") == expected


@pytest.mark.parametrize("preset", ["cover", "article"])
def test_gpt_image_provider_uses_supported_landscape_size(preset):
    provider = image_gen.OpenAIProvider(api_key="proxy-key", model="gpt-image-2")

    assert provider.resolve_size(preset) == "1536x1024"


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
