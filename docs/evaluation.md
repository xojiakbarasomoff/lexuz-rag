# Evaluation

## Benchmark

`evals/benchmark.jsonl` — 50 items, 30 `dev` + 20 `holdout`.

| type | dev | holdout |
|---|---|---|
| fact | 13 | 7 |
| paraphrase (everyday wording) | 5 | 2 |
| multi_article | 2 | 2 |
| script_variant (Cyrillic, missing/odd apostrophes) | 2 | 3 |
| false_premise | 2 | 2 |
| ambiguous → clarification | 2 | 1 |
| out_of_corpus → insufficient evidence | 2 | 2 |
| prompt_injection | 2 | 1 |

Each item: `id, split, question, type, expected_status, relevant[], also_relevant[],
reference_answer, reference_sources[{source_key, article, quote}], verification`.
The corpus version an item was checked against is recorded in every report.

**Verification status: `ai_drafted_unverified`.** Questions, reference answers
and quotes were drafted with AI assistance from the article texts. The only
check so far is automatic: `python -m app.cli eval check` confirms every
relevant article exists and every reference quote occurs verbatim in the
active corpus (0 problems on 2026-11-11). No human legal review has been done.

## Commands

```bash
python -m app.cli eval check                          # benchmark ↔ corpus consistency
python -m app.cli eval retrieval --split dev          # no AI calls (local embeddings)
python -m app.cli eval answers --split dev --max-cost-usd 1.0   # LIVE, needs ANTHROPIC_API_KEY
```

CI never runs `answers`. Holdout is run only after a tuning round is finished.

## Metrics (kept separate on purpose)

| Layer | Metric |
|---|---|
| Retrieval | Article Recall@k, MRR, latency p50/p95 (embedding + SQL) |
| Generation (live) | status accuracy; refusal/clarification accuracy; citation precision/recall vs expected articles; claim citation coverage; first-try validity, repair and fallback rates; tokens; estimated cost; latency p50/p95 |
| Faithfulness (manual) | per-claim 0/1/2 score, completeness, over-reach — `evals/RUBRIC.md` |

Finding the right article (retrieval) and saying something legally correct
about it (generation + faithfulness) are reported separately.

## Results so far (real runs, 2026-11-11)

Embedding `fastembed:intfloat/multilingual-e5-large:1024`, `top_k=6`,
candidates 40, RRF k 60. Corpus: Consumer Protection Law `7c759eec74a0`
(live fetch, edition 02.02.2026), Labor Code `af3d92c6ade6` (local import of an
official page, later confirmed identical by a live fetch; edition “15.10.2026 01”).
Why 26 and 17 instead of 30 and 20: Recall@k and MRR need at least one
expected article. Items whose correct behaviour is to ask a clarifying
question or to abstain have none, so they are excluded from retrieval metrics
and scored only by the live answer eval (status accuracy):

| Split | In benchmark | Counted | Excluded (reason: no expected article) |
|---|---|---|---|
| dev | 30 | 26 | dev-17, dev-28 (ambiguous → clarification); dev-18, dev-29 (out of corpus → insufficient evidence) |
| holdout | 20 | 17 | hold-12 (ambiguous); hold-13, hold-19 (out of corpus) |

Retrieval reports from `20261111T060835Z` on list counted and excluded items.
For the earlier holdout run, `20261111T055136Z_retrieval_holdout.counted.md`
lists them (generated from the benchmark file; holdout was not re-run).

| Run (report in `evals/results/`) | Split | Weights sem/FTS/ref | R@1 | R@3 | R@6 | MRR |
|---|---|---|---|---|---|---|
| `20261111T054820Z` baseline | dev | 1 / 1 / (in FTS list) | 0.500 | 0.788 | 0.827 | 0.664 |
| `20261111T054917Z` + title list | dev | 1 / 1 / – | 0.462 | 0.769 | 0.788 | 0.637 |
| `20261111T055034Z` | dev | 1 / 0.5 / 2 | 0.615 | 0.827 | 0.827 | 0.732 |
| `20261111T055046Z` | dev | 1 / 0.25 / 2 | 0.635 | 0.827 | 0.827 | 0.749 |
| `20261111T055058Z` | dev | 1 / 0 / 2 | 0.673 | 0.827 | 0.865 | 0.765 |
| `20261111T055136Z` final config | **holdout** | 1 / 0.25 / 2 | 0.706 | 0.882 | 1.000 | 0.801 |

Retrieval latency on the development laptop (CPU): p50 ≈ 220–360 ms,
p95 ≈ 380–1240 ms (17–26 samples) — not a production measurement.

Reading these numbers honestly:

- Samples are tiny; one item moves dev Recall by ~0.04. The holdout score being
  higher than dev says more about item difficulty than about generalisation.
- Remaining dev misses: “Yillik asosiy mehnat taʼtili kamida necha kun?” (217
  at rank ~6–18 depending on weights), everyday-language resignation question
  (160), one of two articles of a multi-article question (173), a heavily
  padded injection question (130).
- **Answer-level metrics: not yet measured.** No `ANTHROPIC_API_KEY` was
  available in the build environment, so `eval answers` has not been run and
  no answer-quality, cost or end-to-end latency numbers exist yet
  (setup: docs/llm-setup.md). The project is not "ready" until it is.

## Human review

`python -m evals.build_review_sheet` writes `evals/review/review_sheet.md`
(question, reference answer, article and original text side by side, from the
active corpus) and `evals/review/review_form.csv` (one row per item,
`review_status = not_reviewed`). **No item has been reviewed by a human.**

## Error analysis notes (dev)

- e5-large alone ranked 182, 217, 130, 132 first for their questions; the
  OR-style FTS list ranked long, term-rich chunks above short precise
  articles, so equal-weight fusion pushed correct answers down.
- A title-only FTS list was tried and removed: prefix terms such as `ish:*`
  match dozens of titles.
- Next candidates (measure on dev first): AND-weighted FTS ranking, a small
  reranker, query rewriting for colloquial phrases.
