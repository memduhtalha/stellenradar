"""Laden von .env und den YAML-Dateien unter config/."""
from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

from werkstudent.modelle import Category, ScoringConfig


class Env(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_token: str
    allowed_user_id: int
    lightpanda_cdp_url: str = "ws://lightpanda:9222"
    db_path: str = "data/jobs.db"
    healthcheck_url: str | None = None  # optional, z. B. https://hc-ping.com/<id>


def load_categories(path: Path) -> list[Category]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [
        Category(
            key=c["key"],
            label=c["label"],
            emoji=c["emoji"],
            default_on=bool(c.get("default_on", False)),
            search_terms=list(c["search_terms"]),
            keywords=[k.lower() for k in c["keywords"]],
            art=c.get("art", "werkstudent"),
        )
        for c in raw
    ]


def load_title_excludes(path: Path) -> list[str]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [w.lower() for w in raw.get("ausschluss_titel", [])]


def load_enabled_sources(config_dir: Path, local_name: str = "quellen.local.yaml") -> dict[str, bool]:
    """quellen.yaml (öffentlicher Standard), überschrieben von quellen.local.yaml (eigene, nicht eingecheckt)."""
    enabled: dict[str, bool] = {}
    for name in ("quellen.yaml", local_name):
        path = config_dir / name
        if path.exists():
            enabled.update({k: bool(v) for k, v in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).items()})
    return enabled


def load_scoring(path: Path) -> ScoringConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    known = {f.name for f in fields(ScoringConfig)}
    return ScoringConfig(**{k: v for k, v in raw.items() if k in known})
