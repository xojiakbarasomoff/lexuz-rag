"""Local retrieval diagnostics: where does an expected article get lost?

    python -m evals.diagnose_retrieval --split dev [--ids dev-03,dev-04] [--k 6]

For every item with expected articles it prints, per ranked list, the
article-level rank and raw score (cosine distance for semantic, ts_rank_cd for
lexical), the fused RRF rank/score, whether the article made it into the
answer context, and the top-k competitors. No AI API calls. Dev only by
default; holdout requires --allow-holdout.
"""

from __future__ import annotations

import argparse

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.providers.embeddings import get_embedding_provider
from app.retrieval.search import retrieve
from evals.run import article_index, load


def _article_ranks(cands) -> dict:
    """First (best) rank and score of each article in one chunk-level list."""
    out: dict = {}
    seen: list = []
    for c in cands:
        if c.article_id not in seen:
            seen.append(c.article_id)
            out[c.article_id] = (len(seen), c.score)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--split", default="dev", choices=["dev", "holdout"])
    p.add_argument("--allow-holdout", action="store_true")
    p.add_argument("--ids", default="")
    args = p.parse_args(argv)
    if args.split == "holdout" and not args.allow_holdout:
        print("holdout diagnostics need --allow-holdout (do not tune on holdout)")
        return 2
    settings = get_settings()
    emb = get_embedding_provider(settings)
    want_ids = {x for x in args.ids.split(",") if x}
    with get_sessionmaker()() as s:
        idx = article_index(s)
        label = {v[0]: f"{k[0].split('-')[0][:6]}:{k[1]}" for k, v in idx.items()}
        for it in load(args.split):
            if not it["relevant"] or (want_ids and it["id"] not in want_ids):
                continue
            dbg: dict = {}
            res = retrieve(s, it["question"], settings, emb, debug=dbg)
            fused = res.ranked_article_ids
            in_ctx = {a.article_id for a in res.articles}
            print(f"\n{it['id']} ({it['type']}): {it['question']}")
            per_list = {name: _article_ranks(lst) for name, lst in dbg["lists"].items()}
            for rel in it["relevant"]:
                aid = idx[(rel["source_key"], rel["article"])][0]
                parts = []
                for name, ranks in per_list.items():
                    r = ranks.get(aid)
                    parts.append(f"{name}: " + (f"#{r[0]} ({r[1]:.4f})" if r else "—"))
                fr = fused.index(aid) + 1 if aid in fused else None
                sc = dbg["article_score"].get(aid)
                print(
                    f"  expected {label[aid]}: " + "; ".join(parts) + f" | fused #{fr} ({sc:.5f})"
                    if sc
                    else f"  expected {label[aid]}: not retrieved at all"
                )
                print(f"    in answer context: {aid in in_ctx}")
            top = []
            for n, aid in enumerate(fused[: settings.retrieval_top_k], 1):
                bits = [
                    f"{name.split('[')[0][:3]}#{per_list[name][aid][0]}" for name in per_list if aid in per_list[name]
                ]
                top.append(f"{n}.{label.get(aid, '?')}({dbg['article_score'][aid]:.5f};{','.join(bits)})")
            print("  fused top: " + "  ".join(top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
