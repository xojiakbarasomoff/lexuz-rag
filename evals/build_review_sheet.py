"""Build the human review materials for the 50-item benchmark.

    python -m evals.build_review_sheet            # refuses to overwrite a form that has reviewer input
    python -m evals.build_review_sheet --force    # regenerate anyway (destroys reviewer input!)

Writes:
  evals/review/review_sheet.md   one card per item: question + expected status, reference answer,
                                 document/article, original source text + Lex.uz link, the model's
                                 answer and citations (frozen baseline runs), and verdict boxes.
                                 Flagged items come first.
  evals/review/review_form.csv   one row per item for the reviewer (UTF-8 with BOM for Excel).

Model answers come from the frozen-baseline runs (RRF k=10, prompt answer-v1,
gemini-3.5-flash-lite): dev = checkpoints/answers_dev_rrf10.jsonl,
holdout = checkpoints/answers_holdout.jsonl. Nothing here calls an API.

"Priority" flags are AUTOMATIC signals (status mismatch, citation outside the
expected articles, etc.) to decide what a person should look at first. They
are not a review. Every item keeps review_status = not_reviewed.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path

from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.generation.validate import find_quote
from app.models import Article, Document
from evals.run import corpus_state, load

ROOT = Path(__file__).parent
OUT = ROOT / "review"
CKPT = ROOT / "results" / "checkpoints"
RUNS = {
    "dev": CKPT / "answers_dev_rrf10.jsonl",
    "holdout": CKPT / "answers_holdout.jsonl",
}
EARLIER_DEV_RUN = CKPT / "answers_dev.jsonl"  # k=60 run, only used to flag run-to-run differences
MAX_ARTICLE_CHARS = 1500
VERDICTS = "to‘g‘ri / qisman / noto‘g‘ri / noaniq"
FORM_FIELDS = [
    "item_id",
    "split",
    "type",
    "priority",
    "priority_reasons",
    "review_status",
    "question_status_verdict",
    "reference_answer_verdict",
    "source_article_verdict",
    "model_answer_verdict",
    "corrected_reference_answer",
    "missing_or_wrong_articles",
    "comment",
    "reviewer",
    "reviewed_at",
]
REVIEWER_FIELDS = FORM_FIELDS[6:]


def _cell(text: str) -> str:
    return html.escape(text or "").replace("\n", "<br>")


def _rows(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {r["id"]: r for r in (json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip())}


def priority_reasons(item: dict, run: dict | None, earlier: dict | None) -> list[str]:
    if run is None:
        return ["no model answer recorded"]
    out = []
    if run.get("error"):
        out.append(f"provider error ({run['error']}) — no answer")
    elif not run.get("status_correct"):
        out.append(f"status mismatch: expected {item['expected_status']}, got {run['status']}")
    p, r = run.get("citation_precision"), run.get("citation_recall")
    if p is not None and p < 1:
        out.append("cites articles outside the expected set")
    if run.get("status") == "answered" and r is not None and r < 1:
        out.append("an expected article was not cited")
    if run.get("fallback"):
        out.append("answer withheld by citation validation (fallback)")
    elif run.get("repaired"):
        out.append("first output failed citation validation (repaired)")
    if earlier is not None and earlier.get("status") != run.get("status"):
        out.append(f"status differed in the earlier dev run ({earlier.get('status')})")
    return out


def _form_has_reviewer_input(path: Path) -> bool:
    if not path.exists():
        return False
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if (row.get("review_status") or "not_reviewed") != "not_reviewed":
                return True
            if any((row.get(f) or "").strip() for f in REVIEWER_FIELDS):
                return True
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    form_path = OUT / "review_form.csv"
    if _form_has_reviewer_input(form_path) and not args.force:
        print(f"{form_path} already contains reviewer input; not overwriting (use --force only if you mean it)")
        return 2

    items = load("all")
    runs = {split: _rows(path) for split, path in RUNS.items()}
    earlier = _rows(EARLIER_DEV_RUN)
    with get_sessionmaker()() as s:
        corpus = corpus_state(s)
        rows = s.execute(
            select(
                Document.source_key, Document.title, Article.label, Article.title, Article.text, Article.source_url
            ).join(Article, Article.version_id == Document.active_version_id)
        ).all()
    arts = {(r[0], r[2]): r for r in rows}

    flagged, cards, form_rows = [], {}, []
    for it in items:
        run = runs.get(it["split"], {}).get(it["id"])
        reasons = priority_reasons(it, run, earlier.get(it["id"]) if it["split"] == "dev" else None)
        prio = "high" if reasons else "normal"
        if reasons:
            flagged.append((it, reasons))
        cards[it["id"]] = _card(it, run, reasons, arts)
        form_rows.append(
            {
                "item_id": it["id"],
                "split": it["split"],
                "type": it["type"],
                "priority": prio,
                "priority_reasons": "; ".join(reasons),
                "review_status": "not_reviewed",
                **{f: "" for f in REVIEWER_FIELDS},
            }
        )

    OUT.mkdir(exist_ok=True)
    md = [
        "# Benchmark review sheet (50 items)",
        "",
        "**Status: NOT REVIEWED.** All 50 items are `not_reviewed`. The questions, expected statuses, reference",
        "answers and reference quotes were drafted with AI assistance; the only checks so far are automatic",
        "(every reference quote exists verbatim in the active corpus). Priority flags below are automatic",
        "signals, **not** a review.",
        "",
        "How to review: fill one row per item in `review_form.csv` (open in Excel/LibreOffice; UTF-8).",
        f"Use one of **{VERDICTS}** for each verdict column, then set `review_status` to `reviewed`, add your",
        "name in `reviewer` and the date (YYYY-MM-DD) in `reviewed_at`. Do not edit this generated file.",
        "",
        "| Verdict column | Question to answer |",
        "|---|---|",
        "| question_status_verdict | Is the question realistic and is the expected status right? |",
        "| reference_answer_verdict | Does it say only what the article says (incl. conditions)? |",
        "| source_article_verdict | Are the listed articles the right and complete source? |",
        "| model_answer_verdict | Is the model's answer correct and supported by the cited text? |",
        "",
        "Model answers: frozen baseline (RRF k=10, prompt `answer-v1`, `gemini-3.5-flash-lite`, free tier) —",
        "dev from `results/checkpoints/answers_dev_rrf10.jsonl`, holdout from the one-time final assessment",
        "`results/checkpoints/answers_holdout.jsonl`. Valid citations mean the quoted words exist in the cited",
        "article; they do not prove legal correctness.",
        "",
        "Corpus: " + "; ".join(f"{k} `{v['content_checksum']}` ({v['source_kind']})" for k, v in corpus.items()),
        "",
        f"## Review first — {len(flagged)} flagged items",
        "",
        "| Item | Split | Type | Why flagged (automatic) |",
        "|---|---|---|---|",
    ]
    md += [f"| [{it['id']}](#{it['id']}) | {it['split']} | {it['type']} | {'; '.join(r)} |" for it, r in flagged]
    md += ["", "## Flagged items", ""]
    for it, _ in flagged:
        md += cards[it["id"]]
    md += ["## Other items", ""]
    flagged_ids = {it["id"] for it, _ in flagged}
    for it in items:
        if it["id"] not in flagged_ids:
            md += cards[it["id"]]
    (OUT / "review_sheet.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    with open(form_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FORM_FIELDS)
        w.writeheader()
        w.writerows(form_rows)
    print(
        f"wrote {OUT / 'review_sheet.md'} and {form_path}: {len(items)} items, {len(flagged)} flagged, "
        "all review_status=not_reviewed"
    )
    return 0


def _card(it: dict, run: dict | None, reasons: list[str], arts: dict) -> list[str]:
    left = (
        f"<b>Savol</b><br>{_cell(it['question'])}<br><br>"
        f"<b>Kutilgan status</b>: <code>{_cell(it['expected_status'])}</code><br><br>"
        f"<b>Reference javob</b><br>{_cell(it['reference_answer'])}"
    )
    refs = {(r["source_key"], r["article"]): r["quote"] for r in it["reference_sources"]}
    src_parts = []
    for rel in it["relevant"] + it.get("also_relevant", []):
        key = (rel["source_key"], rel["article"])
        a = arts.get(key)
        if a is None:
            src_parts.append(f"<b>{_cell(rel['article'])}</b>: NOT IN ACTIVE CORPUS")
            continue
        tag = "also acceptable" if rel in it.get("also_relevant", []) else "expected"
        quote = refs.get(key)
        found = find_quote(a[4], quote) if quote else None
        body = a[4] if len(a[4]) <= MAX_ARTICLE_CHARS else a[4][:MAX_ARTICLE_CHARS] + " … [full text on Lex.uz]"
        src_parts.append(
            f"<b>{_cell(a[1])}, {_cell(a[2])}-modda. {_cell(a[3])}</b> ({tag})<br>"
            f'<a href="{_cell(a[5])}">{_cell(a[5])}</a><br>'
            + (f"<b>Reference parcha</b>: «{_cell(found)}»<br>" if found else "")
            + f"<b>Original matn</b><br>{_cell(body)}"
        )
    if not src_parts:
        src_parts.append("(modda kutilmaydi: to‘g‘ri xatti-harakat — rad etish yoki aniqlashtiruvchi savol)")

    if run is None:
        model = "<i>model javobi yozilmagan</i>"
    else:
        bits = [f"<b>Status</b>: <code>{_cell(run['status'])}</code>"]
        if run.get("error"):
            bits.append(f"<b>Provider xatosi</b>: {_cell(run['error'])}")
        if run.get("answer"):
            bits.append("<b>Da’volar</b><br>" + "<br>".join(f"• {_cell(c)}" for c in run["answer"]))
        if run.get("clarifying_question"):
            bits.append(f"<b>Aniqlashtiruvchi savol</b>: {_cell(run['clarifying_question'])}")
        if run.get("limitations"):
            bits.append("<b>Cheklovlar</b><br>" + "<br>".join(f"• {_cell(x)}" for x in run["limitations"]))
        for src in run.get("sources", []):
            bits.append(f"<b>Citation {src['id']}</b> = {_cell(src['article'])}<br>«{_cell(src['excerpt'])}»")
        if run.get("validation_errors"):
            bits.append(
                "<b>Validatsiya xatolari (backend)</b><br>"
                + "<br>".join(f"• {_cell(e)}" for e in run["validation_errors"][:6])
            )
        model = "<br><br>".join(bits)

    boxes = "<br>".join(
        f"<b>{label}</b>: ☐ to‘g‘ri ☐ qisman ☐ noto‘g‘ri ☐ noaniq"
        for label in ("Savol va status", "Reference javob", "Manba / modda", "Model javobi")
    )
    head = f"### {it['id']}"
    flag = f"**Priority: high** — {'; '.join(reasons)}" if reasons else "Priority: normal"
    return [
        f'<a id="{it["id"]}"></a>',
        "",
        f"{head} · {it['split']} · {it['type']} · review_status: `not_reviewed`",
        "",
        flag,
        "",
        '<table><tr><th width="28%">Savol / reference</th><th width="40%">Manba (original, faol korpus)</th>'
        "<th>Model javobi (baseline)</th></tr>",
        f'<tr><td valign="top">{left}</td><td valign="top">{"<hr>".join(src_parts)}</td>'
        f'<td valign="top">{model}</td></tr>',
        f'<tr><td colspan="3">{boxes}<br><b>Izoh</b>: ______ &nbsp; <b>Tekshiruvchi</b>: ______ &nbsp; '
        "<b>Sana</b>: ______ (record in review_form.csv)</td></tr></table>",
        "",
    ]


if __name__ == "__main__":
    raise SystemExit(main())
