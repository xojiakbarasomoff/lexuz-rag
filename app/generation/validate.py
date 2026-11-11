"""Validation of the model's structured output against the retrieved sources.

Checks (deterministic, no model involved):
- JSON parses and matches the expected shape;
- every source id was actually given to the model;
- every claim of an `answered` result has >= 1 source id and >= 1 quote;
- every quote occurs in the cited source's stored original text
  (whitespace / apostrophe / dash / case differences tolerated);
- no URLs anywhere in model text.

What this does NOT prove: that the claim *means* what the quoted text says.
Semantic faithfulness is measured separately (evals/, manual rubric).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field

from app.retrieval.normalize import unify_apostrophes

_URL_RE = re.compile(r"(https?://|www\.|\b[a-z0-9-]+\.(uz|com|org|net)\b/)", re.I)
MIN_QUOTE, MAX_QUOTE = 8, 400
MAX_CLAIMS, MAX_CLAIM_CHARS = 12, 1500
_DASH_MAP = {c: "-" for c in "—–‑‒"}
_QUOTE_MAP = {c: '"' for c in '«»“”„"'}


def _norm_char(ch: str) -> str:
    ch = unify_apostrophes(ch)
    ch = _DASH_MAP.get(ch, ch)
    ch = _QUOTE_MAP.get(ch, ch)
    return ch.lower()


def normalized_with_map(text: str) -> tuple[str, list[int]]:
    """Normalized text plus, for each normalized char, its index in `text`."""
    text_nfc = unicodedata.normalize("NFC", text)
    out, idx = [], []
    prev_space = True
    for i, ch in enumerate(text_nfc):
        if ch.isspace():
            if not prev_space:
                out.append(" ")
                idx.append(i)
            prev_space = True
            continue
        for c in _norm_char(ch):
            out.append(c)
            idx.append(i)
        prev_space = False
    while out and out[-1] == " ":
        out.pop()
        idx.pop()
    return "".join(out), idx


def find_quote(source_text: str, quote: str) -> str | None:
    """Return the matching slice of the ORIGINAL source text, or None."""
    q, _ = normalized_with_map(quote.strip().strip('"«»“”').strip())
    if len(q) < MIN_QUOTE:
        return None
    s_norm, s_map = normalized_with_map(source_text)
    pos = s_norm.find(q)
    if pos < 0:
        return None
    start, end = s_map[pos], s_map[pos + len(q) - 1] + 1
    return unicodedata.normalize("NFC", source_text)[start:end]


@dataclass
class ValidatedClaim:
    text: str
    source_ids: list[str]
    excerpts: dict[str, list[str]] = field(default_factory=dict)  # source_id -> original-text slices


@dataclass
class ValidationOutcome:
    ok: bool
    status: str | None = None
    claims: list[ValidatedClaim] = field(default_factory=list)
    clarifying_question: str | None = None
    limitations: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def validate_output(raw_text: str, sources: dict[str, str]) -> ValidationOutcome:
    """`sources` maps source id -> stored original article text."""
    errors: list[str] = []
    try:
        data = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        return ValidationOutcome(False, errors=["output is not valid JSON"])
    if not isinstance(data, dict):
        return ValidationOutcome(False, errors=["output is not a JSON object"])

    status = data.get("status")
    if status not in ("answered", "insufficient_evidence", "clarification_needed"):
        return ValidationOutcome(False, errors=[f"invalid status {status!r}"])
    claims_in = data.get("claims") or []
    clarq = (data.get("clarifying_question") or "").strip()
    limitations = [str(x).strip() for x in (data.get("limitations") or []) if str(x).strip()][:5]
    if not isinstance(claims_in, list):
        return ValidationOutcome(False, errors=["claims must be a list"])
    if len(claims_in) > MAX_CLAIMS:
        errors.append(f"too many claims ({len(claims_in)} > {MAX_CLAIMS})")

    for text in [clarq, *limitations]:
        if _URL_RE.search(text):
            errors.append("URLs are not allowed in the answer")

    claims: list[ValidatedClaim] = []
    for n, c in enumerate(claims_in[:MAX_CLAIMS], start=1):
        if not isinstance(c, dict):
            errors.append(f"claim {n}: not an object")
            continue
        text = str(c.get("text") or "").strip()
        ids = [str(x).strip() for x in (c.get("source_ids") or [])]
        quotes = c.get("quotes") or []
        if not text:
            errors.append(f"claim {n}: empty text")
            continue
        if len(text) > MAX_CLAIM_CHARS:
            errors.append(f"claim {n}: too long")
        if _URL_RE.search(text):
            errors.append(f"claim {n}: contains a URL")
        if not ids:
            errors.append(f"claim {n}: no source ids")
        unknown = [i for i in ids if i not in sources]
        if unknown:
            errors.append(f"claim {n}: unknown source ids {unknown}")
        vc = ValidatedClaim(text=text, source_ids=[i for i in dict.fromkeys(ids) if i in sources])
        for q in quotes if isinstance(quotes, list) else []:
            sid = str((q or {}).get("source_id") or "").strip()
            quote = str((q or {}).get("quote") or "")
            if sid not in vc.source_ids:
                errors.append(f"claim {n}: quote cites {sid!r} which is not among the claim's source ids")
                continue
            if len(quote.strip()) > MAX_QUOTE:
                errors.append(f"claim {n}: quote longer than {MAX_QUOTE} characters")
                continue
            found = find_quote(sources[sid], quote)
            if found is None:
                errors.append(f"claim {n}: quote not found verbatim in {sid}: {quote[:80]!r}")
                continue
            vc.excerpts.setdefault(sid, []).append(found)
        if not vc.excerpts:
            errors.append(f"claim {n}: no verifiable quote")
        claims.append(vc)

    if status == "answered" and not claims:
        errors.append("status answered requires at least one claim")
    if status == "clarification_needed" and not clarq:
        errors.append("status clarification_needed requires clarifying_question")

    return ValidationOutcome(
        ok=not errors,
        status=status,
        claims=claims,
        clarifying_question=clarq or None,
        limitations=limitations,
        errors=errors,
    )
