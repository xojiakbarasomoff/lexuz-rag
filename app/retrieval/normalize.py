"""Uzbek text normalization for *search only*.

Original article text and citation quotes are never passed through these
functions; they are stored and shown exactly as the source prints them.

PostgreSQL has no Uzbek stemmer, so lexical search uses the 'simple' config on
this normalized text plus conservative prefix matching (see search.py).
"""

from __future__ import annotations

import re
import unicodedata

# Every apostrophe-like character seen in Uzbek Latin text -> ASCII "'".
# U+02BB (ʻ) is the official o‘/g‘ mark, U+02BC (ʼ) the tutuq belgisi;
# users type ', `, ‘, ’ or ´ instead.
_APOSTROPHES = "ʻʼ‘’`´ʹʾʿ′"
_APOS_RE = re.compile(f"[{_APOSTROPHES}]")
_NON_WORD_RE = re.compile(r"[^\w'⁰¹²³⁴⁵⁶⁷⁸⁹]+", re.U)
_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")

# Uzbek Cyrillic -> Latin (official 1995 alphabet). Used to build a *query
# variant*; ambiguous cases (е at word start = "ye") are handled below.
_CYR2LAT = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "yo",
    "ж": "j",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "x",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sh",
    "ъ": "'",
    "ы": "i",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
    "ў": "o'",
    "қ": "q",
    "ғ": "g'",
    "ҳ": "h",
}


def unify_apostrophes(text: str) -> str:
    return _APOS_RE.sub("'", text)


def has_cyrillic(text: str) -> bool:
    return bool(_CYRILLIC_RE.search(text))


def cyrillic_to_latin(text: str) -> str:
    out: list[str] = []
    prev_alpha = False
    for ch in text:
        lower = ch.lower()
        if lower in _CYR2LAT:
            lat = _CYR2LAT[lower]
            if lower == "е" and not prev_alpha:
                lat = "ye"
            if ch.isupper() and lat:
                lat = lat[0].upper() + lat[1:]
            out.append(lat)
            prev_alpha = True
        else:
            out.append(ch)
            prev_alpha = ch.isalpha()
    return "".join(out)


def normalize_for_search(text: str) -> str:
    """Lowercase, NFC, apostrophes removed, punctuation -> spaces.

    Apostrophes are *removed* (boʻshatish, bo'shatish, boshatish -> boshatish)
    so that every spelling users type maps to the same lexical token.
    """
    text = unicodedata.normalize("NFC", text)
    text = unify_apostrophes(text).lower().replace("'", "")
    text = _NON_WORD_RE.sub(" ", text)
    return " ".join(text.split())


# Function words that carry no retrieval signal in questions.
STOPWORDS = frozenset(
    [
        "va",
        "yoki",
        "bilan",
        "uchun",
        "ham",
        "agar",
        "bu",
        "shu",
        "u",
        "ular",
        "men",
        "biz",
        "siz",
        "mi",
        "mumkinmi",
        "qanday",
        "qaysi",
        "nima",
        "nimalar",
        "kerak",
        "kerakmi",
        "bolsa",
        "boladi",
        "bolib",
        "bormi",
        "yoq",
        "qachon",
        "qancha",
        "necha",
        "kim",
        "kimga",
        "nega",
        "haqida",
        "togrisida",
        "edi",
        "ekan",
        "emas",
        "lekin",
        "ammo",
        "hamda",
        "dan",
        "da",
        "ga",
        "ni",
        "ning",
        "the",
    ]
)

# Conservative suffix list for *query* prefix matching (no stemmer for Uzbek in
# PostgreSQL). Longest first; a stem must keep >= 4 characters.
_SUFFIXES = sorted(
    [
        "larining",
        "larini",
        "lariga",
        "laridan",
        "larida",
        "lardan",
        "larda",
        "larga",
        "larni",
        "lari",
        "lar",
        "ning",
        "dagi",
        "dan",
        "da",
        "ga",
        "ka",
        "qa",
        "ni",
        "mi",
        "miz",
        "ingiz",
        "imiz",
        "ish",
        "ishi",
        "ishga",
        "ishni",
        "gan",
        "si",
        "i",
    ],
    key=len,
    reverse=True,
)


def query_stem(token: str, max_len: int = 7) -> str:
    for suf in _SUFFIXES:
        if token.endswith(suf) and len(token) - len(suf) >= 4:
            token = token[: -len(suf)]
            break
    return token[:max_len]


def normalize_for_match(text: str) -> str:
    """Looser normalization used to check that a quote occurs in a source."""
    text = unicodedata.normalize("NFC", text)
    text = unify_apostrophes(text).lower()
    text = re.sub(r"[«»“”„\"]", '"', text)
    text = re.sub(r"[—–‑-]", "-", text)
    return " ".join(text.split())


def query_variants(question: str) -> list[str]:
    """Original question plus a Latin variant when it contains Cyrillic."""
    variants = [question]
    if has_cyrillic(question):
        variants.append(cyrillic_to_latin(question))
    return variants
