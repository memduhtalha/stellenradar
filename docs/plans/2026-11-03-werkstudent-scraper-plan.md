# Werkstudent-Scraper – Umsetzungsplan

> **Für ausführende Agenten:** PFLICHT-SKILL: superpowers:subagent-driven-development (empfohlen) oder superpowers:executing-plans, um diesen Plan Aufgabe für Aufgabe umzusetzen. Die Schritte nutzen Checkboxen (`- [ ]`) zur Verfolgung.

**Ziel:** Ein Telegram-Bot, der stündlich Werkstudentenstellen (Informatik) rund um Düsseldorf auf Arbeitsagentur, StepStone, Indeed und LinkedIn sucht, filtert, bewertet und neue Treffer meldet.

**Architektur:** Ein asynchroner Python-Prozess (Bot und Zeitplaner) plus ein Lightpanda-Container, verbunden per CDP. Quellen sind austauschbare Module mit derselben Schnittstelle. Die Verarbeitung (Filter, Kategorien, Punktzahl, Duplikate) besteht aus reinen Funktionen. Der Zustand liegt in SQLite.

**Tech-Stack:** Python 3.12, python-telegram-bot[job-queue] 21.x, httpx, Playwright (Python), selectolax (HTML-Parsing), PyYAML, pydantic-settings, pytest, pytest-asyncio, respx, Docker Compose, Lightpanda (`lightpanda/browser:nightly`).

**Spec:** `docs/design/2026-11-03-werkstudent-scraper-design.md` – bitte zusammen mit diesem Plan lesen.

## Globale Vorgaben

- Code-Bezeichner sind englisch, Modul-Ordner deutsch wie im Spec (`bot/`, `quellen/`, `verarbeitung/`, `speicher/`). Alle Texte für den Nutzer sind **deutsch**.
- Zeitzone überall `Europe/Berlin`.
- Standardwerte: Ort `Düsseldorf` (51.2277, 6.7735), Umkreis `25` km (Auswahl 10/25/40/60), Remote `aus`, Praktika `aus`, Nicht-Top-Treffer `Sofort`, Intervall `60` Min., aktiv `7`–`22` Uhr, Sammelnachricht `18:00`.
- Standardmäßig aktive Kategorien: `cloud`, `ki`, `security`. Alle anderen aus Spec 4.2 sind aus.
- Kein Login bei irgendeinem Portal. Captchas werden nie umgangen: Bei einem Captcha wird `SourceBlocked` ausgelöst und die Quelle übersprungen.
- Pause zwischen zwei Seitenaufrufen derselben Quelle: zufällig 2–5 s. Höchstens 2 Ergebnisseiten pro Suchanfrage. LinkedIn höchstens 1 Durchlauf pro Stunde, 1 Seite pro Anfrage.
- Detailseiten nur bei unklarem Ergebnis laden, höchstens `10` pro Quelle und Lauf.
- Rückstau: mehr als `10` neue Stellen **und** (erster Lauf **oder** letzter erfolgreicher Lauf liegt mehr als 24 h zurück **oder** `/weiter`). Dann gehen die Top 10 raus, der Rest wird still gespeichert.
- Quellen-Warnung nach `3` Ausfällen hintereinander, genau einmal, bis die Quelle wieder funktioniert.
- Nur die Telegram-User-ID aus `ALLOWED_USER_ID` (.env) wird bedient.
- Geheimnisse stehen nur in `.env`, die in `.gitignore` steht. Im Repo liegt `.env.example`.

## Prüf-Schwerpunkte

Diese Fälle nennt der Spec nicht ausdrücklich, aber sie treffen den Nutzer am ehesten. Zu jedem gibt es einen Test in der Aufgabe, der der Code gehört.

1. **Portal ändert sein HTML** und der Parser liefert dann 0 Treffer ohne Fehler. Das muss als Ausfall zählen und darf nicht als „keine neuen Stellen“ durchgehen. Test: Aufgabe 8, `test_zero_results_after_history_counts_as_failure`.
2. **Dieselbe Stelle mit Varianten** wie „(m/w/d)“ statt „(w/m/d)“, „GmbH“ statt „GmbH & Co. KG“ oder „Düsseldorf-Bilk“ statt „Düsseldorf“ muss als Duplikat erkannt werden. Test: Aufgabe 2, `test_dedupe_key_ignores_gender_tags_legal_forms_and_districts`.
3. **Sonderzeichen in Titel oder Firma** (`<`, `&`, `_`, `*`) dürfen das Senden nicht kaputt machen. Deshalb wird HTML-escaped. Test: Aufgabe 9, `test_format_escapes_html`.
4. **Viele Nachrichten auf einmal** lösen das Telegram-Limit `RetryAfter` aus. Dann wird gewartet und erneut gesendet, nichts geht verloren. Test: Aufgabe 10, `test_send_jobs_retries_after_flood_limit`.
5. **`/jetzt` während eines laufenden geplanten Laufs** darf keinen Doppellauf und keine doppelten Meldungen auslösen. Test: Aufgabe 8, `test_concurrent_run_is_rejected`.

---

## Dateistruktur

```
werkstudent-scraper/
├─ pyproject.toml
├─ Dockerfile
├─ docker-compose.yml
├─ .env.example · .gitignore · README.md
├─ config/
│  ├─ kategorien.yaml          ← Kategorien: label, emoji, default_on, search_terms, keywords
│  └─ bewertung.yaml           ← Punkt-Gewichte, 🔥-Schwelle
├─ src/werkstudent/
│  ├─ main.py                  ← Einstiegspunkt: baut alles zusammen, startet den Bot
│  ├─ config.py                ← .env + YAML laden
│  ├─ modelle.py               ← Datenklassen (Job, ProcessedJob, UserSettings, Category …)
│  ├─ speicher/store.py        ← SQLite-Zugriff
│  ├─ verarbeitung/
│  │  ├─ filter.py             ← Werkstudent-Pflichtfilter, Kategorie-Zuordnung
│  │  ├─ bewertung.py          ← Punktzahl
│  │  ├─ duplikate.py          ← dedupe_key
│  │  └─ geo.py                ← Entfernung, Geocoding mit Cache
│  ├─ quellen/
│  │  ├─ basis.py              ← Source-Protokoll, Fehlerklassen, polite_sleep
│  │  ├─ browser.py            ← fetch_html: Lightpanda → Chromium-Fallback
│  │  ├─ arbeitsagentur.py · stepstone.py · indeed.py · linkedin.py
│  ├─ lauf.py                  ← run_search: Orchestrierung, Rückstau, Quellenstatus
│  └─ bot/
│     ├─ nachrichten.py        ← Formatierung + Buttons (rein)
│     ├─ senden.py             ← send_jobs mit Flood-Handling
│     ├─ einrichtung.py        ← /start-Dialog und /einstellungen
│     ├─ befehle.py            ← /jetzt /pause /weiter /status /gemerkt /hilfe + Button-Callbacks
│     └─ zeitplan.py           ← stündlicher Lauf, Sammelnachricht, Nachholen beim Start
├─ scripts/fixture_aufnehmen.py ← speichert echte Suchseiten als Test-Fixtures
└─ tests/ (spiegelt src/, Fixtures unter tests/fixtures/)
```

