# Test fixture provenance

Both fixtures are **trimmed copies of real Lex.uz pages**, produced with
`scripts/make_fixture.py`. They keep the original markup of the document header,
the edition selector, all part/section/chapter headings and the listed article blocks of `div#divCont`; everything
else (scripts, menus, the rest of the articles) was dropped. One synthetic
`div.lx_menu` line is added on purpose so tests can assert that navigation text
is never parsed.

| File | Source URL | Fetched (Asia/Tashkent) | Raw page SHA-256 | Articles kept |
|---|---|---|---|---|
| `lexuz_consumer_excerpt.html` | https://lex.uz/docs/-4704 | 2026-11-11 09:44 | `838e60a02fab4dce24d39ee6dd03d55ab30982851be487573931d4bafa6fcd6f` | 1, 2, 3, 4, 12¹, 14 |
| `lexuz_labor_excerpt.html` | https://lex.uz/docs/-6257288 | 2026-11-11 09:42 | `bffb616e655fa77efc2767ee904905c7f103e8d8ccd7b8c57e95200d67a5ad54` | 1, 2, 3, 129, 130, 131, 132 |

Edge cases that real pages did not contain on that date (Cyrillic text in a
Latin page, an amendment that enters into force in the future, a missing
container, removed articles) are produced **synthetically inside the tests** by
modifying these fixtures; those tests say so in their docstrings.

The fixtures are legal texts published by the Ministry of Justice of Uzbekistan
on Lex.uz and are used here only to test parsing.
