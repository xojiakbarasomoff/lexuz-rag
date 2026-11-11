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

### D9. Claude via the official `anthropic` SDK, structured JSON output, no tools — *superseded by D17*
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

### D15. Default LLM: `claude-haiku-5-5` (verified 2026-11-11) — *superseded by D17*
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

### D17. Generation moved to Google Gemini API (`gemini-3.8-flash`, free tier)
Decision by the project owner: the app's LLM provider is Gemini; Anthropic
code, settings and the `anthropic` dependency were removed. Verified on
2026-11-11 (ai.google.dev now redirects to aistudio.google.com/docs):
- SDK: `google-genai` (3.1.0 locked); the old `google-generativeai` is
  deprecated (libraries page). Call: `client.models.generate_content` with
  `response_mime_type="application/json"` + `response_json_schema` (SDK field
  docs list the supported keywords; ours — `type`, `properties`, `required`,
  `items`, `enum`, `additionalProperties` — are all supported).
- Model: `gemini-3.8-flash` is marked **Stable** on the models page, has a
  free tier (“Free of charge” input/output on the pricing page), thinking
  levels low/medium/high (default medium; `minimal` rejected). Paid list price
  $0.75 / $3.75 per 1M (through 2026-12-31), output price includes thinking.
- Alternative: `gemini-3.5-flash-lite` (stable, free tier, default thinking
  `minimal`, paid $0.30 / $2.50). Switch via `LLM_MODEL` + prices +
  `LLM_THINKING_LEVEL=minimal` if 3.8 Flash quota or latency is a problem.
- `gemini-2.5-flash` is deprecated (auto-routed to 3.5 Flash-Lite from
  2026-12-01) and is not used.
- No tools: no `tools`, no Google Search grounding, no function calling.
- Usage: `prompt_token_count` → input; `candidates_token_count +
  thoughts_token_count` → output (both billed as output on paid tiers).

### D18. Free tier only; no automatic paid fallback
The free tier is the only supported mode. There is no fallback to another
model/provider. Free-tier numeric limits are shown only in AI Studio, so the
app has its own project-wide caps (`LLM_GLOBAL_CALLS_PER_MINUTE=5`,
`LLM_GLOBAL_CALLS_PER_DAY=200`, counted in Pacific days like Google's RPD),
`MAX_CONCURRENT_LLM_CALLS=1`, per-IP 3/min and 20/day, 2048 output tokens.
A 429 is never retried; it sets a 2-minute block in Redis. Budget accounting
uses paid-equivalent prices as a conservative ceiling even though the free
tier is not charged.

### D19. Data-use constraints of the free tier
Unpaid-service content may be used by Google to improve products and read by
human reviewers; personal/confidential data must not be submitted; users must
be 18+; free-tier API clients must not be offered to EEA/CH/UK users. The UI
shows a short notice, raw questions are not logged, and a public launch is
blocked until EEA/CH/UK access is restricted (docs/llm-setup.md).

### D20. Default model changed to `gemini-3.5-flash-lite` after testing with the real key
On 2026-11-11, with the project's free-tier key:
- `models.get("gemini-3.8-flash")` succeeded (Gemini 3.8 Flash, 1,048,576 input /
  65,536 output tokens, `generateContent` supported), but our request and then a
  tiny structured-output probe both failed: the app's call hit the 60 s client
  timeout, the probe got `504 DEADLINE_EXCEEDED` after ~178 s. Only those two
  calls were made; no retry loop.
- The same tiny probe on `gemini-3.5-flash-lite` (stable, free tier per the
  pricing page) returned valid JSON in 1.2 s.
- Default is now `gemini-3.5-flash-lite`, thinking level `minimal` (model
  default), paid-equivalent price $0.30 / $2.50 per 1M for estimates. Still
  free tier only, no automatic fallback between models at runtime: switching
  back to 3.8 Flash is a config change (`LLM_MODEL`, `LLM_THINKING_LEVEL=low`,
  prices) after it is verified to respond.

### D21. Provider safety blocks are a separate API status
`provider_blocked` (API response only; the LLM output schema keeps its three
statuses) is returned when Gemini's safety filter blocks the prompt or the
answer. It is not merged into `insufficient_evidence`, because a block says
nothing about whether the sources cover the question. Evals count it
separately.

### D22. RRF k lowered from 60 to 10 (dev diagnostics, 2026-11-11)
`python -m evals.diagnose_retrieval --split dev` showed where the expected
articles of the failing dev items were lost (benchmark references checked
against the source text first: they were correct, nothing was changed in the
benchmark):

| Item | Article | Semantic | Lexical | Fused (k=60) | Lost at |
|---|---|---|---|---|---|
| dev-03 | 217 | #1 (dist 0.120) | — | #10 | fusion |
| dev-04 | 182 | #1 (dist 0.120) | — | #9 | fusion |
| dev-08 | 160 | #9 (dist 0.207) | — | #12 | semantic (paraphrase) |
| dev-09 | 173 | — | #5 | #34 | lexical-only hit, weight 0.25 |
| dev-19 | 130 | — | — | — | query dominated by injection text |

Parsing, chunking and the context limit were not the cause. With k=60 the RRF
curve is so flat that any article present in both lists (e.g. semantic #4 +
lexical #11) beats the semantic #1 article that has no lexical match.

Same 26 dev items, retrieval only (`--k 10`), no holdout:

| Config | R@1 | R@3 | R@6 | R@10 | MRR | p50 ms |
|---|---|---|---|---|---|---|
| k=60, lex 0.25 (before) | 0.635 | 0.827 | 0.827 | 0.904 | 0.749 | 149 |
| k=30 | 0.635 | 0.827 | 0.904 | 0.904 | 0.750 | 144 |
| k=20 | 0.635 | 0.827 | 0.904 | 0.904 | 0.758 | 172 |
| **k=10 (chosen)** | **0.712** | 0.827 | **0.904** | 0.904 | **0.796** | 150 |
| k=5 | 0.712 | 0.827 | 0.904 | 0.904 | 0.795 | 147 |
| k=10, lex 0.5 | 0.673 | 0.865 | 0.904 | 0.904 | 0.782 | 151 |
| k=10, lex 0.1 | 0.712 | 0.827 | 0.865 | 0.942 | 0.785 | 142 |
| k=10, pool 80 | 0.712 | — | 0.904 | 0.904 | 0.797 | 155 |
| k=10 + bge-reranker-v2-m3-int8 (pool 20) | 0.731 | 0.846 | 0.904 | 0.904 | 0.802 | **16 729** |

Per-item comparison k=60 → k=10 (`python -m evals.compare_retrieval`):
fixed 217 (#10→#1) and 182 (#9→#1); nothing left the top 6; inside the top 6
three articles moved down: 262 (#2→#5), 129 (#2→#4), 22 (#1→#2); 312 and 160
moved up (160 still #11, outside the context).

The reranker is implemented (`RETRIEVAL_RERANKER`, off by default) but not
enabled: +0.006 MRR is not worth ~110× retrieval latency on CPU.
Still unsolved: dev-08 (160), dev-09 second aspect (173), dev-19 (130).