---

### Aufgabe 1: Projektgerüst, Konfiguration, Datenmodelle

**Dateien:**
- Erstellen: `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `.env.example`, `.gitignore`, `README.md` (nur Gerüst), `config/kategorien.yaml`, `config/bewertung.yaml`, `src/werkstudent/__init__.py`, `src/werkstudent/config.py`, `src/werkstudent/modelle.py`
- Test: `tests/test_config.py`

**Schnittstellen:**
- Erzeugt (`modelle.py`):
  ```python
  @dataclass(frozen=True)
  class Category:
      key: str; label: str; emoji: str; default_on: bool
      search_terms: list[str]   # z. B. ["Werkstudent Cloud", "Werkstudent DevOps"]
      keywords: list[str]       # zum Zuordnen, Kleinschreibung egal

  @dataclass
  class Job:
      source: str; source_id: str; title: str; company: str; location: str; url: str
      snippet: str = ""; description: str | None = None
      posted_at: datetime | None = None; remote: bool = False
      lat: float | None = None; lon: float | None = None

  @dataclass
  class ProcessedJob:
      job: Job; kind: Literal["werkstudent", "praktikum"]; categories: list[str]
      distance_km: float | None; score: float; is_top: bool; dedupe_key: str
      also_on: list[tuple[str, str]] = field(default_factory=list)  # (source, url)

  @dataclass
  class UserSettings:
      location: str = "Düsseldorf"; lat: float = 51.2277; lon: float = 6.7735
      radius_km: int = 25; categories: set[str] = {"cloud","ki","security"}
      remote: bool = False; internships: bool = False
      digest_mode: Literal["sofort","taeglich"] = "sofort"
      interval_minutes: int = 60; active_from: int = 7; active_to: int = 22
      paused: bool = False; onboarded: bool = False

  @dataclass(frozen=True)
  class ScoringConfig:
      title_keyword: float = 3; title_keyword_max: int = 2; snippet_keyword: float = 1
      near_km: float = 10; near_bonus: float = 2; mid_km: float = 25; mid_bonus: float = 1
      fresh_24h: float = 2; fresh_72h: float = 1; disliked_company: float = -5
      top_threshold: float = 5
  ```
- Erzeugt (`config.py`): `class Env(BaseSettings)` mit `telegram_token: str`, `allowed_user_id: int`, `lightpanda_cdp_url: str = "ws://lightpanda:9222"`, `db_path: str = "data/jobs.db"`. Dazu `load_categories(path: Path) -> list[Category]` und `load_scoring(path: Path) -> ScoringConfig`.

- [ ] **Schritt 1:** `git init`. Lege `.gitignore` an (`.env`, `data/`, `__pycache__/`, `.venv/`, `.pytest_cache/`). Lege `pyproject.toml` mit den Abhängigkeiten aus dem Tech-Stack an, `pytest` mit `asyncio_mode = "auto"` und `pythonpath = ["src"]`.
- [ ] **Schritt 2:** `config/kategorien.yaml` mit allen 8 Kategorien aus Spec 4.2 befüllen: Keys `cloud, ki, security, software, data, infra, qa, consulting`, Emojis und Stichwörter wie im Spec. Pro Kategorie 1–2 `search_terms` (LinkedIn nutzt nur den ersten). `default_on: true` nur für `cloud`, `ki` und `security`. Hinweis für die KI-Kategorie: Kurze Stichwörter wie „KI“ und „AI“ werden später nur als ganzes Wort gezählt (siehe Aufgabe 2).
- [ ] **Schritt 3: Failing Test schreiben**
  ```python
  def test_load_categories_reads_all_eight():
      cats = load_categories(Path("config/kategorien.yaml"))
      assert [c.key for c in cats] == ["cloud","ki","security","software","data","infra","qa","consulting"]
      assert {c.key for c in cats if c.default_on} == {"cloud","ki","security"}
      assert all(c.search_terms and c.keywords for c in cats)

  def test_load_scoring_defaults_when_keys_missing(tmp_path):
      p = tmp_path / "b.yaml"; p.write_text("top_threshold: 7\n")
      s = load_scoring(p)
      assert s.top_threshold == 7 and s.title_keyword == 3
  ```
- [ ] **Schritt 4:** `python -m pytest tests/test_config.py -v` ausführen. Erwartet: FAIL (Import-Fehler).
- [ ] **Schritt 5:** `modelle.py` und `config.py` wie oben implementieren. `config/bewertung.yaml` enthält alle Felder von `ScoringConfig` mit den Standardwerten.
- [ ] **Schritt 6:** Tests ausführen. Erwartet: PASS.
- [ ] **Schritt 7:** `Dockerfile` schreiben: Basis `mcr.microsoft.com/playwright/python:v1.48.0-jammy` (bringt Chromium für den Fallback mit), installiert das Paket, Startbefehl `python -m werkstudent.main`. Dann `docker-compose.yml` mit zwei Diensten:
  - `bot` (build ., `env_file: .env`, Volumes `./data:/app/data` und `./config:/app/config`, `restart: unless-stopped`, `TZ=Europe/Berlin`)
  - `lightpanda` (Image `lightpanda/browser:nightly`, startet den CDP-Server auf `0.0.0.0:9222`, `restart: unless-stopped`; den genauen Startbefehl im Lightpanda-README nachsehen)

  `.env.example` enthält `TELEGRAM_TOKEN=`, `ALLOWED_USER_ID=` und `LIGHTPANDA_CDP_URL=ws://lightpanda:9222`.
- [ ] **Schritt 8:** `docker compose config` ausführen. Erwartet: keine Fehler.
- [ ] **Schritt 9: Commit** `chore: Projektgerüst, Konfiguration und Datenmodelle`

---

### Aufgabe 2: Verarbeitung – Filter, Kategorien, Punktzahl, Duplikate, Entfernung

**Dateien:**
- Erstellen: `src/werkstudent/verarbeitung/{__init__,filter,bewertung,duplikate,geo}.py`
- Test: `tests/verarbeitung/test_filter.py`, `test_bewertung.py`, `test_duplikate.py`, `test_geo.py`

**Schnittstellen:**
- `filter.py`:
  - `classify_kind(text: str, internships: bool) -> Literal["werkstudent","praktikum"] | None`. Werkstudent-Begriffe (Regex, Groß- und Kleinschreibung egal): `werkstudent(in|en|innen)?`, `werkstudierende[rn]?`, `working student`, `studentische (aus)?hilfe`. Praktika-Begriffe, nur wenn `internships` gilt: `(pflicht)?praktik(um|ant)`, `abschlussarbeit`, `bachelorarbeit`, `masterarbeit`, `thesis`. Werkstudent hat Vorrang.
  - `is_excluded_title(title: str) -> bool`: `\bsenior\b` oder `\bvollzeit\b`.
  - `match_categories(title: str, text: str, active: list[Category]) -> tuple[list[str], int, int]` liefert `(keys, Treffer im Titel, Treffer nur im Text)`. Stichwörter mit höchstens 3 Zeichen (KI, AI, SOC, SAP, SQL, QA) zählen nur als ganzes Wort (`\b`), längere als Teilstring.
