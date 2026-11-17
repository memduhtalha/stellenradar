"""Ein Suchlauf: Quellen abfragen, filtern, bewerten, Duplikate zusammenführen, Status vergeben."""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import escape

from werkstudent.modelle import Category, Job, ProcessedJob, ScoringConfig, UserSettings
from werkstudent.quellen.basis import Source, SourceBlocked, SourceSkipped
from werkstudent.speicher.store import Store
from werkstudent.verarbeitung.bewertung import score
from werkstudent.verarbeitung.duplikate import dedupe_key, normalize_city, normalize_company, training_key
from werkstudent.verarbeitung.filter import (
    classify_kind,
    is_excluded_title,
    is_off_topic,
    match_categories,
    weak_categories,
)
from werkstudent.verarbeitung.geo import haversine_km

log = logging.getLogger(__name__)

BACKLOG_LIMIT = 10
BACKLOG_AFTER = timedelta(hours=24)
DETAIL_BUDGET = 10
WARN_AFTER_FAILURES = 3
ZERO_IS_FAILURE_FROM = 5  # 0 Treffer gilt als Ausfall, wenn der letzte gute Lauf mindestens so viele hatte
RADIUS_TOLERANCE_KM = 5
REVIEW_CAP = 40  # höchstens so viele offene „Zum Prüfen“-Stellen; darüber wird später erneut versucht
NEXT_YEAR_BONUS = 1


def next_training_year(now: datetime) -> int:
    """Ausbildungen beginnen meist im August/September – ab August geht es ums nächste Jahr."""
    return now.year + 1 if now.month >= 8 else now.year


# eindeutig andere Stellenarten – kommen nie in „Zum Prüfen“ (Abschlussarbeiten nur mit Praktika-Schalter, s. filter.py)
_OTHER_JOB_TYPE = re.compile(
    r"trainee|dual(?:es|er|e)?\s+stud|quereinsteiger|masterarbeit|bachelorarbeit|abschlussarbeit|thesis|ausbildung",
    re.I,
)
_DUAL_STUDY = re.compile(r"studium|studiengang|bachelor|b\.\s?a\.|b\.\s?sc", re.I)
_YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def _starts_too_early(job: Job, training_year: int) -> bool:
    """Titel oder Ausbildungsbeginn nennen ein Jahr vor dem kommenden Ausbildungsjahr (Fristen zählen nicht)."""
    start = re.search(r"Ausbildungsbeginn ([^·]+)", job.snippet or "")
    years = [int(y) for y in _YEAR.findall(job.title)] + ([int(y) for y in _YEAR.findall(start.group(1))] if start else [])
    return bool(years) and max(years) < training_year


def rank(p: ProcessedJob) -> tuple[float, float]:
    """Höhere Punktzahl zuerst, bei Gleichstand die nähere Stelle."""
    return (-p.score, p.distance_km if p.distance_km is not None else float("inf"))

SOURCE_NAMES = {
    "arbeitsagentur": "Arbeitsagentur",
    "stepstone": "StepStone",
    "indeed": "Indeed",
    "linkedin": "LinkedIn",
    "stellenwerk": "Stellenwerk",
    "ausbildungde": "ausbildung.de",
    "azubiyo": "AZUBIYO",
    "azubide": "azubi.de",
    "firmen": "Firmenseite",
}


@dataclass
class RunResult:
    to_send: list[tuple[int, ProcessedJob]] = field(default_factory=list)
    backlog_total: int | None = None
    warnings: list[str] = field(default_factory=list)
    source_counts: dict[str, int | str] = field(default_factory=dict)


@dataclass
class CollectResult:
    items: list[tuple[int, ProcessedJob, bool]] = field(default_factory=list)  # (Job-ID, Stelle, neu?)
    warnings: list[str] = field(default_factory=list)
    source_counts: dict[str, int | str] = field(default_factory=dict)


