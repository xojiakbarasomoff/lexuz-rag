# Data provenance

## Sources (MVP)

| Key | Document | URL (Uzbek Latin) | Checked on 2026-11-11 |
|---|---|---|---|
| `mehnat-kodeksi` | Oʻzbekiston Respublikasining Mehnat kodeksi | https://lex.uz/docs/-6257288 | page title date 28.10.2022; “Кучга кириш санаси” 30.04.2023; latest edition in the selector “15.10.2026 01”; 593 articles |
| `istemolchilar-huquqlari` | Isteʼmolchilarning huquqlarini himoya qilish toʻgʻrisida (221-I, 26.04.1996) | https://lex.uz/docs/-4704 | “Кучга кириш санаси” 17.05.1996; latest edition “02.02.2026”; 33 articles (incl. 12¹, 27¹, 28¹) |

How the URLs were verified:

- `https://lex.uz/docs/-6257288` and `/docs/-4704` (negative id) returned the
  Latin text; `/docs/6257288` returned Cyrillic. The parser re-checks script on
  every run and rejects a version whose article text contains Cyrillic.
- Neither page prints an explicit status field (“amalda”, “kuchini yoʻqotgan”),
  so `official_status` is left empty. Dates shown in the UI come only from the page.
- “Latest edition” is the first entry of the page’s edition comparison list. It
  is a label printed by the source, not a computed effective date.

## Access method and terms

- No official public API was found. `https://lex.uz/robots.txt` returned a
  redirect to a 404 page (no robots rules published). `https://lex.uz/agreement`
  (“Foydalanish shartlari”) contained the privacy policy only and no rule about
  automated reading of public documents.
- The project therefore reads **only the two public document pages above**, at
  low frequency (weekly schedule, ≥10 s between requests, 3 retries with
  exponential backoff, descriptive User-Agent, size cap). There is no endpoint
  or flag that fetches an arbitrary URL; redirects are re-checked against the
  host allow-list (`lex.uz`, `www.lex.uz`).
- If the operator of Lex.uz publishes rules that forbid this, stop the
  scheduler (`beat`) and switch to manual local imports.
- Lex.uz did not return `ETag`/`Last-Modified` on 2026-11-11. The fetcher sends
  conditional headers when they appear; otherwise change detection is the
  checksum of the parsed content.

This is not an official Lex.uz product and has no affiliation with the Ministry of Justice.

## What is stored per version

| Field | Meaning |
|---|---|
| `raw_snapshot_path` | gzip of the exact bytes received (`SNAPSHOT_DIR/<source>/<UTC time>_<sha12>.html.gz`) |
| `raw_checksum` | SHA-256 of those bytes |
| `content_checksum` | SHA-256 of the parsed articles + parser version (decides “changed or not”) |
| `source_kind` | `live_fetch` or `local_import` |
| `provenance` | URL, final URL, HTTP status, selected headers, parsed title/number/dates; `last_live_verification` when a later live fetch found identical content |
| `validation` | publish-gate report (errors, review reasons, stats) |
| `parser_version` | `lexuz-html-1` |

## Local import (not live sync)

When Lex.uz cannot be reached, a person can import a page they downloaded from
the approved URL:

```bash
python -m app.cli ingest mehnat-kodeksi --from-file page.html \
  --source-url https://lex.uz/docs/-6257288 \
  --retrieved-at 2026-11-11T09:42:00+05:00 --note "downloaded manually"
```

The version is marked `local_import` and the UI/API expose `source_kind`.

### Current corpus history (dev environment, 2026-11-11)

- Consumer Protection Law: live fetch, activated.
- Labor Code: the first live fetch failed (`fetch_network`, DNS). The page had
  been fetched with curl from the approved URL ~20 minutes earlier during
  parser development (SHA-256 `bffb616e…a5ad54`); that file was imported as a
  `local_import` with this note. A later live fetch is recorded in
  `provenance.last_live_verification` when it returns identical content.

## Publish gate

| Outcome | Examples | Effect |
|---|---|---|
| `rejected` | no `#divCont`, < min articles, wrong title, duplicate labels, Cyrillic in Latin text, many empty articles | stored for audit, never indexed |
| `needs_review` | amendment note with an entry-into-force date after today (Asia/Tashkent), > 10 % of articles disappeared, unknown headings, empty article without repeal note | indexed but **not** activated; `python -m app.cli approve-version <id>` after a human check |
| `ok` | — | activated atomically |

Future-effective amendments: Lex.uz notes look like
“… — 2022-yil 19-apreldan kuchga kiradi” or “Kuchga kirish sanasi — 2025-yil 2-noyabr”.
The parser cannot separate the future wording from the current one reliably,
so such a version waits for review instead of mixing both texts.

## Test fixtures

`tests/fixtures/` holds trimmed copies of the two real pages; see
`tests/fixtures/PROVENANCE.md` for URLs, fetch times and raw hashes.