- `duplikate.py`:
  - `normalize_company(name: str) -> str`: Kleinschreibung. Entfernt Rechtsformen (`gmbh & co. kg`, `gmbh`, `ag`, `se`, `kg`, `mbh`, `ug`, `e.v.`, `inc`, `ltd`) und Satzzeichen, fasst Leerzeichen zusammen.
  - `normalize_title(title: str) -> str`: Kleinschreibung, entfernt Klammern mit Geschlechtsangaben (`(m/w/d)`, `(w/m/d)`, `(all genders)`, `(d/m/w)` usw., Regex `\((?:[mwdfx]\s*/\s*){1,3}[mwdfx]\)|\(all genders?\)`), `*in` und `:in`, Satzzeichen.
  - `normalize_city(location: str) -> str`: erster Teil vor `-`, `,`, `(`, in Kleinschreibung.
  - `dedupe_key(job: Job) -> str` = sha1 aus `company|title|city`, jeweils normalisiert.
- `geo.py`:
  - `haversine_km(a: tuple[float,float], b: tuple[float,float]) -> float` (der `Geocoder` kommt in Aufgabe 3)
- `bewertung.py`:
  - `score(title_hits: int, text_hits: int, distance_km: float | None, posted_at: datetime | None, company_disliked: bool, now: datetime, cfg: ScoringConfig) -> float`. Rechnung: `min(title_hits, title_keyword_max)*title_keyword + (snippet_keyword wenn text_hits>0 und title_hits==0)`, Bonus für Entfernung ≤ `near_km` beziehungsweise ≤ `mid_km`, Bonus für Frische ≤ 24 h beziehungsweise ≤ 72 h, und `disliked_company`, falls die Firma abgelehnt wurde.

- [ ] **Schritt 1: Failing Tests schreiben**
  - `test_kind_werkstudent_variants`: „Werkstudentin Cloud“, „Working Student AI“ und „Werkstudierende IT-Security“ werden alle als `"werkstudent"` erkannt.
  - `test_kind_praktikum_only_when_enabled`: Für „Pflichtpraktikum DevOps“ liefert `internships=False` den Wert `None`, `internships=True` den Wert `"praktikum"`.
  - `test_kind_none_for_fulltime`: „Cloud Engineer (m/w/d)“ ergibt `None`.
  - `test_excluded_title`: „Senior Werkstudent“ ergibt `True`, „Werkstudent Security“ ergibt `False`.
  - `test_short_keyword_whole_word`: „Werkstudent KI“ passt zu `ki`. „Werkstudent Marketing **Ki**ta-Verwaltung“ passt nicht zu `ki`.
  - `test_match_counts_title_vs_text`: Titel „Werkstudent AWS“ und Text mit „Kubernetes“ ergeben für `cloud` die Werte `(["cloud"], 1, 0)`. Stichwörter, die nur im Titel stehen, werden nicht zusätzlich als Text-Treffer gezählt.
  - `test_dedupe_key_ignores_gender_tags_legal_forms_and_districts` (Prüf-Schwerpunkt 2): Diese beiden Stellen ergeben denselben Key:
    - „Werkstudent Cloud (m/w/d)“, „Beispiel GmbH & Co. KG“, „Düsseldorf-Bilk“
    - „Werkstudent Cloud (w/m/d)“, „Beispiel GmbH“, „Düsseldorf“

    „Werkstudent Security“ bei derselben Firma ergibt dagegen einen anderen Key.
  - `test_haversine_duesseldorf_koeln`: ungefähr 34 km (±2).
  - `test_score_top_example`: 2 Titel-Treffer, 3 km entfernt, 5 h alt, ergibt `3*2+2+2 = 10`, also über der 🔥-Schwelle 5.
  - `test_score_disliked_company`: Mit denselben Werten und `company_disliked=True` ergibt sich `5`.
  - `test_score_unknown_distance_and_date`: 1 Titel-Treffer, ohne Entfernung und ohne Datum, ergibt `3`.
- [ ] **Schritt 2:** `python -m pytest tests/verarbeitung -v` ausführen. Erwartet: FAIL.
- [ ] **Schritt 3:** Alle Funktionen wie oben implementieren.
- [ ] **Schritt 4:** Tests ausführen. Erwartet: PASS.
- [ ] **Schritt 5: Commit** `feat: Filter, Kategorien, Punktzahl, Duplikate, Entfernung`

---

### Aufgabe 3: SQLite-Speicher und Geocoder

**Dateien:**
- Erstellen: `src/werkstudent/speicher/__init__.py`, `src/werkstudent/speicher/store.py`, `src/werkstudent/verarbeitung/geo.py` (Geocoder-Klasse ergänzen)
- Test: `tests/speicher/test_store.py`, `tests/verarbeitung/test_geo.py` (Geocoder-Test ergänzen)

**Schnittstellen:**
- Nutzt: `Job`, `ProcessedJob`, `UserSettings` aus Aufgabe 1; `normalize_company`, `haversine_km` aus Aufgabe 2.
- Erzeugt zusätzlich in `geo.py`: `class Geocoder(store: Store, client: httpx.AsyncClient)` mit `async locate(place: str) -> tuple[float,float] | None`. Fragt zuerst den Cache, dann Nominatim (`https://nominatim.openstreetmap.org/search?format=json&countrycodes=de&limit=1&q=…`, mit eigenem `User-Agent` und höchstens 1 Anfrage pro Sekunde). Bei Fehlern kommt `None` zurück. Test: `test_geocoder_uses_cache`: Ist ein Ort im Cache, wird kein HTTP-Aufruf ausgelöst (respx `call_count == 0`). Test: `test_geocoder_stores_result`: Nach einem Nominatim-Treffer ist der Ort im Cache.
- Erzeugt: `class Store` (synchrones `sqlite3`, eine Verbindung, `check_same_thread=False`; die Zugriffe sind klein, async wäre hier unnötig):
  - `Store(path: str)`. `init()` legt diese Tabellen an: `jobs`, `also_on`, `bookmarks`, `disliked_companies`, `settings` (eine JSON-Zeile), `source_state`, `meta` (Schlüssel/Wert), `geocache`.
  - `JobStatus = Literal["reported","silent","digest","held","rejected"]`
  - `is_known(dedupe_key: str) -> bool`; `is_rejected(source: str, source_id: str) -> bool`
  - `save_job(p: ProcessedJob | None, job: Job, status: JobStatus) -> int` gibt die Job-ID zurück. Bei `rejected` darf `p` `None` sein. Dann werden nur `source` und `source_id` gespeichert, damit die Detailseite nicht erneut geladen wird.
  - `add_also_on(dedupe_key: str, source: str, url: str) -> None`
  - `jobs_with_status(status: JobStatus) -> list[tuple[int, ProcessedJob]]`; `set_status(job_ids: list[int], status: JobStatus) -> None`
  - `get_job(job_id: int) -> ProcessedJob | None`
  - `bookmark(job_id: int) -> None`; `bookmarks() -> list[ProcessedJob]`
  - `dismiss(job_id: int) -> None` (merkt sich zusätzlich die normalisierte Firma); `disliked_companies() -> set[str]`
  - `load_settings() -> UserSettings` (Standardwerte, wenn noch nichts gespeichert ist); `save_settings(s: UserSettings) -> None`
  - `record_source_result(name: str, ok: bool, count: int, now: datetime) -> SourceState`
  - `@dataclass class SourceState: consecutive_failures: int; warned: bool; last_ok_at: datetime | None; last_ok_count: int`
  - `set_warned(name: str, warned: bool) -> None`; `all_source_states() -> dict[str, SourceState]`
  - `last_successful_run() -> datetime | None`; `set_last_successful_run(t: datetime) -> None`
  - `geocache_get(place: str) -> tuple[float, float] | None`; `geocache_put(place: str, lat: float, lon: float) -> None`

