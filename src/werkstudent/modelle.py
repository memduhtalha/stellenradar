"""Gemeinsame Datenklassen."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

DEFAULT_CATEGORIES = frozenset({"cloud", "ki", "security"})

Art = Literal["werkstudent", "ausbildung"]  # Suchart einer Person


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    emoji: str
    default_on: bool
    search_terms: list[str]
    keywords: list[str]
    art: str = "werkstudent"


@dataclass
class Job:
    source: str
    source_id: str
    title: str
    company: str
    location: str
    url: str
    snippet: str = ""
    description: str | None = None
    posted_at: datetime | None = None
    remote: bool = False
    lat: float | None = None
    lon: float | None = None
    kind_hint: str | None = None  # Quelle weiß die Art sicher (z. B. Arbeitsagentur angebotsart=4 → ausbildung)


@dataclass
class ProcessedJob:
    job: Job
    kind: Literal["werkstudent", "praktikum", "ausbildung"]
    categories: list[str]
    distance_km: float | None
    score: float
    is_top: bool
    dedupe_key: str
    also_on: list[tuple[str, str]] = field(default_factory=list)  # (source, url)
    review_reason: str | None = None  # gesetzt = „Zum Prüfen“: passt vielleicht, war aber nicht prüfbar


@dataclass
class UserSettings:
    art: Art = "werkstudent"
    location: str = "Düsseldorf"
    lat: float = 51.2277
    lon: float = 6.7735
    radius_km: int = 25
    categories: set[str] = field(default_factory=lambda: set(DEFAULT_CATEGORIES))
    remote: bool = False
    internships: bool = False
    digest_mode: Literal["sofort", "taeglich"] = "sofort"
    interval_minutes: int = 60
    active_from: int = 7
    active_to: int = 22
    digest_hour: int = 18
    paused: bool = False
    onboarded: bool = False


@dataclass(frozen=True)
class ScoringConfig:
    title_keyword: float = 3
    title_keyword_max: int = 2
    snippet_keyword: float = 1
    near_km: float = 10
    near_bonus: float = 2
    mid_km: float = 25
    mid_bonus: float = 1
    fresh_24h: float = 2
    fresh_72h: float = 1
    disliked_company: float = -5
    top_threshold: float = 5
