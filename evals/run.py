"""Evaluation commands.

  python -m app.cli eval check                      # reference quotes exist in the active corpus
  python -m app.cli eval retrieval --split dev      # Recall@k / MRR, no AI API calls
  python -m app.cli eval answers --split dev --max-cost-usd 1.0   # LIVE: calls the configured LLM

Retrieval metrics and answer metrics are reported separately; finding the
right article is not the same as giving a legally correct answer.
Results are written to evals/results/<timestamp>_<kind>_<split>.{json,md}.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings

ROOT = Path(__file__).parent
BENCH = ROOT / "benchmark.jsonl"
RESULTS = ROOT / "results"


def load(split: str) -> list[dict]:
    items = [json.loads(line) for line in BENCH.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [i for i in items if split == "all" or i["split"] == split]


def git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10)
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, timeout=10).stdout
        return out.stdout.strip() + ("-dirty" if dirty.strip() else "")
    except Exception:
        return "unknown"


def corpus_state(session) -> dict:
    from app.models import Document, DocumentVersion

    out = {}
    for d in session.scalars(select(Document).where(Document.active_version_id.is_not(None))):
        v = session.get(DocumentVersion, d.active_version_id)
        out[d.source_key] = {
            "version_id": str(v.id),
            "content_checksum": v.content_checksum[:12],
            "source_kind": v.source_kind,
            "revision_label": v.source_revision_label,
            "fetched_at": v.fetched_at.isoformat(),
        }
    return out


def article_index(session) -> dict[tuple[str, str], tuple]:
    from app.models import Article, Document

    rows = session.execute(
        select(Document.source_key, Article.label, Article.id, Article.text).join(
            Article, Article.version_id == Document.active_version_id
        )
    ).all()
    return {(r[0], r[1]): (r[2], r[3]) for r in rows}


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, round(p / 100 * (len(s) - 1))))
    return s[k]


def write_report(kind: str, split: str, payload: dict, md_lines: list[str]) -> Path:
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = RESULTS / f"{stamp}_{kind}_{split}"
    base.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    base.with_suffix(".md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return base.with_suffix(".md")


def header(kind: str, split: str, session, n: int, extra: dict) -> tuple[dict, list[str]]:
    s = get_settings()
    meta = {
        "kind": kind,
        "date": datetime.now(UTC).isoformat(),
        "git_commit": git_commit(),
        "split": split,
        "items": n,
        "corpus": corpus_state(session),
        "embedding_space": s.embedding_space,
        "retrieval": {
            "top_k": s.retrieval_top_k,
            "candidates": s.retrieval_candidate_limit,
            "rrf_k": s.retrieval_rrf_k,
            "context_max_tokens": s.context_max_tokens,
        },
        "benchmark_verification": "ai_drafted_unverified (no human review recorded yet)",
        **extra,
    }
    md = [
        f"# Eval report — {kind} / {split}",
        "",
        f"- Date: {meta['date']}",
        f"- Git commit: `{meta['git_commit']}`",
        f"- Items: {n}",
        f"- Embedding space: `{meta['embedding_space']}`",
        f"- Retrieval config: {meta['retrieval']}",
        f"- Benchmark manual verification: {meta['benchmark_verification']}",
        "- Corpus:",
    ]
    md += [
        f"  - {k}: version `{v['content_checksum']}` ({v['source_kind']}, revision {v['revision_label']}, "
        f"fetched {v['fetched_at']})"
        for k, v in meta["corpus"].items()
    ]
    for k, v in extra.items():
        md.append(f"- {k}: {v}")
    return meta, md


# --------------------------------------------------------------------------- check


def cmd_check(args) -> int:
    from app.db.session import get_sessionmaker
    from app.generation.validate import find_quote

    items = load("all")
    bad = []
    with get_sessionmaker()() as s:
        idx = article_index(s)
    for it in items:
        for rel in it["relevant"] + it.get("also_relevant", []):
            if (rel["source_key"], rel["article"]) not in idx:
                bad.append(f"{it['id']}: article {rel} not in active corpus")
        for ref in it["reference_sources"]:
            art = idx.get((ref["source_key"], ref["article"]))
            if art is None or find_quote(art[1], ref["quote"]) is None:
                bad.append(f"{it['id']}: reference quote not found in {ref['source_key']} {ref['article']}")
    print(json.dumps({"items": len(items), "problems": bad}, ensure_ascii=False, indent=2))
    return 1 if bad else 0


# --------------------------------------------------------------------------- retrieval


def cmd_retrieval(args) -> int:
    from app.db.session import get_sessionmaker
    from app.providers.embeddings import get_embedding_provider
    from app.retrieval.search import retrieve

    settings = get_settings()
    embedder = get_embedding_provider(settings)
    items = [i for i in load(args.split) if i["relevant"]]
    ks = sorted({1, 3, 5, args.k, settings.retrieval_top_k})
    rows, latencies = [], []
    with get_sessionmaker()() as s:
        idx = article_index(s)
        meta, md = header("retrieval", args.split, s, len(items), {})
        for it in items:
            want = {idx[(r["source_key"], r["article"])][0] for r in it["relevant"]}
            ok_extra = {
                idx[(r["source_key"], r["article"])][0]
                for r in it.get("also_relevant", [])
                if (r["source_key"], r["article"]) in idx
            }
            t0 = time.perf_counter()
            res = retrieve(s, it["question"], settings, embedder)
            latencies.append((time.perf_counter() - t0) * 1000)
            ranked = res.ranked_article_ids
            first = next((n for n, a in enumerate(ranked, 1) if a in want), None)
            row = {
                "id": it["id"],
                "type": it["type"],
                "first_relevant_rank": first,
                "recall": {k: len(want & set(ranked[:k])) / len(want) for k in ks},
                "top5": [str(a) for a in ranked[:5]],
                "acceptable_in_top5": bool(ok_extra & set(ranked[:5])),
            }
            rows.append(row)
    labels = {}
    with get_sessionmaker()() as s:
        from app.models import Article, Document, DocumentVersion

        for aid, label, key in s.execute(
            select(Article.id, Article.label, Document.source_key)
            .join(DocumentVersion, DocumentVersion.id == Article.version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
        ):
            labels[str(aid)] = f"{key}:{label}"
    for r in rows:
        r["top5_labels"] = [labels.get(a, a) for a in r.pop("top5")]
    n = len(rows)
    summary = {f"recall@{k}": round(sum(r["recall"][k] for r in rows) / n, 3) for k in ks}
    summary["mrr"] = round(sum(1 / r["first_relevant_rank"] for r in rows if r["first_relevant_rank"]) / n, 3)
    summary["latency_ms_p50"] = round(percentile(latencies, 50), 1)
    summary["latency_ms_p95"] = round(percentile(latencies, 95), 1)
    summary["samples"] = n
    by_type: dict[str, list] = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(r)
    tk = settings.retrieval_top_k
    per_type = {
        t: {"n": len(v), f"recall@{tk}": round(sum(x["recall"][tk] for x in v) / len(v), 3)} for t, v in by_type.items()
    }
    misses = [r for r in rows if r["recall"][settings.retrieval_top_k] < 1]
    md += ["", "## Results (article-level, active corpus only)", "", "| metric | value |", "|---|---|"]
    md += [f"| {k} | {v} |" for k, v in summary.items()]
    md += [
        "",
        "Latency covers query embedding + SQL on the eval machine; it excludes the LLM.",
        "",
        "## By question type",
        "",
        "| type | n | recall@top_k |",
        "|---|---|---|",
    ]
    md += [f"| {t} | {v['n']} | {v[f'recall@{settings.retrieval_top_k}']} |" for t, v in per_type.items()]
    md += ["", "## Misses (relevant article not in top_k)", ""]
    md += [
        f"- {r['id']} ({r['type']}): first relevant rank {r['first_relevant_rank']}; top5 {r['top5_labels']}"
        for r in misses
    ] or ["- none"]
    path = write_report("retrieval", args.split, {**meta, "summary": summary, "per_type": per_type, "rows": rows}, md)
    print("\n".join(md))
    print(f"\nreport: {path}")
    return 0


# --------------------------------------------------------------------------- answers (live)


def cmd_answers(args) -> int:
    from app.db.session import get_sessionmaker
    from app.generation.answer import AnswerError, AnswerTrace, Deps, answer_question
    from app.providers.embeddings import get_embedding_provider
    from app.providers.llm import get_llm_provider

    settings = get_settings()
    if settings.llm_provider == "fake":
        print("LLM_PROVIDER=fake: refusing to report fake answers as an evaluation")
        return 2
    deps = Deps(settings, get_llm_provider(settings), get_embedding_provider(settings), guards=None)
    items = load(args.split)
    rows, spent = [], 0.0
    with get_sessionmaker()() as s:
        from app.models import Document

        doc_keys = {d.id: d.source_key for d in s.scalars(select(Document))}
        meta, md = header(
            "answers",
            args.split,
            s,
            len(items),
            {
                "llm_model": settings.llm_model,
                "llm_effort": settings.llm_effort,
                "max_output_tokens": settings.llm_max_output_tokens,
                "prices_per_mtok_usd": [settings.llm_input_price_per_mtok_usd, settings.llm_output_price_per_mtok_usd],
            },
        )
    for it in items:
        if spent >= args.max_cost_usd:
            print(f"stopping: estimated cost {spent:.3f} >= --max-cost-usd {args.max_cost_usd}")
            break
        trace = AnswerTrace()
        t0 = time.perf_counter()
        try:
            resp = answer_question(
                it["question"], document_ids=None, request_id=f"eval-{it['id']}", deps=deps, trace=trace
            )
            status, err = resp.status, None
        except AnswerError as exc:
            resp, status, err = None, "error", exc.code
        latency = (time.perf_counter() - t0) * 1000
        spent += trace.est_cost_usd
        want = {(r["source_key"], r["article"]) for r in it["relevant"]}
        acceptable = want | {(r["source_key"], r["article"]) for r in it.get("also_relevant", [])}
        claims = resp.claims if resp else []
        cited = {
            (doc_keys[src.document_id], src.article_label)
            for src in (resp.sources if resp else [])
            if resp and resp.status == "answered"
        }
        rows.append(
            {
                "id": it["id"],
                "type": it["type"],
                "expected_status": it["expected_status"],
                "status": status,
                "error": err,
                "status_correct": status == it["expected_status"],
                "claims": len(claims),
                "claims_with_sources": sum(1 for c in claims if c.source_ids),
                "cited": sorted(f"{a}:{b}" for a, b in cited),
                "citation_precision": (len(cited & acceptable) / len(cited)) if cited else None,
                "citation_recall": (len(cited & want) / len(want)) if want else None,
                "first_try_valid": not trace.repaired,
                "repaired": trace.repaired,
                "fallback": trace.fallback,
                "input_tokens": trace.input_tokens,
                "output_tokens": trace.output_tokens,
                "est_cost_usd": round(trace.est_cost_usd, 5),
                "latency_ms": round(latency),
                "answer": [c.text for c in claims],
                "clarifying_question": resp.clarifying_question if resp else None,
                "limitations": resp.limitations if resp else [],
            }
        )
        print(f"{it['id']}: {status} (expected {it['expected_status']}) {round(latency)} ms")
    summary = _answer_summary(rows)
    md += ["", "## Results", "", "| metric | value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in summary.items()]
    md += [
        "",
        "Citation validity is enforced by the backend (invalid ids/quotes never reach the user); the rows "
        "below show how often the model needed a repair or fell back.",
        "",
        "Semantic faithfulness is NOT measured here — see evals/RUBRIC.md (manual review pending).",
        "",
        "## Status errors",
        "",
    ]
    md += [
        f"- {r['id']} ({r['type']}): expected {r['expected_status']}, got {r['status']} {r['error'] or ''}"
        for r in rows
        if not r["status_correct"]
    ] or ["- none"]
    path = write_report("answers", args.split, {**meta, "summary": summary, "rows": rows}, md)
    print("\n".join(md))
    print(f"\nreport: {path}")
    return 0


def _answer_summary(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"samples": 0}
    ans = [r for r in rows if r["expected_status"] == "answered"]
    non = [r for r in rows if r["expected_status"] != "answered"]
    prec = [r["citation_precision"] for r in rows if r["citation_precision"] is not None]
    rec = [r["citation_recall"] for r in ans if r["citation_recall"] is not None]
    claims = sum(r["claims"] for r in rows)
    lat = [r["latency_ms"] for r in rows]
    return {
        "samples": n,
        "status_accuracy": round(sum(r["status_correct"] for r in rows) / n, 3),
        "answered_items_status_accuracy": round(sum(r["status_correct"] for r in ans) / len(ans), 3) if ans else None,
        "refusal_clarification_accuracy": round(sum(r["status_correct"] for r in non) / len(non), 3) if non else None,
        "citation_precision_vs_expected": round(statistics.mean(prec), 3) if prec else None,
        "citation_recall_vs_expected": round(statistics.mean(rec), 3) if rec else None,
        "claim_citation_coverage": round(sum(r["claims_with_sources"] for r in rows) / claims, 3) if claims else None,
        "first_try_valid_rate": round(sum(r["first_try_valid"] for r in rows) / n, 3),
        "fallback_rate": round(sum(r["fallback"] for r in rows) / n, 3),
        "errors": sum(1 for r in rows if r["error"]),
        "latency_ms_p50": percentile(lat, 50),
        "latency_ms_p95": percentile(lat, 95),
        "input_tokens": sum(r["input_tokens"] for r in rows),
        "output_tokens": sum(r["output_tokens"] for r in rows),
        "est_cost_usd": round(sum(r["est_cost_usd"] for r in rows), 4),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="lexuz eval")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    r = sub.add_parser("retrieval")
    r.add_argument("--split", default="dev", choices=["dev", "holdout", "all"])
    r.add_argument("--k", type=int, default=5)
    r.set_defaults(fn=cmd_retrieval)
    a = sub.add_parser("answers")
    a.add_argument("--split", default="dev", choices=["dev", "holdout", "all"])
    a.add_argument("--max-cost-usd", type=float, default=1.0)
    a.set_defaults(fn=cmd_answers)
    args = p.parse_args(argv)
    return args.fn(args)