- [ ] **Schritt 1: Failing Tests schreiben** (mit `Store(":memory:")`)
  - `test_settings_roundtrip`: Standardwerte laden, `radius_km=40` setzen, speichern und neu laden, danach gilt `== 40`. Das Set `categories` überlebt den Weg über JSON.
  - `test_save_and_is_known`: Nach `save_job(..., "reported")` gilt `is_known(key)`, ein anderer Key gilt als unbekannt.
  - `test_rejected_is_remembered_without_processed`: `save_job(None, job, "rejected")` führt zu `is_rejected("indeed", "x1")`.
  - `test_status_transitions`: Zwei Jobs werden als `held` gespeichert. `jobs_with_status("held")` liefert beide. Nach `set_status([id1], "reported")` liefert die Abfrage nur noch einen.
  - `test_dismiss_adds_company`: Bei `dismiss(id)` mit Firma „Beispiel GmbH“ enthält `disliked_companies()` den Wert `"beispiel"`. Dafür wird `normalize_company` aus Aufgabe 2 genutzt.
  - `test_source_failures_count_and_reset`: Drei Mal `ok=False` ergibt `consecutive_failures == 3`. Ein Mal `ok=True, count=12` setzt den Wert auf `0`, `last_ok_count == 12` und `warned == False`.
- [ ] **Schritt 2:** Tests ausführen. Erwartet: FAIL.
- [ ] **Schritt 3:** `Store` und `Geocoder` implementieren. `ProcessedJob` wird als JSON in der Spalte `data` gespeichert, dazu die Spalten `dedupe_key` (indexiert), `source`, `source_id`, `status`, `created_at`.
- [ ] **Schritt 4:** Tests ausführen. Erwartet: PASS.
- [ ] **Schritt 5: Commit** `feat: SQLite-Speicher und Geocoder`

---

### Aufgabe 4: Quellen-Basis und Arbeitsagentur

**Dateien:**
- Erstellen: `src/werkstudent/quellen/{__init__,basis,arbeitsagentur}.py`
- Test: `tests/quellen/test_arbeitsagentur.py`, Fixture `tests/fixtures/arbeitsagentur_search.json`

**Schnittstellen:**
- `basis.py`:
  ```python
  class SourceError(Exception): ...
  class SourceBlocked(SourceError): ...   # Captcha/Bot-Schutz
  class Source(Protocol):
      name: str
      async def search(self, settings: UserSettings, categories: list[Category],
                       now: datetime | None = None) -> list[Job]: ...
      async def fetch_detail(self, job: Job) -> str | None: ...   # Volltext oder None
  async def polite_sleep(min_s: float = 2, max_s: float = 5) -> None
  ```
  Die Liste von `search` wird innerhalb der Quelle nach `source_id` dedupliziert. `polite_sleep` lässt sich in Tests per `monkeypatch` ausschalten.
- `arbeitsagentur.py`: `class ArbeitsagenturSource(client: httpx.AsyncClient)` mit `name = "arbeitsagentur"`.
  - `GET https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs`, Header `X-API-Key: jobboerse-jobsuche`
  - Parameter: `was=<search_term>`, `wo=<settings.location>`, `umkreis=<radius_km>`, `angebotsart=1`, `veroeffentlichtseit=7`, `size=50`, `page=1..2`
  - Bei `settings.internships` zusätzlich ein Durchlauf mit `angebotsart=34`.
  - Bei `settings.remote` zusätzlich `arbeitszeit=ho` ohne `wo`/`umkreis`.
  - Abbildung: `refnr` → `source_id`, `titel`, `arbeitgeber`, `arbeitsort.ort`, `arbeitsort.koordinaten.lat/lon`, `aktuelleVeroeffentlichungsdatum` → `posted_at`, URL `https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}`.
  - `fetch_detail` liefert `None` (die API gibt keinen Volltext her, der Titel reicht).
  - Wichtig: Endpunkt und Felder sind nicht offiziell dokumentiert (Quelle: bundesAPI/jobsuche-api). Prüfe sie deshalb einmal live, wenn du die Fixture anlegst (Schritt 1).

- [ ] **Schritt 1:** Eine echte Antwort mit `curl` holen (`was=Werkstudent Cloud`, `wo=Düsseldorf`, `umkreis=25`), auf 3 Stellen kürzen und als Fixture speichern.
- [ ] **Schritt 2: Failing Tests schreiben** (respx mockt den Endpunkt mit der Fixture)
  - `test_maps_fields`: Prüft `source_id`, `title`, `company`, `lat` und `lon` der ersten Stelle, `url` beginnt mit `https://www.arbeitsagentur.de/jobsuche/jobdetail/`, und `posted_at` ist zeitzonenbewusst.
  - `test_sends_api_key_and_params`: Header `X-API-Key` und `umkreis=25` sind in der Anfrage enthalten.
  - `test_internships_adds_angebotsart_34`: Mit `internships=True` gibt es eine zusätzliche Anfrage mit `angebotsart=34`.
  - `test_http_500_raises_source_error`
- [ ] **Schritt 3:** Tests ausführen. Erwartet: FAIL.
- [ ] **Schritt 4:** Implementieren.
- [ ] **Schritt 5:** Tests ausführen. Erwartet: PASS.
- [ ] **Schritt 6: Commit** `feat: Quelle Arbeitsagentur`

---

### Aufgabe 5: Browser-Zugang (Lightpanda → Chromium) und StepStone

**Dateien:**
- Erstellen: `src/werkstudent/quellen/browser.py`, `src/werkstudent/quellen/stepstone.py`, `scripts/fixture_aufnehmen.py`
- Test: `tests/quellen/test_browser.py`, `tests/quellen/test_stepstone.py`, Fixtures `tests/fixtures/stepstone_search.html` und `stepstone_detail.html`

