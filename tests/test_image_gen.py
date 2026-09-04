"""Tests for toolkit/image_gen.py provider ordering and fallback loop.

These guard the image pipeline: IMAGE_PROVIDER_ORDER decides which
providers run and in what order, unknown ids fail loudly, and the first
successful API response is written unchanged.
"""
import base64
import inspect
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
TOOLKIT_DIR = SKILL_DIR / "toolkit"
for _path in (str(SKILL_DIR), str(TOOLKIT_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import image_gen  # noqa: E402
from toolkit import env_config  # noqa: E402


IMAGE_SETTINGS = {
    "provider_id": "cliproxy", "adapter": "openai", "model": "gpt-image-2",
    "base_url": "http://127.0.0.1:8317/v1", "api_key": "image-secret",
}


def _config(*entries):
    return {"image": {"providers": list(entries)}}


def _entry(entry_id, provider, key="k"):
    return {"id": entry_id, "provider": provider, "api_key": key}


@pytest.fixture(autouse=True)
def _no_order_env(monkeypatch):
    monkeypatch.setattr(env_config, "_loaded", True)
    monkeypatch.delenv("IMAGE_PROVIDER_ORDER", raising=False)


def test_chain_falls_back_to_config_order_when_env_unset():
    chain = image_gen._build_provider_chain(_config(
        _entry("cliproxy", "openai"),
        _entry("seedream", "seedream"),
    ))
    assert [p.provider_key for p in chain] == ["openai", "seedream"]


def test_env_order_selects_and_reorders_providers(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER_ORDER", "seedream,cliproxy")
    chain = image_gen._build_provider_chain(_config(
        _entry("cliproxy", "openai"),
        _entry("seedream", "seedream"),
        _entry("minimax", "minimax"),
    ))
    assert [p.provider_key for p in chain] == ["seedream", "openai"]


def test_env_order_distinguishes_two_entries_sharing_a_provider(monkeypatch):
    """config.yaml holds two `provider: openai` entries; only id can address them."""
    monkeypatch.setenv("IMAGE_PROVIDER_ORDER", "openai")
    chain = image_gen._build_provider_chain(_config(
        {"id": "cliproxy", "provider": "openai", "api_key": "local",
         "base_url": "http://127.0.0.1:8317/v1"},
        {"id": "openai", "provider": "openai", "api_key": "official",
         "base_url": "https://api.openai.com/v1"},
    ))
    assert len(chain) == 1
    assert chain[0]._base_url == "https://api.openai.com/v1"


def test_unknown_id_raises_and_lists_available_ids(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER_ORDER", "cliproxy,typo")
    with pytest.raises(ValueError) as excinfo:
        image_gen._build_provider_chain(_config(
            _entry("cliproxy", "openai"),
            _entry("seedream", "seedream"),
        ))
    message = str(excinfo.value)
    assert "typo" in message
    assert "cliproxy" in message and "seedream" in message


def test_entry_without_id_raises():
    with pytest.raises(ValueError) as excinfo:
        image_gen._build_provider_chain(_config(
            {"provider": "openai", "api_key": "k"},
        ))
    assert "id" in str(excinfo.value)


def test_seedream_provider_is_available_in_provider_chain():
    chain = image_gen._build_provider_chain(_config(
        {
            "id": "seedream",
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


def test_generate_image_with_provider_builds_only_selected_provider(tmp_path, monkeypatch):
    """The explicit Web path must not enter the legacy fallback chain."""
    calls = []

    class FakeProvider:
        def resolve_size(self, size):
            return "1536x1024"

        def generate(self, prompt, size):
            calls.append((prompt, size))
            return b"image-bytes"

    monkeypatch.setattr(
        image_gen, "_build_provider_from_entry", lambda entry: FakeProvider()
    )
    monkeypatch.setattr(
        image_gen,
        "_build_provider_chain",
        lambda config: pytest.fail("strict Web generation entered provider fallback chain"),
    )
    out = tmp_path / "image.jpg"

    image_gen.generate_image_with_provider("prompt", out, IMAGE_SETTINGS)

    assert out.read_bytes() == b"image-bytes"
    assert calls == [("prompt", "1536x1024")]


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


def test_legacy_generate_image_still_falls_back(fake_chain, tmp_path):
    first = FakeProvider("first", [RuntimeError("first failed")])
    second = FakeProvider("second", [b"clean"])
    fake_chain(first, second)

    image_gen.generate_image("prompt", tmp_path / "out.jpg", config={})

    assert len(second.prompts) == 1


def test_generate_image_raises_when_every_provider_fails(tmp_path, fake_chain):
    minimax = FakeProvider("minimax", [RuntimeError("quota")])
    fallback = FakeProvider("fallback", [RuntimeError("down")])
    fake_chain(minimax, fallback)

    with pytest.raises(ValueError, match="All providers failed"):
        image_gen.generate_image("prompt", str(tmp_path / "c.jpg"), config={})
    assert not (tmp_path / "c.jpg").exists()
