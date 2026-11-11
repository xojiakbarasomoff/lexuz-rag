# Operations

## Daily checks

```bash
C="docker compose -f docker-compose.prod.yml --env-file .env"
curl -fsS https://$DOMAIN/health/ready            # database, corpus, redis, generation
$C exec api python -m app.cli status              # versions, last check, recent jobs
$C exec api python -c "from app.core.limits import get_guards; print(get_guards().budget_state())"
```

## Ingestion

| Task | Command |
|---|---|
| list approved sources | `python -m app.cli sources` |
| check/update one or all | `python -m app.cli ingest mehnat-kodeksi` / `ingest all` |
| import a downloaded page | `python -m app.cli ingest <key> --from-file f.html --source-url <approved url> --retrieved-at <ISO>` |
| inspect a version | `python -m app.cli show-version <id>` |
| approve after manual review | `python -m app.cli approve-version <id>` |
| new embedding model | `EMBEDDING_MODEL=… EMBEDDING_DIM=… python -m app.cli reindex-embeddings`, then eval, then switch env |

The weekly Celery beat job (`Mon 04:15 Asia/Tashkent`) calls the same pipeline.
A `needs_review` result never goes live by itself: read
`validation.review_reasons`, compare the snapshot with Lex.uz, then approve
or ignore.

## Metrics (internal only)

`GET /internal/metrics` (Prometheus format). nginx returns 404 for
`/internal/*`; scrape it from inside the Docker network with
`Authorization: Bearer $METRICS_TOKEN`.

| Metric | Use |
|---|---|
| `lexuz_http_requests_total{route,status}`, `lexuz_http_request_seconds` | traffic, error rate, latency |
| `lexuz_answers_total{status}` | refusal / clarification share |
| `lexuz_provider_errors_total{code}` | provider timeouts, 429, auth |
| `lexuz_validation_failures_total{stage}` | citation repair / fallback |
| `lexuz_llm_tokens_total`, `lexuz_llm_estimated_cost_usd_total` | usage (estimates) |
| `lexuz_rate_limited_total{reason}` | abuse, Redis outages |
| `lexuz_corpus_oldest_check_age_seconds` | corpus freshness (updated on `/health/ready`) |

`usage_events` table keeps per-call estimates (no question text).

## Logs and privacy

- JSON logs with `request_id`; question text is **not** logged
  (`LOG_QUESTION_TEXT` must stay false; it is refused in production).
- API keys matching `sk-ant-…` and `token=`/`api_key=` patterns are redacted
  by the log processor; error responses contain only a public code + message.
- Client IPs are hashed in Redis keys and not written to application logs
  (nginx access logs do contain IPs — set a retention policy).

## Cost control

- Per call: worst-case cost (estimated input × 1.3 + `LLM_MAX_OUTPUT_TOKENS`)
  is reserved atomically in Redis, then replaced by the provider-reported usage.
- A call that times out is counted at its full reservation (it may be billed).
- Reservations never settled (crash) expire after `BUDGET_RESERVATION_TTL_S`
  and are counted as spent.
- `DAILY_AI_BUDGET_USD` (public) and `DAILY_INGESTION_BUDGET_USD` are separate.
- All figures use configured prices and are **estimates**; set a hard limit in
  nothing is charged while the Gemini project has no billing account — keep it
  that way (free tier only, docs/llm-setup.md).
- Redis down → `/ask` closed (fail closed).

## External monitoring (to set up)

- Uptime: an external HTTP check on `https://$DOMAIN/health/ready` every
  1–5 min (e.g. UptimeRobot, Better Stack, Healthchecks). Only add an uptime
  badge to the README once such a monitor exists.
- Error tracking (optional Sentry): if added, set `send_default_pii=False`,
  strip request bodies, and add a `before_send` hook that drops the question
  text and `Authorization` headers.

## Incident playbook

| Symptom | Action |
|---|---|
| `generation: disabled` | Redis down → `$C ps redis`, `$C logs redis`, restart |
| many `provider_*` errors | check provider status page; budget/limits; temporarily lower `MAX_CONCURRENT_LLM_CALLS` |
| `budget_exhausted` early | look at `usage_events`; lower limits; look for abuse in nginx logs |
| ingestion `fetch_*` failures | Lex.uz unreachable — active index keeps serving; retry later or local import |
| `validation_failed` | Lex.uz markup changed → compare snapshot, fix parser, add fixture + test |