**Schnittstellen:**
- `browser.py`:
  ```python
  class Browser:
      def __init__(self, cdp_url: str): ...
      async def fetch_html(self, url: str, wait_selector: str, timeout_s: float = 20) -> str
      async def close(self) -> None
  ```
  Ablauf: Zuerst `playwright.chromium.connect_over_cdp(cdp_url)`, neuer Kontext, `goto` und `wait_for_selector`. Scheitert die Verbindung oder läuft das Warten auf den Selektor ab, folgt **ein** zweiter Versuch mit lokalem `chromium.launch(headless=True)`. Scheitert auch der, wird `SourceError` ausgelöst. Welcher Browser genutzt wurde, kommt ins Log (`logging.info`). Kontexte immer schließen, damit kein Speicherleck entsteht.
- `stepstone.py`: `class StepStoneSource(browser: Browser)` mit `name = "stepstone"`.
  - Such-URL: `https://www.stepstone.de/jobs/{slug(search_term)}/in-{slug(location)}?radius={radius_km}&ag=age_7` (Format live prüfen)
  - Parser: `parse_search(html: str) -> list[Job]` und `parse_detail(html: str) -> str`, beide rein mit selectolax. Selektoren legst du anhand der Fixture fest.
  - Mit `settings.remote` zusätzlich eine Suche mit Ort „Homeoffice“, die gefundenen Stellen bekommen `remote=True`.
- `scripts/fixture_aufnehmen.py <url> <wait_selector> <ausgabe.html>`: nutzt `Browser.fetch_html` und speichert das Ergebnis.

- [ ] **Schritt 1:** Lightpanda lokal starten (`docker compose up -d lightpanda`). Dann mit dem Skript eine Suchseite und eine Detailseite von StepStone als Fixture aufnehmen. Notiere im Commit-Text, ob Lightpanda die Seite vollständig gerendert hat oder ob der Fallback greifen musste.
- [ ] **Schritt 2: Failing Tests schreiben**
  - `test_parse_search_finds_jobs`: Mindestens 5 Stellen. Jede hat einen nicht leeren `title`, `company`, `location`, eine `url` mit `https://www.stepstone.de/` am Anfang und eine eindeutige `source_id`.
  - `test_parse_detail_returns_text`: Liefert mehr als 200 Zeichen und enthält ein Wort aus dem Titel.
  - `test_fetch_html_falls_back_to_chromium` (in `test_browser.py`): `connect_over_cdp` wird per Monkeypatch zum Fehlschlag gebracht. Danach muss `launch` aufgerufen werden und das HTML zurückkommen. Playwright wird dafür über ein kleines Fake-Objekt ersetzt.
  - `test_search_raises_on_both_browsers_failing`: Ergibt `SourceError`.
- [ ] **Schritt 3:** Tests ausführen. Erwartet: FAIL.
- [ ] **Schritt 4:** Implementieren.
- [ ] **Schritt 5:** Tests ausführen. Erwartet: PASS.
- [ ] **Schritt 6: Commit** `feat: Browser-Zugang mit Fallback und Quelle StepStone`

---

### Aufgabe 6: Indeed

**Dateien:**
- Erstellen: `src/werkstudent/quellen/indeed.py`
- Test: `tests/quellen/test_indeed.py`, Fixtures `indeed_search.html` und `indeed_captcha.html` (eine Captcha-Seite aufnehmen, sobald eine erscheint. Falls keine erscheint, eine Minimalseite mit `<title>Just a moment...</title>` verwenden.)

**Schnittstellen:**
- `class IndeedSource(browser: Browser)` mit `name = "indeed"`
- Such-URL: `https://de.indeed.com/jobs?q={search_term}&l={location}&radius={radius_km}&fromage=7`. Bei `remote` zusätzlich `&sc=0kf%3Aattr(DSQF7)%3B` (Remote-Filter, live prüfen) ohne `l`.
- `parse_search(html) -> list[Job]` und `parse_detail(html) -> str`
- `is_blocked(html: str) -> bool` erkennt eine Sperrseite an Titeln wie „Just a moment“, „Security Check“ oder „hCaptcha“ beziehungsweise an `cf-challenge`- oder `captcha`-Elementen. Dann wird `SourceBlocked` ausgelöst, **ohne neuen Versuch**.
- Bei Indeed führt ein abgelaufener `wait_selector` oft zu einer Captcha-Seite. `fetch_html` liefert in diesem Fall das HTML trotzdem zurück, wenn ein Parameter `return_on_timeout=True` gesetzt ist. Füge diesen Parameter zu `Browser.fetch_html` hinzu, mit Standardwert `False`.

- [ ] **Schritt 1:** Fixtures aufnehmen.
- [ ] **Schritt 2: Failing Tests schreiben**
  - `test_parse_search_finds_jobs` (wie bei StepStone, URL beginnt mit `https://de.indeed.com/`)
  - `test_captcha_page_is_blocked`: `is_blocked(captcha_html)` ist `True`, `is_blocked(search_html)` ist `False`.
  - `test_search_raises_source_blocked_on_captcha` (mit einem Fake-`Browser`, der das Captcha-HTML zurückgibt)
- [ ] **Schritt 3:** Tests ausführen. Erwartet: FAIL. Dann implementieren, Tests erneut ausführen. Erwartet: PASS.
- [ ] **Schritt 4: Commit** `feat: Quelle Indeed mit Captcha-Erkennung`

---

### Aufgabe 7: LinkedIn (öffentliche Gast-Suche)

**Dateien:**
- Erstellen: `src/werkstudent/quellen/linkedin.py`
- Test: `tests/quellen/test_linkedin.py`, Fixture `linkedin_search.html`

**Schnittstellen:**
- `class LinkedInSource(client: httpx.AsyncClient)` mit `name = "linkedin"`, **ohne Browser und ohne Login**.
- Anfrage: `GET https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={search_terms[0]}&location={location}&distance={round(radius_km/1.609)}&f_TPR=r604800&start=0`. Der Parameter `distance` ist in Meilen. Dazu ein normaler Browser-`User-Agent`.
- Pro Kategorie genau **eine** Anfrage (nur `search_terms[0]`). Die Quelle merkt sich `_last_run: datetime` und liefert `[]`, ohne Fehler, wenn der letzte Durchlauf weniger als 60 Minuten her ist.
- `parse_search(html) -> list[Job]`, mit Selektoren für jeweils eine Karte: `div.base-card` mit `data-entity-urn` (`urn:li:jobPosting:<id>`), `h3.base-search-card__title`, `h4.base-search-card__subtitle`, `span.job-search-card__location`, `time[datetime]`, `a.base-card__full-link[href]`. Diese Selektoren gegen die Fixture prüfen.
- Status 429 oder 999 (so antwortet LinkedIn bei einer Sperre) löst `SourceBlocked` aus.
- `fetch_detail` lädt `https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}` und liefert den Text von `div.show-more-less-html__markup`.

