from datetime import date

from app.ingestion.parser_lexuz import ARTICLE_HEAD_RE, effective_dates_in, parse_lexuz_html
from app.ingestion.sources import get_source
from app.ingestion.validate import validate_parsed
from tests.conftest import fixture_html

TODAY = date(2026, 11, 11)


def consumer():
    return parse_lexuz_html(fixture_html("lexuz_consumer_excerpt.html"), as_of=TODAY)


def labor():
    return parse_lexuz_html(fixture_html("lexuz_labor_excerpt.html"), as_of=TODAY)


def test_document_metadata_is_read_from_page():
    d = consumer()
    assert d.title == "Isteʼmolchilarning huquqlarini himoya qilish toʻgʻrisida"
    assert d.adoption_date == date(1996, 4, 26)
    assert d.doc_number == "221-I"
    assert d.entry_into_force_date == date(1996, 5, 17)
    assert d.revision_label == "02.02.2026"


def test_missing_metadata_stays_empty_instead_of_guessed():
    d = labor()
    assert d.doc_number is None  # the Labor Code page header prints no number
    assert d.adoption_date == date(2022, 10, 28)  # from the page <title>
    assert d.entry_into_force_date == date(2023, 4, 30)


def test_article_labels_titles_and_real_anchors():
    d = consumer()
    labels = [a.label for a in d.articles]
    assert labels == ["1", "2", "3", "4", "12¹", "14"]
    a = d.articles[4]
    assert a.title.startswith("Oldi-sotdi shartnomasi boʻyicha tovarni topshirish")
    assert a.anchor == "-7674463"
    assert all(x.anchor and x.anchor.lstrip("-").isdigit() for x in d.articles)


def test_superscript_label_is_kept_as_string():
    m = ARTICLE_HEAD_RE.match("12¹-modda. Oldi-sotdi")
    assert m and m["label"] == "12¹"


def test_heading_context_and_paragraphs():
    d = labor()
    a = {x.label: x for x in d.articles}["130"]
    assert a.title == "Dastlabki sinov muddati"
    assert "1-bob" not in a.heading_context  # context is the article's own chapter, not the first one
    assert a.heading_context.startswith("MAXSUS QISM")
    assert len(a.paragraphs) >= 2
    assert a.text.count("\n") == len(a.paragraphs) - 1


def test_navigation_comments_and_widgets_are_not_text():
    for d in (consumer(), labor()):
        blob = "\n".join(a.text + " ".join(a.notes) for a in d.articles)
        assert "NAVIGATION MENU" not in blob
        assert "Аудиони тинглаш" not in blob  # per-element widget labels
        assert "LexUZ sharhi" not in blob  # editorial comments
        assert "OKOZ" not in blob  # classifier tags


def test_amendment_notes_are_attached_to_their_article():
    d = consumer()
    a = {x.label: x for x in d.articles}["12¹"]
    assert any("OʻRQ-1078" in n for n in a.notes)
    assert a.future_effective_dates == []  # entered into force 2025-11-02 < 2026-11-11


def test_effective_date_phrasings():
    assert effective_dates_in("... — 2022-yil 19-apreldan kuchga kiradi)") == [date(2022, 4, 19)]
    assert effective_dates_in("... 0682-son. Kuchga kirish sanasi — 2025-yil 2-noyabr)") == [date(2025, 11, 2)]
    assert effective_dates_in("hech qanday sana yo'q") == []


def test_future_amendment_is_flagged_synthetic():
    """Synthetic: a note with a future entry-into-force date is injected."""
    html = fixture_html("lexuz_consumer_excerpt.html").replace(
        "Kuchga kirish sanasi — 2025-yil 2-noyabr", "Kuchga kirish sanasi — 2027-yil 1-yanvar"
    )
    d = parse_lexuz_html(html, as_of=TODAY)
    a = {x.label: x for x in d.articles}["12¹"]
    assert a.future_effective_dates == ["2027-01-01"]


def test_missing_container_yields_no_articles():
    d = parse_lexuz_html("<html><body><div id='other'>x</div></body></html>", as_of=TODAY)
    assert d.articles == [] and d.warnings


def test_gate_rejects_cyrillic_body_synthetic():
    """Synthetic: Cyrillic text swapped into a Latin page must be rejected."""
    d = consumer()
    d.articles[0].paragraphs = ["Ушбу Қонунда қуйидаги тушунчалар қўлланилади"]
    rep = validate_parsed(d, _spec(min_articles=3), previous_labels=None, as_of=TODAY)
    assert rep.outcome == "rejected"
    assert any("Cyrillic" in e for e in rep.errors)


def test_gate_requires_minimum_article_count():
    rep = validate_parsed(consumer(), get_source("istemolchilar-huquqlari"), previous_labels=None, as_of=TODAY)
    assert rep.outcome == "rejected"  # excerpt has 6 < 25 articles


def test_gate_needs_review_for_future_amendment_and_mass_removal():
    d = consumer()
    d.articles[1].future_effective_dates = ["2027-01-01"]
    rep = validate_parsed(d, _spec(min_articles=3), previous_labels=None, as_of=TODAY)
    assert rep.outcome == "needs_review"
    prev = {str(i) for i in range(1, 30)}
    rep2 = validate_parsed(consumer(), _spec(min_articles=3), previous_labels=prev, as_of=TODAY)
    assert rep2.outcome == "needs_review"


def test_gate_accepts_clean_parse():
    rep = validate_parsed(consumer(), _spec(min_articles=3), previous_labels=None, as_of=TODAY)
    assert rep.outcome == "ok", rep.to_dict()


def _spec(min_articles: int):
    from dataclasses import replace

    return replace(get_source("istemolchilar-huquqlari"), min_articles=min_articles)
