<div align="center">

# 📡 Stellenradar

**Telegram-Bot, der stündlich Werkstudenten- und Ausbildungsstellen in deiner Nähe sucht,
bewertet und dir nur Neues meldet.**

[![Tests](https://github.com/memduhtalha/stellenradar/actions/workflows/tests.yml/badge.svg)](https://github.com/memduhtalha/stellenradar/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Docker](https://img.shields.io/badge/docker-compose-2496ED)
![Lizenz: MIT](https://img.shields.io/badge/Lizenz-MIT-green)

*English: self-hosted Telegram bot that searches German job sources hourly for working-student jobs or
apprenticeships near you, ranks them, merges duplicates and only sends new matches.*

</div>

---

## Was er macht

```
🔥 ☁️ Cloud & DevOps
Werkstudent Cloud Engineering (m/w/d)
🏢 Beispiel GmbH · 📍 Düsseldorf (3 km)
📅 vor 2 Std. · Quelle: Arbeitsagentur (auch auf: azubi.de)
🔗 Zur Anzeige
        [ ⭐ Merken ]   [ 👎 Uninteressant ]
```

- 🎯 **Zwei Sucharten** – Werkstudentenstellen (z. B. Cloud, KI, Security) oder Ausbildungsplätze (z. B. Immobilienkaufmann/-frau)
- 📍 **Ort und Umkreis** frei wählbar, Entfernung pro Stelle
- 🧹 **Filtert und bewertet** – passt die Art, der Bereich, die Entfernung? 🔥 für Top-Treffer
- 🔁 **Keine Duplikate** – dieselbe Stelle auf mehreren Portalen kommt nur einmal
- 💬 **Alles in Telegram** – Einrichtung per Buttons, Merkliste, Erinnerungen, Wochenrückblick
- 🔍 **Zum Prüfen** – unsichere Treffer kommen täglich zur Entscheidung, statt still zu verschwinden
- 👥 **Mehrere Personen** – jede mit eigenem Bereich, Zugang per Einladungslink

## Quellen

| Quelle | Standard |
|---|---|
| Bundesagentur für Arbeit (Jobsuche-API) | ✅ an |
| Stellenwerk Düsseldorf · ausbildung.de · AZUBIYO · azubi.de · Firmen-Karriereseiten | ✅ an |
| StepStone · Indeed · LinkedIn | ⛔ aus ([Hinweis](#️-hinweis)) |

Ein- und ausschalten in `config/quellen.yaml`.

## Schnellstart

Du brauchst [Docker](https://docs.docker.com/get-docker/) und ein Telegram-Konto.

```bash
git clone https://github.com/memduhtalha/stellenradar.git && cd stellenradar
cp .env.example .env        # TELEGRAM_TOKEN (von @BotFather) und ALLOWED_USER_ID (von @userinfobot) eintragen
docker compose up -d --build
```

Dann dem Bot in Telegram `/start` schicken und die Fragen beantworten – fertig.

## Befehle

| | |
|---|---|
| `/start` · `/einstellungen` | Einrichten bzw. ändern (Suchart, Ort, Umkreis, Bereiche, Uhrzeiten …) |
| `/jetzt` · `/alle` | Sofort suchen · alle aktuellen Stellen zum Blättern oder als Datei |
| `/gemerkt` · `/pruefen` | Merkliste · unsichere Treffer entscheiden |
| `/status` · `/pause` · `/weiter` | Zustand der Quellen · Benachrichtigungen anhalten/fortsetzen |
| `/einladen` · `/personen` | *(nur Admin)* weitere Person einladen bzw. verwalten |

## Anpassen

| Datei | Wofür |
|---|---|
| `config/kategorien.yaml` | Bereiche und Stichwörter – auch eigene Berufe |
| `config/quellen.yaml` | Quellen an/aus (eigene Abweichungen in `quellen.local.yaml`) |
| `config/firmen.yaml` | Karriereseiten, die bei der Ausbildungssuche beobachtet werden |
| `config/filter.yaml` · `config/bewertung.yaml` | Fachfremde Titel · Punkte und 🔥-Schwelle |

## So funktioniert's

```
stündlich → Quellen parallel abfragen (httpx / Lightpanda, Fallback Chromium)
          → filtern → bewerten → Duplikate zusammenführen → SQLite → Telegram
```

**Stack:** Python · python-telegram-bot · httpx · Playwright + [Lightpanda](https://github.com/lightpanda-io/browser) ·
selectolax · SQLite · Docker Compose

## Entwicklung

```bash
pip install -c constraints.txt -e ".[dev]"
pytest             # Tests laufen offline mit erfundenen Beispielseiten
ruff check src tests
```

## ⚠️ Hinweis

StepStone, Indeed und LinkedIn untersagen automatisierte Abfragen in ihren Nutzungsbedingungen – diese Quellen sind
deshalb standardmäßig aus; Einschalten auf eigene Verantwortung. Der Bot umgeht **keine** Captchas oder
Bot-Schutzmaßnahmen und ist für den privaten Gebrauch mit wenigen Abfragen gedacht.

## Lizenz

[MIT](LICENSE)
