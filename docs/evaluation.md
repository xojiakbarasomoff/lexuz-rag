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
python -m app.cli eval answers --split dev --max-cost-usd 1.0   # LIVE, needs GEMINI_API_KEY; paced, checkpointed, --resume
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
- **Answer-level metrics: not yet measured.** No `GEMINI_API_KEY` was
  available in the build environment, so `eval answers` has not been run and
  no answer-quality, cost or end-to-end latency numbers exist yet
  (setup: docs/llm-setup.md). The project is not "ready" until it is.

## Answer eval — dev, real Gemini API (2026-11-11)

Report: `evals/results/20261111T123230Z_answers_dev.{md,json}`; per-item
checkpoint: `evals/results/checkpoints/answers_dev.jsonl`.

- Model: **`gemini-3.5-flash-lite`** (free tier, thinking `minimal`,
  max 2048 output tokens). `gemini-3.8-flash` was tried first and timed out
  (decision D20). Retrieval config unchanged. Holdout not touched.
- Pacing 13 s between items, project caps 5 calls/min, checkpoint per item.
  No quota error, no provider safety block, no cap stop: 30/30 items ran.
- 33 LLM calls (30 + 3 repairs). Tokens: 145,630 input / 14,712 output
  (incl. thinking). Free tier → $0 charged; paid-equivalent estimate
  $0.0805 (of the $1 cap).
- End-to-end latency per item (retrieval + LLM + repair, dev laptop):
  p50 3.8 s, p95 14.4 s, max 17.7 s (first item includes loading the
  embedding model).

| Metric | Value |
|---|---|
| Status accuracy (all 30) | 0.867 (26/30) |
| — items expected `answered` | 0.846 (22/26) |
| — abstain / clarify items | 1.000 (4/4: 2 clarification, 2 out-of-corpus) |
| Provider safety blocks (`provider_blocked`) | 0 — counted separately from `insufficient_evidence` |
| Citation precision vs expected articles | 0.932 |
| Citation recall vs expected articles (answered) | 0.788 |
| Claim citation coverage | 1.000 (every shown claim has a validated source id + quote) |
| First-try valid output | 0.900 (3 needed a repair) |
| Safe fallback after failed repair | 1 (dev-14) |

Failure examples (all from the report):

- **dev-03, dev-04, dev-08 → `insufficient_evidence` instead of an answer.**
  These are exactly the retrieval misses (217, 182, 160 ranked 9–12, outside
  the 6-article context). The model said the sources do not state the rule
  rather than inventing it — correct abstention, but the user gets no
  answer. Fix belongs in retrieval, not generation.
- **dev-14 (apostrophe-less question) → safe fallback.** Retrieval found 173,
  but the model's quotes did not match the stored text verbatim twice (first
  try and repair), so the backend refused to show the answer.
- **dev-09, dev-23: first output had a quote > 400 chars**; the repair call
  fixed it. dev-09 still missed the second article (173): the model said the
  sources do not cover severance pay although 173 was not in the context.
- **dev-25: extra citation** of Labor Code art. 565 (moral harm to employees)
  for a consumer-law question — valid quote, but outside the expected scope.
- **dev-19 (injection): the system prompt was not revealed**, but the answer
  is built on articles 129 and 132; the asked-for duration (130) was not in
  the context, so the claims are related but do not answer “how long”.
- First live answer (CLI): claim text dropped “kamida” (“at least”) from
  “kamida uch kun oldin”; the citation is valid. Validation cannot catch such
  meaning shifts — that is what the manual rubric is for.

Not measured: semantic faithfulness (manual review pending), holdout answers.

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
