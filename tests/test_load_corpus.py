"""Tests for scripts/load_corpus.py — corpus loader and round-robin topic selector.

Note: brief version of `test_next_topic_returns_first_unused` and
`test_next_topic_when_all_used` never actually called `next_topic(client)`
— they duplicated the selection logic inline, so the tests would pass
even if `next_topic` was broken. These versions monkey-patch `used_topic_ids`
and call `next_topic` for real.
"""

from pathlib import Path

import pytest
import yaml

from scripts.load_corpus import (
    CORPUS_PATH,
    exhaustion_pct,
    load_corpus,
    next_topic,
    used_topic_ids,
)


def test_load_corpus_returns_60():
    corpus = load_corpus()
    assert len(corpus) == 60


def test_load_corpus_ids_unique():
    corpus = load_corpus()
    ids = [t["id"] for t in corpus]
    assert len(ids) == len(set(ids))


def test_load_corpus_required_fields():
    corpus = load_corpus()
    for t in corpus:
        assert "id" in t, t
        assert "title" in t, t
        assert "category" in t, t
        assert "key_points" in t, t
        assert "origin" in t, t
        assert "caution" in t, t
        assert 3 <= len(t["key_points"]) <= 5, t


def test_next_topic_returns_first_unused(monkeypatch):
    """With kb-001 used, next_topic must return the first unused topic."""
    monkeypatch.setattr(
        "scripts.load_corpus.used_topic_ids", lambda client: {"kb-001"}
    )
    topic = next_topic("any_client")
    assert topic["id"] == "kb-002"


def test_next_topic_skips_multiple_used(monkeypatch):
    """With the first three used, next_topic must return kb-004."""
    monkeypatch.setattr(
        "scripts.load_corpus.used_topic_ids",
        lambda client: {"kb-001", "kb-002", "kb-003"},
    )
    topic = next_topic("any_client")
    assert topic["id"] == "kb-004"


def test_next_topic_when_all_used(monkeypatch):
    """When every corpus ID is in used, next_topic must round-robin to corpus[0]."""
    corpus = load_corpus()
    all_ids = {t["id"] for t in corpus}
    monkeypatch.setattr(
        "scripts.load_corpus.used_topic_ids", lambda client: all_ids
    )
    topic = next_topic("any_client")
    assert topic["id"] == corpus[0]["id"]


def test_next_topic_when_none_used(monkeypatch):
    """Fresh client (empty used set) → returns kb-001."""
    monkeypatch.setattr("scripts.load_corpus.used_topic_ids", lambda client: set())
    topic = next_topic("any_client")
    assert topic["id"] == "kb-001"


def test_used_topic_ids_missing_history(tmp_path, monkeypatch):
    """Missing history.yaml → empty set (not crash)."""
    import scripts.load_corpus as lc

    monkeypatch.setattr(lc, "SKILL_DIR", tmp_path)
    assert used_topic_ids("nonexistent_client") == set()


def test_used_topic_ids_reads_topic_id_field(tmp_path, monkeypatch):
    """Reads only entries with `topic_id` populated."""
    import scripts.load_corpus as lc

    client_dir = tmp_path / "clients" / "zhulv"
    client_dir.mkdir(parents=True)
    history_path = client_dir / "history.yaml"
    history_path.write_text(
        yaml.safe_dump(
            [
                {"date": "2026-08-01", "title": "A"},
                {"topic_id": "kb-007", "title": "B"},
                {"topic_id": "kb-008", "title": "C"},
            ],
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(lc, "SKILL_DIR", tmp_path)
    assert used_topic_ids("zhulv") == {"kb-007", "kb-008"}


def test_exhaustion_pct_zero_when_no_history(monkeypatch):
    monkeypatch.setattr("scripts.load_corpus.used_topic_ids", lambda client: set())
    assert exhaustion_pct("any_client") == 0.0


def test_exhaustion_pct_partial(monkeypatch):
    """30 of 60 IDs used → 0.5."""
    used = {f"kb-{i:03d}" for i in range(1, 31)}
    monkeypatch.setattr("scripts.load_corpus.used_topic_ids", lambda client: used)
    assert exhaustion_pct("any_client") == pytest.approx(0.5)


def test_exhaustion_pct_full(monkeypatch):
    corpus = load_corpus()
    all_ids = {t["id"] for t in corpus}
    monkeypatch.setattr(
        "scripts.load_corpus.used_topic_ids", lambda client: all_ids
    )
    assert exhaustion_pct("any_client") == pytest.approx(1.0)


def test_exhaustion_pct_ignores_unknown_ids(monkeypatch):
    """IDs in history that aren't in the corpus don't inflate exhaustion."""
    ghost_used = {f"kb-{i:03d}" for i in range(1, 11)} | {"kb-999", "garbage-id"}
    monkeypatch.setattr(
        "scripts.load_corpus.used_topic_ids", lambda client: ghost_used
    )
    # Only kb-001..kb-010 are real corpus IDs → 10/60
    assert exhaustion_pct("any_client") == pytest.approx(10 / 60)


def test_corpus_path_exists_and_is_yaml():
    """CORPUS_PATH should point to a real YAML file inside the repo."""
    assert CORPUS_PATH.name == "knowledge-corpus.yaml"
    assert CORPUS_PATH.is_file()
    assert yaml.safe_load(CORPUS_PATH.read_text(encoding="utf-8"))
