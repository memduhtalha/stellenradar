import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from werkstudent.config import load_categories
from werkstudent.lauf import Runner
from werkstudent.modelle import Job, ScoringConfig
from werkstudent.quellen.basis import SourceBlocked, SourceSkipped
from werkstudent.speicher.store import Store

CATS = load_categories(Path("config/kategorien.yaml"))
NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)
DUS = (51.2277, 6.7735)


def make_job(i, source="a", title=None, company=None, lat=DUS[0], lon=DUS[1], snippet="", remote=False, hours_old=None):
    return Job(
        source=source,
        source_id=f"{source}-{i}",
        title=title or f"Werkstudent Cloud Team {i}",
        company=company or f"Firma {i}",
        location="Düsseldorf",
        url=f"https://{source}/{i}",
        snippet=snippet,
        lat=lat,
        lon=lon,
        remote=remote,
        posted_at=NOW - timedelta(hours=hours_old) if hours_old is not None else None,
    )


class FakeSource:
    def __init__(self, name, jobs=None, exc=None, details=None, gate=None):
        self.name = name
        self.jobs = jobs or []
        self.exc = exc
        self.details = details or {}
        self.detail_calls = 0
        self.gate = gate

    async def search(self, settings, categories, now=None):
        if self.gate:
            await self.gate.wait()
        if self.exc:
            raise self.exc
        return [Job(**vars(j)) for j in self.jobs]

    async def fetch_detail(self, job):
        self.detail_calls += 1
        return self.details.get(job.source_id)


class FakeGeocoder:
    def __init__(self, places=None):
        self.places = places or {}

    async def locate(self, place):
        return self.places.get(place.lower())


@pytest.fixture
def store():
    s = Store(":memory:")
    s.init()
    return s


def runner(store, *sources, geocoder=None):
    return Runner(store, list(sources), CATS, ScoringConfig(), geocoder or FakeGeocoder())


async def test_first_run_backlog_top10_rest_silent(store):
    jobs = [make_job(i, hours_old=i) for i in range(25)]
    res = await runner(store, FakeSource("a", jobs)).run(NOW)
    assert len(res.to_send) == 10
    assert res.backlog_total == 25
    assert len(store.jobs_with_status("silent")) == 15
    scores = [p.score for _, p in res.to_send]
    assert scores == sorted(scores, reverse=True)


async def test_normal_run_reports_only_new(store):
    jobs = [make_job(i) for i in range(25)]
    await runner(store, FakeSource("a", jobs)).run(NOW)
    more = jobs + [make_job(100), make_job(101)]
    res = await runner(store, FakeSource("a", more)).run(NOW + timedelta(hours=1))
    assert len(res.to_send) == 2
    assert res.backlog_total is None


async def test_backlog_after_24h_downtime(store):
    await runner(store, FakeSource("a", [make_job(0)])).run(NOW)
    jobs = [make_job(i) for i in range(1, 20)]
    res = await runner(store, FakeSource("a", jobs)).run(NOW + timedelta(hours=30))
    assert res.backlog_total == 19 and len(res.to_send) == 10


async def test_cross_source_duplicate_goes_to_also_on(store):
    a = FakeSource("a", [make_job(1, source="a")])
    b = FakeSource("b", [make_job(1, source="b")])
    res = await runner(store, a, b).run(NOW)
    assert len(res.to_send) == 1
    jid, p = res.to_send[0]
    assert p.also_on == [("b", "https://b/1")]
    assert store.get_job(jid).also_on == [("b", "https://b/1")]


async def test_known_job_from_other_source_later_adds_also_on(store):
    await runner(store, FakeSource("a", [make_job(1, source="a")])).run(NOW)
    res = await runner(store, FakeSource("b", [make_job(1, source="b")])).run(NOW + timedelta(hours=1))
    assert res.to_send == []
    (_, p), = store.jobs_with_status("reported")
    assert p.also_on == [("b", "https://b/1")]


async def test_digest_mode_holds_non_top(store):
    s = store.load_settings()
    s.digest_mode = "taeglich"
    store.save_settings(s)
    top = make_job(1, title="Werkstudent Cloud AWS", hours_old=1)  # 6 + 2 + 2 = 10
    low = make_job(2, title="Werkstudent Team", snippet="mit Kubernetes und Docker", lat=51.4, lon=6.9)  # 2 Punkte
    res = await runner(store, FakeSource("a", [top, low])).run(NOW)
    assert [p.job.source_id for _, p in res.to_send] == ["a-1"]
    assert [p.job.source_id for _, p in store.jobs_with_status("digest")] == ["a-2"]


