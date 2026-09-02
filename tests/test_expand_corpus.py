import yaml
import pytest
from pathlib import Path

from scripts.expand_corpus import (
    next_id,
    validate_topic,
    append_topic,
)


def test_next_id_gap_handling():
    existing = [{"id": "kb-001"}, {"id": "kb-002"}, {"id": "kb-005"}]
    assert next_id(existing) == "kb-006"


def test_next_id_full():
    existing = [{"id": f"kb-{i:03d}"} for i in range(1, 1000)]
    assert next_id(existing).startswith("kb-")


def test_validate_topic_ok():
    topic = {
        "id": "kb-999",
        "title": "测试",
        "category": "understanding_world",
        "key_points": [
            "原理：测试原理",
            "证据：测试证据",
            "应用：测试应用",
            "边界：测试边界",
        ],
        "origin": "测试起源",
        "caution": "no",
    }
    assert validate_topic(topic) is None


def test_validate_topic_missing_field():
    topic = {"id": "kb-999", "title": "测试"}  # missing fields
    with pytest.raises(ValueError, match="missing required field"):
        validate_topic(topic)


def test_validate_topic_bad_category():
    topic = {
        "id": "kb-999",
        "title": "测试",
        "category": "wrong_category",
        "key_points": ["p1", "p2", "p3"],
        "origin": "测试",
        "caution": "no",
    }
    with pytest.raises(ValueError, match="invalid category"):
        validate_topic(topic)


def test_validate_topic_requires_combined_article_angles():
    topic = {
        "id": "kb-999",
        "title": "测试",
        "category": "understanding_world",
        "key_points": ["起源：测试", "机制：测试", "案例：测试", "应用：测试"],
        "origin": "测试起源",
        "caution": "no",
    }
    with pytest.raises(ValueError, match="principle, evidence, application, boundary"):
        validate_topic(topic)


def test_append_topic(tmp_path):
    corpus_path = tmp_path / "corpus.yaml"
    corpus_path.write_text(yaml.safe_dump([{"id": "kb-001", "title": "t1"}], allow_unicode=True))

    new_topic = {
        "id": "kb-002",
        "title": "测试",
        "category": "understanding_world",
        "key_points": [
            "原理：测试原理",
            "证据：测试证据",
            "应用：测试应用",
            "边界：测试边界",
        ],
        "origin": "起源",
        "caution": "no",
    }
    append_topic(corpus_path, new_topic)
    loaded = yaml.safe_load(corpus_path.read_text(encoding="utf-8"))
    assert len(loaded) == 2
    assert loaded[1]["title"] == "测试"
