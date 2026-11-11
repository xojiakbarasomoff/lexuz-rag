"""Pre-approved source documents.

Only URLs listed here can be fetched. There is deliberately no API endpoint or
CLI flag that fetches an arbitrary user-provided URL.

Verification notes (2026-11-11, see docs/data-provenance.md):
- `https://lex.uz/docs/<negative id>` served the Uzbek *Latin* text; the same
  number without the minus sign served Cyrillic. The parser re-checks script
  on every fetch and rejects the version if Cyrillic body text appears.
- Neither page stated an explicit "amalda / kuchini yo'qotgan" status field,
  so `official_status` stays empty unless a parser finds it on the page.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSpec:
    key: str
    lexuz_id: str
    url: str
    language: str
    expected_title_contains: str
    min_articles: int
    short_name: str


SOURCES: dict[str, SourceSpec] = {
    s.key: s
    for s in [
        SourceSpec(
            key="mehnat-kodeksi",
            lexuz_id="-6257288",
            url="https://lex.uz/docs/-6257288",
            language="uz-Latn",
            expected_title_contains="Mehnat kodeksi",
            min_articles=500,
            short_name="Mehnat kodeksi",
        ),
        SourceSpec(
            key="istemolchilar-huquqlari",
            lexuz_id="-4704",
            url="https://lex.uz/docs/-4704",
            language="uz-Latn",
            expected_title_contains="huquqlarini himoya qilish",
            min_articles=25,
            short_name="Isteʼmolchilar huquqlarini himoya qilish toʻgʻrisidagi qonun",
        ),
    ]
}


def get_source(key: str) -> SourceSpec:
    try:
        return SOURCES[key]
    except KeyError:
        raise KeyError(f"Unknown source '{key}'. Allowed: {', '.join(SOURCES)}") from None