async def test_paused_holds_then_release_applies_backlog(store):
    store.set_last_successful_run(NOW - timedelta(hours=1))
    s = store.load_settings()
    s.paused = True
    store.save_settings(s)
    r = runner(store, FakeSource("a", [make_job(i) for i in range(12)]))
    res = await r.run(NOW)
    assert res.to_send == []
    assert len(store.jobs_with_status("held")) == 12
    rel = r.release_held(NOW)
    assert len(rel.to_send) == 10 and rel.backlog_total == 12
    assert store.jobs_with_status("held") == []


async def test_release_held_small_batch_sends_all(store):
    s = store.load_settings()
    s.paused = True
    store.save_settings(s)
    r = runner(store, FakeSource("a", [make_job(i) for i in range(3)]))
    await r.run(NOW)
    rel = r.release_held(NOW)
    assert len(rel.to_send) == 3 and rel.backlog_total is None


async def test_no_category_triggers_detail_fetch_once(store):
    unclear = make_job(1, title="Werkstudent IT (m/w/d)")
    rejected = make_job(2, title="Werkstudent Team (m/w/d)", company="Andere")
    src = FakeSource("a", [unclear, rejected], details={"a-1": "Du betreust unsere Azure Cloud."})
    res = await runner(store, src).run(NOW)
    assert [p.job.source_id for _, p in res.to_send] == ["a-1"]
    assert src.detail_calls == 2
    await runner(store, src).run(NOW + timedelta(hours=1))
    assert src.detail_calls == 2


async def test_detail_budget_is_10_per_source(store):
    jobs = [make_job(i, title=f"Werkstudent Allgemein {i}") for i in range(15)]
    src = FakeSource("a", jobs, details={f"a-{i}": "Allgemeine Bürotätigkeiten" for i in range(15)})
    await runner(store, src).run(NOW)
    assert src.detail_calls == 10


async def test_jobs_over_detail_budget_are_retried_next_run(store):
    jobs = [make_job(i, title=f"Werkstudent Allgemein {i}") for i in range(15)]
    src = FakeSource("a", jobs, details={f"a-{i}": "Allgemeine Bürotätigkeiten" for i in range(15)})
    await runner(store, src).run(NOW)
    await runner(store, src).run(NOW + timedelta(hours=1))
    assert src.detail_calls == 15  # die 5 übrigen werden im nächsten Lauf geprüft, nicht verworfen


async def test_detail_fetch_error_does_not_stop_run(store):
    class Flaky(FakeSource):
        async def fetch_detail(self, job):
            raise SourceBlocked("captcha")

    src = Flaky("a", [make_job(1, title="Werkstudent Allgemein"), make_job(2)])
    res = await runner(store, src).run(NOW)
    assert [p.job.source_id for _, p in res.to_send] == ["a-2"]
    assert not store.is_rejected("a", "a-1")  # Fehler beim Laden ≠ unpassend → nächster Lauf versucht es erneut


async def test_blocked_source_does_not_stop_others(store):
    a = FakeSource("a", exc=SourceBlocked("captcha"))
    b = FakeSource("b", [make_job(i, source="b") for i in range(3)])
    res = await runner(store, a, b).run(NOW)
    assert len(res.to_send) == 3
    assert res.source_counts["a"] == "blockiert"
    assert res.source_counts["b"] == 3


async def test_skipped_source_is_not_a_failure(store):
    a = FakeSource("a", exc=SourceSkipped("limit"))
    for k in range(4):
        res = await runner(store, a).run(NOW + timedelta(hours=k))
        assert res.warnings == []
    assert store.all_source_states().get("a") is None


async def test_warning_after_three_failures_once(store):
    bad = FakeSource("a", exc=RuntimeError("kaputt"))
    warnings = []
    for k in range(4):
        warnings.append((await runner(store, bad).run(NOW + timedelta(hours=k))).warnings)
    assert [len(w) for w in warnings] == [0, 0, 1, 0]
    assert "seit 3 Läufen" in warnings[2][0]
    await runner(store, FakeSource("a", [make_job(1)])).run(NOW + timedelta(hours=5))
    again = [len((await runner(store, bad).run(NOW + timedelta(hours=6 + k))).warnings) for k in range(3)]
    assert again == [0, 0, 1]


