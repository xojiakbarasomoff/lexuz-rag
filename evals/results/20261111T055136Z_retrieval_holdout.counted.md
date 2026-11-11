# Addendum to 20261111T055136Z_retrieval_holdout

Generated from evals/benchmark.jsonl only; retrieval was NOT re-run on holdout.

## Items counted (17 of 20)

hold-01, hold-02, hold-03, hold-04, hold-05, hold-06, hold-07, hold-08, hold-09, hold-10, hold-11, hold-14, hold-15, hold-16, hold-17, hold-18, hold-20

## Items excluded from retrieval metrics (3)

- hold-12 (ambiguous, expected clarification_needed): no expected article; the correct behaviour is to abstain/clarify, so Recall@k is undefined
- hold-13 (out_of_corpus, expected insufficient_evidence): no expected article; the correct behaviour is to abstain/clarify, so Recall@k is undefined
- hold-19 (out_of_corpus, expected insufficient_evidence): no expected article; the correct behaviour is to abstain/clarify, so Recall@k is undefined

These items are scored only in the live answer eval (status accuracy).
