from pathlib import Path

from werkstudent.config import load_categories, load_scoring


def test_load_categories_reads_all_eight():
    cats = [c for c in load_categories(Path("config/kategorien.yaml")) if c.art == "werkstudent"]
    assert [c.key for c in cats] == ["cloud", "ki", "security", "software", "data", "infra", "qa", "consulting"]
    assert {c.key for c in cats if c.default_on} == {"cloud", "ki", "security"}
    assert all(c.search_terms and c.keywords for c in cats)


def test_load_scoring_defaults_when_keys_missing(tmp_path):
    p = tmp_path / "b.yaml"
    p.write_text("top_threshold: 7\n")
    s = load_scoring(p)
    assert s.top_threshold == 7 and s.title_keyword == 3


from werkstudent.config import load_title_excludes


def test_load_title_excludes():
    ex = load_title_excludes(Path("config/filter.yaml"))
    assert {"marketing", "vertrieb", "recruiting", "controlling"} <= set(ex)
    assert all(e == e.lower() for e in ex)


def test_categories_have_art_and_immobilien_is_ausbildung():
    cats = {c.key: c for c in load_categories(Path("config/kategorien.yaml"))}
    assert cats["cloud"].art == "werkstudent"
    imm = cats["immobilien"]
    assert imm.art == "ausbildung" and imm.default_on
    assert "immobilienkaufmann" in imm.keywords



from werkstudent.config import load_enabled_sources


def test_public_default_disables_tos_sensitive_sources():
    enabled = load_enabled_sources(Path("config"), local_name="gibt-es-nicht.yaml")
    assert enabled["arbeitsagentur"] and enabled["stellenwerk"] and enabled["firmen"]
    assert not enabled["stepstone"] and not enabled["indeed"] and not enabled["linkedin"]


def test_local_file_overrides_defaults(tmp_path):
    (tmp_path / "quellen.yaml").write_text("stepstone: false" + chr(10) + "arbeitsagentur: true" + chr(10), encoding="utf-8")
    (tmp_path / "quellen.local.yaml").write_text("stepstone: true" + chr(10), encoding="utf-8")
    enabled = load_enabled_sources(tmp_path)
    assert enabled == {"stepstone": True, "arbeitsagentur": True}