async def test_zero_results_after_history_counts_as_failure(store):
    await runner(store, FakeSource("a", [make_job(i) for i in range(8)])).run(NOW)
    empty = FakeSource("a", [])
    counts = [len((await runner(store, empty).run(NOW + timedelta(hours=k + 1))).warnings) for k in range(3)]
    assert counts == [0, 0, 1]


async def test_concurrent_run_is_rejected(store):
    gate = asyncio.Event()
    r = runner(store, FakeSource("a", [make_job(1)], gate=gate))
    first = asyncio.create_task(r.run(NOW))
    await asyncio.sleep(0)
    second = await r.run(NOW)
    gate.set()
    res = await first
    assert second is None
    assert len(res.to_send) == 1
    assert len(store.jobs_with_status("reported")) == 1


async def test_far_away_job_rejected_unless_remote_enabled(store):
    muc = make_job(1, title="Werkstudent Cloud München", lat=48.137, lon=11.575, remote=True)
    res = await runner(store, FakeSource("a", [muc])).run(NOW)
    assert res.to_send == []

    s2 = Store(":memory:")
    s2.init()
    settings = s2.load_settings()
    settings.remote = True
    s2.save_settings(settings)
    res = await runner(s2, FakeSource("a", [muc])).run(NOW)
    assert len(res.to_send) == 1


async def test_far_away_non_remote_rejected_even_with_remote_on(store):
    settings = store.load_settings()
    settings.remote = True
    store.save_settings(settings)
    muc = make_job(1, lat=48.137, lon=11.575)
    assert (await runner(store, FakeSource("a", [muc])).run(NOW)).to_send == []


async def test_geocoder_used_when_no_coordinates(store):
    job = make_job(1, lat=None, lon=None)
    job.location = "Neuss"
    res = await runner(store, FakeSource("a", [job]), geocoder=FakeGeocoder({"neuss": (51.198, 6.691)})).run(NOW)
    (_, p), = res.to_send
    assert 5 < p.distance_km < 8


async def test_excluded_and_inactive_category_rejected(store):
    jobs = [make_job(1, title="Senior Werkstudent Cloud"), make_job(2, title="Werkstudent SAP Basis")]
    res = await runner(store, FakeSource("a", jobs)).run(NOW)
    assert res.to_send == []


async def test_disliked_company_lowers_score(store):
    await runner(store, FakeSource("a", [make_job(1, company="Böse GmbH")])).run(NOW)
    (jid, _), = store.jobs_with_status("reported")
    store.dismiss(jid)
    res = await runner(store, FakeSource("a", [make_job(2, company="Böse AG")])).run(NOW + timedelta(hours=1))
    (_, p), = res.to_send
    assert p.score == 3 + 2 - 5


async def test_failure_reason_is_html_escaped(store):
    bad = FakeSource("a", exc=RuntimeError("<launching> chromium &co"))
    warnings = []
    for k in range(3):
        warnings += (await runner(store, bad).run(NOW + timedelta(hours=k))).warnings
    assert "&lt;launching&gt;" in warnings[0] and "<launching>" not in warnings[0]


async def test_weiter_during_run_reports_instead_of_holding(store):
    s = store.load_settings()
    s.paused = True
    store.save_settings(s)

    class ResumesDuringSearch(FakeSource):
        async def search(self, settings, categories, now=None):
            cur = store.load_settings()
            cur.paused = False  # Nutzer schickt /weiter, während der Lauf noch sucht
            store.save_settings(cur)
            return await super().search(settings, categories, now)

    store.set_last_successful_run(NOW - timedelta(hours=1))
    res = await runner(store, ResumesDuringSearch("a", [make_job(1)])).run(NOW)
    assert len(res.to_send) == 1 and store.jobs_with_status("held") == []


async def test_unsent_jobs_are_resent_next_run(store):
    store.set_last_successful_run(NOW - timedelta(hours=1))
    r = runner(store, FakeSource("a", [make_job(1)]))
    res = await r.run(NOW)
    (jid, _), = res.to_send
    store.set_status([jid], "unsent")
    res2 = await runner(store, FakeSource("a", [])).run(NOW + timedelta(hours=1))
    assert [i for i, _ in res2.to_send] == [jid]
    assert store.jobs_with_status("unsent") == []


