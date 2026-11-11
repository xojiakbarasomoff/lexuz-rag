# One-minute demo script

> No video has been recorded yet. Before recording, an LLM key and (ideally) the
> public HTTPS deployment are needed; until then the demo runs on localhost.

| Time | Action | What to say |
|---|---|---|
| 0:00 | Open the site (live URL or `http://localhost:8000`). Point at “Qamrab olingan hujjatlar”. | “Two official texts from Lex.uz are indexed: the Labor Code and the Consumer Protection Law. Each shows when the index last checked the source.” |
| 0:10 | Click the example “Sinov muddati davomida ishdan bo‘shash mumkinmi?” → Yuborish. | “The question goes through hybrid search over article-level chunks, then Claude answers using only those articles.” |
| 0:25 | Click a citation chip (e.g. S1) → the source card opens. | “Every claim carries a source id. The backend checked that the id was retrieved and that the quoted words exist in the article — citations come from the database, not from the model.” |
| 0:35 | Click “Lex.uz’da ochish”. | “The link jumps to the exact article anchor on Lex.uz, so anyone can verify the wording.” |
| 0:45 | Ask “Yer solig‘i stavkasi qancha?” | “This is outside the corpus. The system says it has no evidence instead of inventing an answer.” |
| 0:55 | Point at the disclaimer line. | “It explains sources; it is not legal advice and not an official Lex.uz product.” |

Backup plan if the AI provider is unavailable: show the out-of-corpus answer
and the documents list, and explain that generation fails closed.
