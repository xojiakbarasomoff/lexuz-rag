"""Per-item comparison of two retrieval configs on the SAME dev questions.

    python -m evals.compare_retrieval --a "retrieval_rrf_k=60" --b "retrieval_rrf_k=10"

Prints the article rank of every expected article under both configs and
flags improvements / regressions (inside vs outside top_k). Dev only.
"""

from __future__ import annotations

import argparse

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.providers.embeddings import get_embedding_provider
from app.retrieval.search import retrieve
from evals.run import article_index, load


def _parse(spec: str) -> dict:
    out = {}
    for part in filter(None, spec.split(",")):
        k, v = part.split("=")
        out[k.strip()] = type(getattr(get_settings(), k.strip()))(v)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--a", required=True)
    p.add_argument("--b", required=True)
    args = p.parse_args(argv)
    base = get_settings()
    cfg_a, cfg_b = base.model_copy(update=_parse(args.a)), base.model_copy(update=_parse(args.b))
    emb = get_embedding_provider(base)
    k = base.retrieval_top_k
    better = worse = 0
    with get_sessionmaker()() as s:
        idx = article_index(s)
        print(f"A: {args.a}\nB: {args.b}\n(top_k={k}; '·' = unchanged)")
        for it in load("dev"):
            if not it["relevant"]:
                continue
            ra = retrieve(s, it["question"], cfg_a, emb).ranked_article_ids
            rb = retrieve(s, it["question"], cfg_b, emb).ranked_article_ids
            for rel in it["relevant"]:
                aid = idx[(rel["source_key"], rel["article"])][0]
                a = ra.index(aid) + 1 if aid in ra else None
                b = rb.index(aid) + 1 if aid in rb else None
                in_a, in_b = a is not None and a <= k, b is not None and b <= k
                flag = "·"
                if in_b and not in_a:
                    flag, better = "FIXED", better + 1
                elif in_a and not in_b:
                    flag, worse = "REGRESSION", worse + 1
                elif a and b and b != a:
                    flag = "rank up" if b < a else "rank down"
                print(f"{it['id']:7} {rel['article']:>5}  A #{a}  B #{b}  {flag}")
    print(f"\nentered top-{k}: {better}; left top-{k}: {worse}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
