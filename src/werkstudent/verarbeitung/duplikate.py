"""Erkennung derselben Stelle über mehrere Portale."""
from __future__ import annotations

import hashlib
import re

from werkstudent.modelle import Job

_LEGAL_FORMS = re.compile(
    r"\b(gmbh\s*&\s*co\.?\s*kg(aa)?|ag\s*&\s*co\.?\s*kg(aa)?|gmbh|mbh|kgaa|ag|se|kg|ug|e\.\s?v\.|inc\.?|ltd\.?)(?!\w)",
    re.I,
)
# (m/w/d), (w/m/div.), (gn), (all genders) … und dieselben Angaben ohne Klammern
_GENDER_TAG = re.compile(
    r"\([^)]*(?:\b[mwdfx]\s*/\s*[mwdfx]|all gender|\bgn\b|\bdiv\b)[^)]*\)"
    r"|(?<!\w)[mwdfx]\s*/\s*[mwdfx](?:\s*/\s*(?:[mwdfx]|div)\.?)?(?!\w)",
    re.I,
)
_GENDER_SUFFIX = re.compile(r"(?:[*:/]|/-)in(nen)?\b", re.I)
_POSTCODE = re.compile(r"^\s*\d{5}\s*")
# Firmen, deren erstes Wort zu allgemein ist – hier zählen die ersten zwei Wörter
_GENERIC_FIRST = {
    "deutsche", "deutscher", "stadtwerke", "stadt", "landeshauptstadt", "the", "die", "der", "das",
    "dr", "bank", "universität", "universitaet", "hochschule", "gruppe", "group", "verband",
}
_PUNCT = re.compile(r"[^\w\s]")
_SPACES = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _SPACES.sub(" ", _PUNCT.sub(" ", text)).strip()


def normalize_company(name: str) -> str:
    return _clean(_LEGAL_FORMS.sub(" ", name.lower()))


def normalize_title(title: str) -> str:
    t = _GENDER_TAG.sub(" ", title.lower())
    t = _GENDER_SUFFIX.sub("", t)
    return _clean(t)


def normalize_city(location: str) -> str:
    return re.split(r"[-,(/+]", _POSTCODE.sub("", location), maxsplit=1)[0].strip().lower()


def company_token(name: str) -> str:
    """Erstes Wort der Firma – Portale schreiben Zusätze unterschiedlich („SAP“ vs. „SAP IT Business Systeme“)."""
    words = normalize_company(name).split()
    if not words:
        return ""
    return " ".join(words[:2]) if words[0] in _GENERIC_FIRST else words[0]


def dedupe_key(job: Job) -> str:
    # Titel + Stadt müssen exakt passen, deshalb reicht bei der Firma das erste Wort.
    raw = f"{company_token(job.company)}|{normalize_title(job.title)}|{normalize_city(job.location)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def training_key(job: Job, categories: list[str]) -> str:
    """Ausbildung: dieselbe Firma in derselben Stadt im selben Bereich ist praktisch immer derselbe Platz –
    Portale betiteln ihn aber verschieden („Immobilienkaufmann/-frau in Krefeld 2027“ vs. „zum/zur …“)."""
    raw = f"ausbildung|{company_token(job.company)}|{normalize_city(job.location)}|{','.join(sorted(categories))}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()
