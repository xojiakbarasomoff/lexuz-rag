"""Parser for Lex.uz document pages (`/docs/<id>`).

Observed structure (verified on the Labor Code and the Consumer Protection Law,
2026-11-11): the legal text lives in `div#divCont`; each direct child is one
element whose first class names its role:

  ACT_TITLE / ACT_FORM        document title lines
  TEXT_HEADER_DEFAULT         part / section / chapter headings
  CLAUSE_DEFAULT              article heading "12-modda. Title" (12<sup>1</sup> for 12¹)
  ACT_TEXT / BY_DEFAULT       paragraphs
  CHANGES_ORIGINS             amendment note printed by Lex.uz
  COMMENT                     Lex.uz editorial comment / "see previous edition" (skipped)
  INDEXES_ON_REF              classifier tags (skipped)
  ACT_ESSENTIAL_ELEMENTS, PUBLICATION_ORIGIN, SIGNATURE, NEW_EDITION   metadata / skipped

The element `id` (e.g. "-6257549") is a real anchor on the page, so
`<url>#<id>` opens that article. Navigation, menus and the per-element
"send suggestion / listen / copy link" widgets are outside the text node we
read and are therefore never part of the extracted text.

Nothing here invents dates: every date is read from the page and left empty
when the page does not print it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

from selectolax.lexbor import LexborHTMLParser

PARSER_VERSION = "lexuz-html-1"

_SUPERSCRIPT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_SUP_RE = re.compile(r"<sup>\s*(\d+)\s*</sup>", re.I)
_BR_RE = re.compile(r"<br\s*/?>", re.I)
_WS_RE = re.compile(r"[ \t ​]+")

ARTICLE_HEAD_RE = re.compile(r"^\s*(?P<label>\d+[⁰¹²³⁴⁵⁶⁷⁸⁹]*)\s*-\s*modda\.?\s*(?P<title>.*)$", re.S)

_MONTHS = {
    "yanvar": 1,
    "fevral": 2,
    "mart": 3,
    "aprel": 4,
    "may": 5,
    "iyun": 6,
    "iyul": 7,
    "avgust": 8,
    "sentabr": 9,
    "oktabr": 10,
    "noyabr": 11,
    "dekabr": 12,
}
_MONTH_ALT = "yanvar|fevral|mart|aprel|may|iyun|iyul|avgust|sentabr|oktabr|noyabr|dekabr"
# Two phrasings seen in Lex.uz amendment notes:
#   "... — 2022-yil 19-apreldan kuchga kiradi)"
#   "... Kuchga kirish sanasi — 2025-yil 25-sentabr)"
EFFECTIVE_FROM_RE = re.compile(
    rf"(?:(?P<y>\d{{4}})-yil\s+(?P<d>\d{{1,2}})-(?P<m>{_MONTH_ALT})\w*\s+kuchga\s+kir"
    rf"|kuchga\s+kirish\s+sanasi\s*[—–-]\s*(?P<y2>\d{{4}})-yil\s+(?P<d2>\d{{1,2}})-(?P<m2>{_MONTH_ALT}))",
    re.I,
)
_HEADER_DATE_NUM_RE = re.compile(r"(?P<date>\d{2}\.\d{2}\.\d{4})\s*yildagi\s+(?P<num>[\w\-–]+?)-son", re.I)
_TITLE_DATE_RE = re.compile(r"(\d{2}\.\d{2}\.\d{4})\.")
_EDITION_RE = re.compile(r"ONDATE2=([0-9.]+(?: \d+)?)&(?:amp;)?action=compare")

_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
_LATIN_RE = re.compile(r"[A-Za-z]")


@dataclass
class ParsedArticle:
    label: str
    title: str
    heading_context: str
    anchor: str | None
    paragraphs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    future_effective_dates: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.paragraphs)

    @property
    def is_repealed(self) -> bool:
        # No body text and the source note says it was removed ("chiqarilgan").
        return not self.text.strip() and any("chiqarilgan" in n.lower() for n in self.notes)


@dataclass
class ParsedDocument:
    title: str
    header_label: str | None
    adoption_date: date | None
    doc_number: str | None
    entry_into_force_date: date | None
    revision_label: str | None
    articles: list[ParsedArticle]
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _clean_html_fragment(html: str) -> str:
    html = _SUP_RE.sub(lambda m: m.group(1).translate(_SUPERSCRIPT), html)
    return _BR_RE.sub("\n", html)


def _node_text(node) -> str:
    # Re-parse the cleaned fragment so <sup> and <br> survive as text.
    frag = LexborHTMLParser(_clean_html_fragment(node.html or ""))
    raw = frag.body.text(separator="") if frag.body else ""
    lines = [_WS_RE.sub(" ", ln).strip() for ln in raw.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def _content_node(elem):
    # The text lives in the child div that carries a `name` attribute.
    for child in elem.iter():
        if child.tag == "div" and "name" in child.attributes:
            return child
    return None


def _parse_ddmmyyyy(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip()[:10], "%d.%m.%Y").date()
    except ValueError:
        return None


def _heading_level(text: str) -> int:
    t = text.strip()
    if re.search(r"\bQISM\b", t):
        return 0
    if re.search(r"\bBO.?LIM\b", t, re.I):
        return 1
    if re.match(r"^\d+[⁰¹²³⁴⁵⁶⁷⁸⁹]*-bob\b", t, re.I):
        return 2
    if re.match(r"^\d+[⁰¹²³⁴⁵⁶⁷⁸⁹]*-§|paragraf", t, re.I):
        return 3
    return 3


def effective_dates_in(note: str) -> list[date]:
    out = []
    for m in EFFECTIVE_FROM_RE.finditer(note):
        y, mo, d = (m["y"], m["m"], m["d"]) if m["y"] else (m["y2"], m["m2"], m["d2"])
        try:
            out.append(date(int(y), _MONTHS[mo.lower()], int(d)))
        except (ValueError, KeyError):
            continue
    return out


def cyrillic_ratio(text: str) -> float:
    cyr = len(_CYRILLIC_RE.findall(text))
    lat = len(_LATIN_RE.findall(text))
    return cyr / max(1, cyr + lat)


def parse_lexuz_html(html: str, *, as_of: date) -> ParsedDocument:
    """Parse a Lex.uz page. `as_of` decides which amendment notes are 'future'."""
    tree = LexborHTMLParser(html)
    container = tree.css_first("div#divCont")
    warnings: list[str] = []
    if container is None:
        return ParsedDocument("", None, None, None, None, None, [], ["container div#divCont not found"])

    title_parts: list[str] = []
    headings: dict[int, str] = {}
    articles: list[ParsedArticle] = []
    current: ParsedArticle | None = None
    counts: dict[str, int] = {}
    preamble: list[str] = []

    for elem in container.iter():
        if elem.tag != "div":
            continue
        cls = (elem.attributes.get("class") or "").split()
        kind = cls[0] if cls else ""
        counts[kind] = counts.get(kind, 0) + 1
        node = _content_node(elem)
        if node is None:
            continue
        text = _node_text(node)
        anchor = node.attributes.get("id")

        if kind in ("ACT_TITLE",):
            if text:
                title_parts.append(text)
        elif kind == "TEXT_HEADER_DEFAULT":
            if not text:
                continue
            level = _heading_level(text)
            headings = {k: v for k, v in headings.items() if k < level}
            headings[level] = text
        elif kind == "CLAUSE_DEFAULT":
            m = ARTICLE_HEAD_RE.match(text.replace("\n", " "))
            if not m:
                warnings.append(f"unrecognized article heading at {anchor}: {text[:80]!r}")
                current = None
                continue
            current = ParsedArticle(
                label=m["label"],
                title=m["title"].strip(),
                heading_context=" › ".join(headings[k] for k in sorted(headings)),
                anchor=anchor,
            )
            articles.append(current)
        elif kind in ("ACT_TEXT", "BY_DEFAULT"):
            if not text:
                continue
            if current is None:
                preamble.append(text)
            else:
                current.paragraphs.append(text)
        elif kind == "CHANGES_ORIGINS":
            if current is not None and text:
                current.notes.append(text)
                for d in effective_dates_in(text):
                    if d > as_of:
                        current.future_effective_dates.append(d.isoformat())
        # COMMENT, INDEXES_ON_REF, ACT_FORM, NEW_EDITION, PUBLICATION_ORIGIN,
        # ACT_ESSENTIAL_ELEMENTS, SIGNATURE: not part of article text.

    header = tree.css_first(".docHeader__col__1 .docHeader__item-label")
    header_label = header.text(strip=True) if header else None
    adoption_date = doc_number = None
    if header_label and (m := _HEADER_DATE_NUM_RE.search(header_label)):
        adoption_date = _parse_ddmmyyyy(m["date"])
        doc_number = m["num"]
    if adoption_date is None:
        page_title = tree.css_first("title")
        if page_title and (m := _TITLE_DATE_RE.search(page_title.text())):
            adoption_date = _parse_ddmmyyyy(m.group(1))

    entry_into_force = None
    for item in tree.css(".docHeader__item"):
        label = item.css_first(".docHeader__item-label")
        value = item.css_first(".docHeader__item-value")
        if label and value and "Кучга кириш" in label.text():
            entry_into_force = _parse_ddmmyyyy(value.text(strip=True))

    editions = _EDITION_RE.findall(html)
    revision_label = editions[0].strip() if editions else None

    return ParsedDocument(
        title=" ".join(title_parts).strip(),
        header_label=header_label,
        adoption_date=adoption_date,
        doc_number=doc_number,
        entry_into_force_date=entry_into_force,
        revision_label=revision_label,
        articles=articles,
        warnings=warnings,
        stats={"element_counts": counts, "preamble_paragraphs": len(preamble)},
    )
