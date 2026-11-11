"""Publish gate for a parsed document version.

`rejected`     -> structurally wrong (empty, wrong script, wrong document...).
`needs_review` -> plausible but the parser cannot be sure the text is the
                  version in force today (future-effective amendments, large
                  removals, unknown headings). Requires `lexuz approve-version`.
Only a clean result is activated automatically.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date

from app.ingestion.parser_lexuz import ParsedDocument, cyrillic_ratio
from app.ingestion.sources import SourceSpec

MAX_CYRILLIC_RATIO = 0.02
MAX_EMPTY_ARTICLE_RATIO = 0.05
MAX_REMOVED_RATIO = 0.10


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def outcome(self) -> str:
        if self.errors:
            return "rejected"
        if self.review_reasons:
            return "needs_review"
        return "ok"

    def to_dict(self) -> dict:
        return {**asdict(self), "outcome": self.outcome}


def validate_parsed(
    parsed: ParsedDocument,
    spec: SourceSpec,
    *,
    previous_labels: set[str] | None,
    as_of: date,
) -> ValidationReport:
    rep = ValidationReport(warnings=list(parsed.warnings))
    arts = parsed.articles
    labels = [a.label for a in arts]
    rep.stats = {"articles": len(arts), "repealed": sum(a.is_repealed for a in arts)}

    if not arts:
        rep.errors.append("no articles parsed")
        return rep
    if len(arts) < spec.min_articles:
        rep.errors.append(f"only {len(arts)} articles parsed, expected at least {spec.min_articles}")
    if spec.expected_title_contains.lower() not in parsed.title.lower():
        rep.errors.append(f"title {parsed.title!r} does not contain {spec.expected_title_contains!r}")
    dupes = sorted({x for x in labels if labels.count(x) > 1})
    if dupes:
        rep.errors.append(f"duplicate article labels: {dupes[:10]}")

    worst = max(arts, key=lambda a: cyrillic_ratio(a.text + a.title))
    ratio = cyrillic_ratio(worst.text + worst.title)
    rep.stats["max_cyrillic_ratio"] = round(ratio, 4)
    if ratio > MAX_CYRILLIC_RATIO:
        rep.errors.append(f"Cyrillic text in Latin document (article {worst.label}, ratio {ratio:.2%})")

    empty = [a.label for a in arts if not a.text.strip() and not a.is_repealed]
    if len(empty) / len(arts) > MAX_EMPTY_ARTICLE_RATIO:
        rep.errors.append(f"{len(empty)} articles without text: {empty[:10]}")
    elif empty:
        rep.review_reasons.append(f"articles without text and without a repeal note: {empty[:10]}")

    future = {a.label: a.future_effective_dates for a in arts if a.future_effective_dates}
    if future:
        rep.review_reasons.append(
            f"amendments that enter into force after {as_of.isoformat()} in articles {sorted(future)[:10]}"
        )
    if any("unrecognized article heading" in w for w in parsed.warnings):
        rep.review_reasons.append("unrecognized article headings")

    if previous_labels:
        removed = previous_labels - set(labels)
        rep.stats["removed_vs_active"] = len(removed)
        if len(removed) / len(previous_labels) > MAX_REMOVED_RATIO:
            rep.review_reasons.append(f"{len(removed)} articles disappeared compared with the active version")
    return rep
