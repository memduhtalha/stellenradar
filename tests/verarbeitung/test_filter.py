from pathlib import Path

from werkstudent.config import load_categories
from werkstudent.verarbeitung.filter import classify_kind, is_excluded_title, match_categories

CATS = {c.key: c for c in load_categories(Path("config/kategorien.yaml"))}


def test_kind_werkstudent_variants():
    for t in ["Werkstudentin Cloud", "Working Student AI", "Werkstudierende IT-Security"]:
        assert classify_kind(t, internships=False) == "werkstudent", t


def test_kind_praktikum_only_when_enabled():
    assert classify_kind("Pflichtpraktikum DevOps", internships=False) is None
    assert classify_kind("Pflichtpraktikum DevOps", internships=True) == "praktikum"


def test_kind_none_for_fulltime():
    assert classify_kind("Cloud Engineer (m/w/d)", internships=True) is None


def test_excluded_title():
    assert is_excluded_title("Senior Werkstudent") is True
    assert is_excluded_title("Werkstudent Security") is False


def test_short_keyword_whole_word():
    keys, _, _ = match_categories("Werkstudent KI", "", [CATS["ki"]])
    assert keys == ["ki"]
    keys, _, _ = match_categories("Werkstudent Marketing Kita-Verwaltung", "", [CATS["ki"]])
    assert keys == []


def test_match_counts_title_vs_text():
    assert match_categories("Werkstudent AWS", "Wir nutzen Kubernetes", [CATS["cloud"]]) == (["cloud"], 1, 0)


from werkstudent.verarbeitung.filter import is_off_topic

EXCLUDES = ["marketing", "vertrieb", "sales", "hr", "recruiting", "controlling"]


def test_text_only_match_needs_two_keywords():
    assert match_categories("Werkstudent Team", "Wir nutzen auch KI.", [CATS["ki"]])[0] == []
    assert match_categories("Werkstudent Team", "KI und Machine Learning im Alltag", [CATS["ki"]]) == (["ki"], 0, 1)


def test_off_topic_title_excluded():
    assert is_off_topic("Werkstudent SEO & Online Marketing (m/w/d)", EXCLUDES, [CATS["ki"]])
    assert is_off_topic("Werkstudent HR Recruiting", EXCLUDES, [CATS["ki"]])


def test_off_topic_kept_when_title_has_it_keyword():
    assert not is_off_topic("Werkstudent Marketing Automation mit KI", EXCLUDES, [CATS["ki"]])
    assert not is_off_topic("Werkstudent Cloud", EXCLUDES, [CATS["cloud"]])
    assert not is_off_topic("Werkstudent Shrink", EXCLUDES, [CATS["cloud"]])  # „hr“ nur als ganzes Wort


def test_off_topic_only_matches_word_start():
    assert not is_off_topic("Werkstudent Berechtigungsmanagement", ["recht"], [CATS["ki"]])
    assert is_off_topic("Werkstudent Rechtsabteilung", ["recht"], [CATS["ki"]])


def test_kind_ausbildung():
    for t in ["Ausbildung zum Immobilienkaufmann (m/w/d) 2027", "Azubi Immobilien", "Auszubildende/r Immobilienkauffrau"]:
        assert classify_kind(t, internships=False, art="ausbildung") == "ausbildung", t
    assert classify_kind("Werkstudent Immobilien", internships=False, art="ausbildung") is None
    assert classify_kind("Ausbildung Immobilienkaufmann", internships=False, art="werkstudent") is None


def test_immobilien_category_matches():
    keys, title_hits, _ = match_categories("Ausbildung Immobilienkaufmann (m/w/d)", "", [CATS["immobilien"]])
    assert keys == ["immobilien"] and title_hits >= 1


from werkstudent.verarbeitung.filter import weak_categories


def test_weak_categories_counts_single_text_hit():
    assert weak_categories("Werkstudent Team", "Du unterstützt bei Kubernetes", [CATS["cloud"], CATS["ki"]]) == ["cloud"]
    assert weak_categories("Werkstudent Cloud", "", [CATS["cloud"]]) == ["cloud"]
    assert weak_categories("Werkstudent Einkauf", "Bestellungen prüfen", [CATS["cloud"]]) == []
