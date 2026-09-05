import logging

import requests
import pytest

from toolkit import llm_adapters


OPENAI_SETTINGS = {
    "provider_id": "custom-openai",
    "adapter": "openai_compatible",
    "model": "writer",
    "base_url": "https://gateway.example/v1",
    "api_key": "write-secret",
}

ANTHROPIC_SETTINGS = {
    "provider_id": "custom-anthropic",
    "adapter": "anthropic_messages",
    "model": "claude-model",
    "base_url": "https://anthropic.example",
    "api_key": "anthropic-secret",
}


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.content = b'{"detail":"response body"}'

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} response")

    def json(self):
        return self._payload


class FakeAnthropicResponse:
    def __init__(self, text):
        self.content = [
            type("TextBlock", (), {"text": text})(),
            type("OtherBlock", (), {"text": None})(),
        ]


class CapturingAnthropicFactory:
    def __init__(self, response):
        self.response = response
        self.client_kwargs = None
        self.message_kwargs = None

    def __call__(self, **kwargs):
        self.client_kwargs = kwargs
        factory = self

        class Client:
            class Messages:
                def create(self, **message_kwargs):
                    factory.message_kwargs = message_kwargs
                    return factory.response

            messages = Messages()

        return Client()


def raising_post_with_secret_url(*args, **kwargs):
    raise requests.ConnectionError(
        "request write-secret failed at https://user:pass@example.com/v1"
    )


def test_openai_compatible_posts_chat_completions(monkeypatch):
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return FakeResponse(200, {"choices": [{"message": {"content": "# 正文"}}]})

    monkeypatch.setattr(llm_adapters.requests, "post", fake_post)

    result = llm_adapters.generate_text("写文章", OPENAI_SETTINGS, max_tokens=123, timeout=9)

    assert result == "# 正文"
    assert captured == {
        "url": "https://gateway.example/v1/chat/completions",
        "headers": {"Authorization": "Bearer write-secret", "Content-Type": "application/json"},
        "json": {"model": "writer", "max_tokens": 123, "messages": [{"role": "user", "content": "写文章"}]},
        "timeout": 9,
    }


def test_anthropic_messages_uses_selected_endpoint_key_and_model(monkeypatch):
    fake = FakeAnthropicResponse("# 正文")
    factory = CapturingAnthropicFactory(fake)
    monkeypatch.setattr(llm_adapters.anthropic, "Anthropic", factory)

    assert llm_adapters.generate_text("写文章", ANTHROPIC_SETTINGS) == "# 正文"
    assert factory.client_kwargs == {
        "base_url": "https://anthropic.example",
        "api_key": "anthropic-secret",
    }
    assert factory.message_kwargs == {
        "model": "claude-model",
        "max_tokens": 4096,
        "timeout": 240,
        "messages": [{"role": "user", "content": "写文章"}],
    }


def test_empty_or_malformed_responses_fail_with_provider_context():
    with pytest.raises(RuntimeError, match="custom-openai.*返回为空"):
        llm_adapters.extract_openai_text({"choices": []}, "custom-openai")


def test_openai_compatible_rejects_whitespace_only_text():
    with pytest.raises(RuntimeError, match="custom-openai.*返回为空"):
        llm_adapters.extract_openai_text(
            {"choices": [{"message": {"content": " \n\t "}}]},
            "custom-openai",
        )


def test_anthropic_messages_rejects_whitespace_only_text(monkeypatch):
    factory = CapturingAnthropicFactory(FakeAnthropicResponse(" \n\t "))
    monkeypatch.setattr(llm_adapters.anthropic, "Anthropic", factory)

    with pytest.raises(RuntimeError, match="custom-anthropic.*返回为空"):
        llm_adapters.generate_text("x", ANTHROPIC_SETTINGS)


def test_connection_check_reports_whitespace_response_as_failure(monkeypatch):
    response = FakeResponse(
        200,
        {"choices": [{"message": {"content": " \n\t "}}]},
    )
    monkeypatch.setattr(llm_adapters.requests, "post", lambda *args, **kwargs: response)

    result = llm_adapters.test_writing_connection(OPENAI_SETTINGS)

    assert result["ok"] is False
    assert result["provider_id"] == "custom-openai"
    assert result["model"] == "writer"
    assert "返回为空" in result["error"]
    assert "text" not in result


