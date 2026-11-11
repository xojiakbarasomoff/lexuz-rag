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
| Generation (live) | status accuracy (returned status = expected status; not answer or legal accuracy); refusal/clarification accuracy; citation precision/recall vs expected articles; claim citation coverage; first-try validity, repair and fallback rates; tokens; estimated cost; latency p50/p95 |
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

## Retrieval fix (RRF k 60 → 10) and second dev answer eval (2026-11-11)

Diagnosis, sweep and per-item comparison: decision D22 (`docs/decisions.md`),
tools `python -m evals.diagnose_retrieval` and `python -m evals.compare_retrieval`.
Benchmark references of the failing items were re-checked against the
stored source text and were correct; the benchmark was **not** changed and
this is not a human review.

Retrieval, same 26 dev items: R@6 0.827 → **0.904**, MRR 0.749 → **0.796**,
R@1 0.635 → 0.712, p50 ≈ 150 ms unchanged (report `20261111T142712Z_retrieval_dev`).
Fixed 217 and 182; nothing left the top 6; three articles moved down inside
the top 6 (262 #2→#5, 129 #2→#4, 22 #1→#2).

Answer eval, same 30 dev questions, `gemini-3.5-flash-lite` free tier,
checkpoint `evals/results/checkpoints/answers_dev_rrf10.jsonl`:

- First pass (`20261111T143905Z_answers_dev`): 4 items ended with
  `provider_unavailable` (Gemini 5xx after one SDK retry) — infrastructure
  errors, kept on record in that report's JSON (all 30 rows incl. the errors).
- Those 4 items were re-run once with `--resume --retry-errors`
  (`20261111T144129Z_answers_dev`, the final report below). No other item was
  re-run.

| Metric (30 dev items) | k=60 run | k=10 run |
|---|---|---|
| Status accuracy | 0.867 | **0.933** |
| — expected `answered` | 0.846 | **0.923** |
| — abstain / clarify | 1.000 | 1.000 |
| Citation precision vs expected | 0.932 | 0.906 |
| Citation recall vs expected | 0.788 | **0.846** |
| Claim citation coverage | 1.000 | 1.000 |
| First-try valid | 0.900 | 0.900 |
| Safe fallbacks | 1 | 1 |
| Provider safety blocks | 0 | 0 |
| p50 / p95 end-to-end latency | 3.8 s / 14.4 s | **8.2 s / 18.5 s** |
| Tokens in / out (final rows) | 145,630 / 14,712 | 140,242 / 15,450 |
| Paid-equivalent estimate (charged: $0) | $0.08 | $0.08 final rows + $0.05 counted for the 4 failed calls |

Latency got worse while retrieval latency stayed ~150 ms; the increase
happened together with Gemini 503s, so it is most likely provider-side load
on the free tier. It is not proven and is reported as measured.

Per-item changes (k=60 → k=10):

- **Fixed:** dev-03 (217, 21 days) and dev-04 (182, 40 hours) are now answered
  from the right article; dev-14 is now answered (173, plus an extra cite of 442).
- **Worse:** dev-09 — the first output's quote was > 400 chars / not verbatim,
  the repair failed too → safe fallback (previously answered from 165 after a
  repair). dev-23 — 12¹ was retrieved at #1, but the model answered only from
  28¹ and said the delivery-delay penalty is not in the sources (generation
  error). dev-25 — now cites Labor Code 174, 335, 565 besides consumer-law 22
  (precision 0.25).
- **Unchanged failures:** dev-08 (160 still rank 11, semantic miss on the
  everyday-language resignation question), dev-19 (130 not retrieved for the
  injection-padded question; the system prompt was not revealed).

Generation is not deterministic between runs; part of the dev-09 / dev-23
difference is run-to-run variance, not the retrieval change. Valid citations
mean the quoted words exist in the cited article — **not** that the answer is
legally correct. Holdout was not run.

## Holdout answer eval — one-time run (2026-11-11) — PRELIMINARY

**The holdout benchmark has not been human-reviewed** (questions, expected
statuses, reference articles and answers were AI-drafted). These numbers
are a preliminary assessment only.

Frozen baseline (no change made after seeing holdout):

| Item | Value |
|---|---|
| Git commit | `801e957` (second pass shows `801e957-dirty` only because the first pass's result files were untracked; no tracked file differed) |
| Corpus | Consumer law `7c759eec74a0` (live fetch, edition 02.02.2026); Labor Code `af3d92c6ade6` (local import, confirmed by live fetch, edition “15.10.2026 01”) |
| Prompt | `answer-v1`, sha256(system prompt + schema) `c30ae786c78d3557` |
| Model | `gemini-3.5-flash-lite` (provider-reported version: `gemini-3.5-flash-lite`), free tier, thinking `minimal`, max 2048 output tokens |
| Retrieval | e5-large, top_k 6, candidates 40, **RRF k 10**, weights semantic 1.0 / FTS 0.25 / article number 2.0, title list off, **reranker off**, context 6000 tokens |

Run: all 20 items once (`20261111T145607Z_answers_holdout`); hold-10 ended
with a transient `provider_unavailable`; it was retried once with
`--resume --retry-errors` and failed again with `provider_unavailable`
(final report `20261111T145638Z_answers_holdout`). Both failed attempts are
kept in `evals/results/checkpoints/answers_holdout.attempts.jsonl` and
counted below. No further retries.

| Metric (20 holdout items) | Value |
|---|---|
| Status accuracy (status match, not answer/legal accuracy) | 0.900 (18/20) |
| — expected `answered` | 0.882 (15/17) |
| — abstain / clarify | 1.000 (3/3: 1 clarification, 2 out-of-corpus) |
| Citation precision vs expected articles | 0.900 |
| Citation recall vs expected articles | 0.824 |
| Claim citation coverage | 1.000 |
| First-try valid output | 0.900 (2 needed a repair) |
| Citation validation errors | quote not found verbatim ×2, no verifiable quote ×1 |
| Safe fallbacks | 0 |
| Provider safety blocks | 0 |
| Transient provider errors | **2** (both on hold-10; unresolved → counted as an error) |
| Attempts / LLM calls | 21 attempts, 23 calls |
| Latency p50 / p95 (end-to-end) | 4.7 s / 14.3 s |
| Tokens in / out (all attempts) | 84,125 / 8,077 |
| Charged | $0 (free tier); paid-equivalent estimate $0.071 over all attempts |

Failing or imperfect items (none hidden):

- **hold-08** (multi_article, overtime → time off) → `insufficient_evidence`;
  the model said the sources do not cover it (expected art. 262).
- **hold-10** (false premise, pregnancy) → `error provider_unavailable` twice;
  the first output had also failed quote validation before the repair call.
- **hold-16** (paraphrase, phone defect under warranty) → answered from art. 15
  (free repair within 20 days) instead of the expected art. 13; plausible but
  counted as a recall miss (15 is listed as also-acceptable for precision).
- **hold-03** → also cites art. 496 and adds a claim about temporary workers;
  needs manual check of whether that claim is supported.
- **hold-05** → extra cite of art. 258; **hold-06** (Cyrillic) → extra claim
  about disability leave from art. 429.
- **hold-01** → first output quoted a non-contiguous sentence (rejected by
  validation), the repair produced a valid quote.

## Future work (from dev + holdout; holdout NOT used for tuning)

The holdout set was used **once, for a final assessment** of the frozen
baseline; no code, prompt or retrieval change was made after seeing its
results. Its results are now known, so using it again to choose between
configurations would turn it into tuning data. Further tuning therefore
needs **new development questions** (and ideally a fresh holdout).

1. Human review of all 50 benchmark items (`evals/review/`), then re-label
   results; until then every number above is preliminary.
2. Retrieval: everyday-language paraphrases (dev-08 / 160), multi-aspect
   questions where the second aspect is only a lexical hit (dev-09 / 173),
   injection-padded queries (dev-19 / 130). Candidates: query rewriting or
   per-aspect sub-queries, measured on new dev items.
3. Generation: non-verbatim or over-long quotes (dev-09, dev-14, hold-01,
   hold-10) — prompt/quote guidance or quote extraction help; abstaining
   although the article is in context (dev-23, hold-08); extra citations from
   the other document (dev-25, hold-03/05/06).
4. Provider reliability: Gemini free-tier 5xx/timeouts (`gemini-3.8-flash`
   unusable today, 6 × `provider_unavailable` on 3.5 Flash-Lite across runs (4 dev, 2 holdout));
   a user-facing retry hint already exists, nothing else is automatic.
5. Latency: p50 varied 3.8–8.2 s between dev runs with unchanged retrieval
   (~150 ms); monitor provider latency separately.
6. Semantic faithfulness rubric (`evals/RUBRIC.md`) has not been applied.

## Human review

`python -m evals.build_review_sheet` writes (no API calls):

- `evals/review/review_sheet.md` — one card per item: question and expected
  status, reference answer, document/article, original source text with the
  Lex.uz link, the frozen-baseline model answer with its citations and any
  backend validation errors, and verdict boxes (to‘g‘ri / qisman / noto‘g‘ri /
  noaniq) for question+status, reference answer, source article and model
  answer. **16 items are flagged to review first** (automatic signals: status
  mismatch, provider error, citations outside the expected articles, missed
  expected article, repair/fallback, status changed between dev runs).
- `evals/review/review_form.csv` — one row per item with the four verdict
  columns, corrected reference answer, missing/wrong articles, comment,
  reviewer and date. UTF-8 with BOM (opens in Excel). The generator refuses to
  overwrite a form that already contains reviewer input.

**All 50 items are `not_reviewed`. No item has been reviewed by a human;** the
priority flags are automatic and are not a review. See `evals/review/README.md`.

## Error analysis notes (dev)

- e5-large alone ranked 182, 217, 130, 132 first for their questions; the
  OR-style FTS list ranked long, term-rich chunks above short precise
  articles, so equal-weight fusion pushed correct answers down.
- A title-only FTS list was tried and removed: prefix terms such as `ish:*`
  match dozens of titles.
- Next candidates (measure on dev first): AND-weighted FTS ranking, a small
  reranker, query rewriting for colloquial phrases.
