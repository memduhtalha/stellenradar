# Werkstudent-Scraper Düsseldorf – Design

**Stand:** 2026-11-03 · **Status:** Entwurf, wartet auf Freigabe

---

## 1. Worum es geht

### 1.1 Ziel
Ein Tool, das regelmäßig und automatisch **Werkstudentenstellen im Bereich Informatik** rund um **Düsseldorf** auf mehreren Jobportalen findet und **neue Angebote sofort per Telegram** meldet.

### 1.2 Warum
- Gute Werkstudentenstellen sind schnell vergeben. Wer früh reagiert, hat bessere Chancen.
- Mehrere Portale von Hand zu durchsuchen kostet Zeit, und viele Stellen stehen doppelt auf mehreren Portalen.
- Der Nutzer will „die besten Angebote direkt“. Es zählen also **Vollständigkeit** (die großen Portale sind dabei), **Geschwindigkeit** und **Relevanz** (passende Stellen zuerst, Unpassendes aussortiert).

### 1.3 Nutzer
Genau eine Person, nämlich der Besitzer des Tools. Der Bot reagiert nur auf einen festgelegten Telegram-Account.

---

## 2. Ziele, Nicht-Ziele, Anti-Ziele

### 2.1 Ziele
- Stündliche Suche zwischen 7 und 22 Uhr. Das Intervall und die Uhrzeiten sind einstellbar.
- Quellen: Bundesagentur für Arbeit, StepStone, Indeed und LinkedIn (nur die öffentlichen Seiten). Weitere Quellen lassen sich leicht hinzufügen.
- Duplikate über Portale hinweg werden erkannt und nur einmal gemeldet.
- Kategorien lassen sich wählen (siehe 4.2).
- Alle Einstellungen laufen über **Telegram**, mit Fragen und Antwort-Buttons.
- Jede Stelle bekommt eine Relevanz-Punktzahl. Top-Treffer kommen sofort und markiert, der Rest optional als tägliche Sammelnachricht.
- Merkliste und „Uninteressant“ werden per Button gesetzt.
- Läuft zuerst lokal auf dem Windows-PC (WSL + Docker), lässt sich aber ohne Umbau auf einen kleinen Linux-Server umziehen.

### 2.2 Nicht-Ziele (vorerst)
- Mehrere Nutzer
- Automatisch bewerben oder Bewerbungen verwalten
- Web-Oberfläche oder App: Telegram ist die einzige Oberfläche
- Hosting in der Cloud oder auf einem Server: nur vorbereitet, nicht umgesetzt

### 2.3 Anti-Ziele (das wäre ein Fehlschlag, selbst wenn es technisch läuft)
- **Spam:** viele unpassende Meldungen, zum Beispiel Vollzeit-, Senior- oder Nicht-IT-Stellen, oder dieselbe Stelle mehrfach.
- **Stilles Versagen:** Eine Quelle ist kaputt oder blockiert, und der Nutzer merkt es nicht.
- **Konto-Risiko:** Scraping mit dem LinkedIn-Login des Nutzers. Das ist ausdrücklich ausgeschlossen.
- **Umgehen von Schutzmaßnahmen:** Captchas oder Bot-Schutz werden **nicht** umgangen. Blockiert ein Portal, wird diese Quelle für den Lauf übersprungen und gemeldet.
- **Aggressive Last auf den Portalen:** Anfragen bleiben sparsam und langsam getaktet.

---

## 3. Rahmenbedingungen

