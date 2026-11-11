# Setting up the Gemini API key (free tier only)

The app generates answers with the Google Gemini API through the official
`google-genai` SDK. This project is configured for the **unpaid (free) tier
only**: do not enable billing on the Google Cloud project that owns the key,
and the app never switches to a paid model or provider by itself.

## 1. Get a key in Google AI Studio

1. Open https://aistudio.google.com/apikey and sign in with a Google account
   (you must be 18+ — Gemini API terms).
2. Accept the Gemini API terms. New users get a default Google Cloud project
   and key automatically; otherwise click **Create API key**.
3. Do **not** set up billing for that project. Per the Gemini API Additional
   Terms, API use is a *Paid Service* only through a project with an active
   billing account; without billing it is the unpaid quota.
4. In AI Studio, open the rate-limit view for the project and note the free
   limits for `gemini-3.5-flash-lite` (RPM / TPM / RPD). Google publishes them only
   there; the docs give no fixed numbers.
5. Some imported/externally created projects need verification before they
   can use the free tier; AI Studio says so if it applies.

Availability: Uzbekistan is on the list of countries where the Gemini API
and AI Studio are available (https://aistudio.google.com/docs/available-regions,
checked 2026-11-11). If AI Studio still refuses your account or region, the
free API is not available to you — stop there; this project will not switch
to a paid tier for you.

## 2. Put the key in `.env` (never in chat, git, logs or shell history)

Open `.env` in an editor and set:

```
LLM_PROVIDER=gemini
GEMINI_API_KEY=<paste the key here>
LLM_MODEL=gemini-3.5-flash-lite
LLM_GLOBAL_CALLS_PER_MINUTE=<at or below the RPM AI Studio shows>
LLM_GLOBAL_CALLS_PER_DAY=<at or below the RPD AI Studio shows>
```

- `.env` is git-ignored (`git check-ignore .env` prints `.env`).
- The app reads `GEMINI_API_KEY` into a `SecretStr` and passes it to
  `genai.Client(api_key=…)` explicitly. Do not also set `GOOGLE_API_KEY`: when
  the SDK reads env vars itself, `GOOGLE_API_KEY` wins over `GEMINI_API_KEY`.
- HTTP client loggers are silenced and log output is scrubbed for
  `AIza…`-style keys.

Check without printing the key:

```bash
grep -q '^GEMINI_API_KEY=.\+' .env && echo "key present"
uv run python -m app.cli ask "Sinov muddati davomida ishdan bo'shash mumkinmi?"
```

If a key leaks, delete it in AI Studio and create a new one.

## 3. What the free tier means for this demo (Gemini API Additional Terms, effective 2026-03-23)

| Rule (unpaid services) | Consequence here |
|---|---|
| Google uses submitted content and responses to provide, improve and develop its products and ML technologies; **human reviewers may read** inputs and outputs | UI tells users not to type personal/confidential data; the app does not log raw questions |
| “Do not submit sensitive, confidential, or personal information” | Same notice; questions should describe the rule, not the person's case |
| Only Paid Services may be used for API clients made available to users in the **EEA, Switzerland or the UK** | A public free-tier deployment must not be offered to those users (geo-restrict or stay private). Not solved yet — blocker for public launch |
| Users must be 18+; clients must not be directed at or likely used by minors | UI states 18+ |

Sources: https://aistudio.google.com/docs/terms (Gemini API Additional Terms),
https://aistudio.google.com/docs/pricing (“Used to improve our products: Yes” for the free tier).

## 4. Quota and cost behaviour

- Model: `gemini-3.5-flash-lite` (stable). Free tier: input and output “Free
  of charge”. Paid list price, used only as a conservative estimate:
  $0.30 / 1M input, $2.50 / 1M output incl. thinking tokens.
  (`gemini-3.8-flash` is visible to the key but returned 504 DEADLINE_EXCEEDED
  even for a tiny request on 2026-11-11 — decision D20.)
- Thinking tokens count as output and against `LLM_MAX_OUTPUT_TOKENS`
  (2048). Thinking level `minimal` (the model default).
- SDK retries: at most one, only on HTTP 5xx; **never on 429**.
- On a 429 / `RESOURCE_EXHAUSTED` the app returns “Bepul AI kvotasi hozircha
  tugagan…” and blocks further provider calls for 2 minutes. Daily quotas
  reset at midnight Pacific time.
- Project-wide caps (`LLM_GLOBAL_CALLS_PER_MINUTE/PER_DAY`), one concurrent
  call, per-IP limits (3/min, 20/day) and the Redis budget cap stay in force;
  without Redis, generation is closed.
- `eval answers` paces calls (`--sleep-s 13`), writes a checkpoint after every
  item and stops cleanly on quota exhaustion; continue later with `--resume`.
