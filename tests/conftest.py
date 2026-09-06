import os
import shutil
from pathlib import Path

import pytest


@pytest.fixture
def local_storage(monkeypatch, tmp_path):
    """Point history/topics/jobs at a fresh tmp_path directory."""
    data_dir = tmp_path / "_data"
    data_dir.mkdir()
    from webapp import history, jobs, topics, local_store
    from webapp import app as app_module

    history._init_store(data_dir / "history.json")
    topics._init_store(
        path=data_dir / "topics.json",
        corpus_path=Path(__file__).resolve().parent.parent / "references" / "knowledge-corpus.yaml",
    )
    jobs._init_store(data_dir / "jobs")
    monkeypatch.setenv("WS_DATA_DIR", str(data_dir))
    yield data_dir


@pytest.fixture
def web_client(tmp_path, monkeypatch, local_storage):
    import importlib

    from webapp import history, jobs, model_settings, writing_prompt_settings

    app_module = importlib.import_module("webapp.app")

    executor = FakeExecutor()
    monkeypatch.setattr(app_module, "JOB_EXECUTOR", executor)
    monkeypatch.setattr(
        app_module.model_settings,
        "snapshot_settings",
        lambda: copy.deepcopy(RESOLVED_SETTINGS_WITH_KEYS),
    )
    prompt_path = tmp_path / "writing-prompt.json"
    monkeypatch.setattr(writing_prompt_settings, "WRITING_PROMPT_PATH", prompt_path)
    client = app_module.app.test_client()
    client.set_cookie(app_module.COOKIE_NAME, app_module.COOKIE_VALUE)
    yield client, executor


import copy


RESOLVED_SETTINGS_WITH_KEYS = {
    "schema_version": 1,
    "writing": {
        "provider_id": "custom-openai",
        "adapter": "openai_compatible",
        "model": "writer",
        "base_url": "https://llm.example/v1",
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


class FakeExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, fn, *args):
        self.calls.append((fn, args))
        return None