class Runner:
    def __init__(
        self,
        store: Store,
        sources: list[Source],
        categories: list[Category],
        scoring: ScoringConfig,
        geocoder,
        title_excludes: list[str] | None = None,
        run_lock: asyncio.Lock | None = None,
    ):
        self._store = store
        self._sources = sources
        self._categories = categories
        self._scoring = scoring
        self._geocoder = geocoder
        self._title_excludes = title_excludes or []
        # Gemeinsam für alle Personen: Läufe kommen nacheinander dran (schont PC und Portale).
        self._run_lock = run_lock or asyncio.Lock()
        self._busy = False

    @property
    def running(self) -> bool:
        return self._busy

    async def run(self, now: datetime, force_backlog: bool = False) -> RunResult | None:
        if self._busy:  # für diese Person läuft schon eine Suche
            return None
        self._busy = True
        try:
            async with self._run_lock:
                return await self._run(now, force_backlog)
        finally:
            self._busy = False

    # --- Ablauf ---------------------------------------------------------------

    async def _run(self, now: datetime, force_backlog: bool) -> RunResult:
        settings = self._store.load_settings()
        active = [c for c in self._categories if c.key in settings.categories and c.art == settings.art]
        disliked = self._store.disliked_companies()
        result = RunResult()
        unsent = self._store.jobs_with_status("unsent")  # beim letzten Mal nicht zustellbar
        self._store.set_status([i for i, _ in unsent], "reported")
        new: dict[str, ProcessedJob] = {}
        any_ok = False

        for src, jobs in await self._fetch_all(settings, active, now, result):
            any_ok = True
            budget = {"left": DETAIL_BUDGET, "broken": None}
            for job in jobs:
                await self._process(src, job, settings, active, disliked, now, new, budget)

        # Einstellungen neu lesen: /pause oder /weiter kann während des Laufs gekommen sein.
        current = self._store.load_settings()
        self._assign(list(new.values()), current, now, force_backlog, result)
        if current.paused:
            self._store.set_status([i for i, _ in unsent], "held")
        else:
            result.to_send = unsent + result.to_send
        if any_ok:
            self._store.set_last_successful_run(now)
        return result

    async def _fetch_all(
        self, settings: UserSettings, active: list[Category], now: datetime, result
    ) -> list[tuple[Source, list[Job]]]:
        """Alle Portale gleichzeitig abfragen (Browser-Quellen teilen sich intern den Browser).
        Gibt die erfolgreichen Quellen in fester Reihenfolge zurück, damit „erste Quelle gewinnt“ stabil bleibt."""
        outcomes = await asyncio.gather(
            *(src.search(settings, active, now) for src in self._sources), return_exceptions=True
        )
        ok: list[tuple[Source, list[Job]]] = []
        for src, jobs in zip(self._sources, outcomes, strict=True):
            prev = self._store.all_source_states().get(src.name)
            if isinstance(jobs, SourceSkipped):
                log.info("%s ausgesetzt: %s", src.name, jobs)
                result.source_counts[src.name] = "pausiert"
                continue
            if isinstance(jobs, SourceBlocked):
                log.warning("%s blockiert: %s", src.name, jobs)
                result.source_counts[src.name] = "blockiert"
                self._record_failure(src.name, "blockiert", now, result)
                continue
            if isinstance(jobs, BaseException):  # eine kaputte Quelle darf den Lauf nicht stoppen
                log.error("%s fehlgeschlagen", src.name, exc_info=jobs)
                result.source_counts[src.name] = "Fehler"
                self._record_failure(src.name, f"Fehler: {jobs}", now, result)
                continue
            if not jobs and prev is not None and prev.last_ok_count >= ZERO_IS_FAILURE_FROM:
                result.source_counts[src.name] = 0
                self._record_failure(src.name, "0 Treffer – Seite evtl. verändert", now, result)
                continue
            self._store.record_source_result(src.name, ok=True, count=len(jobs), now=now)
            result.source_counts[src.name] = len(jobs)
            ok.append((src, jobs))
        return ok

    # --- /alle: alle aktuell gefundenen Stellen ------------------------------------------------

    async def collect(self, now: datetime) -> CollectResult | None:
        """Live-Suche, die auch schon bekannte Stellen auflistet. Neue Stellen werden gespeichert
        (als gemeldet), damit sie danach nicht noch einmal als Einzelnachricht kommen."""
        if self._busy:
            return None
        self._busy = True
        try:
            async with self._run_lock:
                return await self._collect(now)
        finally:
            self._busy = False

    async def _collect(self, now: datetime) -> CollectResult:
        settings = self._store.load_settings()
        active = [c for c in self._categories if c.key in settings.categories and c.art == settings.art]
        disliked = self._store.disliked_companies()
        result = CollectResult()
        new: dict[str, ProcessedJob] = {}
        known: dict[int, None] = {}  # Job-IDs, Reihenfolge egal (wird später sortiert)
        any_ok = False
        for src, jobs in await self._fetch_all(settings, active, now, result):
            any_ok = True
            budget = {"left": DETAIL_BUDGET, "broken": None}
            for job in jobs:
                found = self._store.find_job(job.source, job.source_id)
                if found is None:
                    key = self._key(job, settings, active)
                    found = self._store.find_by_key(key)
                    if found is not None and self._store.source_of(key) != job.source:
                        self._store.add_also_on(key, job.source, job.url)
                if found is not None:
                    job_id, status = found
                    self._store.touch_job(job_id, now)
                    if status not in ("dismissed", "review", "review_sent"):  # „Zum Prüfen“ nicht in /alle
                        known[job_id] = None
                    continue
                await self._process(src, job, settings, active, disliked, now, new, budget)

        limit = settings.radius_km + RADIUS_TOLERANCE_KM
        active_keys = {c.key for c in active}
        excludes = self._title_excludes if settings.art == "werkstudent" else []
        items: list[tuple[int, ProcessedJob, bool]] = []
        for job_id in known:
            p = self._store.get_job(job_id)
            if p is None or not active_keys & set(p.categories):
                continue  # Bereich inzwischen abgewählt
            # ältere Stellen gegen die heutigen Filter prüfen (z. B. Fachfremd-Liste kam später dazu)
            if is_off_topic(p.job.title, excludes, active) or (
                settings.art == "werkstudent" and is_excluded_title(p.job.title)
            ):
                continue
            if settings.art == "ausbildung" and (
                _DUAL_STUDY.search(p.job.title) or _starts_too_early(p.job, next_training_year(now))
            ):
                continue
            near = p.distance_km is None or p.distance_km <= limit or (p.job.remote and settings.remote)
            if near:
                items.append((job_id, p, False))
        for p in new.values():
            job_id = self._store.save_job(p, p.job, "review" if p.review_reason else "reported")
            for source, url in p.also_on:
                self._store.add_also_on(p.dedupe_key, source, url)
            if not p.review_reason:
                items.append((job_id, p, True))
        items.sort(key=lambda t: rank(t[1]))
        result.items = items
        if any_ok:
            self._store.set_last_successful_run(now)
        return result

    def _record_failure(self, name: str, reason: str, now: datetime, result) -> None:
        st = self._store.record_source_result(name, ok=False, count=0, now=now)
        if st.consecutive_failures >= WARN_AFTER_FAILURES and not st.warned:
            label = SOURCE_NAMES.get(name, name)
            short = escape(reason if len(reason) <= 200 else reason[:200] + " …")
            result.warnings.append(f"⚠️ {label} liefert seit {st.consecutive_failures} Läufen nichts ({short}).")
            self._store.set_warned(name, True)

    async def _process(
        self,
        src: Source,
        job: Job,
        settings: UserSettings,
        active: list[Category],
        disliked: set[str],
        now: datetime,
        new: dict[str, ProcessedJob],
        budget: dict,
    ) -> None:
        if self._store.is_rejected(job.source, job.source_id):
            return
        if self._store.is_seen_source_id(job.source, job.source_id):
            self._store.touch_seen(job.source, job.source_id, now)  # noch online
            return
        key = self._key(job, settings, active)
        if key in new:
            p = new[key]
            if p.job.source != job.source and all(s != job.source for s, _ in p.also_on):
                p.also_on.append((job.source, job.url))
            return
        if self._store.is_known(key):
            if self._store.source_of(key) != job.source:
                self._store.add_also_on(key, job.source, job.url)
            found = self._store.find_by_key(key)
            if found:
                self._store.touch_job(found[0], now)
            return
        # Die Ausschlussliste ist für IT-Werkstudentenstellen gedacht (bei Ausbildung ist z. B. „Verkauf“ gewollt).
        excludes = self._title_excludes if settings.art == "werkstudent" else []
        senior_or_fulltime = settings.art == "werkstudent" and is_excluded_title(job.title)  # Ausbildung = Vollzeit
        if senior_or_fulltime or is_off_topic(job.title, excludes, active):
            self._store.save_job(None, job, "rejected")
            return

        kind = self._kind(job, job.snippet, settings)
        cats, title_hits, text_hits = match_categories(job.title, job.snippet, active)
        if settings.art == "ausbildung" and _starts_too_early(job, next_training_year(now)):
            self._store.save_job(None, job, "rejected")  # Ausbildung hat schon begonnen
            return
        if (kind is None or not cats) and settings.art == "ausbildung":
            self._store.save_job(None, job, "rejected")  # Entscheidung fällt am Titel – Detailseiten bringen nichts
            return
        review_reason = None
        if kind is None or not cats:
            if budget["left"] <= 0 and not budget["broken"]:
                return  # unentschieden – im nächsten Lauf erneut prüfen
            detail, state = await self._fetch_detail(src, job, budget)
            if detail:
                job.description = detail
                kind = self._kind(job, detail, settings)
                cats, title_hits, text_hits = match_categories(job.title, detail, active)
                if kind is None or not cats:
                    self._store.save_job(None, job, "rejected")
                    return
            elif state == "error":
                return  # Ladefehler/Captcha: im nächsten Lauf erneut versuchen, nichts endgültig entscheiden
            else:
                # Quelle liefert für diese Anzeige keinen Text: mit Bereichs-Signal → „Zum Prüfen“
                weak = weak_categories(job.title, job.snippet, active)
                if state == "none" or not weak or (kind is None and _OTHER_JOB_TYPE.search(job.title)):
                    self._store.save_job(None, job, "rejected")  # Quelle ohne Detailseiten / kein Signal
                    return
                if self._review_full(new):
                    return  # Warteschlange voll – später erneut
                review_reason = (
                    "Werkstudent nicht bestätigt – Anzeige nicht prüfbar" if kind is None
                    else "nur schwacher Bereichs-Treffer – Anzeige nicht prüfbar"
                )
                kind = kind or "werkstudent"
                cats = weak

        distance = await self._distance(job, settings)
        limit = settings.radius_km + RADIUS_TOLERANCE_KM
        if job.remote:
            if not settings.remote and (distance is None or distance > limit):
                self._store.save_job(None, job, "rejected")
                return
        elif distance is not None and distance > limit:
            self._store.save_job(None, job, "rejected")
            return

        s = score(
            title_hits,
            text_hits,
            distance,
            job.posted_at,
            normalize_company(job.company) in disliked,
            now,
            self._scoring,
        )
        year = re.compile(rf"(?<!\d){next_training_year(now)}(?!\d)")
        if settings.art == "ausbildung" and year.search(f"{job.title} {job.snippet} {job.description or ''}"):
            s += NEXT_YEAR_BONUS  # passender Ausbildungsbeginn
        new[key] = ProcessedJob(
            job=job,
            kind=kind,
            categories=cats,
            distance_km=distance,
            score=s,
            is_top=review_reason is None and s >= self._scoring.top_threshold,
            dedupe_key=key,
            review_reason=review_reason,
        )

    def _review_full(self, new: dict[str, ProcessedJob]) -> bool:
        queued = sum(1 for p in new.values() if p.review_reason)
        return self._store.count_status("review", "review_sent") + queued >= REVIEW_CAP

    @staticmethod
    async def _fetch_detail(src: Source, job: Job, budget: dict) -> tuple[str | None, str]:
        """(Detailtext, Zustand): "ok", "empty" (Quelle lieferte keinen Text), "error" (Ladefehler/Captcha –
        später erneut) oder "none" (Quelle hat grundsätzlich keine Detailseiten). Nach dem ersten
        „empty“/„error“ wird die Quelle in diesem Lauf nicht mehr gefragt – das spart bei Indeed Minuten."""
        if not getattr(src, "provides_details", True):
            return None, "none"
        if budget["broken"]:
            return None, budget["broken"]
        budget["left"] -= 1
        try:
            detail = await src.fetch_detail(job)
        except SourceBlocked as e:
            log.info("Detailseiten von %s blockiert: %s", src.name, e)
            budget["broken"] = "error"
            return None, "error"
        except Exception as e:  # noqa: BLE001
            log.info("Detailseite %s nicht ladbar: %s", job.url, e)
            budget["broken"] = "error"
            return None, "error"
        if not detail:
            budget["broken"] = "empty"
            return None, "empty"
        return detail, "ok"

    @staticmethod
    def _kind(job: Job, text: str, settings: UserSettings):
        if settings.art == "ausbildung":
            if _DUAL_STUDY.search(job.title):
                return None  # duales Studium ist (noch) kein eigener Bereich
            if job.kind_hint == "ausbildung" and not classify_kind(job.title, False, "werkstudent"):
                return "ausbildung"
            # Nur der Titel zählt: „abgeschlossene Ausbildung“ im Text heißt meist Berufserfahrung gesucht.
            return classify_kind(job.title, False, "ausbildung")
        return classify_kind(f"{job.title} {text}", settings.internships, settings.art)

    @staticmethod
    def _key(job: Job, settings: UserSettings, active: list[Category]) -> str:
        if settings.art == "ausbildung":
            cats = match_categories(job.title, job.snippet, active)[0]
            if cats and job.company:
                return training_key(job, cats)
        return dedupe_key(job)

    async def _distance(self, job: Job, settings: UserSettings) -> float | None:
        coords = (job.lat, job.lon) if job.lat is not None and job.lon is not None else None
        if coords is None and job.location:
            place = re.split(r"\s\+\s", job.location, maxsplit=1)[0].strip()  # „Essen + 7 weitere“
            coords = await self._geocoder.locate(place)
            city = normalize_city(place)
            if coords is None and city and city != place.lower():
                coords = await self._geocoder.locate(city.title())  # ohne PLZ/Stadtteil nochmal versuchen
        if coords is None:
            log.info("Ort nicht bestimmbar: %r (%s)", job.location, job.url)
            return None
        return haversine_km((settings.lat, settings.lon), coords)

    # --- Status vergeben --------------------------------------------------------

    def _is_backlog(self, count: int, now: datetime, force: bool) -> bool:
        if count <= BACKLOG_LIMIT:
            return False
        last = self._store.last_successful_run()
        return force or last is None or now - last > BACKLOG_AFTER

    def _assign(
        self, jobs: list[ProcessedJob], settings: UserSettings, now: datetime, force: bool, result: RunResult
    ) -> None:
        for p in [p for p in jobs if p.review_reason]:
            self._store.save_job(p, p.job, "review")
            for source, url in p.also_on:
                self._store.add_also_on(p.dedupe_key, source, url)
        jobs = [p for p in jobs if not p.review_reason]
        jobs.sort(key=rank)
        backlog = not settings.paused and self._is_backlog(len(jobs), now, force)
        if backlog:
            result.backlog_total = len(jobs)
        for i, p in enumerate(jobs):
            if settings.paused:
                status = "held"
            elif backlog:
                status = "reported" if i < BACKLOG_LIMIT else "silent"
            elif p.is_top or settings.digest_mode == "sofort":
                status = "reported"
            else:
                status = "digest"
            job_id = self._store.save_job(p, p.job, status)
            for source, url in p.also_on:
                self._store.add_also_on(p.dedupe_key, source, url)
            if status == "reported":
                result.to_send.append((job_id, p))

    def release_held(self, now: datetime) -> RunResult:
        """Nach /weiter: zurückgehaltene Stellen melden – bei mehr als 10 nur die Top 10."""
        held = sorted(self._store.jobs_with_status("held"), key=lambda t: rank(t[1]))
        result = RunResult()
        if len(held) > BACKLOG_LIMIT:
            result.backlog_total = len(held)
            send, silent = held[:BACKLOG_LIMIT], held[BACKLOG_LIMIT:]
        else:
            send, silent = held, []
        self._store.set_status([i for i, _ in send], "reported")
        self._store.set_status([i for i, _ in silent], "silent")
        result.to_send = send
        return result
