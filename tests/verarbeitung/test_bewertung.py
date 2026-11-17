from datetime import UTC, datetime, timedelta

from werkstudent.modelle import ScoringConfig
from werkstudent.verarbeitung.bewertung import score

NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)
CFG = ScoringConfig()


def test_score_top_example():
    s = score(2, 0, 3, NOW - timedelta(hours=5), False, NOW, CFG)
    assert s == 10 and s >= CFG.top_threshold


def test_score_disliked_company():
    assert score(2, 0, 3, NOW - timedelta(hours=5), True, NOW, CFG) == 5


def test_score_unknown_distance_and_date():
    assert score(1, 0, None, None, False, NOW, CFG) == 3


def test_score_snippet_only():
    assert score(0, 2, 30, NOW - timedelta(days=2), False, NOW, CFG) == 1 + 1
