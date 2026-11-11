# Setting up the Anthropic API key

**A Claude subscription (claude.ai Pro/Max/Team) does not include API
access.** The API is billed separately, per token, through the Claude
Console (platform.claude.com) with its own prepaid credits or invoice. You
need a Console account with billing set up and an API key.

1. Sign in at https://platform.claude.com (create an organization if asked).
2. **Billing**: add credits (a few USD is enough for this demo and its evals).
3. **Limits** (Settings → Limits): set a monthly spend limit for the
   workspace — a hard stop independent of this app's own budget.
4. **API keys**: create a key, ideally in a dedicated workspace for this
   project. It is shown once.
5. Put it in `.env` with an editor — not in chat, not in a shell command that
   ends up in history, not in git:

   ```
   ANTHROPIC_API_KEY=<paste here>
   LLM_MODEL=claude-haiku-5-5
   ```

   `.env` is in `.gitignore`. Check: `git check-ignore .env` prints `.env`.
6. Verify without printing the key:

   ```bash
   grep -q '^ANTHROPIC_API_KEY=.\+' .env && echo "key present"
   uv run python -m app.cli ask "Sinov muddati davomida ishdan bo'shash mumkinmi?"
   ```

If the key leaks (pasted somewhere, committed), revoke it in the Console
immediately and create a new one.

## Cost of the checks in this repo

- One question with Haiku 5.5 ≈ a few thousand input tokens and a few hundred
  output tokens: a fraction of a cent (estimate; the Console usage page is the source of truth).
- `python -m app.cli eval answers --split dev --max-cost-usd 1` reserves the
  worst case of every call (repairs and SDK retries included) in Redis before
  sending it and stops when the next reservation would exceed 1 USD.
