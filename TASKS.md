# ZoBot — Task Tracking

## Completed

- ✅ **Initial bot** — Discord bot responding to @mentions using xAI Grok (`grok-4-1-fast-reasoning`)
- ✅ **Docs index** — Sitemap fetch/parse with in-memory allowlist of valid documentation URLs
- ✅ **Doc retrieval** — Grounding via live page fetches; excerpts + URLs passed to model as context
- ✅ **Prompt guardrails** — System prompt forbids invented URLs; citations must come from provided context
- ✅ **URL validator** — Validation and canonicalization of all outgoing URLs with /intro fallback
- ✅ **GitHub release** — Public repo with clean README, .gitignore, .env.example
- ✅ **Full docs snapshot + BM25** — Replaced per-query HTTP fetching with a full sitemap crawl at startup; BM25 index over chunked content for local search (zero HTTP calls per query)
- ✅ **Rate limiting** — Per-user 5s cooldown to prevent token waste
- ✅ **Background refresh** — Snapshot auto-refreshes every 24h without restart

## Current Architecture

```
Startup:
  fetch sitemap → crawl all pages (5 concurrent) → chunk content → BM25 index

On @mention:
  BM25 search (local, no HTTP) → pass top chunks to Grok → Discord reply
  
Background:
  every 24h → re-crawl sitemap → rebuild BM25 index
```

## Future Improvements

- Add per-channel rate limiting in addition to per-user
- Slash commands (`/ask`, `/docs`) in addition to @mentions
- Semantic embedding search (e.g. sentence-transformers) for better handling of vague/conversational queries
- Cache BM25 snapshot to disk so restarts don't require a full re-crawl
- Metrics: log query → matched URLs → answer quality signals
- Multi-turn conversation memory (thread-scoped context)