| Thema | Vorgabe |
|---|---|
| Betriebssystem | Windows 11. Lightpanda läuft nur unter Linux/macOS, deshalb **WSL2 + Docker**. |
| Browser | **Lightpanda** (https://github.com/lightpanda-io/browser), Wunsch des Nutzers. Es ist noch jung, und manche JS-lastigen Seiten rendern unvollständig. Deshalb gibt es einen **Fallback auf Headless-Chromium** pro Quelle. |
| Sprache | **Python** (vom Nutzer gewählt) |
| Rechner | Wenn der PC aus ist, wird nicht gesucht. Nach dem Start holt das Tool den verpassten Lauf sofort nach. |
| Nutzungsbedingungen | StepStone, Indeed und LinkedIn erlauben Scraping laut AGB meist nicht. Das Tool ist für den **privaten Einzelgebrauch** gedacht, mit niedriger Frequenz und ohne Login. Dieses Risiko hat der Nutzer bewusst in Kauf genommen. |

---

## 4. Was das Tool tut

### 4.1 Suche
- **Ort:** Standard ist Düsseldorf, einstellbar.
- **Umkreis:** Standard sind 25 km. Auswahl: 10 / 25 / 40 / 60 km.
- **Remote:** Schalter, Standard ist aus. Wenn er an ist, kommen reine Remote-Stellen aus ganz Deutschland mit, markiert mit „🏠 Remote“.
- **Praktika und Abschlussarbeiten:** Schalter, Standard ist aus.
- **Pflichtfilter:** Die Stelle muss als Werkstudentenstelle erkennbar sein, also „Werkstudent“, „Werkstudentin“, „Werkstudierende“, „Working Student“ oder „studentische Aushilfe“ im Titel oder in der Beschreibung enthalten. Stellen ohne diesen Hinweis werden verworfen, ebenso Stellen mit „Senior“ oder „Vollzeit“ im Titel.
- **Praktika/Abschlussarbeiten-Schalter an** → „Praktikum“, „Pflichtpraktikum“, „Abschlussarbeit“, „Bachelorarbeit“, „Masterarbeit“ gelten zusätzlich als erlaubte Begriffe – in den Suchanfragen *und* im Pflichtfilter. Solche Stellen werden in der Nachricht mit „🎓 Praktikum/Abschlussarbeit“ markiert. *(Entscheidung von Claude)*
- Pro Quelle und Kategorie wird mit „Werkstudent“ plus Stichwörtern der aktiven Kategorien gesucht. Danach wird jede Stelle lokal einer oder mehreren Kategorien zugeordnet.
- **Kategorie ist Pflicht:** Eine Stelle, die zu keiner aktiven Kategorie passt, wird verworfen – auch wenn das Portal sie für die Suche geliefert hat. Alles, was Pflichtfilter und Kategorie besteht, wird gemeldet (sofort oder in der Sammelnachricht); die Punktzahl sortiert nur, sie wirft nichts weg. *(Entscheidung von Claude – verhindert Spam durch „Werkstudent Marketing“ o. Ä.)*
- **Detailseiten:** Gefiltert wird zuerst anhand von Titel und Vorschautext aus der Trefferliste. Nur wenn das nicht reicht (z. B. „Werkstudent“ steht nicht drin, Kategorie unklar), wird die Detailseite geladen – gecacht und mit eigenem Anfrage-Limit pro Quelle und Lauf. *(Entscheidung von Claude – Balance aus Trefferqualität und wenig Last)*

### 4.2 Kategorien
Die Kategorien stehen in einer Konfigurationsdatei (`config/kategorien.yaml`) und lassen sich per Telegram an- und abschalten.

| Kategorie | Standard | Beispiel-Stichwörter |
|---|---|---|
| ☁️ Cloud & DevOps | an | AWS, Azure, GCP, Kubernetes, Docker, Terraform, CI/CD, DevOps |
| 🤖 KI & Data Science | an | KI, AI, Machine Learning, LLM, Data Science, NLP, Deep Learning |
| 🔐 Cyber Security | an | IT-Sicherheit, Security, SOC, Pentest, ISMS, Informationssicherheit |
| 💻 Softwareentwicklung | aus | Backend, Frontend, Fullstack, Java, C#, Python, Web |
| 📊 Data Engineering & BI | aus | SQL, ETL, Power BI, Data Warehouse, Data Engineer |
| 🖧 IT-Infrastruktur & Support | aus | Systemadministration, Netzwerk, IT-Support, Linux |
| 🧪 Testing & QA | aus | Testautomatisierung, QA, Testing |
| 📈 IT-Consulting & SAP | aus | SAP, IT-Beratung, ERP |

### 4.3 Relevanz-Punktzahl
Jede Stelle bekommt eine Punktzahl aus diesen Faktoren:
- Stichwort einer aktiven Kategorie **im Titel** (stark) oder nur in der Beschreibung (schwach)
- **Entfernung** zu Düsseldorf: je näher, desto besser
- **Frische:** Veröffentlichungsdatum, falls bekannt
- Firma wurde früher als „uninteressant“ markiert: starker Abzug

Stellen über der 🔥-Schwelle werden **sofort** gemeldet. Alles darunter landet, je nach Einstellung, ebenfalls sofort oder in einer **täglichen Sammelnachricht** (Standard: 18 Uhr). Die genauen Gewichte legt der Entwickler fest und macht sie in der Konfiguration einstellbar.

### 4.4 Duplikate
Dieselbe Stelle auf mehreren Portalen wird nur einmal gemeldet. Erkannt wird sie über normalisierte **Firma + Titel + Ort**. In der Nachricht steht dann „auch auf: StepStone, Indeed“ mit allen Links. Schon gemeldete Stellen werden nie erneut gemeldet.

### 4.5 Rückstau (erster Start, PC lange aus, nach `/pause`)
Wenn bei einem Lauf mehr als 10 neue Stellen anfallen, weil es der erste Lauf ist, der letzte erfolgreiche Lauf über 24 h zurückliegt oder `/weiter` nach einer Pause kam, gilt:
- Nur die **10 Stellen mit der höchsten Punktzahl** werden einzeln gemeldet, vorweg kommt eine kurze Info wie „📦 Rückstau: 87 neue Stellen, hier die Top 10“.
- Alle übrigen werden **still als „gesehen“** gespeichert und nie gemeldet.
- Danach läuft alles normal weiter.
*(Entscheidung des Nutzers)*

### 4.6 Quellen
| Quelle | Zugriff | Hinweis |
|---|---|---|
| Bundesagentur für Arbeit | offizielle REST-API (`rest.arbeitsagentur.de/jobboerse/jobsuche-service`), reines HTTP | stabil, Basisquelle. Parameter `was`, `wo` und `umkreis` |
| StepStone | Lightpanda (Fallback: Chromium) | |
| Indeed | Lightpanda (Fallback: Chromium) | blockt oft. Bei Captcha die Quelle überspringen und den Status melden |
| LinkedIn | öffentliche Gast-Suche **ohne Login**, bevorzugt per HTTP auf die Gast-Endpunkte, sonst per Browser | sparsam: höchstens 1 Durchlauf pro Stunde, wenige Seiten |

Jede Quelle ist ein eigenes Modul mit derselben Schnittstelle („suche(einstellungen) → Liste von Stellen“). Neue Quellen wie Stellenwerk, Uni-Jobbörsen oder Firmen-Karriereseiten kommen als neues Modul dazu.

**Fehlerverhalten:** Fällt eine Quelle aus (Fehler, Blockade, 0 Treffer bei sonst vielen), läuft der Rest normal weiter. Ist eine Quelle **3 Läufe hintereinander** ausgefallen, schickt der Bot eine Warnung („⚠️ Indeed liefert seit 3 Läufen nichts“). Die Warnung kommt nur einmal und nicht bei jedem Lauf.

---

## 5. Telegram-Bot

### 5.1 Einrichtung beim ersten Start (`/start`)
Der Bot stellt seine Fragen nacheinander, beantwortet wird per Button:
1. **Ort?** [Düsseldorf] oder einen anderen Ort eintippen
2. **Umkreis?** [10 km] [25 km] [40 km] [60 km]
3. **Bereiche?** Kategorien als An/Aus-Buttons (☁️ ✅ / 🤖 ✅ / …) und [Fertig]
4. **Remote-Stellen auch?** [Ja] [Nein]
5. **Praktika und Abschlussarbeiten auch?** [Ja] [Nein]
6. **Nicht-Top-Treffer:** [Sofort] [Tägliche Sammelnachricht]

### 5.2 Befehle
| Befehl | Funktion |
|---|---|
| `/einstellungen` | Menü, um einzelne Punkte aus 5.1 und das Suchintervall zu ändern |
| `/jetzt` | sofort eine Suche starten |
| `/pause` · `/weiter` | Benachrichtigungen aus und wieder an (die Suche läuft weiter, gemeldet wird nach `/weiter`) |
| `/status` | letzter Lauf, nächster Lauf, Zustand jeder Quelle, Anzahl der Treffer |
| `/gemerkt` | Merkliste anzeigen |
| `/hilfe` | Befehlsübersicht |

Die Befehle werden beim Bot registriert und erscheinen deshalb im Telegram-Menü.

### 5.3 Nachricht pro Stelle
```
🔥 ☁️ Cloud & DevOps
Werkstudent Cloud Engineering (m/w/d)
🏢 Beispiel GmbH · 📍 Düsseldorf (3 km)
📅 vor 2 Std. · Quelle: StepStone (auch auf: Indeed)
🔗 Link

[⭐ Merken]  [👎 Uninteressant]
```
- **⭐ Merken** setzt die Stelle auf die Merkliste.
- **👎 Uninteressant** blendet die Stelle aus. Weitere Stellen derselben Firma bekommen Punktabzug, werden aber nicht komplett gesperrt.

### 5.4 Zugriffsschutz
Die erlaubte Telegram-User-ID steht in der `.env`. Nachrichten von allen anderen werden ignoriert.

---

## 6. Wie es gebaut wird

### 6.1 Erwogene Ansätze
| Ansatz | Vor- und Nachteile | Entscheidung |
|---|---|---|
| **Python** (python-telegram-bot, httpx, Playwright per CDP zu Lightpanda) | Python ist im IT-Umfeld am verbreitetsten, mit vielen Scraping-Bibliotheken, und lässt sich gut mit KI-Unterstützung erweitern. Die Lightpanda-Doku zeigt eher Node, CDP funktioniert aber genauso. | **Gewählt** (Nutzer) |
| Node.js / TypeScript (grammY, Puppeteer) | entspricht Lightpandas offiziellem Weg, braucht aber mehr Setup | verworfen |
| Möglichst wenig Browser (HTTP, wo es geht) | schnell und robust, aber pro Portal eigener Code | **als Taktik in den Python-Ansatz übernommen:** Arbeitsagentur und LinkedIn-Gast per HTTP, Browser nur, wo nötig |

### 6.2 Aufbau
```
┌──────────────────────── docker compose ─────────────────────────┐
│                                                                  │
│  bot (Python, ein Prozess)                 lightpanda            │
│  ├─ Telegram-Bot (Befehle, Buttons)  ──CDP──►  (Container)        │
│  ├─ Zeitplaner (stündlich 7–22 Uhr)                              │
│  ├─ Quellen: arbeitsagentur · stepstone · indeed · linkedin      │
│  ├─ Filter → Kategorien → Punktzahl → Duplikate                  │
│  └─ SQLite (data/jobs.db)                  chromium (Fallback)   │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```
- **Ein einziger Python-Prozess** mit asyncio: Der Bot hört dauerhaft zu, ein eingebauter Zeitplaner (zum Beispiel die JobQueue von python-telegram-bot) löst die Suchen aus.
- **Lightpanda** läuft als eigener Container (offizielles Docker-Image) mit CDP-Server. Playwright verbindet sich per `connect_over_cdp`.
- **Fallback:** Playwright startet bei Bedarf sein eigenes Headless-Chromium im Bot-Container.
- **SQLite** speichert die Stellen (inklusive „schon gemeldet“), die Merkliste, die als uninteressant markierten Firmen, die Einstellungen und den Zustand jeder Quelle. Die Datei liegt in einem Docker-Volume (`data/`) und überlebt Neustarts und den Umzug auf einen Server.
- **Geheimnisse** wie Bot-Token und erlaubte User-ID stehen in `.env`. Diese Datei kommt nicht ins Git, dafür gibt es eine `.env.example`.

### 6.3 Ordnerstruktur (Vorschlag)
```
werkstudent-scraper/
├─ docs/design/            ← dieses Dokument
├─ config/kategorien.yaml  ← Kategorien & Stichwörter
├─ src/werkstudent/
│  ├─ bot/                 ← Telegram: Befehle, Dialoge, Nachrichten
│  ├─ quellen/             ← ein Modul pro Portal
│  ├─ verarbeitung/        ← Filter, Kategorien, Punktzahl, Duplikate
│  ├─ speicher/            ← SQLite
│  └─ main.py
├─ tests/
├─ docker-compose.yml
├─ Dockerfile
├─ .env.example
└─ README.md               ← Einrichtung Schritt für Schritt (WSL, Docker, Bot anlegen)
```

### 6.4 Betrieb
- Läuft in **WSL2 + Docker** auf dem Windows-PC und startet automatisch mit Docker (`restart: unless-stopped`).
- Für den späteren Umzug auf einen Server dieselbe `docker-compose.yml` verwenden und den Ordner `data/` mitnehmen.
- Das README erklärt Schritt für Schritt: WSL und Docker installieren, Bot bei @BotFather anlegen, eigene User-ID herausfinden, `.env` ausfüllen, starten.

---

## 7. Was dem Entwickler überlassen bleibt
- Konkrete Selektoren und URL-Parameter pro Portal
- Genaue Gewichte der Punktzahl und die 🔥-Schwelle (einstellbar in der Konfiguration)
- Genaue Regeln zur Normalisierung bei der Duplikaterkennung
- Pausen zwischen Anfragen und Anzahl der Ergebnisseiten pro Quelle (sparsam halten)
- Entfernungsberechnung: aus API-Daten, wo vorhanden, sonst Geocoding des Orts mit einer kleinen Cache-Tabelle
- Teststrategie: gespeicherte Beispielseiten pro Portal als Fixtures, damit die Tests nicht live scrapen
