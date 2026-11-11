"""Gemini adapter, fully offline: the SDK client is replaced, real SDK types are used.

No test here (or anywhere in CI) calls the real Gemini API.
"""

import pytest
from google.genai import errors, types

from app.core.config import Settings
from app.generation.prompt import OUTPUT_SCHEMA
from app.providers.llm import GeminiProvider, LLMError

FAKE_KEY = "test-key-not-real-0123456789"


def settings(**kw) -> Settings:
    return Settings(llm_provider="gemini", gemini_api_key=FAKE_KEY, app_env="test", **kw)


def response(
    text='{"status":"insufficient_evidence","claims":[],"clarifying_question":"","limitations":[]}',
    finish=types.FinishReason.STOP,
    block=None,
    candidates=True,
):
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(content=types.Content(role="model", parts=[types.Part(text=text)]), finish_reason=finish)
        ]
        if candidates
        else [],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=1200, candidates_token_count=150, thoughts_token_count=80
        ),
        prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason=block) if block else None,
        model_version="gemini-3.8-flash",
    )


@pytest.fixture
def provider(monkeypatch):
    captured = {}

    class FakeModels:
        def __init__(self):
            self.next = response()
            self.calls = []

        def generate_content(self, *, model, contents, config):
            self.calls.append({"model": model, "contents": contents, "config": config})
            if isinstance(self.next, Exception):
                raise self.next
            return self.next

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.models = FakeModels()

    monkeypatch.setattr("google.genai.Client", FakeClient)
    p = GeminiProvider(settings())
    p.captured = captured
    return p


def test_request_uses_json_schema_no_tools_and_bounded_thinking(provider):
    res = provider.complete_json(system="SYS", user="USER", schema=OUTPUT_SCHEMA, max_tokens=2048)
    call = provider.client.models.calls[0]
    cfg = call["config"]
    assert call["model"] == "gemini-3.5-flash-lite" and call["contents"] == "USER"
    assert cfg.response_mime_type == "application/json" and cfg.response_json_schema == OUTPUT_SCHEMA
    assert cfg.system_instruction == "SYS"
    assert not cfg.tools and not cfg.automatic_function_calling  # no tools, no search grounding
    assert cfg.max_output_tokens == 2048
    assert cfg.thinking_config.thinking_level == types.ThinkingLevel.MINIMAL
    # thinking tokens are billed as output
    assert (res.input_tokens, res.output_tokens, res.thinking_tokens) == (1200, 230, 80)


def test_sdk_retries_are_bounded_and_never_on_429(provider):
    opts = provider.captured["http_options"]
    assert opts.timeout == 60_000  # milliseconds
    assert opts.retry_options.attempts == 2  # 1 request + LLM_MAX_RETRIES=1
    assert 429 not in opts.retry_options.http_status_codes
    assert provider.captured["api_key"] == FAKE_KEY


def test_quota_429_maps_to_provider_quota_not_billed(provider):
    provider.client.models.next = errors.ClientError(
        429, {"error": {"code": 429, "message": "Quota exceeded", "status": "RESOURCE_EXHAUSTED"}}
    )
    with pytest.raises(LLMError) as e:
        provider.complete_json(system="s", user="u", schema={}, max_tokens=10)
    assert e.value.code == "provider_quota" and "provider_quota" in LLMError.NOT_BILLED


def test_auth_and_server_errors(provider):
    provider.client.models.next = errors.ClientError(
        403, {"error": {"code": 403, "message": "denied", "status": "PERMISSION_DENIED"}}
    )
    with pytest.raises(LLMError) as e:
        provider.complete_json(system="s", user="u", schema={}, max_tokens=10)
    assert e.value.code == "provider_auth"
    provider.client.models.next = errors.ServerError(
        503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}}
    )
    with pytest.raises(LLMError) as e:
        provider.complete_json(system="s", user="u", schema={}, max_tokens=10)
    assert e.value.code == "provider_unavailable"


def test_transport_timeout_maps_to_provider_timeout(provider):
    import httpx

    provider.client.models.next = httpx.ReadTimeout("timed out")
    with pytest.raises(LLMError) as e:
        provider.complete_json(system="s", user="u", schema={}, max_tokens=10)
    assert e.value.code == "provider_timeout"


def test_safety_block_on_prompt_and_on_candidate(provider):
    provider.client.models.next = response(block=types.BlockedReason.SAFETY, candidates=False)
    with pytest.raises(LLMError) as e:
        provider.complete_json(system="s", user="u", schema={}, max_tokens=10)
    assert e.value.code == "provider_blocked" and e.value.input_tokens == 1200
    provider.client.models.next = response(text="", finish=types.FinishReason.SAFETY)
    with pytest.raises(LLMError) as e:
        provider.complete_json(system="s", user="u", schema={}, max_tokens=10)
    assert e.value.code == "provider_blocked"


def test_empty_and_truncated_responses_go_to_validation(provider):
    provider.client.models.next = response(candidates=False)
    res = provider.complete_json(system="s", user="u", schema={}, max_tokens=10)
    assert res.text == "" and res.finish_reason == "EMPTY"
    provider.client.models.next = response(text='{"status": "answ', finish=types.FinishReason.MAX_TOKENS)
    res = provider.complete_json(system="s", user="u", schema={}, max_tokens=10)
    assert res.finish_reason == "MAX_TOKENS" and res.text.startswith("{")


def test_missing_key_is_provider_auth_and_key_never_in_repr(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    p = GeminiProvider(Settings(llm_provider="gemini", gemini_api_key=None, app_env="test"))
    with pytest.raises(LLMError) as e:
        p.complete_json(system="s", user="u", schema={}, max_tokens=10)
    assert e.value.code == "provider_auth"
    s = settings()
    assert FAKE_KEY not in repr(s) and FAKE_KEY not in str(s.model_dump())


def test_logger_redacts_google_style_keys():
    from app.core.logging import _redact

    leaked = "url ?key=AIzaSyA1234567890abcdefghijklmnopqrstuv and AIzaSyB0000000000000000000000000000000"
    out = _redact(leaked)
    assert "AIzaSy" not in out