- [ ] **Schritt 1:** Fixture mit `curl` aufnehmen.
- [ ] **Schritt 2: Failing Tests schreiben**
  - `test_parse_search_finds_jobs` (URL ohne Query-Tracking, eindeutige `source_id`, `posted_at` gesetzt)
  - `test_status_999_raises_blocked` (respx)
  - `test_skips_if_last_run_under_60_min`: Ein zweiter Aufruf mit `now` + 30 min ergibt `[]` und keine HTTP-Anfrage.
  - `test_distance_in_miles`: Bei 25 km steht `distance=16` in der Anfrage.
- [ ] **Schritt 3:** Tests ausführen. Erwartet: FAIL. Dann implementieren, Tests erneut ausführen. Erwartet: PASS.
- [ ] **Schritt 4: Commit** `feat: Quelle LinkedIn (Gast-Suche)`

---

### Aufgabe 8: Suchlauf – Orchestrierung, Rückstau, Quellenstatus

**Dateien:**
- Erstellen: `src/werkstudent/lauf.py`
- Test: `tests/test_lauf.py`, mit Fake-Quellen und `Store(":memory:")`

**Schnittstellen:**
- Nutzt: `Source`, `Store`, alle Funktionen aus Aufgabe 2, `Geocoder` aus Aufgabe 3, `ScoringConfig`.
- Erzeugt:
  ```python
  @dataclass
  class RunResult:
      to_send: list[tuple[int, ProcessedJob]]       # sofort melden (ID aus Store)
      backlog_total: int | None                     # gesetzt, wenn Rückstau-Regel griff
      warnings: list[str]                           # deutsche Warntexte
      source_counts: dict[str, int | str]           # Treffer je Quelle oder "blockiert"/"Fehler"

  class Runner:
      def __init__(self, store, sources: list[Source], categories: list[Category],
                   scoring: ScoringConfig, geocoder: Geocoder): ...
      running: bool
      async def run(self, now: datetime, force_backlog: bool = False) -> RunResult | None
      def release_held(self, now: datetime) -> RunResult    # für /weiter
  ```
- Ablauf von `run`. Gibt `None` zurück, wenn bereits ein Lauf aktiv ist (`asyncio.Lock`, nicht blockierend prüfen):
  1. Einstellungen laden. Aktive Kategorien sind die Schnittmenge aus der Konfiguration und `settings.categories`.
  2. Alle Quellen nacheinander durchlaufen, mit `try/except` pro Quelle. `SourceBlocked` zählt als „blockiert“, `SourceError` und andere Exceptions als „Fehler“. Danach `record_source_result` aufrufen. **Ausfall** heißt Exception **oder** 0 Treffer, obwohl `last_ok_count >= 5` war.
  3. Pro Stelle:
     - Bei `is_rejected` überspringen.
     - Mit `dedupe_key` prüfen, ob die Stelle bekannt ist. Dann nur `add_also_on` aufrufen und überspringen. Gleiches gilt für Duplikate innerhalb desselben Laufs: Die erste Quelle gewinnt, weitere werden zu `also_on`.
     - `is_excluded_title` ergibt `rejected`.
     - `classify_kind` und `match_categories` auf Titel und Snippet anwenden. Ist das Ergebnis `None` oder gibt es keine Kategorie, wird die Detailseite geladen, solange das Budget von 10 pro Quelle reicht, und dasselbe mit dem Volltext wiederholt. Bleibt es dabei, wird die Stelle als `rejected` gespeichert.
     - Entfernung: Koordinaten der Stelle verwenden oder `geocoder.locate(location)`. Ist die Entfernung bekannt, größer als `radius_km + 5` und die Stelle nicht (`remote` und `settings.remote`), wird sie als `rejected` gespeichert. Remote-Stellen bei `settings.remote == False`, die außerhalb des Radius liegen oder deren Entfernung unbekannt ist, ebenfalls `rejected`.
     - Punktzahl berechnen, `is_top = score >= top_threshold`.
  4. Status zuteilen:
     - Bei `settings.paused` bekommen alle Stellen `held`.
     - Sonst gilt der Rückstau, wenn `force_backlog`, `last_successful_run() is None` oder `now - last > 24h` zutrifft **und** es mehr als 10 neue Stellen gibt. Dann bekommen die 10 mit der höchsten Punktzahl `reported`, der Rest `silent`, und `backlog_total` wird auf die Anzahl gesetzt.
     - Sonst bekommt `is_top` oder `digest_mode=="sofort"` den Status `reported`, alles andere `digest`.
  5. Wenn mindestens eine Quelle erfolgreich war, `set_last_successful_run(now)`.
  6. Warnungen: Hat eine Quelle `consecutive_failures >= 3` und noch nicht `warned`, kommt der Text `"⚠️ {Name} liefert seit {n} Läufen nichts ({Grund})."` dazu, danach `set_warned(name, True)`.
  7. `to_send` ist nach Punktzahl absteigend sortiert.
- `release_held` nimmt alle `held`-Jobs und wendet die Rückstau-Regel mit `force_backlog=True` an.

- [ ] **Schritt 1: Failing Tests schreiben**
  - `test_first_run_backlog_top10_rest_silent`: Eine Fake-Quelle liefert 25 passende Stellen. Ergebnis: `len(to_send) == 10`, `backlog_total == 25`, 15 Jobs haben `silent`, und `to_send` ist absteigend nach Punktzahl sortiert.
  - `test_normal_run_reports_only_new`: Ein zweiter Lauf mit denselben 25 Stellen und 2 neuen ergibt `len(to_send) == 2`, `backlog_total is None`.
  - `test_cross_source_duplicate_goes_to_also_on`: Zwei Quellen liefern dieselbe Stelle. Ergebnis: 1 Job in `to_send`, mit `also_on` mit 1 Eintrag. Beim Auslesen über den Store enthält er die zweite Quelle.
  - `test_digest_mode_holds_non_top`: Bei `digest_mode="taeglich"` bekommen Nicht-Top-Stellen `digest`, Top-Stellen werden gemeldet.
  - `test_paused_holds_then_release_applies_backlog`: Bei `paused` ergibt sich `to_send == []` und 12 Jobs mit `held`. `release_held` liefert dann 10 Jobs zum Senden und `backlog_total == 12`.
  - `test_no_category_triggers_detail_fetch_once`: Die Fake-Quelle zählt Aufrufe von `fetch_detail`. Eine Stelle ohne Kategorie im Snippet, aber mit Kategorie in der Detailseite, wird gemeldet. Beim zweiten Lauf mit einer abgelehnten Stelle gibt es keinen erneuten `fetch_detail`.
  - `test_detail_budget_is_10_per_source`: 15 unklare Stellen führen zu genau 10 Aufrufen von `fetch_detail`.
  - `test_blocked_source_does_not_stop_others`: Quelle A löst `SourceBlocked` aus, Quelle B liefert 3 Stellen. Ergebnis: 3 Stellen in `to_send` und `source_counts["a"] == "blockiert"`.
  - `test_warning_after_three_failures_once`: Drei Läufe mit Ausfall ergeben genau eine Warnung, der vierte Lauf ergibt keine. Nach einem erfolgreichen Lauf und drei weiteren Ausfällen kommt wieder eine Warnung.
  - `test_zero_results_after_history_counts_as_failure` (Prüf-Schwerpunkt 1): Erst ein Lauf mit 8 Treffern, dann drei Läufe mit 0 Treffern. Ergebnis: eine Warnung.
  - `test_concurrent_run_is_rejected` (Prüf-Schwerpunkt 5): Eine Fake-Quelle wartet auf ein `asyncio.Event`. Zwei `run`-Aufrufe parallel ergeben einmal `None` und einmal ein Ergebnis. Danach gibt es keine doppelten Jobs im Store.
  - `test_far_away_job_rejected_unless_remote_enabled`: Eine Stelle in München (Entfernung über 400 km) wird abgelehnt. Mit `remote=True` und einer Stelle mit `remote=True` wird sie gemeldet.
