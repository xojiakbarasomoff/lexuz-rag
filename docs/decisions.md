# Decisions

Short ADR-style log. Newest last.

### D1. Modular monolith, no LangChain/LlamaIndex
One codebase, separate processes (api, worker, beat). The pipeline is a few
SQL queries and two provider calls; a framework would hide the parts we need
to test (fusion, validation, budgets).

### D2. Sync SQLAlchemy + psycopg 3; sync FastAPI handlers
Handlers run in the threadpool. Traffic is a small public demo; the slow part
is the LLM call, which is bounded by Redis slots. Simpler code and tests.

### D3. Lex.uz page parsing, not an API
No public API was found; robots.txt is absent; the terms page is a privacy
policy. Only two allow-listed URLs are read, weekly, politely
(docs/data-provenance.md). Local import exists for when fetching is not possible.

### D4. Parser keyed on Lex.uz element classes (`CLAUSE_DEFAULT`, `ACT_TEXT`, …)
Observed on both documents. Element ids are real page anchors → citation
links open the exact article. A publish gate rejects or holds anything that
looks wrong, so a markup change cannot silently replace the active index.

### D5. Future-effective amendments → manual review
Lex.uz prints notes like “…dan kuchga kiradi”. We cannot reliably separate the
future wording from today's, so we refuse to auto-activate.

### D6. Article labels are strings
`12¹`, `27¹`, `28¹` exist. Superscripts from `<sup>` are kept as Unicode.

### D7. Embeddings keyed by `(content_hash, embedding_space)` in their own table
Gives idempotent re-ingestion (unchanged text is not re-embedded) and makes
mixing spaces impossible. The column is an untyped `vector`; we do exact
search (≈ 900 chunks) and skip an ANN index for now. Add a per-space partial
HNSW index with a dimension cast when the corpus grows.

### D8. Local embedding model (fastembed + `intfloat/multilingual-e5-large`)
No credential needed, so retrieval can be evaluated for real; e5 covers Uzbek
(XLM-R base) and documents `query:`/`passage:` prefixes, which we set via env.
Cost: CPU time (≈ 38 min to index the Labor Code on a laptop) and a 687 MB
image + 2.2 GB model download. An API embedding adapter can be added behind
the same interface; it must go through the ingestion budget.

### D9. Claude via the official `anthropic` SDK, structured JSON output, no tools
Originally `claude-opus-5-5`; since D15 the default is `claude-haiku-5-5`. Effort `low`, configurable (`LLM_MODEL`,
`LLM_EFFORT`, prices). A cheaper model (e.g. `claude-haiku-5-5`) can be set
by env; that choice should be made after a live eval on dev. Server-side
refusal fallback (`fallbacks: "default"`) is available for Opus/Sonnet and is off by default since D15 (`LLM_REFUSAL_FALLBACK`); was controlled by
`LLM_REFUSAL_FALLBACK=off`. Thinking cannot be disabled on Opus 5.5; it
counts toward `LLM_MAX_OUTPUT_TOKENS`, which the budget reserves in full.

### D10. Quotes must be verbatim; one repair; then fallback
A claim without a verifiable quote is rejected. After one repair attempt the
user gets `insufficient_evidence` plus related articles — never an
unvalidated answer.

### D11. Weighted RRF, lexical weight 0.25 (tuned on dev)
Equal-weight RRF let a noisy OR-style FTS list push correct articles down
(dev MRR 0.664). FTS weight 0 gave the best dev numbers (R@6 0.865, MRR
0.765) but dev has few exact-term questions, so FTS is kept at 0.25
(R@6 0.827, MRR 0.749) as a tie-breaker for literal terms. Explicit
“N-modda” references use their own list with weight 2.0. A title-only FTS
list was tried and made dev worse; it stays off (`RETRIEVAL_TITLE_LIST`).

### D12. Fail closed when Redis is down
Without Redis we cannot enforce rate limits or the budget, so `/ask` returns
503; catalog and health keep working.

### D13. Public API docs on, no admin HTTP endpoints
`/api/docs` documents a read-only public API, so it stays enabled
(`ENABLE_API_DOCS` can turn it off). Ingestion/approval are CLI/worker only;
there is no admin endpoint to protect. Metrics live under `/internal/`, blocked
by nginx and optionally token-protected.

### D14. Client IP from nginx only
uvicorn `--forwarded-allow-ips` is set to nginx's fixed container IP; nginx
overwrites `X-Forwarded-For` with `$remote_addr`. Clients cannot spoof their
rate-limit identity.

### D15. Default LLM: `claude-haiku-5-5` (verified 2026-11-11)
Checked on the official docs (platform.claude.com: models overview, pricing,
structured outputs). Current API IDs: `claude-opus-5-5`, `claude-sonnet-5-5`,
`claude-haiku-5-5` (all active; retirement not before Sep–Oct 2027). All three
are listed as supporting structured outputs (`output_config.format`).
List prices per 1M tokens: Opus 5.5 $4 / $20, Sonnet 5.5 $2 / $10,
Haiku 5.5 $0.10 / $0.50 for prompts up to 100k tokens ($0.50 / $2.50 above;
our prompts are < 10k). For a public demo with a few-dollar daily budget,
Haiku 5.5 is ~40× cheaper than Opus 5.5; whether its Uzbek legal answers are
good enough is decided by the dev answer eval, not assumed. Switch with
`LLM_MODEL` + the two price variables. Haiku 5.5 has no server-side refusal
fallback, so `LLM_REFUSAL_FALLBACK=off` is the default (set `default` for
Opus/Sonnet). Our JSON schema uses only supported features (no
`minLength`/`maximum` etc.). Haiku 5.5 thinking is adaptive with default
effort `medium`; we send `low` and do not try to disable thinking.

### D16. Budget reservation covers SDK retries
Worst-case reservation = (estimated input × 1.3 + max output) × prices ×
(1 + `LLM_MAX_RETRIES`), so a retried request cannot exceed the cap. The
answer eval uses its own Redis budget scope with `--max-cost-usd` as the limit;
a call whose reservation is refused is never sent and the run stops.