async def test_off_topic_title_rejected(store):
    r = Runner(store, [FakeSource("a", [make_job(1, title="Werkstudent Online Marketing", snippet="KI und Machine Learning")])],
               CATS, ScoringConfig(), FakeGeocoder(), title_excludes=["marketing"])
    assert (await r.run(NOW)).to_send == []


async def test_same_source_id_with_edited_title_not_reported_again(store):
    await runner(store, FakeSource("a", [make_job(1, title="Werkstudent Cloud Team")])).run(NOW)
    edited = make_job(1, title="Werkstudent Cloud Team (Remote möglich)")
    res = await runner(store, FakeSource("a", [edited])).run(NOW + timedelta(hours=1))
    assert res.to_send == []


async def test_sources_are_searched_concurrently(store):
    import time

    class Slow(FakeSource):
        async def search(self, settings, categories, now=None):
            await asyncio.sleep(0.3)
            return await super().search(settings, categories, now)

    r = runner(store, Slow("a", [make_job(1, source="a")]), Slow("b", [make_job(2, source="b")]),
               Slow("c", [make_job(3, source="c")]))
    t0 = time.perf_counter()
    res = await r.run(NOW)
    assert time.perf_counter() - t0 < 0.6
    assert len(res.to_send) == 3


def _ausbildung_store(store):
    s = store.load_settings()
    s.art = "ausbildung"
    s.categories = {"immobilien"}
    s.location, s.lat, s.lon = "Nettetal", 51.317, 6.283
    store.save_settings(s)
    store.set_last_successful_run(NOW - timedelta(hours=1))


NETTETAL = (51.317, 6.283)


async def test_ausbildung_user_gets_ausbildung_jobs_only(store):
    _ausbildung_store(store)
    jobs = [make_job(1, title="Ausbildung Immobilienkaufmann (m/w/d)", lat=51.26, lon=6.39),  # Viersen
            make_job(2, title="Werkstudent Cloud", lat=51.26, lon=6.39)]
    r = Runner(store, [FakeSource("a", jobs)], CATS, ScoringConfig(), FakeGeocoder(), title_excludes=["verkauf"])
    res = await r.run(NOW)
    assert [(p.job.source_id, p.kind) for _, p in res.to_send] == [("a-1", "ausbildung")]


async def test_ausbildung_ignores_it_title_excludes(store):
    _ausbildung_store(store)
    job = make_job(1, title="Ausbildung Immobilienkaufmann – Verkauf & Vermietung", lat=51.26, lon=6.39)
    r = Runner(store, [FakeSource("a", [job])], CATS, ScoringConfig(), FakeGeocoder(), title_excludes=["verkauf"])
    assert len((await r.run(NOW)).to_send) == 1


async def test_ausbildung_next_year_bonus(store):
    _ausbildung_store(store)
    a = make_job(1, title="Ausbildung Immobilienkaufmann 2027", lat=51.26, lon=6.39)
    b = make_job(2, title="Ausbildung Immobilienkaufmann", company="Andere", lat=51.26, lon=6.39)
    res = await runner(store, FakeSource("a", [a, b])).run(NOW)
    scores = {p.job.source_id: p.score for _, p in res.to_send}
    assert scores["a-1"] == scores["a-2"] + 1


async def test_equal_score_closer_job_first(store):
    _ausbildung_store(store)
    krefeld = make_job(1, title="Ausbildung Immobilienkaufmann", company="K", lat=51.33, lon=6.56)
    viersen = make_job(2, title="Ausbildung Immobilienkaufmann", company="V", lat=51.26, lon=6.39)
    s = store.load_settings(); s.radius_km = 40; store.save_settings(s)
    res = await runner(store, FakeSource("a", [krefeld, viersen])).run(NOW)
    assert [p.job.company for _, p in res.to_send] == ["V", "K"]


async def test_ausbildung_vollzeit_title_is_fine(store):
    _ausbildung_store(store)
    job = make_job(1, title="Ausbildung Immobilienkaufmann (m/w/d) in Vollzeit", lat=51.26, lon=6.39)
    assert len((await runner(store, FakeSource("a", [job])).run(NOW)).to_send) == 1