- [ ] **Schritt 2:** `python -m pytest tests/test_lauf.py -v` ausführen. Erwartet: FAIL.
- [ ] **Schritt 3:** `Runner` implementieren.
- [ ] **Schritt 4:** Tests ausführen. Erwartet: PASS. Danach die gesamte Testsuite ausführen. Erwartet: PASS.
- [ ] **Schritt 5: Commit** `feat: Suchlauf mit Rückstau-Regel und Quellenstatus`

---

### Aufgabe 9: Telegram-Nachrichten formatieren

**Dateien:**
- Erstellen: `src/werkstudent/bot/{__init__,nachrichten}.py`
- Test: `tests/bot/test_nachrichten.py`

**Schnittstellen:**
- Alle Texte nutzen `parse_mode="HTML"`, Inhalte werden mit `html.escape` geschützt.
- `format_job(job_id: int, p: ProcessedJob, categories: dict[str, Category], now: datetime) -> tuple[str, InlineKeyboardMarkup]`. Das Layout entspricht Spec 5.3:
  - Zeile 1: `🔥 ` (nur bei Top) + Emojis und Labels der Kategorien, mit ` · ` getrennt. Dazu ` · 🎓 Praktikum/Abschlussarbeit` bei `kind=="praktikum"` und ` · 🏠 Remote` bei `remote`.
  - Zeile 2: `<b>Titel</b>`
  - Zeile 3: `🏢 Firma · 📍 Ort (X km)`. Die km-Angabe gibt es nur, wenn die Entfernung bekannt ist, gerundet.
  - Zeile 4: `📅 vor N Std.` oder `vor N Tagen` (fehlt, wenn kein Datum vorliegt), dazu ` · Quelle: StepStone`. Gibt es `also_on`: ` (auch auf: Indeed, LinkedIn)`.
  - Zeile 5: `🔗 <a href="url">Zur Anzeige</a>`
  - Buttons: `[⭐ Merken]` mit Callback `bm:{job_id}` und `[👎 Uninteressant]` mit Callback `dz:{job_id}`
  - Anzeigenamen der Quellen: `arbeitsagentur` → „Arbeitsagentur“, `stepstone` → „StepStone“, `indeed` → „Indeed“, `linkedin` → „LinkedIn“.
- `format_backlog_intro(total: int) -> str` ergibt `"📦 Rückstau: {total} neue Stellen – hier die Top 10."`
- `format_digest(items: list[ProcessedJob]) -> list[str]`: Eine Sammelnachricht mit einer Zeile pro Stelle (Titel als Link, Firma, Ort). Sie wird an der Grenze von 4096 Zeichen in mehrere Nachrichten geteilt.
- `format_status(states: dict[str, SourceState], counts: dict, last_run: datetime | None, next_run: datetime | None, paused: bool) -> str`

- [ ] **Schritt 1: Failing Tests schreiben**
  - `test_format_top_job_layout`: Der Text beginnt mit `🔥 ☁️ Cloud & DevOps` und enthält `<b>Werkstudent Cloud</b>`, `(3 km)`, `vor 2 Std.` und `Quelle: StepStone (auch auf: Indeed)`. Die Callback-Daten der Buttons sind `["bm:7","dz:7"]`.
  - `test_format_escapes_html` (Prüf-Schwerpunkt 3): Bei der Firma `"A&B <Tech>"` enthält der Text `A&amp;B &lt;Tech&gt;`, und bei der URL mit `&` ist das `href` korrekt escaped.
  - `test_format_without_distance_and_date`: Der Text enthält weder `km` noch `📅`.
  - `test_format_praktikum_and_remote_tags`
  - `test_digest_splits_over_4096`: 200 Stellen ergeben mehr als eine Nachricht, jede höchstens 4096 Zeichen lang.
- [ ] **Schritt 2:** Tests ausführen. Erwartet: FAIL. Dann implementieren, Tests erneut ausführen. Erwartet: PASS.
- [ ] **Schritt 3: Commit** `feat: Telegram-Nachrichten formatieren`

---

### Aufgabe 10: Telegram-Bot – Einrichtung, Befehle, Buttons, Zeitplan, Start

**Dateien:**
- Erstellen: `src/werkstudent/bot/{senden,einrichtung,befehle,zeitplan}.py`, `src/werkstudent/main.py`
- Ändern: `README.md` (vollständige Anleitung)
- Test: `tests/bot/test_senden.py`, `tests/bot/test_befehle.py`, `tests/bot/test_zeitplan.py`

**Schnittstellen:**
- `senden.py`: `async def send_jobs(bot, chat_id: int, result: RunResult, categories, now, sleep=asyncio.sleep) -> None`
  - Sendet zuerst die Warnungen, dann bei Rückstau das Intro, dann jede Stelle einzeln mit `sleep(1.1)` dazwischen.
  - Bei `telegram.error.RetryAfter`: `sleep(e.retry_after)` und dieselbe Nachricht erneut senden, höchstens 3 Versuche.
  - Andere Fehler beim Senden werden geloggt, die nächste Stelle wird trotzdem gesendet.
- `einrichtung.py`: Ein `ConversationHandler` für `/start` und `/einstellungen` mit den Fragen aus Spec 5.1 in genau dieser Reihenfolge:
  1. Ort: Button `[Düsseldorf]` oder Freitext. Freitext wird mit `Geocoder.locate` geprüft. Bei `None` antwortet der Bot „Ort nicht gefunden, bitte nochmal.“
  2. Umkreis: `[10 km] [25 km] [40 km] [60 km]`
  3. Kategorien: An/Aus-Buttons `✅`/`☐` je Kategorie und `[Fertig]`. Ein Tippen bearbeitet dieselbe Nachricht (`edit_message_reply_markup`). Bei `[Fertig]` ohne gewählte Kategorie antwortet der Bot „Bitte mindestens einen Bereich wählen.“
  4. Remote `[Ja] [Nein]`
  5. Praktika/Abschlussarbeiten `[Ja] [Nein]`
  6. Nicht-Top-Treffer `[Sofort] [Tägliche Sammelnachricht]`
  7. **nur bei `/einstellungen`:** Intervall `[30 Min] [60 Min] [120 Min]`

  `/einstellungen` zeigt zuerst ein Menü mit einem Button pro Punkt, gefolgt von der jeweiligen Einzelfrage. Am Ende wird `save_settings` aufgerufen und eine Zusammenfassung gesendet. Nach dem ersten `/start` gilt `onboarded=True`, und es folgt sofort ein Lauf (über den Rückstau-Weg, da es der erste Lauf ist).
