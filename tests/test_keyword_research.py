import pytest
from unittest.mock import patch

from scripts.keyword_research import research


def test_research_returns_dict():
    with patch("scripts.keyword_research._fetch") as mock:
        mock.return_value = {"volume": 1000, "related": ["幸存者", "偏差"]}
        result = research("幸存者偏差")
    assert "estimated_volume" in result
    assert "related_keywords" in result


def test_research_handles_failure():
    with patch("scripts.keyword_research._fetch") as mock:
        mock.side_effect = Exception("network")
        result = research("幸存者偏差")
    assert result["estimated_volume"] == 0
    assert result["related_keywords"] == []