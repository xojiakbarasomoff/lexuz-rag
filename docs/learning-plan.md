# 15-day learning and delivery plan

A calendar for *understanding and owning* this project (≈ 3 weeks of working
days). It is a plan, not a record: commit history shows what was actually
done and when; do not backdate commits to match this table.

For every day: **Result** → **How to verify** → **Concept** → **Interview questions**.

## Week 1

**Day 1 — Scaffold, Docker, health, frontend, deploy skeleton**
- Result: `docker compose up`, `/health/live` + `/health/ready`, static page served.
- Verify: `curl localhost:8000/health/ready`; open the page; `docker compose ps` healthy.
- Concept: process model (api/worker/beat), 12-factor config, non-root containers.
- Questions: Why is readiness different from liveness? Why a modular monolith? What does a healthcheck protect you from?

**Day 2 — Official source fetch and snapshot**
- Result: allow-listed fetcher, gzip snapshot + SHA-256, provenance JSON.
- Verify: `python -m app.cli ingest istemolchilar-huquqlari`; inspect `show-version`.
- Concept: provenance, idempotency, polite crawling (backoff, intervals, conditional requests), SSRF via redirects.
- Questions: How do you stop an SSRF through a redirect? Why store raw bytes and not only parsed text? What do ETag/Last-Modified buy you?

**Day 3 — Article parser and versions**
- Result: parser for `#divCont`, labels like `12¹`, anchors, chapter context, publish gate.
- Verify: `pytest tests/test_parser.py`; compare 3 articles with Lex.uz by eye.
- Concept: brittle HTML parsing, validation gates, atomic activation.
- Questions: Why not an integer article number? What happens when Lex.uz changes its markup? Why is a future-effective note a reason to stop?

**Day 4 — Embeddings and vector retrieval**
- Result: chunks embedded with e5-large; pgvector cosine search.
- Verify: `eval retrieval` with lexical weight 0 → semantic-only numbers.
- Concept: embedding spaces, query/passage prefixes, exact vs ANN search.
- Questions: Why must vectors from two models never be compared? When do you add HNSW? What does the e5 prefix do?

**Day 5 — Vertical slice with cited answers**
- Result: `/api/v1/ask` returns claims + DB-built sources for one document.
- Verify: `python -m app.cli ask "…"` with a key; click a citation in the UI.
- Concept: structured output, grounding, trusted vs untrusted fields.
- Questions: Why does the backend, not the model, produce URLs? What is a source id? How do you stop invented articles?

## Week 2

**Day 6 — Hybrid search and Uzbek normalization**
- Result: FTS + semantic + article-number list fused with RRF; apostrophe/Cyrillic handling.
- Verify: `pytest tests/test_text_units.py`; Cyrillic question returns the same article.
- Concept: RRF, BM25-like ranking vs dense retrieval, normalization without stemming.
- Questions: Why RRF instead of adding scores? Why remove apostrophes for search but never in citations? What breaks without an Uzbek stemmer?

**Day 7 — Citation validation and abstention**
- Result: quote verification, one repair, safe fallback, insufficient-evidence path.
- Verify: `pytest tests/test_answer_validation.py tests/test_answer_integration.py`.
- Concept: validation ≠ faithfulness; abstention as a feature.
- Questions: What does a valid citation prove and not prove? Why only one repair? When do you ask a clarifying question?

**Day 8 — Second document and update pipeline**
- Result: both documents active; weekly beat job; unchanged content → no new embeddings.
- Verify: run ingest twice → `unchanged`; `pytest tests/test_ingestion_integration.py`.
- Concept: content checksums, embedding reuse by hash, one-running-job constraint.
- Questions: How is activation atomic? What happens if the worker crashes mid-job? How are repealed articles removed from search?

**Day 9 — Benchmark and baseline eval**
- Result: 50-item benchmark, `eval check`, baseline retrieval report.
- Verify: `eval check` → 0 problems; report in `evals/results/`.
- Concept: dev/holdout split, leakage, separating retrieval from answer quality.
- Questions: Why keep a holdout untouched? What does Recall@k miss? How would you get human-verified labels?

**Day 10 — Improve retrieval from eval evidence**
- Result: weighted RRF tuned on dev; holdout run once.
- Verify: compare reports (docs/evaluation.md table).
- Concept: error analysis, small-sample noise, not overfitting to dev.
- Questions: Why did equal-weight fusion hurt? Why keep a lexical signal the dev set says is useless? How big must a change be to trust it with 26 items?

## Week 3

**Day 11 — Rate limit and budget**
- Result: per-IP limits, LLM slots, reserve/settle budget in Lua.
- Verify: `pytest tests/test_limits_integration.py` (20 threads, exactly 3 reservations fit).
- Concept: atomicity, race conditions, fail-closed design, estimate vs invoice.
- Questions: Why a Lua script and not GET+SET? What happens to a reservation when the worker dies? Why count a timed-out call as spent?

**Day 12 — Monitoring and security**
- Result: metrics, request ids, redacted logs, CSP, XSS test, injection tests.
- Verify: `/internal/metrics` locally; `tests/frontend_xss_test.js`; nginx blocks `/internal`.
- Concept: privacy-by-default logging, prompt injection threat model, CSP.
- Questions: Why not log questions? What can a prompt injection achieve here, given no tools? How do you prevent `X-Forwarded-For` spoofing?

**Day 13 — CI/CD, backup and rollback**
- Result: CI (ruff, migrations, tests, docker build), CD workflow, backup/restore scripts.
- Verify: CI green on GitHub; restore a dump into a scratch DB.
- Concept: expand/contract migrations, immutable SHA images, deploy locks.
- Questions: Why is app rollback safe but DB rollback not? What do you verify before trusting a backup? Why pin SSH host keys?

**Day 14 — Holdout eval and final tests**
- Result: live answer eval on dev, then holdout; manual rubric for a sample.
- Verify: `eval answers --split dev --max-cost-usd 1` report; RUBRIC scores recorded.
- Concept: cost-bounded evaluation, LLM-judge limits.
- Questions: How do you measure faithfulness? What is the cost per answer? When would you switch to a cheaper model?

**Day 15 — Docs, demo, explanation practice**
- Result: README status table up to date, 1-minute demo recorded (if deployed).
- Verify: a teammate sets it up from README alone.
- Concept: communicating limits honestly.
- Questions: Explain the whole request path in 2 minutes. What would you build next and why? What are the legal/ethical limits of this tool?