async def test_runs_of_different_people_wait_for_each_other(store):
    shared = asyncio.Lock()
    gate = asyncio.Event()
    other = Store(":memory:")
    other.init()
    r1 = Runner(store, [FakeSource("a", [make_job(1)], gate=gate)], CATS, ScoringConfig(), FakeGeocoder(), run_lock=shared)
    r2 = Runner(other, [FakeSource("a", [make_job(2)])], CATS, ScoringConfig(), FakeGeocoder(), run_lock=shared)
    t1 = asyncio.create_task(r1.run(NOW))
    await asyncio.sleep(0)
    t2 = asyncio.create_task(r2.run(NOW))
    await asyncio.sleep(0.05)
    assert not t2.done()  # wartet auf den ersten Lauf, wird aber nicht abgewiesen
    gate.set()
    assert (await t1) is not None and (await t2) is not None


async def test_ausbildung_job_marked_by_source_needs_no_keyword_in_title(store):
    _ausbildung_store(store)
    job = make_job(1, title="Immobilienkaufmann/-frau (m/w/d)", lat=51.26, lon=6.39)
    job.kind_hint = "ausbildung"  # z. B. Arbeitsagentur mit angebotsart=4
    assert [p.kind for _, p in (await runner(store, FakeSource("a", [job])).run(NOW)).to_send] == ["ausbildung"]


async def test_regular_job_mentioning_completed_training_is_not_ausbildung(store):
    _ausbildung_store(store)
    job = make_job(1, title="Immobilienkaufmann (m/w/d) Vollzeit", lat=51.26, lon=6.39,
                   snippet="Abgeschlossene kaufmännische Ausbildung als Immobilienkaufmann erforderlich.")
    trainer = make_job(2, title="Ausbildungsleiter Immobilien (m/w/d)", company="T", lat=51.26, lon=6.39)
    assert (await runner(store, FakeSource("a", [job, trainer])).run(NOW)).to_send == []


async def test_year_bonus_needs_whole_number(store):
    _ausbildung_store(store)
    a = make_job(1, title="Ausbildung Immobilienkaufmann", lat=51.26, lon=6.39, snippet="Ref. 120270")
    b = make_job(2, title="Ausbildung Immobilienkaufmann", company="B", lat=51.26, lon=6.39)
    res = await runner(store, FakeSource("a", [a, b])).run(NOW)
    scores = {p.job.source_id: p.score for _, p in res.to_send}
    assert scores["a-1"] == scores["a-2"]


async def test_location_with_more_places_and_postcode_is_located(store):
    _ausbildung_store(store)
    job = make_job(1, title="Ausbildung Immobilienkaufmann", lat=None, lon=None)
    job.location = "45127 Essen + 7 weitere"
    geo = FakeGeocoder({"essen": (51.455, 7.011)})
    res = await runner(store, FakeSource("a", [job]), geocoder=geo).run(NOW)
    assert res.to_send == []  # Essen liegt ~55 km von Nettetal – außerhalb des Umkreises


async def test_ausbildung_same_company_city_category_is_one_job(store):
    _ausbildung_store(store)
    a = make_job(1, source="azubiyo", title="Ausbildung Immobilienkaufmann/-frau (m/w/d) in Krefeld 2027",
                 company="Musterwohnen Krefeld AG", lat=51.33, lon=6.56)
    a.location = "47798 Krefeld"
    b = make_job(1, source="arbeitsagentur", title="Ausbildung zum/zur Immobilienkaufmann/-kauffrau (m/w/d)",
                 company="Musterwohnen Krefeld Aktiengesellschaft", lat=51.33, lon=6.56)
    b.location = "Krefeld"
    res = await runner(store, FakeSource("azubiyo", [a]), FakeSource("arbeitsagentur", [b])).run(NOW)
    assert len(res.to_send) == 1
    assert res.to_send[0][1].also_on == [("arbeitsagentur", "https://arbeitsagentur/1")]


# --- /alle: Live-Suche mit allen aktuellen Stellen -----------------------------------------


