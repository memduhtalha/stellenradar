from werkstudent.modelle import Job
from werkstudent.verarbeitung.duplikate import dedupe_key, normalize_company


def _job(title, company, location):
    return Job(source="x", source_id="1", title=title, company=company, location=location, url="u")


def test_dedupe_key_ignores_gender_tags_legal_forms_and_districts():
    a = _job("Werkstudent Cloud (m/w/d)", "Beispiel GmbH & Co. KG", "Düsseldorf-Bilk")
    b = _job("Werkstudent Cloud (w/m/d)", "Beispiel GmbH", "Düsseldorf")
    c = _job("Werkstudent Security", "Beispiel GmbH", "Düsseldorf")
    assert dedupe_key(a) == dedupe_key(b)
    assert dedupe_key(a) != dedupe_key(c)


def test_dedupe_key_tolerates_company_spelling_across_portals():
    # echte Fälle aus einem Probelauf: Indeed und LinkedIn schreiben die Firma unterschiedlich
    a = _job("Working Student (f/m/d) - SAP Enterprise Architect", "SAP IT Business Systeme", "Ratingen")
    b = _job("Working Student (f/m/d) - SAP Enterprise Architect", "SAP", "Ratingen, North Rhine-Westphalia, Germany")
    c = _job("Werkstudent AI Hub (m/w/d)", "Peek & Cloppenburg B.V. & Co. KG", "Düsseldorf")
    d = _job("Werkstudent AI Hub (m/w/d)", "Peek & Cloppenburg* Düsseldorf", "Düsseldorf")
    assert dedupe_key(a) == dedupe_key(b)
    assert dedupe_key(c) == dedupe_key(d)


def test_normalize_company():
    assert normalize_company("Beispiel GmbH") == "beispiel"
    assert normalize_company("ACME Deutschland AG") == "acme deutschland"


from werkstudent.verarbeitung.duplikate import company_token, normalize_city, normalize_title


def test_gender_variants_without_parentheses():
    base = normalize_title("Werkstudent Cloud (m/w/d)")
    for t in ["Werkstudent Cloud m/w/d", "Werkstudent/in Cloud (w/m/div.)", "Werkstudent*in Cloud (gn)",
              "Werkstudent:in Cloud - m/w/d", "Werkstudent (all genders) Cloud"]:
        assert normalize_title(t).replace("werkstudent ", "werkstudent ", 1) == base, t


def test_city_strips_postcode():
    assert normalize_city("40210 Düsseldorf") == "düsseldorf"
    assert normalize_city("Düsseldorf, North Rhine-Westphalia, Germany") == "düsseldorf"


def test_legal_forms_only_whole_words():
    assert company_token("Agentur Müller GmbH") == "agentur"
    assert company_token("SEW Eurodrive") == "sew"


def test_generic_first_word_uses_two_words():
    assert company_token("Deutsche Bank AG") != company_token("Deutsche Telekom AG")
    assert company_token("Stadtwerke Düsseldorf AG") != company_token("Stadtwerke Neuss GmbH")
    assert company_token("Deutsche Telekom IT GmbH") == company_token("Deutsche Telekom")


def test_city_ignores_more_places_suffix():
    assert normalize_city("Düsseldorf + 2 weitere") == "düsseldorf"
