"""Tests for toolkit/image_gen.py provider gating, OCR validation and retry.

These guard the no-cost image pipeline: OpenAI stays off unless explicitly
opted in, pseudo-text candidates are rejected locally via Tesseract, and a
rejection retries the *same* provider before falling back down the chain.
"""
import subprocess
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


# ── local Tesseract text detection ────────────────────────────────────
_TSV_HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def _tsv(rows):
    """Build a Tesseract TSV payload from (conf, text) pairs."""
    lines = [_TSV_HEADER]
    for i, (conf, text) in enumerate(rows, start=1):
        lines.append(
            f"5\t1\t1\t1\t1\t{i}\t10\t10\t50\t20\t{conf}\t{text}"
        )
    return "\n".join(lines) + "\n"


def _fake_tesseract(monkeypatch, stdout, calls=None):
    def fake_run(cmd, **kwargs):
        if calls is not None:
            calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout, "")

    monkeypatch.setattr(image_gen.subprocess, "run", fake_run)


def test_detect_text_rejects_dense_high_confidence_alphanumerics(monkeypatch):
    _fake_tesseract(monkeypatch, _tsv([
        (92, "Survivorship"), (88, "Bias2024"),
    ]))
    status, detail = image_gen.detect_text(b"jpegbytes")
    assert status == "rejected"
    assert "Survivorship" not in detail and "Bias2024" not in detail


def test_detect_text_passes_sparse_tokens(monkeypatch):
    _fake_tesseract(monkeypatch, _tsv([(91, "ab"), (90, "c")]))
    assert image_gen.detect_text(b"jpegbytes")[0] == "pass"


def test_detect_text_passes_when_no_tokens_found(monkeypatch):
    _fake_tesseract(monkeypatch, _tsv([]))
    assert image_gen.detect_text(b"jpegbytes")[0] == "pass"


def test_detect_text_ignores_low_confidence_noise(monkeypatch):
    _fake_tesseract(monkeypatch, _tsv([
        (12, "Survivorship"), (-1, "Bias2024"), (8, "abcdefghijkl"),
    ]))
    assert image_gen.detect_text(b"jpegbytes")[0] == "pass"


def test_detect_text_reports_not_available_without_tesseract(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("tesseract")

    monkeypatch.setattr(image_gen.subprocess, "run", fake_run)
    status, detail = image_gen.detect_text(b"jpegbytes")
    assert status == "not_available"
    assert detail


def test_detect_text_feeds_bytes_on_stdin_with_psm_11_tsv(monkeypatch):
    calls = []
    _fake_tesseract(monkeypatch, _tsv([]), calls)
    image_gen.detect_text(b"jpegbytes")
    cmd, kwargs = calls[0]
    assert cmd[:2] == ["tesseract", "stdin"]
    assert "stdout" in cmd and "tsv" in cmd
    assert cmd[cmd.index("--psm") + 1] == "11"
    assert kwargs["input"] == b"jpegbytes"


# ── same-provider retry driven by candidate validation ────────────────
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


def _reject_all(_raw):
    return "rejected", "detected 30 confident characters in 3 tokens"


def _pass_all(_raw):
    return "pass", "detected 0 confident characters (under threshold)"


def test_validation_rejection_retries_the_same_provider(tmp_path, fake_chain):
    minimax = FakeProvider("minimax", [b"first-bad", b"second-good"])
    fallback = FakeProvider("openai", [b"never"])
    fake_chain(minimax, fallback)
    out = tmp_path / "cover.jpg"

    def validator(raw):
        return ("rejected", "pseudo text") if raw == b"first-bad" else _pass_all(raw)

    image_gen.generate_image(
        "base prompt", str(out), size="cover", config={},
        validator=validator, attempts_per_provider=2,
    )

    assert len(minimax.prompts) == 2
    assert fallback.prompts == []
    assert out.read_bytes() == b"second-good"


def test_validation_retry_uses_a_strengthened_no_text_prompt(tmp_path, fake_chain):
    minimax = FakeProvider("minimax", [b"first-bad", b"second-good"])
    fake_chain(minimax)

    def validator(raw):
        return ("rejected", "pseudo text") if raw == b"first-bad" else _pass_all(raw)

    image_gen.generate_image(
        "base prompt", str(tmp_path / "c.jpg"), size="cover", config={},
        validator=validator, attempts_per_provider=2,
    )

    assert minimax.prompts[0] == "base prompt"
    retry = minimax.prompts[1]
    assert retry.startswith("base prompt")
    assert "absolutely no text" in retry.lower()


def test_validation_advances_to_fallback_only_after_attempts_exhausted(tmp_path, fake_chain):
    minimax = FakeProvider("minimax", [b"bad-1", b"bad-2", b"bad-3"])
    fallback = FakeProvider("openai", [b"clean"])
    fake_chain(minimax, fallback)
    out = tmp_path / "cover.jpg"

    def validator(raw):
        return _pass_all(raw) if raw == b"clean" else ("rejected", "pseudo text")

    image_gen.generate_image(
        "base prompt", str(out), size="cover", config={},
        validator=validator, attempts_per_provider=2,
    )

    assert len(minimax.prompts) == 2
    assert len(fallback.prompts) == 1
    assert out.read_bytes() == b"clean"


def test_validation_rejecting_every_candidate_raises_quality_error(tmp_path, fake_chain):
    minimax = FakeProvider("minimax", [b"bad"])
    fake_chain(minimax)

    with pytest.raises(ValueError, match="quality validation rejected"):
        image_gen.generate_image(
            "base prompt", str(tmp_path / "c.jpg"), size="cover", config={},
            validator=_reject_all, attempts_per_provider=2,
        )
    assert not (tmp_path / "c.jpg").exists()


def test_validation_not_available_accepts_the_candidate(tmp_path, fake_chain):
    minimax = FakeProvider("minimax", [b"only"])
    fake_chain(minimax)
    out = tmp_path / "c.jpg"

    image_gen.generate_image(
        "base prompt", str(out), size="cover", config={},
        validator=lambda raw: ("not_available", "tesseract CLI not installed"),
        attempts_per_provider=2,
    )
    assert out.read_bytes() == b"only"


def test_retry_diagnostics_record_provider_attempts_and_status(tmp_path, fake_chain):
    minimax = FakeProvider("minimax", [b"first-bad", b"second-good"])
    fake_chain(minimax)
    diagnostics = {}

    def validator(raw):
        return ("rejected", "detected 30 confident characters") if raw == b"first-bad" else _pass_all(raw)

    image_gen.generate_image(
        "base prompt", str(tmp_path / "c.jpg"), size="cover", config={},
        validator=validator, attempts_per_provider=2, diagnostics=diagnostics,
    )

    assert diagnostics["provider"] == "minimax"
    assert diagnostics["attempts"] == 2
    assert diagnostics["validation"] == "pass"
    assert diagnostics["rejections"] == ["minimax attempt 1: detected 30 confident characters"]


def test_retry_keeps_working_for_callers_that_pass_no_validator(tmp_path, fake_chain):
    minimax = FakeProvider("minimax", [b"only"])
    fake_chain(minimax)
    out = tmp_path / "c.jpg"

    assert image_gen.generate_image("p", str(out), size="cover", config={}) == str(out)
    assert out.read_bytes() == b"only"
    assert len(minimax.prompts) == 1
