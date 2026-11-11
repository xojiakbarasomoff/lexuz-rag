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
Default model `claude-opus-5-5`, effort `low`, configurable (`LLM_MODEL`,
`LLM_EFFORT`, prices). A cheaper model (e.g. `claude-haiku-5-5`) can be set
by env; that choice should be made after a live eval on dev. Server-side
refusal fallback (`fallbacks: "default"`) is on and can be disabled with
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
