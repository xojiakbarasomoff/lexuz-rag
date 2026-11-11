# Human review of the benchmark

Status: **all 50 items `not_reviewed`.** Nothing in this folder has been
checked by a person yet. The benchmark was drafted with AI assistance; the
priority flags are automatic signals, not a review.

## Files

- `review_sheet.md` — read-only cards (regenerate with
  `python -m evals.build_review_sheet`). Flagged items come first.
- `review_form.csv` — the reviewer fills this in (Excel / LibreOffice, UTF-8).

## How to fill `review_form.csv`

| Column | Value |
|---|---|
| `question_status_verdict` | to‘g‘ri / qisman / noto‘g‘ri / noaniq — is the question realistic and the expected status right? |
| `reference_answer_verdict` | same scale — does the reference answer say only what the article says, incl. conditions? |
| `source_article_verdict` | same scale — are the listed articles the right and complete source? |
| `model_answer_verdict` | same scale — is the model's answer correct and supported by the cited text? |
| `corrected_reference_answer` | your corrected reference answer, if needed |
| `missing_or_wrong_articles` | e.g. `mehnat-kodeksi:173 missing` |
| `comment` | free text |
| `reviewer` | your name |
| `reviewed_at` | YYYY-MM-DD |
| `review_status` | change from `not_reviewed` to `reviewed` only after you checked the item |

Do not change `item_id`, `split`, `type`, `priority`, `priority_reasons`.
A valid citation only proves that the quoted words exist in the cited article;
judge legal correctness against the official text on Lex.uz.
