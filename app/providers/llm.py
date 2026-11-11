"""LLM provider adapters.

`gemini` - Google Gemini API via the official `google-genai` SDK
           (`client.models.generate_content`), JSON-schema structured output
           (`response_mime_type="application/json"` + `response_json_schema`).
           No tools, no Google Search grounding, no function calling.
`fake`   - scripted responses for tests; refused in production by Settings.

Verified against SDK google-genai 3.1.0 and https://aistudio.google.com/docs
(models, pricing, structured-output, thinking) on 2026-11-11 — see docs/decisions.md D17.
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
        self.input_tokens = input_tokens  # usage still counted for blocked responses
        self.output_tokens = output_tokens


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int  # includes thinking tokens (billed as output)
    model: str
    finish_reason: str = "STOP"
    thinking_tokens: int = 0


class LLMProvider(Protocol):
    model: str

    def complete_json(self, *, system: str, user: str, schema: dict, max_tokens: int) -> LLMResult: ...


# Finish reasons that mean the content was blocked rather than produced.
_BLOCKED_FINISH = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "LANGUAGE"}
# Server errors worth one bounded SDK retry. 429 is NOT retried: on the free
# tier it usually means the per-minute or per-day quota is used up.
_RETRY_STATUS = [500, 502, 503, 504]


class GeminiProvider:
    def __init__(self, settings: Settings):
        from google import genai
        from google.genai import types

        self._types = types
        key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
        if not key:
            self.client = None  # reported as provider_auth on first use; key never logged
        else:
            self.client = genai.Client(
                api_key=key,
                http_options=types.HttpOptions(
                    timeout=int(settings.llm_timeout_s * 1000),  # milliseconds
                    retry_options=types.HttpRetryOptions(
                        attempts=1 + settings.llm_max_retries,  # includes the first request
                        http_status_codes=_RETRY_STATUS,
                    ),
                ),
            )
        self.model = settings.llm_model
        self.thinking_level = settings.llm_thinking_level

    def complete_json(self, *, system: str, user: str, schema: dict, max_tokens: int) -> LLMResult:
        if self.client is None:
            raise LLMError("provider_auth", "GEMINI_API_KEY is not configured")
        from google.genai import errors

        t = self._types
        config = t.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema,
            max_output_tokens=max_tokens,  # hard cap, includes thinking tokens
            thinking_config=t.ThinkingConfig(thinking_level=self.thinking_level.upper()),
            candidate_count=1,
        )
        try:
            resp = self.client.models.generate_content(model=self.model, contents=user, config=config)
        except errors.ClientError as exc:
            code = getattr(exc, "code", None)
            status = str(getattr(exc, "status", "") or "")
            if code == 429 or status == "RESOURCE_EXHAUSTED":
                raise LLMError("provider_quota", status or "429") from exc
            if code in (401, 403) or status in ("UNAUTHENTICATED", "PERMISSION_DENIED"):
                raise LLMError("provider_auth", status or str(code)) from exc
            if code == 408:
                raise LLMError("provider_timeout", status or "408") from exc
            raise LLMError("provider_bad_request", f"{code} {status}") from exc
        except errors.ServerError as exc:
            code = getattr(exc, "code", None)
            if code == 504:
                raise LLMError("provider_timeout", "504") from exc
            raise LLMError("provider_unavailable", str(code)) from exc
        except errors.APIError as exc:
            raise LLMError("provider_unavailable", str(getattr(exc, "code", ""))) from exc
        except Exception as exc:
            # httpx/httpx2 transport errors are not wrapped by the SDK.
            name = type(exc).__name__
            if "Timeout" in name:
                raise LLMError("provider_timeout", name) from exc
            if "Connect" in name or "Network" in name or "Transport" in name:
                raise LLMError("provider_unavailable", name) from exc
            raise

        usage = resp.usage_metadata
        prompt = (usage.prompt_token_count or 0) if usage else 0
        candidates = (usage.candidates_token_count or 0) if usage else 0
        thoughts = (usage.thoughts_token_count or 0) if usage else 0
        out_tokens = candidates + thoughts  # thinking tokens are billed at the output price

        feedback = getattr(resp, "prompt_feedback", None)
        if feedback is not None and getattr(feedback, "block_reason", None):
            raise LLMError(
                "provider_blocked", str(feedback.block_reason), input_tokens=prompt, output_tokens=out_tokens
            )
        if not resp.candidates:
            # Empty response: let backend validation turn it into a repair / safe fallback.
            return LLMResult("", prompt, out_tokens, self.model, "EMPTY", thoughts)
        finish = resp.candidates[0].finish_reason
        finish_name = getattr(finish, "name", str(finish or "STOP"))
        if finish_name in _BLOCKED_FINISH:
            raise LLMError("provider_blocked", finish_name, input_tokens=prompt, output_tokens=out_tokens)
        try:
            text = resp.text or ""
        except Exception:
            text = ""
        # MAX_TOKENS / OTHER: possibly truncated JSON; validation decides.
        return LLMResult(
            text, prompt, out_tokens, getattr(resp, "model_version", None) or self.model, finish_name, thoughts
        )


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
    if settings.llm_provider == "gemini":
        return GeminiProvider(settings)
    if settings.llm_provider == "fake":
        return FakeLLMProvider()
    raise LLMError("provider_unknown", settings.llm_provider)