async def test_collect_lists_known_and_new_jobs(store):
    store.set_last_successful_run(NOW - timedelta(hours=1))
    await runner(store, FakeSource("a", [make_job(1), make_job(2)])).run(NOW)
    src = FakeSource("a", [make_job(1), make_job(2), make_job(3)])
    res = await runner(store, src).collect(NOW + timedelta(minutes=5))
    ids = {p.job.source_id: is_new for _, p, is_new in res.items}
    assert ids == {"a-1": False, "a-2": False, "a-3": True}
    # die neue Stelle kommt danach nicht noch einmal als Einzelnachricht
    later = await runner(store, src).run(NOW + timedelta(hours=2))
    assert later.to_send == []


async def test_collect_skips_dismissed_and_rejected(store):
    store.set_last_successful_run(NOW - timedelta(hours=1))
    res = await runner(store, FakeSource("a", [make_job(1), make_job(2, company="Weg")])).run(NOW)
    weg = next(i for i, p in res.to_send if p.job.company == "Weg")
    store.dismiss(weg)
    jobs = [make_job(1), make_job(2, company="Weg"), make_job(3, title="Senior Werkstudent Cloud")]
    res = await runner(store, FakeSource("a", jobs)).collect(NOW)
    assert [p.job.source_id for _, p, _ in res.items] == ["a-1"]


async def test_collect_respects_current_settings_for_known_jobs(store):
    store.set_last_successful_run(NOW - timedelta(hours=1))
    far = make_job(1, lat=51.45, lon=7.01)  # Essen, ~25 km von Düsseldorf
    await runner(store, FakeSource("a", [far])).run(NOW)
    s = store.load_settings()
    s.radius_km = 10
    store.save_settings(s)
    res = await runner(store, FakeSource("a", [far])).collect(NOW)
    assert res.items == []


async def test_collect_sorted_best_first_and_rejects_parallel_run(store):
    gate = asyncio.Event()
    r = runner(store, FakeSource("a", [make_job(1, title="Werkstudent Team", snippet="Kubernetes und Docker"),
                                       make_job(2, title="Werkstudent Cloud AWS", hours_old=1)], gate=gate))
    first = asyncio.create_task(r.collect(NOW))
    await asyncio.sleep(0)
    assert await r.collect(NOW) is None
    gate.set()
    res = await first
    assert [p.job.source_id for _, p, _ in res.items] == ["a-2", "a-1"]


async def test_collect_finds_same_job_from_other_source_as_known(store):
    store.set_last_successful_run(NOW - timedelta(hours=1))
    await runner(store, FakeSource("a", [make_job(1, source="a")])).run(NOW)
    res = await runner(store, FakeSource("b", [make_job(1, source="b")])).collect(NOW)
    assert [(p.job.source, is_new) for _, p, is_new in res.items] == [("a", False)]


async def test_collect_applies_current_filters_to_known_jobs(store):
    store.set_last_successful_run(NOW - timedelta(hours=1))
    old = make_job(1, title="Werkstudent Sales Cloud-Lösungen", snippet="")
    store.save_job(None, old, "reported")  # Platzhalter, wird unten ersetzt
    # Stelle aus der Zeit vor dem Fachfremd-Filter direkt speichern
    from werkstudent.modelle import ProcessedJob
    from werkstudent.verarbeitung.duplikate import dedupe_key
    legacy = make_job(2, title="Werkstudent Online Marketing", company="Alt")
    p = ProcessedJob(job=legacy, kind="werkstudent", categories=["ki"], distance_km=1, score=5, is_top=True,
                     dedupe_key=dedupe_key(legacy))
    store.save_job(p, legacy, "reported")
    r = Runner(store, [FakeSource("a", [legacy])], CATS, ScoringConfig(), FakeGeocoder(), title_excludes=["marketing"])
    assert (await r.collect(NOW)).items == []


async def test_ausbildung_never_fetches_detail_pages(store):
    _ausbildung_store(store)
    src = FakeSource("a", [make_job(1, title="Immobilienkaufmann (m/w/d)", lat=51.26, lon=6.39)])
    await runner(store, src).run(NOW)
    assert src.detail_calls == 0  # Entscheidung fällt bei Ausbildungen am Titel – Detailseiten kosten nur Zeit


