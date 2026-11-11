"""Build the human review sheet for the benchmark.

    python -m evals.build_review_sheet

Writes:
  evals/review/review_sheet.md   question | reference answer  ⟷  article | original text (side by side)
  evals/review/review_form.csv   one empty row per item for the reviewer to fill in

The sheet is generated from the ACTIVE corpus so the reviewer sees the exact
text the system uses. Nothing here marks an item as reviewed.
"""

from __future__ import annotations

import csv
import html
from pathlib import Path

from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.generation.validate import find_quote
from app.models import Article, Document
from evals.run import corpus_state, load

OUT = Path(__file__).parent / "review"
MAX_ARTICLE_CHARS = 1500


def _cell(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


def main() -> int:
    items = load("all")
    with get_sessionmaker()() as s:
        corpus = corpus_state(s)
        rows = s.execute(
            select(
                Document.source_key, Document.title, Article.label, Article.title, Article.text, Article.source_url
            ).join(Article, Article.version_id == Document.active_version_id)
        ).all()
    arts = {(r[0], r[2]): r for r in rows}

    OUT.mkdir(exist_ok=True)
    md = [
        "# Benchmark review sheet",
        "",
        "**Status: NOT REVIEWED.** Items were drafted with AI assistance; no human legal review is recorded.",
        "Record decisions in `review_form.csv` (one row per item). Do not edit this generated file.",
        "",
        "Corpus used: " + "; ".join(f"{k} `{v['content_checksum']}` ({v['source_kind']})" for k, v in corpus.items()),
        "",
        "For each item check: (1) the question is realistic and unambiguous for its type; (2) the expected status is",
        "right; (3) the listed articles are the right and complete source; (4) the reference answer says only what",
        "the article text says, including conditions and exceptions.",
        "",
    ]
    for it in items:
        md += [f"## {it['id']} · {it['split']} · {it['type']} · expected `{it['expected_status']}`", ""]
        left = (
            f"<b>Savol</b><br>{_cell(it['question'])}<br><br><b>Reference answer</b><br>{_cell(it['reference_answer'])}"
        )
        right_parts = []
        refs = {(r["source_key"], r["article"]): r["quote"] for r in it["reference_sources"]}
        for rel in it["relevant"] + it.get("also_relevant", []):
            key = (rel["source_key"], rel["article"])
            a = arts.get(key)
            if a is None:
                right_parts.append(f"<b>{_cell(rel['article'])}</b>: NOT IN ACTIVE CORPUS")
                continue
            tag = "also acceptable" if rel in it.get("also_relevant", []) else "expected"
            quote = refs.get(key)
            found = find_quote(a[4], quote) if quote else None
            body = a[4] if len(a[4]) <= MAX_ARTICLE_CHARS else a[4][:MAX_ARTICLE_CHARS] + " … [full text on Lex.uz]"
            right_parts.append(
                f"<b>{_cell(a[1])}, {_cell(a[2])}-modda. {_cell(a[3])}</b> ({tag})<br>"
                f'<a href="{_cell(a[5])}">{_cell(a[5])}</a><br>'
                + (f"<b>Reference quote</b>: «{_cell(found)}»<br>" if found else "")
                + f"<b>Original text</b><br>{_cell(body)}"
            )
        if not right_parts:
            right_parts.append("(no article expected: correct behaviour is to abstain or ask a clarifying question)")
        md += [
            '<table><tr><th width="40%">Question / reference</th><th>Source (original, active corpus)</th></tr>',
            f'<tr><td valign="top">{left}</td><td valign="top">{"<hr>".join(right_parts)}</td></tr></table>',
            "",
        ]
    (OUT / "review_sheet.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    with open(OUT / "review_form.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "item_id",
                "split",
                "type",
                "review_status",
                "question_ok",
                "expected_status_ok",
                "articles_ok",
                "missing_or_wrong_articles",
                "reference_answer_ok",
                "corrected_reference_answer",
                "reviewer",
                "reviewed_at",
                "notes",
            ]
        )
        for it in items:
            w.writerow([it["id"], it["split"], it["type"], "not_reviewed", "", "", "", "", "", "", "", "", ""])
    print(f"wrote {OUT / 'review_sheet.md'} and {OUT / 'review_form.csv'} ({len(items)} items, status not_reviewed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
