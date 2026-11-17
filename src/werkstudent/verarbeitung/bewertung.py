"""Relevanz-Punktzahl einer Stelle."""
from __future__ import annotations

from datetime import datetime, timedelta

from werkstudent.modelle import ScoringConfig


def score(
    title_hits: int,
    text_hits: int,
    distance_km: float | None,
    posted_at: datetime | None,
    company_disliked: bool,
    now: datetime,
    cfg: ScoringConfig,
) -> float:
    s = min(title_hits, cfg.title_keyword_max) * cfg.title_keyword
    if title_hits == 0 and text_hits > 0:
        s += cfg.snippet_keyword

    if distance_km is not None:
        if distance_km <= cfg.near_km:
            s += cfg.near_bonus
        elif distance_km <= cfg.mid_km:
            s += cfg.mid_bonus

    if posted_at is not None:
        age = now - posted_at
        if age <= timedelta(hours=24):
            s += cfg.fresh_24h
        elif age <= timedelta(hours=72):
            s += cfg.fresh_72h

    if company_disliked:
        s += cfg.disliked_company
    return s
