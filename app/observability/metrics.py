"""Prometheus metrics. Exposed only on /internal/metrics, which the reverse
proxy blocks and which requires METRICS_TOKEN when it is set."""

from prometheus_client import Counter, Gauge, Histogram

http_requests = Counter("lexuz_http_requests_total", "HTTP requests", ["route", "method", "status"])
http_latency = Histogram(
    "lexuz_http_request_seconds", "HTTP latency", ["route"], buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 40, 80)
)
answers = Counter("lexuz_answers_total", "Answers by status", ["status"])
provider_errors = Counter("lexuz_provider_errors_total", "LLM provider errors", ["code"])
validation_failures = Counter("lexuz_validation_failures_total", "Answer validation failures", ["stage"])
llm_tokens = Counter("lexuz_llm_tokens_total", "LLM tokens (provider-reported)", ["direction"])
llm_cost = Counter("lexuz_llm_estimated_cost_usd_total", "Estimated LLM cost in USD (not an invoice)")
llm_latency = Histogram("lexuz_llm_call_seconds", "LLM call latency", buckets=(0.5, 1, 2, 5, 10, 20, 40, 80))
rate_limited = Counter("lexuz_rate_limited_total", "Requests rejected by guards", ["reason"])
corpus_age_seconds = Gauge("lexuz_corpus_oldest_check_age_seconds", "Age of the oldest document check")