- `befehle.py`: Handler für `/jetzt`, `/pause`, `/weiter`, `/status`, `/gemerkt`, `/hilfe` und die Callbacks `bm:` und `dz:`.
  - `/jetzt` startet `runner.run`. Ist das Ergebnis `None`, antwortet der Bot „Läuft gerade schon – Ergebnisse kommen gleich.“
  - `/weiter` setzt `paused=False` und ruft `release_held` und dann `send_jobs` auf.
  - `bm:` ruft `store.bookmark` auf und beantwortet den Callback mit „⭐ Gemerkt“.
  - `dz:` ruft `store.dismiss` auf, beantwortet den Callback mit „Ausgeblendet“ und löscht die Nachricht.
  - Alle Handler werden mit `filters.User(user_id=env.allowed_user_id)` registriert. Callbacks prüfen `update.effective_user.id` und ignorieren fremde Nutzer ohne Antwort.
  - Die Befehle werden beim Start per `set_my_commands` mit deutschen Beschreibungen registriert.
- `zeitplan.py`:
  - `def is_active(now: datetime, s: UserSettings) -> bool` gilt, wenn `s.active_from <= now.hour < s.active_to`.
  - `def next_run_at(last: datetime | None, now: datetime, s: UserSettings) -> datetime`: Liegt `last` nicht vor oder ist `now - last >= interval` **und** `is_active(now)`, ist das Ergebnis `now` (Nachholen). Sonst `last + interval`. Fällt dieser Zeitpunkt außerhalb des aktiven Zeitfensters, wird es der nächste Tag um `active_from:00`.
  - `def schedule(app, runner, store, ...)` nutzt die `JobQueue`: Ein Tick pro Minute prüft `next_run_at <= now`, ruft dann `runner.run` und anschließend `send_jobs` auf. Dazu kommt `run_daily(18:00 Europe/Berlin)` für die Sammelnachricht: Alle `digest`-Jobs werden gesendet und auf `reported` gesetzt, bei leerer Liste wird nichts gesendet. Die Sammelnachricht gibt es nur, wenn `digest_mode=="taeglich"` und nicht pausiert ist.
- `main.py`: Lädt `Env` und die Konfiguration, ruft `Store.init()` auf, erstellt `httpx.AsyncClient`, `Browser`, die vier Quellen, `Geocoder` und `Runner` und baut die `Application`. Handler und Zeitplan werden registriert, dann `run_polling()`. Beim Herunterfahren werden der Browser und der Client geschlossen. Logging auf INFO.

- [ ] **Schritt 1: Failing Tests schreiben**
  - `test_send_jobs_retries_after_flood_limit` (Prüf-Schwerpunkt 4): Ein Fake-Bot wirft beim zweiten `send_message` einmal `RetryAfter(3)`. Ergebnis: Alle 3 Stellen werden gesendet, und `sleep` wurde mit `3` aufgerufen.
  - `test_send_jobs_continues_after_other_error`: Eine Stelle wirft `BadRequest`, die übrigen 2 werden trotzdem gesendet.
  - `test_send_order_warnings_intro_jobs`
  - `test_callback_from_foreign_user_ignored` (`test_befehle.py`, mit Fake-`Update`): Die ID einer fremden Person führt zu keinem `bookmark`-Aufruf.
  - `test_bookmark_callback_saves`: `bm:5` setzt einen Merklisten-Eintrag für die ID 5.
  - `test_next_run_catches_up_after_downtime`: `last` = gestern 15:00, `now` = heute 09:30 ergibt `now`.
  - `test_next_run_outside_window_moves_to_morning`: `last` = 21:30, Intervall 60 ergibt morgen 07:00.
  - `test_next_run_normal`: `last` = 10:00, `now` = 10:20 ergibt 11:00.
- [ ] **Schritt 2:** Tests ausführen. Erwartet: FAIL.
- [ ] **Schritt 3:** `senden.py`, `zeitplan.py`, `befehle.py`, `einrichtung.py` und `main.py` implementieren.
- [ ] **Schritt 4:** Tests ausführen. Erwartet: PASS. Danach die gesamte Testsuite ausführen. Erwartet: PASS.
- [ ] **Schritt 5:** `README.md` vollständig schreiben, auf Deutsch und Schritt für Schritt:
  1. WSL2 und Docker Desktop installieren, mit aktivierter WSL-Integration
  2. Bot bei @BotFather anlegen und das Token kopieren
  3. Die eigene User-ID über @userinfobot herausfinden
  4. `.env` aus `.env.example` erstellen
  5. `docker compose up -d --build` ausführen
  6. Dem Bot in Telegram `/start` senden
  7. Logs mit `docker compose logs -f bot` ansehen
  8. Kategorien oder Gewichte in `config/` ändern und mit `docker compose restart bot` übernehmen
  9. Umzug auf einen Server: Ordner kopieren, `data/` mitnehmen, `docker compose up -d`
- [ ] **Schritt 6: Commit** `feat: Telegram-Bot mit Einrichtung, Befehlen und Zeitplan`

---

### Aufgabe 11: End-to-End-Test mit echtem Bot (manuell, gemeinsam mit dem Nutzer)

- [ ] **Schritt 1:** Der Nutzer legt den Bot an und füllt `.env` (README-Schritte 2–4). Der Agent gibt niemals selbst Tokens ein.
- [ ] **Schritt 2:** `docker compose up -d --build` ausführen. Erwartet in `docker compose logs bot`: „Bot gestartet“, keine Tracebacks.
- [ ] **Schritt 3:** Der Nutzer sendet `/start` und beantwortet die 6 Fragen. Erwartet: eine Zusammenfassung, dann die Rückstau-Info und höchstens 10 Stellen.
- [ ] **Schritt 4:** `/status` aufrufen. Erwartet: alle 4 Quellen mit Trefferzahl oder „blockiert“. Notiere, welche Quelle über Lightpanda und welche über den Chromium-Fallback lief (aus den Logs).
- [ ] **Schritt 5:** `⭐ Merken` und dann `/gemerkt` prüfen, `👎` prüfen, `/pause` → `/jetzt` → `/weiter` prüfen.
- [ ] **Schritt 6:** Auffälligkeiten beheben, mit einem eigenen Test pro Fehler, und committen: `fix: …`
