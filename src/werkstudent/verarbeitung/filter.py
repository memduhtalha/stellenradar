"""Werkstudent-Pflichtfilter und Zuordnung zu Kategorien."""
from __future__ import annotations

import re
from functools import cache
from typing import Literal

from werkstudent.modelle import Category

_WERKSTUDENT = re.compile(r"werkstudent|werkstudierend|working student|studentische (aus)?hilfe", re.I)
_PRAKTIKUM = re.compile(r"(pflicht)?praktik(um|ant)|abschlussarbeit|bachelorarbeit|masterarbeit|thesis", re.I)
_AUSBILDUNG = re.compile(r"ausbildung|azubi|auszubildende", re.I)
_NOT_AUSBILDUNG = re.compile(r"ausbilder|ausbildungsleit|ausbildungsbeauftrag|ausbildungsreferent", re.I)
_EXCLUDED = re.compile(r"\b(senior|vollzeit)\b", re.I)


def classify_kind(
    text: str, internships: bool, art: str = "werkstudent"
) -> Literal["werkstudent", "praktikum", "ausbildung"] | None:
    if art == "ausbildung":
        hit = _AUSBILDUNG.search(text) and not _NOT_AUSBILDUNG.search(text) and not _WERKSTUDENT.search(text)
        return "ausbildung" if hit else None
    if _WERKSTUDENT.search(text):
        return "werkstudent"
    if internships and _PRAKTIKUM.search(text):
        return "praktikum"
    return None


def is_excluded_title(title: str) -> bool:
    return bool(_EXCLUDED.search(title))


@cache
def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    escaped = re.escape(keyword)
    if len(keyword) <= 3:
        # Kurze Stichwörter (KI, AI, SOC, C#) nur als ganzes Wort.
        return re.compile(rf"(?<!\w){escaped}(?!\w)", re.I)
    return re.compile(escaped, re.I)


def _hits(text: str, keywords: list[str]) -> int:
    return sum(1 for k in keywords if _keyword_pattern(k).search(text))


MIN_TEXT_HITS = 2  # nur über die Beschreibung: mindestens so viele verschiedene Stichwörter


@cache
def _exclude_pattern(word: str) -> re.Pattern[str]:
    # Nur am Wortanfang („Rechtsabteilung“ ja, „Berechtigungsmanagement“ nein); kurze Wörter nur ganz.
    tail = r"(?!\w)" if len(word) <= 3 else ""
    return re.compile(rf"(?<!\w){re.escape(word)}{tail}", re.I)


def is_off_topic(title: str, excludes: list[str], active: list[Category]) -> bool:
    """Fachfremder Titel (Marketing, HR …) ohne IT-Stichwort eines aktiven Bereichs im Titel."""
    if not any(_exclude_pattern(w).search(title) for w in excludes):
        return False
    return not any(_hits(title, c.keywords) for c in active)


def weak_categories(title: str, text: str, active: list[Category]) -> list[str]:
    """Bereiche mit mindestens einem Stichwort in Titel oder Text – ein schwaches Signal für „Zum Prüfen“."""
    return [c.key for c in active if _hits(title, c.keywords) or _hits(text, c.keywords)]


def match_categories(title: str, text: str, active: list[Category]) -> tuple[list[str], int, int]:
    """Gibt (Kategorie-Keys, Stichwort-Treffer im Titel, Kategorien nur über den Text) zurück."""
    keys: list[str] = []
    title_hits = 0
    text_only = 0
    for cat in active:
        in_title = _hits(title, cat.keywords)
        if in_title:
            keys.append(cat.key)
            title_hits += in_title
        elif _hits(text, cat.keywords) >= MIN_TEXT_HITS:
            keys.append(cat.key)
            text_only += 1
    return keys, title_hits, text_only
