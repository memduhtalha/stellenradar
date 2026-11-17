"""Erzeugt die Test-Beispielseiten unter tests/fixtures/ – mit erfundenen Firmen, Stellen und IDs.

Die Seiten bilden nur den Aufbau nach, den die Parser brauchen (CSS-Selektoren, data-Attribute),
und enthalten keine Inhalte der echten Portale. Aufruf: python scripts/beispieldaten_erzeugen.py
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
HEAD = '<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Beispiel</title></head><body>'
TAIL = "</body></html>"

ORTE = ["Düsseldorf", "Neuss", "Ratingen", "Hilden", "Krefeld", "Mönchengladbach", "Duisburg", "Meerbusch"]
BEREICHE = ["Cloud", "DevOps", "KI", "Data", "IT-Security", "Backend", "Support", "Netzwerk", "QA", "SAP"]


def write(name: str, html: str) -> None:
    (OUT / name).write_bytes(html.encode("utf-8"))


def stepstone() -> None:
    cards = []
    for i in range(8):
        jid = 10000001 + i
        cards.append(
            f'<article data-at="job-item" id="job-item-{jid}">'
            f'<a data-at="job-item-title" href="https://www.stepstone.de/stellenangebote--Werkstudent-'
            f'{BEREICHE[i]}-{jid}-inline.html?rltr=1">Werkstudent {BEREICHE[i]} (m/w/d)</a>'
            f'<span data-at="job-item-company-name">Beispielfirma {i} GmbH</span>'
            f'<span data-at="job-item-location">{ORTE[i]}</span>'
            f'<div data-at="jobcard-content">Du unterstützt unser Team im Bereich {BEREICHE[i]}.</div>'
            f'<time datetime="2026-10-2{i}T08:00:00Z">vor {i + 1} Tagen</time></article>'
        )
    cards.insert(1, cards[0])  # dieselbe Anzeige doppelt (gesponserter Platz) – Parser muss zusammenfassen
    write("stepstone_search.html", HEAD + '<div data-at="unified-resultlist">' + "".join(cards) + "</div>" + TAIL)
    text = ("Einleitung: Als Werkstudent unterstützt du unser Team im direkten Kontakt mit Kunden. "
            "Deine Aufgaben: Betreuung unserer Cloud-Plattform, Pflege von Dokumentation, Automatisierung "
            "wiederkehrender Abläufe. Dein Profil: eingeschriebene Studentin oder eingeschriebener Student, "
            "Interesse an Technik, sorgfältige Arbeitsweise. Wir bieten flexible Arbeitszeiten und Homeoffice.")
    write("stepstone_detail.html", HEAD + f'<div data-at="job-ad-content"><p>{text}</p></div>' + TAIL)


def indeed() -> None:
    orte = ["Hybrides Arbeiten in 40210 Düsseldorf", "40882 Ratingen", "41460 Neuss", "Homeoffice in Düsseldorf",
            "47798 Krefeld", "40721 Hilden", "47051 Duisburg", "40667 Meerbusch", "41061 Mönchengladbach",
            "40210 Düsseldorf"]
    cards = "".join(
        f'<li><div class="job_seen_beacon"><h2><a data-jk="a{i:015d}" href="/rc/clk?jk=a{i:015d}">'
        f"Werkstudent {BEREICHE[i]} (m/w/d)</a></h2>"
        f'<span data-testid="company-name">Musterbetrieb {i} AG</span>'
        f'<div data-testid="text-location">{orte[i]}</div></div></li>'
        for i in range(10)
    )
    write("indeed_search.html", HEAD + f'<div id="mosaic-provider-jobcards"><ul>{cards}</ul></div>' + TAIL)


def linkedin() -> None:
    cards = "".join(
        f'<li><div class="base-card" data-entity-urn="urn:li:jobPosting:{4000000001 + i}">'
        f'<a class="base-card__full-link" href="https://de.linkedin.com/jobs/view/werkstudent-{i}-{4000000001 + i}'
        f'?refId=abc&amp;trk=public_jobs">Werkstudent {BEREICHE[i]}</a>'
        f'<h3 class="base-search-card__title">Werkstudent {BEREICHE[i]} (m/w/d)</h3>'
        f'<h4 class="base-search-card__subtitle">{"Beispiel Consulting GmbH" if i == 0 else f"Firma {i}"}</h4>'
        f'<span class="job-search-card__location">{ORTE[i % len(ORTE)]}, North Rhine-Westphalia, Germany</span>'
        f'<time datetime="2026-10-{20 + i}">vor {i + 1} Tagen</time></div></li>'
        for i in range(10)
    )
    write("linkedin_search.html", HEAD + f"<ul>{cards}</ul>" + TAIL)


def arbeitsagentur() -> None:
    items = [
        {"referenznummer": f"10000-1000000{i}-S", "stellenangebotsTitel": f"Werkstudent (m/w/d) {t}",
         "firma": f"Beispielwerk {i} GmbH", "alleBerufe": [b],
         "stellenlokationen": [{"adresse": {"plz": p, "ort": o}, "breite": lat, "laenge": lon}],
         "datumErsteVeroeffentlichung": "2026-10-2" + str(i)}
        for i, (t, b, p, o, lat, lon) in enumerate([
            ("Software Testing", "Softwaretester/in", "40210", "Düsseldorf", 51.22, 6.78),
            ("IT-Support", "IT-Supporter/in", "47798", "Krefeld", 51.33, 6.56),
            ("Digitale Transformation", "Projektassistent/in", "41460", "Neuss", 51.20, 6.69),
        ])
    ]
    (OUT / "arbeitsagentur_search.json").write_bytes(
        json.dumps({"maxErgebnisse": 3, "page": 1, "size": 50, "ergebnisliste": items},
                   ensure_ascii=False, indent=1).encode("utf-8"))


def stellenwerk() -> None:
    nav = '<a href="/duesseldorf">Jobs</a><a href="/duesseldorf/events">Veranstaltungen</a>'
    jobs = [("Werkstudent Robotik gesucht !", "Musterrobotik GmbH", "Herne, Nordrhein-Westfalen, Deutschland",
             "vor 5 Tagen", 200001)]
    jobs.append(("Consultant (m/w/d) Informatik oder Mathematik", "Beispielberatung GmbH",
                 "Berlin, Düsseldorf, Frankfurt am Main, überall in Deutschland", "vor 2 Tagen", 200002))
    jobs += [(f"Werkstudent {BEREICHE[i]} (m/w/d)", f"Hochschulpartner {i} GmbH",
              f"{ORTE[i % len(ORTE)]}, Nordrhein-Westfalen, Deutschland", f"vor {i} Tagen", 200003 + i)
             for i in range(8)]
    cards = "".join(
        f'<a href="/duesseldorf/stelle-{n}-261014-{jid}" target="_blank" class="flex flex-col">'
        f"<p>{title}</p><p>{co}<span>·</span>{loc}</p>"
        f"<span>Studierendenjob</span><span>Homeoffice möglich</span><p>{age}</p></a>"
        for n, (title, co, loc, age, jid) in enumerate(jobs)
    )
    write("stellenwerk_search.html", HEAD + nav + f"<section>{cards}</section>" + TAIL)
    ld = {"@context": "https://schema.org", "@type": "JobPosting", "title": "Werkstudent Automatisierung",
          "description": "<p><p><strong>Bau Automatisierungen und sieh am nächsten Tag, was sie bewirken</strong>"
                         "</p><p>&nbsp;</p><p>Wir sind ein kleines Beispielunternehmen.</p></p>",
          "datePosted": "2026-10-12T11:42:22Z", "hiringOrganization": {"@type": "Organization", "name": "Muster UG"}}
    write("stellenwerk_detail.html",
          f'<html><head><script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script></head>'
          "<body></body></html>")


def ausbildungde() -> None:
    firmen = [("Rheinblick Versicherung AG", "41460 Neuss")] + [
        (f"Wohnungsbau Muster {i} eG", f"4{i}000 {ORTE[i % len(ORTE)]}") for i in range(1, 10)]
    cards = "".join(
        f'<article><a href="/stellen/ausbildung-immobilienkauffrau-mann-bei-muster-{i}-'
        f'0000000{i}-aaaa-bbbb-cccc-00000000000{i}/">'
        f'<h3 data-testid="jp-title">Ausbildung Immobilienkauffrau/-mann (m/w/d)</h3>'
        f'<h4 data-testid="jp-customer">bei{co}</h4>'
        f'<span data-testid="jp-branches">{ort}</span>'
        f'<span data-testid="jp-starting-at">01.08.2027</span><span>1 Platz</span></a></article>'
        for i, (co, ort) in enumerate(firmen)
    )
    profil = ('<article><div data-testid="profession-title">Immobilienkauffrau/-mann</div>'
              "<span>Zum Berufsprofil</span></article>")  # Karte ohne Stelle – muss ignoriert werden
    write("ausbildungde_search.html", HEAD + profil + cards + TAIL)


def azubiyo() -> None:
    firmen = [("Musterwohnen Krefeld AG", "47798 Krefeld")] + [
        (f"Immobilien Beispiel {i} GmbH", f"4{i % 10}000 {ORTE[i % len(ORTE)]}") for i in range(1, 15)]
    cards = "".join(
        f'<li><div class="job-search-job-offer-teaser"><a href="/stellenanzeigen/ausbildung-immobilienkaufmann-'
        f'{i}_muster_{i:04d}abcd/"><span class="h3">Ausbildung Immobilienkaufmann/-frau (m/w/d) {i}</span>'
        f'<span class="text-secondary">{co}</span>'
        f'<span class="text-placeholder">01.08.2027</span><span class="text-placeholder">{ort}</span>'
        f'<span class="text-placeholder">1.200 - 1.400 € pro Monat</span></a></div></li>'
        for i, (co, ort) in enumerate(firmen)
    )
    write("azubiyo_search.html", HEAD + f"<ul>{cards}</ul>" + TAIL)


def azubide() -> None:
    jobs = [(90000001, "Ausbildung Immobilienkaufmann/-frau (m/w/d) in Krefeld 2027", "Musterwohnen Krefeld AG",
             "47798", "Krefeld", "ausbildung-immobilienkaufmann-frau-m-w-d-in-krefeld-2027"),
            (90000002, "Ausbildung als Immobilienkauffrau/-mann (m/w/d)", "Beispielbau eG", "41460", "Neuss",
             "ausbildung-als-immobilienkauffrau-mann-m-w-d"),
            (90000003, "Ausbildung zum Immobilienkaufmann (m/w/d)", "Muster Immobilien GmbH", "40210", "Düsseldorf",
             "ausbildung-zum-immobilienkaufmann-m-w-d")]
    cards = "".join(
        f'<a href="/ausbildungsplatz/{jid}-s-{slug}"><h2>{title}</h2>'
        f'<span class="text-secondary">{co}</span><svg><title>Beginn</title></svg><span>01.08.2027</span>'
        f"<svg><title>Standort</title></svg><span><span>{plz}</span><span>{ort}</span></span>"
        f"<span>Neu</span></a>"
        for jid, title, co, plz, ort, slug in jobs
    )
    write("azubide_search.html", HEAD + cards + TAIL)


def firma() -> None:
    body = (
        "<nav><a href='/karriere/ausbildung'>Ausbildung</a></nav>"
        "<h1>Ausbildung</h1>"
        "<h2>Ausbildung zur/zum Immobilienkauffrau/-mann (m/w/d)</h2>"
        "<h3>So läuft deine Ausbildung ab</h3>"
        "<p>Am 1. August 2027 geht es los: drei Jahre Praxis im Unternehmen, Theorie im Blockunterricht.</p>"
        "<h3>Starte in die Immobilienwelt – mit einer Ausbildung, die wirklich etwas bewegt:</h3>"
        "<p>Wir freuen uns auf deine Bewerbung. Bitte sende sie bis zum 29.12.2026 per E-Mail.</p>"
    )
    write("firma_beispiel.html", HEAD + body + TAIL)


if __name__ == "__main__":
    for f in (stepstone, indeed, linkedin, arbeitsagentur, stellenwerk, ausbildungde, azubiyo, azubide, firma):
        f()
    print("Beispielseiten erzeugt in", OUT)
