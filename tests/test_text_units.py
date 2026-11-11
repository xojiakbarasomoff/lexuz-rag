"""Chunking, Uzbek normalization, article references, fusion."""

import uuid

from app.ingestion.chunker import chunk_article
from app.retrieval.normalize import (
    cyrillic_to_latin,
    normalize_for_search,
    query_variants,
    unify_apostrophes,
)
from app.retrieval.search import Candidate, article_refs, build_tsquery, rrf_fuse


def _chunks(paragraphs, **kw):
    return chunk_article(
        doc_short_name="Mehnat kodeksi",
        label="130",
        title="Dastlabki sinov muddati",
        heading_context="MAXSUS QISM › 13-bob",
        paragraphs=paragraphs,
        **kw,
    )


def test_short_article_is_one_chunk_with_header():
    cs = _chunks(["Sinov muddati uch oydan oshmasligi kerak."])
    assert len(cs) == 1
    assert cs[0].embed_text.startswith("Mehnat kodeksi. 130-modda. Dastlabki sinov muddati\nMAXSUS QISM")
    assert cs[0].text == "Sinov muddati uch oydan oshmasligi kerak."


def test_long_article_splits_on_paragraph_boundaries_with_overlap():
    pars = [f"{i}-xatboshi. " + ("matn " * 60).strip() for i in range(8)]  # ~310 chars each
    cs = _chunks(pars, max_chars=1000, overlap_paragraphs=1, overlap_max_chars=400)
    assert len(cs) > 1
    for c in cs:
        assert c.char_len <= 1000
        assert all(line in pars for line in c.text.split("\n"))  # never cuts a paragraph
        assert "130-modda" in c.embed_text
    # overlap: last paragraph of chunk k is first of chunk k+1
    assert cs[0].text.split("\n")[-1] == cs[1].text.split("\n")[0]
    assert {p for c in cs for p in c.text.split("\n")} == set(pars)


def test_single_overlong_paragraph_is_split_on_sentences():
    par = " ".join(f"Bu {i}-gap bo'lib, ancha uzun matnni tashkil etadi." for i in range(80))
    cs = _chunks([par], max_chars=500, overlap_paragraphs=0)
    assert len(cs) > 3 and all(c.char_len <= 500 for c in cs)


def test_chunk_hash_is_stable_and_content_based():
    a, b = _chunks(["X matn."]), _chunks(["X matn."])
    assert a[0].content_hash == b[0].content_hash
    assert _chunks(["Y matn."])[0].content_hash != a[0].content_hash


def test_apostrophe_variants_normalize_identically():
    variants = ["boʻshatish", "bo'shatish", "bo‘shatish", "bo’shatish", "bo`shatish", "boshatish"]
    assert len({normalize_for_search(v) for v in variants}) == 1
    assert unify_apostrophes("oʻz") == "o'z"


def test_original_text_untouched_by_query_variants():
    q = "Меҳнат шартномаси қачон бекор қилинади?"
    v = query_variants(q)
    assert v[0] == q
    assert v[1] == "Mehnat shartnomasi qachon bekor qilinadi?"


def test_cyrillic_transliteration_special_letters():
    assert cyrillic_to_latin("ўқиш ғишт ҳақ ёз юқори янги") == "o'qish g'isht haq yoz yuqori yangi"
    assert cyrillic_to_latin("Ерга етказиб") == "Yerga yetkazib"


def test_article_references_in_questions():
    assert article_refs("Mehnat kodeksining 130-moddasi nima deydi?") == ["130"]
    assert article_refs("12¹-modda haqida") == ["12¹"]
    assert article_refs("12-1 modda haqida") == ["12¹"]
    assert article_refs("sinov muddati") == []


def test_tsquery_drops_stopwords_and_uses_prefixes():
    q = build_tsquery("Sinov muddati davomida ishdan boʻshash mumkinmi?")
    assert "mumkinmi" not in q
    assert "sinov:*" in q and "muddat:*" in q


def test_rrf_fusion_dedupes_by_article():
    a1, a2, a3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    c = {n: uuid.uuid4() for n in "abcde"}
    sem = [Candidate(c["a"], a1, 0), Candidate(c["b"], a2, 0), Candidate(c["c"], a1, 1)]
    lex = [Candidate(c["b"], a2, 0), Candidate(c["d"], a3, 0), Candidate(c["c"], a1, 1)]
    scores, chunks = rrf_fuse([sem, lex], k=60)
    assert set(scores) == {a1, a2, a3}  # one entry per article
    assert max(scores, key=scores.get) == a2  # ranked 2nd and 1st -> best fused
    assert {x.chunk_id for x in chunks[a1]} == {c["a"], c["c"]}