async def test_ausbildung_excludes_dual_study_even_from_arbeitsagentur(store):
    _ausbildung_store(store)
    jobs = []
    for i, title in enumerate(["Bachelor of Arts - Real Estate", "Duales Studium BWL - Immobilienwirtschaft"]):
        j = make_job(i, title=title, company=f"F{i}", lat=51.26, lon=6.39)
        j.kind_hint = "ausbildung"
        jobs.append(j)
    assert (await runner(store, FakeSource("a", jobs)).run(NOW)).to_send == []


async def test_ausbildung_with_start_in_the_past_is_rejected(store):
    _ausbildung_store(store)  # NOW = November 2026 → Ausbildungsjahr 2027
    old = make_job(1, title="Ausbildung 01.08.2026 Immobilienkaufmann (m/w/d)", lat=51.26, lon=6.39)
    old_snippet = make_job(2, title="Ausbildung Immobilienkaufmann", company="B", lat=51.26, lon=6.39,
                           snippet="Ausbildungsbeginn 01.08.2026")
    ok = make_job(3, title="Ausbildung Immobilienkaufmann", company="C", lat=51.26, lon=6.39,
                  snippet="Ausbildungsbeginn 01.08.2027 · Bewerbung bis 29.12.2026")
    res = await runner(store, FakeSource("a", [old, old_snippet, ok])).run(NOW)
    assert [p.job.company for _, p in res.to_send] == ["C"]


async def test_collect_drops_known_dual_study_and_past_start(store):
    from werkstudent.modelle import ProcessedJob
    from werkstudent.verarbeitung.duplikate import dedupe_key
    _ausbildung_store(store)
    for i, title in enumerate(["Bachelor of Arts - Real Estate", "Ausbildung 01.08.2026 Immobilienkaufmann"]):
        j = make_job(i, title=title, company=f"F{i}", lat=51.26, lon=6.39)
        store.save_job(ProcessedJob(job=j, kind="ausbildung", categories=["immobilien"], distance_km=10, score=6,
                                    is_top=True, dedupe_key=dedupe_key(j)), j, "reported")
    jobs = [make_job(i, title=t, company=f"F{i}", lat=51.26, lon=6.39)
            for i, t in enumerate(["Bachelor of Arts - Real Estate", "Ausbildung 01.08.2026 Immobilienkaufmann"])]
    assert (await runner(store, FakeSource("a", jobs)).collect(NOW)).items == []



# --- „Zum Prüfen“: passt vielleicht, ließ sich aber nicht abschließend prüfen -----------------


def _reviews(store):
    return {p.job.source_id: p.review_reason for _, p in store.jobs_with_status("review")}


async def test_unverifiable_job_with_area_in_title_goes_to_review(store):
    store.set_last_successful_run(NOW - timedelta(hours=1))
    jobs = [make_job(1, source="indeed", title="Cloud Engineer Azure (m/w/d)"), make_job(2, source="indeed", title="DevOps Kubernetes (m/w/d)")]
    src = FakeSource("indeed", jobs)  # liefert keine Detailseiten
    res = await runner(store, src).run(NOW)
    assert res.to_send == []
    assert set(_reviews(store)) == {"indeed-1", "indeed-2"}
    assert src.detail_calls == 1  # nach dem ersten Fehlschlag keine weiteren Detailseiten dieser Quelle
    assert "nicht prüfbar" in _reviews(store)["indeed-1"]


async def test_detail_error_is_retried_next_run_not_reviewed(store):
    class Broken(FakeSource):
        async def fetch_detail(self, job):
            self.detail_calls += 1
            raise RuntimeError("Timeout")

    jobs = [make_job(1, source="indeed", title="Cloud Engineer Azure (m/w/d)"),
            make_job(2, source="indeed", title="Werkstudent Digitalisierung (m/w/d)")]
    src = Broken("indeed", jobs)
    await runner(store, src).run(NOW)
    assert _reviews(store) == {}
    assert not store.is_rejected("indeed", "indeed-1") and not store.is_rejected("indeed", "indeed-2")
    assert src.detail_calls == 1  # nach dem Fehler im selben Lauf keine weiteren Versuche
    await runner(store, src).run(NOW + timedelta(hours=1))
    assert src.detail_calls == 2  # nächster Lauf versucht es wieder


async def test_loaded_detail_without_werkstudent_is_rejected_not_review(store):
    src = FakeSource("a", [make_job(1, title="Cloud Engineer Azure (m/w/d)")],
                     details={"a-1": "Vollzeitstelle mit Berufserfahrung in Azure."})
    await runner(store, src).run(NOW)
    assert _reviews(store) == {} and store.is_rejected("a", "a-1")


