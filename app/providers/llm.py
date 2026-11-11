"""LLM provider adapters.

`anthropic` - Claude via the official `anthropic` Python SDK, JSON-schema
              structured output (`output_config.format`), no tools.
`fake`      - scripted responses for tests; refused in production by Settings.

The model never gets tools: no shell, DB, URL fetch or any other execution.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings


class LLMError(Exception):
    """`code` is stable and mapped to a user-facing message in the API layer."""

    # Codes for which the provider did not bill the call (safe to release the budget reservation).
    NOT_BILLED = {"provider_auth", "provider_bad_request", "provider_rate_limited", "provider_quota"}

    def __init__(self, code: str, detail: str = "", *, input_tokens: int = 0, output_tokens: int = 0):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.input_tokens = input_tokens  # usage still billed for refusals / truncation
        self.output_tokens = output_tokens


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    model: str


class LLMProvider(Protocol):
    model: str

    def complete_json(self, *, system: str, user: str, schema: dict, max_tokens: int) -> LLMResult: ...


class AnthropicProvider:
    BETA_FALLBACK = "server-side-fallback-2026-07-01"

    def __init__(self, settings: Settings):
        import anthropic

        self._anthropic = anthropic
        # Credentials resolve from ANTHROPIC_API_KEY (never logged, never returned).
        self.client = anthropic.Anthropic(timeout=settings.llm_timeout_s, max_retries=settings.llm_max_retries)
        self.model = settings.llm_model
        self.effort = settings.llm_effort
        self.fallback = settings.llm_refusal_fallback

    def complete_json(self, *, system: str, user: str, schema: dict, max_tokens: int) -> LLMResult:
        a = self._anthropic
        params = dict(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
        )
        try:
            if self.fallback == "default":
                resp = self.client.beta.messages.create(betas=[self.BETA_FALLBACK], fallbacks="default", **params)
            else:
                resp = self.client.messages.create(**params)
        except a.APITimeoutError as exc:
            raise LLMError("provider_timeout", type(exc).__name__) from exc
        except a.RateLimitError as exc:
            raise LLMError("provider_rate_limited", type(exc).__name__) from exc
        except (a.AuthenticationError, a.PermissionDeniedError) as exc:
            raise LLMError("provider_auth", type(exc).__name__) from exc
        except a.EnforcedSpendLimitReachedError as exc:
            raise LLMError("provider_quota", type(exc).__name__) from exc
        except a.BadRequestError as exc:
            raise LLMError("provider_bad_request", getattr(exc, "message", "")[:300]) from exc
        except a.APIStatusError as exc:
            raise LLMError("provider_unavailable", f"status {exc.status_code}") from exc
        except a.APIConnectionError as exc:
            raise LLMError("provider_unavailable", type(exc).__name__) from exc

        usage = resp.usage
        in_tok = (
            (usage.input_tokens or 0)
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
            + (getattr(usage, "cache_read_input_tokens", 0) or 0)
        )
        out_tok = usage.output_tokens or 0
        if resp.stop_reason == "refusal":
            raise LLMError("provider_refused", "refusal", input_tokens=in_tok, output_tokens=out_tok)
        if resp.stop_reason == "max_tokens":
            raise LLMError("provider_truncated", "max_tokens", input_tokens=in_tok, output_tokens=out_tok)
        text = next((b.text for b in resp.content if b.type == "text"), "")
        return LLMResult(text=text, input_tokens=in_tok, output_tokens=out_tok, model=resp.model)


class FakeLLMProvider:
    """Test double. `script` returns a dict/str per call, or raises LLMError."""

    def __init__(self, script: Callable[[str, str], dict | str] | None = None, model: str = "fake-llm"):
        self.model = model
        self.calls: list[dict] = []
        self.script = script or (
            lambda system, user: {
                "status": "insufficient_evidence",
                "claims": [],
                "clarifying_question": "",
                "limitations": [],
            }
        )

    def complete_json(self, *, system: str, user: str, schema: dict, max_tokens: int) -> LLMResult:
        self.calls.append({"system": system, "user": user})
        out = self.script(system, user)
        text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
        return LLMResult(
            text=text, input_tokens=len(system + user) // 4, output_tokens=len(text) // 4, model=self.model
        )


def get_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "anthropic":
        return AnthropicProvider(settings)
    if settings.llm_provider == "fake":
        return FakeLLMProvider()
    raise LLMError("provider_unknown", settings.llm_provider)
