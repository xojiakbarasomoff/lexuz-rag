# Eval report — retrieval / holdout

- Date: 2026-11-11T05:51:26.769357+00:00
- Git commit: `7df3c26-dirty`
- Items: 17
- Embedding space: `fastembed:intfloat/multilingual-e5-large:1024`
- Retrieval config: {'top_k': 6, 'candidates': 40, 'rrf_k': 60, 'context_max_tokens': 6000}
- Benchmark manual verification: ai_drafted_unverified (no human review recorded yet)
- Corpus:
  - istemolchilar-huquqlari: version `7c759eec74a0` (live_fetch, revision 02.02.2026, fetched 2026-11-11T05:01:53.614969+00:00)
  - mehnat-kodeksi: version `af3d92c6ade6` (local_import, revision 15.10.2026 01, fetched 2026-11-11T04:42:00+00:00)

## Results (article-level, active corpus only)

| metric | value |
|---|---|
| recall@1 | 0.706 |
| recall@3 | 0.882 |
| recall@5 | 1.0 |
| recall@6 | 1.0 |
| mrr | 0.801 |
| latency_ms_p50 | 221.9 |
| latency_ms_p95 | 384.8 |
| samples | 17 |

Latency covers query embedding + SQL on the eval machine; it excludes the LLM.

## By question type

| type | n | recall@top_k |
|---|---|---|
| fact | 7 | 1.0 |
| paraphrase | 2 | 1.0 |
| script_variant | 3 | 1.0 |
| multi_article | 2 | 1.0 |
| false_premise | 2 | 1.0 |
| prompt_injection | 1 | 1.0 |

## Misses (relevant article not in top_k)

- none
