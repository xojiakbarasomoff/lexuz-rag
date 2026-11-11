# Manual faithfulness rubric

Automatic checks prove that citations point at real text. They do not prove the
answer is a correct reading of the law. A human reviewer scores each answered
item from a live `answers` run (the report JSON contains the claims).

Score every claim:

| Score | Meaning |
|---|---|
| 2 — supported | The cited article states this; conditions/exceptions relevant to the question are kept. |
| 1 — partly | Correct core, but a relevant condition/exception is missing or the wording overstates it. |
| 0 — unsupported | The cited text does not say this, or it contradicts it. |

Score the whole answer:

- **Completeness** (0–2): are the key rules from the reference answer present?
- **Over-reach** (yes/no): does it decide the user's personal case or promise an outcome?
- **Language** (yes/no): Uzbek Latin, plain wording.

Record results in `evals/manual_review.csv`:

```
run_report,item_id,claim_index,claim_score,completeness,over_reach,language_ok,reviewer,date,notes
```

Status of this benchmark: the 50 questions, reference answers and reference
quotes were **drafted with AI assistance** from the article texts and checked
automatically (`python -m app.cli eval check`: every reference quote exists in
the active corpus). **No human legal review has been recorded yet.** Until it is,
treat reference answers as unverified.

An LLM judge may be added later as an extra signal; if so, the judge model,
prompt and its known limits (same-family bias, sensitivity to wording) must be
recorded in the report, and it must not replace this rubric.
