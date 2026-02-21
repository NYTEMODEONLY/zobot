# ZoBot

A Discord bot that answers questions about [Zo Computer](https://www.zo.computer/) using the official documentation. Built and hosted on Zo Computer itself.

Powered by **xAI's Grok** (`grok-4-1-fast-reasoning`) with live doc retrieval from [docs.zocomputer.com](https://docs.zocomputer.com/).

## How It Works

- Mention the bot in Discord (`@ZoBot your question here`)
- It fetches the Zo Computer sitemap and retrieves relevant documentation pages
- Passes the doc content as context to Grok for grounded, accurate answers
- Validates all URLs before responding to prevent hallucinated links

## Features

- Live documentation grounding (sitemap refreshed every 12 hours)
- Friendly, conversational response style
- URL validation — only cites real, accessible docs pages
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

## Running 24/7 on Zo Computer

If you have a Zo Computer, you can host this bot as a persistent background service via the Zo dashboard or terminal.

## Project Structure

```
zobot/
├── bot_simple.py      # Main bot logic
├── requirements.txt   # Python dependencies
├── run.sh             # Startup script
├── .env.example       # Environment variable template
└── .gitignore
```

## Built With

- [discord.py](https://discordpy.readthedocs.io/)
- [xAI Grok API](https://x.ai/api)
- [Zo Computer](https://www.zo.computer/)