def test_malformed_openai_json_response_fails_with_provider_context(monkeypatch):
    response = FakeResponse(200, {})

    def malformed_json():
        raise ValueError("invalid JSON")

    response.json = malformed_json
    monkeypatch.setattr(llm_adapters.requests, "post", lambda *args, **kwargs: response)

    with pytest.raises(RuntimeError, match="custom-openai.*返回格式错误"):
        llm_adapters.generate_text("x", OPENAI_SETTINGS)


def test_malformed_anthropic_content_fails_with_provider_context(monkeypatch):
    response = type("MalformedAnthropicResponse", (), {"content": None})()
    factory = CapturingAnthropicFactory(response)
    monkeypatch.setattr(llm_adapters.anthropic, "Anthropic", factory)

    with pytest.raises(RuntimeError, match="custom-anthropic.*返回格式错误"):
        llm_adapters.generate_text("x", ANTHROPIC_SETTINGS)


def test_adapter_errors_do_not_expose_api_key_or_url_credentials(monkeypatch):
    monkeypatch.setattr(llm_adapters.requests, "post", raising_post_with_secret_url)

    with pytest.raises(RuntimeError) as exc:
        llm_adapters.generate_text("x", OPENAI_SETTINGS)

    message = str(exc.value)
    assert "write-secret" not in message
    assert "user:pass" not in message


def test_adapter_logging_masks_model_equal_to_api_key(monkeypatch, caplog):
    secret = "adapter-log-collision"
    settings = {**OPENAI_SETTINGS, "model": secret, "api_key": secret}
    response = FakeResponse(200, {"choices": [{"message": {"content": "OK"}}]})
    monkeypatch.setattr(llm_adapters.requests, "post", lambda *args, **kwargs: response)

    with caplog.at_level(logging.INFO, logger=llm_adapters.__name__):
        assert llm_adapters.generate_text("x", settings) == "OK"

    assert secret not in caplog.text
    assert "model=***" in caplog.text


def test_openai_non_success_response_includes_redacted_limited_detail(monkeypatch):
    response = FakeResponse(401, {})
    response.content = b"write-secret https://user:pass@example.com/v1 " + (b"x" * 1000)
    monkeypatch.setattr(llm_adapters.requests, "post", lambda *args, **kwargs: response)

    with pytest.raises(RuntimeError) as exc:
        llm_adapters.generate_text("x", OPENAI_SETTINGS)

    message = str(exc.value)
    assert "401" in message
    assert "write-secret" not in message
    assert "user:pass" not in message
    assert len(message) < 700


def test_openai_error_redacts_secret_that_crosses_detail_limit(monkeypatch):
    settings = {**OPENAI_SETTINGS, "api_key": "SecretValue"}
    response = FakeResponse(401, {})
    response.content = (b"x" * 510) + b"SecretValue" + (b"y" * 100)
    monkeypatch.setattr(llm_adapters.requests, "post", lambda *args, **kwargs: response)

    with pytest.raises(RuntimeError) as exc:
        llm_adapters.generate_text("x", settings)

    message = str(exc.value)
    assert "SecretValue" not in message
    assert "Se" not in message
    assert len(message) < 700


def test_connection_check_returns_identity_text_and_elapsed_time(monkeypatch):
    monotonic = iter((100.0, 100.125))
    monkeypatch.setattr(llm_adapters.time, "monotonic", lambda: next(monotonic))
    captured = {}

    def fake_generate(prompt, settings, *, max_tokens, timeout):
        captured.update(prompt=prompt, settings=settings, max_tokens=max_tokens, timeout=timeout)
        return "OK"

    monkeypatch.setattr(llm_adapters, "generate_text", fake_generate)

    result = llm_adapters.test_writing_connection(OPENAI_SETTINGS, timeout=7)

    assert result == {
        "ok": True,
        "provider_id": "custom-openai",
        "model": "writer",
        "elapsed_ms": 125,
        "text": "OK",
    }
    assert captured == {
        "prompt": "只回复 OK",
        "settings": OPENAI_SETTINGS,
        "max_tokens": 8,
        "timeout": 7,
    }


def test_connection_check_returns_redacted_error(monkeypatch):
    monotonic = iter((100.0, 100.125))
    monkeypatch.setattr(llm_adapters.time, "monotonic", lambda: next(monotonic))

    def fake_generate(*args, **kwargs):
        raise RuntimeError("write-secret https://user:pass@example.com/v1")

    monkeypatch.setattr(llm_adapters, "generate_text", fake_generate)

    result = llm_adapters.test_writing_connection(OPENAI_SETTINGS)

    assert result == {
        "ok": False,
        "provider_id": "custom-openai",
        "model": "writer",
        "elapsed_ms": 125,
        "error": "*** https://example.com/v1",
    }
