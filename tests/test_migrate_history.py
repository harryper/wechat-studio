import yaml
import pytest

from scripts.migrate_history import migrate, NEEDED_FIELDS


def test_migrate_adds_track_and_topic_id(tmp_path):
    history = tmp_path / "history.yaml"
    history.write_text(yaml.safe_dump([
        {"date": "2026-01-01", "title": "老文章", "framework": "痛点型"}
    ], allow_unicode=True))

    migrate(history)
    loaded = yaml.safe_load(history.read_text(encoding="utf-8"))
    entry = loaded[0]
    assert entry["track"] == "knowledge"
    assert entry["topic_id"] is None  # unknown for legacy entries


def test_migrate_idempotent(tmp_path):
    history = tmp_path / "history.yaml"
    history.write_text(yaml.safe_dump([
        {"date": "2026-01-01", "title": "t",
         "track": "knowledge", "topic_id": "kb-001", "framework": "痛点型"}
    ], allow_unicode=True))

    migrate(history)
    loaded = yaml.safe_load(history.read_text(encoding="utf-8"))
    assert loaded[0]["topic_id"] == "kb-001"


def test_migrate_no_overwrite_existing(tmp_path):
    history = tmp_path / "history.yaml"
    history.write_text(yaml.safe_dump([
        {"date": "2026-01-01", "title": "t",
         "track": "hot", "topic_id": "kb-001"}
    ], allow_unicode=True))

    migrate(history)
    loaded = yaml.safe_load(history.read_text(encoding="utf-8"))
    assert loaded[0]["track"] == "hot"  # don't overwrite


def test_migrate_missing_file(tmp_path):
    history = tmp_path / "nope.yaml"
    # should not raise
    migrate(history)