async def test_weak_area_signal_goes_to_review(store):
    src = FakeSource("a", [make_job(1, title="Werkstudent Team (m/w/d)", snippet="Du unterstützt bei Kubernetes")])
    await runner(store, src).run(NOW)
    assert "schwach" in _reviews(store)["a-1"]


async def test_no_signal_at_all_is_not_review(store):
    src = FakeSource("a", [make_job(1, title="Werkstudent Einkauf (m/w/d)")])
    await runner(store, src).run(NOW)
    assert _reviews(store) == {}


async def test_unknown_location_is_still_delivered(store):
    store.set_last_successful_run(NOW - timedelta(hours=1))
    job = make_job(1, lat=None, lon=None)
    job.location = "Irgendwo"
    res = await runner(store, FakeSource("a", [job])).run(NOW)
    assert len(res.to_send) == 1 and _reviews(store) == {}


async def test_review_job_is_not_queued_twice(store):
    src = FakeSource("indeed", [make_job(1, source="indeed", title="Cloud Engineer Azure (m/w/d)")])
    await runner(store, src).run(NOW)
    await runner(store, src).run(NOW + timedelta(hours=1))
    assert len(store.jobs_with_status("review")) == 1


async def test_ausbildung_has_no_title_only_review(store):
    _ausbildung_store(store)
    src = FakeSource("a", [make_job(1, title="Immobilienkaufmann (m/w/d)", lat=51.26, lon=6.39)])
    await runner(store, src).run(NOW)
    assert _reviews(store) == {}



async def test_run_updates_last_seen_of_known_jobs(store):
    await runner(store, FakeSource("a", [make_job(1)])).run(NOW)
    (jid, _), = store.jobs_with_status("reported")
    later = NOW + timedelta(days=5)
    await runner(store, FakeSource("a", [make_job(1)])).run(later)
    assert store.expired_ids([jid], later) == set()
    assert store.last_seen(jid) == later



class NoDetails(FakeSource):
    provides_details = False  # wie Arbeitsagentur/Firmenseiten

    async def fetch_detail(self, job):
        self.detail_calls += 1
        return None


async def test_source_without_detail_pages_never_fills_review(store):
    jobs = [make_job(1, title="Werkstudent Team", snippet="Netzwerk"), make_job(2, title="Cloud Engineer (m/w/d)")]
    src = NoDetails("a", jobs)
    await runner(store, src).run(NOW)
    assert _reviews(store) == {} and src.detail_calls == 0
    assert store.is_rejected("a", "a-1") and store.is_rejected("a", "a-2")


async def test_review_queue_is_capped(store, monkeypatch):
    import werkstudent.lauf as lauf
    monkeypatch.setattr(lauf, "REVIEW_CAP", 3)
    jobs = [make_job(i, source="indeed", title=f"Cloud Engineer {i} (m/w/d)") for i in range(6)]
    await runner(store, FakeSource("indeed", jobs)).run(NOW)
    assert len(_reviews(store)) == 3
    assert not store.is_rejected("indeed", "indeed-5")  # nicht verloren, später erneut



async def test_other_job_types_never_go_to_review(store):
    titles = ["Duale Studierende Cyber Security (m/w/d)", "Duales Studium Data Science & KI",
              "Masterarbeit zum Thema Software und KI", "Trainee Cloud & Data (m/w/d)",
              "Quereinsteiger Data Scientist (m/w/d)"]
    jobs = [make_job(i, source="indeed", title=t, company=f"F{i}") for i, t in enumerate(titles)]
    await runner(store, FakeSource("indeed", jobs)).run(NOW)
    assert _reviews(store) == {}
    assert all(store.is_rejected("indeed", f"indeed-{i}") for i in range(len(titles)))


async def test_thesis_allowed_when_internships_enabled(store):
    s = store.load_settings()
    s.internships = True
    store.save_settings(s)
    store.set_last_successful_run(NOW - timedelta(hours=1))
    job = make_job(1, title="Masterarbeit Cloud Security (m/w/d)")
    res = await runner(store, FakeSource("a", [job])).run(NOW)
    assert [p.kind for _, p in res.to_send] == ["praktikum"]
