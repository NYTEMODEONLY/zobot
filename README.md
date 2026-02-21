# ZoBot

A Discord bot that answers questions about [Zo Computer](https://www.zo.computer/) using the official documentation. Built and hosted on Zo Computer itself.

Powered by **xAI's Grok** (`grok-4-1-fast-reasoning`) with a full local documentation snapshot and BM25 search — no live doc fetches per query.

## How It Works

1. **On startup**, ZoBot crawls every page listed in the Zo Computer docs sitemap and indexes the full content locally using BM25 (a best-in-class text ranking algorithm)
2. **When mentioned** (`@ZoBot your question`), it searches the local index to find the most relevant doc sections — zero outbound HTTP requests per query
3. **Relevant context** is passed to Grok to generate a grounded, accurate answer with real documentation links
4. **Every 24 hours**, the snapshot refreshes automatically in the background to stay current with any doc updates

## Why This Architecture

The naive approach (fetching docs live on every question) wastes API tokens and adds latency. ZoBot instead:

- Crawls all docs **once** at startup with 5 concurrent fetchers
- Stores the full content in memory, chunked and indexed with BM25
- Serves every query from the local index — fast, efficient, no per-query HTTP overhead
- Validates URLs naturally (only indexed URLs can be cited, so hallucinated links are impossible)

## Features

- Full documentation snapshot with BM25 semantic-ish search (much smarter than keyword matching on URL slugs)
- Zero live HTTP calls per query after startup
- 24-hour background refresh keeps the index current
- Per-user rate limiting (5s cooldown) to prevent token waste
- "Still warming up" guard if someone pings before the crawl finishes
- Focused scope — politely declines non-Zo questions

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/NYTEMODEONLY/zobot.git
cd zobot
```

### 2. Install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```
DISCORD_TOKEN=your_discord_bot_token_here
XAI_API_KEY=your_xai_api_key_here
```

**Getting your tokens:**
- **Discord token:** [Discord Developer Portal](https://discord.com/developers/applications) → New Application → Bot → Reset Token
  - Enable **Message Content Intent** under Privileged Gateway Intents
  - Invite the bot with scopes: `bot` and permissions: `Send Messages`, `Read Message History`, `View Channels`
- **xAI API key:** [console.x.ai](https://console.x.ai/) — $25 free credits/month during beta

### 4. Run

```bash
source venv/bin/activate
python bot_simple.py
```

Or use the included script:

```bash
chmod +x run.sh
./run.sh
```

> **Note:** On first start, ZoBot will crawl all Zo Computer documentation pages before going online. This takes a few seconds. The bot will respond "Still warming up" to any pings during this window.

## Running 24/7 on Zo Computer

If you have a Zo Computer, you can host this bot as a persistent background service via the Zo dashboard or terminal. The 24h background refresh means you never need to restart it to get updated docs.

## Project Structure

```
zobot/
├── bot_simple.py      # Main bot — snapshot crawler, BM25 index, Discord events
├── requirements.txt   # Python dependencies (includes rank-bm25)
├── run.sh             # Startup script
├── .env.example       # Environment variable template
├── TASKS.md           # Feature history and improvement ideas
└── .gitignore
```

## Dependencies

| Package | Purpose |
|---|---|
| `discord.py` | Discord bot framework |
| `openai` | xAI Grok API client (OpenAI-compatible) |
| `aiohttp` | Async HTTP for sitemap + doc crawling |
| `beautifulsoup4` + `lxml` | HTML parsing and text extraction |
| `rank-bm25` | Local BM25 search index |
| `python-dotenv` | Environment variable loading |

## Built With

- [discord.py](https://discordpy.readthedocs.io/)
- [xAI Grok API](https://x.ai/api)
- [Zo Computer](https://www.zo.computer/)

---

a [nytemode](https://nytemode.com) project
