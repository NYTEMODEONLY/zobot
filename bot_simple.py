import discord
import openai
import os
import logging
import re
import asyncio
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from dotenv import load_dotenv
import aiohttp
from bs4 import BeautifulSoup
from rank_bm25 import BM25Okapi

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
XAI_API_KEY = os.getenv('XAI_API_KEY')

if not DISCORD_TOKEN or not XAI_API_KEY:
    print("Error: DISCORD_TOKEN and XAI_API_KEY required in environment")
    exit(1)

DOCS_BASE_URL = "https://docs.zocomputer.com"
DOCS_SITEMAP_URL = f"{DOCS_BASE_URL}/sitemap.xml"
DOCS_INTRO_URL = f"{DOCS_BASE_URL}/intro"
SNAPSHOT_REFRESH_HOURS = 24
CRAWL_CONCURRENCY = 5
RATE_LIMIT_SECONDS = 5


# ---------------------------------------------------------------------------
# Docs Snapshot — crawl everything once, search locally with BM25
# ---------------------------------------------------------------------------

class DocsSnapshot:
    """
    On startup, fetches the sitemap and crawls every doc page.
    Builds a BM25 index over chunked content for fast local search.
    Refreshes every 24 hours in the background — zero HTTP calls per query.
    """

    def __init__(self):
        self.pages = {}          # url -> {title, content}
        self.chunks = []         # [{url, title, text}, ...]
        self.bm25 = None
        self.last_refresh = None
        self.refresh_lock = asyncio.Lock()
        self.session = None
        self.ready = False

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        return self.session

    async def _fetch_sitemap_urls(self):
        session = await self._get_session()
        try:
            async with session.get(DOCS_SITEMAP_URL) as response:
                if response.status != 200:
                    logger.error(f"Sitemap fetch failed: HTTP {response.status}")
                    return []
                content = await response.text()
                root = ET.fromstring(content)
                namespace = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
                urls = []
                for url_elem in root.findall('.//ns:url', namespace):
                    loc = url_elem.find('ns:loc', namespace)
                    if loc is not None and loc.text and loc.text.strip().startswith(DOCS_BASE_URL):
                        urls.append(loc.text.strip())
                logger.info(f"Sitemap: found {len(urls)} URLs")
                return urls
        except Exception as e:
            logger.error(f"Sitemap error: {e}")
            return []

    async def _fetch_page(self, url, semaphore):
        async with semaphore:
            session = await self._get_session()
            try:
                async with session.get(url) as response:
                    if response.status != 200:
                        logger.debug(f"Skip {url}: HTTP {response.status}")
                        return None
                    html = await response.text()
                    soup = BeautifulSoup(html, 'lxml')

                    title = ""
                    title_elem = soup.find('title')
                    if title_elem:
                        title = title_elem.get_text().strip()

                    # Prefer semantic content containers
                    main = (
                        soup.find('main') or
                        soup.find('article') or
                        soup.find('div', class_=re.compile(r'content|main|article|docs', re.I))
                    )
                    target = main or soup.find('body')
                    if not target:
                        return None

                    # Extract structured text
                    parts = []
                    for elem in target.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'li']):
                        text = elem.get_text(strip=True)
                        if text and len(text) > 15:
                            parts.append(text)

                    content = '\n'.join(parts)
                    if not content.strip():
                        return None

                    return {'url': url, 'title': title, 'content': content}
            except Exception as e:
                logger.warning(f"Failed to fetch {url}: {e}")
                return None

    def _build_bm25(self):
        """Chunk all pages and build the BM25 index."""
        self.chunks = []

        for url, page in self.pages.items():
            paragraphs = [p.strip() for p in page['content'].split('\n') if p.strip()]

            # Group into ~3-paragraph chunks for better granularity
            chunk_size = 3
            for i in range(0, len(paragraphs), chunk_size):
                text = ' '.join(paragraphs[i:i + chunk_size])
                if len(text) > 30:
                    self.chunks.append({
                        'url': url,
                        'title': page['title'],
                        'text': text,
                    })

        if not self.chunks:
            logger.warning("No chunks to index — BM25 not built")
            return

        tokenized = [c['text'].lower().split() for c in self.chunks]
        self.bm25 = BM25Okapi(tokenized)
        logger.info(f"BM25 index: {len(self.chunks)} chunks from {len(self.pages)} pages")

    async def refresh(self, force=False):
        async with self.refresh_lock:
            if not force and self.last_refresh:
                age = datetime.now() - self.last_refresh
                if age < timedelta(hours=SNAPSHOT_REFRESH_HOURS):
                    return

            logger.info("Starting full docs snapshot crawl...")
            urls = await self._fetch_sitemap_urls()
            if not urls:
                logger.error("No URLs to crawl — aborting snapshot")
                return

            semaphore = asyncio.Semaphore(CRAWL_CONCURRENCY)
            tasks = [self._fetch_page(url, semaphore) for url in urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            new_pages = {}
            for result in results:
                if isinstance(result, dict) and result:
                    new_pages[result['url']] = {
                        'title': result['title'],
                        'content': result['content'],
                    }

            if not new_pages:
                logger.error("Crawl returned no pages")
                return

            self.pages = new_pages
            self._build_bm25()
            self.last_refresh = datetime.now()
            self.ready = True
            logger.info(f"Snapshot complete: {len(self.pages)} pages indexed")

    def search(self, query, top_k=4):
        """BM25 search over local snapshot. No HTTP calls."""
        if not self.bm25 or not self.chunks:
            intro = self.pages.get(DOCS_INTRO_URL)
            if intro:
                return [{'url': DOCS_INTRO_URL, 'title': intro['title'], 'content': intro['content'][:800]}]
            return []

        scores = self.bm25.get_scores(query.lower().split())
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)

        seen_urls = set()
        results = []
        for idx, score in ranked:
            if score <= 0:
                break
            chunk = self.chunks[idx]
            if chunk['url'] not in seen_urls:
                seen_urls.add(chunk['url'])
                results.append({
                    'url': chunk['url'],
                    'title': chunk['title'],
                    'content': chunk['text'],
                })
            if len(results) >= top_k:
                break

        if not results:
            intro = self.pages.get(DOCS_INTRO_URL)
            if intro:
                results = [{'url': DOCS_INTRO_URL, 'title': intro['title'], 'content': intro['content'][:800]}]

        return results

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

_user_last_request: dict[int, datetime] = {}

def check_rate_limit(user_id: int) -> tuple[bool, float]:
    """Returns (allowed, seconds_remaining)."""
    now = datetime.now()
    last = _user_last_request.get(user_id)
    if last:
        elapsed = (now - last).total_seconds()
        if elapsed < RATE_LIMIT_SECONDS:
            return False, RATE_LIMIT_SECONDS - elapsed
    _user_last_request[user_id] = now
    return True, 0


# ---------------------------------------------------------------------------
# Discord + xAI setup
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

openai_client = openai.AsyncOpenAI(
    api_key=XAI_API_KEY,
    base_url="https://api.x.ai/v1",
)

docs = DocsSnapshot()


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def build_system_prompt(relevant_docs=None):
    valid_urls = '\n'.join(f"- {url}" for url in sorted(docs.pages.keys())[:30])

    base = f"""You are the Zo Computer support bot. Answer ONLY questions about Zo Computer (https://www.zo.computer/).

RESPONSE STYLE:
- Brief and conversational (2-3 short paragraphs max)
- Friendly and encouraging
- Format URLs with angle brackets: <https://example.com> to prevent Discord embeds
- Use proper markdown links: [text](<url>)
- No walls of text or unnecessary lists

CRITICAL URL RULES:
- NEVER invent or guess documentation URLs
- ONLY use URLs from the VALID DOCUMENTATION URLS list below
- Default fallback: <{DOCS_INTRO_URL}>

KNOWLEDGE: websites/apps, AI integrations, file management, automations, hosting, pricing, troubleshooting.

If not about Zo Computer: "I'm specifically here to help with Zo Computer questions. Got any?"

VALID DOCUMENTATION URLS:
{valid_urls}
"""

    if relevant_docs:
        base += "\n\nRELEVANT DOCUMENTATION CONTEXT:\n"
        for doc in relevant_docs:
            base += f"\n--- {doc['title']} ({doc['url']}) ---\n"
            base += doc['content'][:1000]
            base += "\n"

    return base


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def wrap_urls_for_discord(text):
    """Wrap bare URLs in angle brackets to suppress Discord embeds."""
    return re.sub(r'(?<!<)(https?://[^\s<>\)]+)(?!>)', r'<\1>', text)


# ---------------------------------------------------------------------------
# Background refresh
# ---------------------------------------------------------------------------

async def background_refresh():
    while True:
        await asyncio.sleep(SNAPSHOT_REFRESH_HOURS * 3600)
        logger.info("Scheduled: refreshing docs snapshot...")
        await docs.refresh(force=True)


# ---------------------------------------------------------------------------
# Bot events
# ---------------------------------------------------------------------------

@client.event
async def on_ready():
    logger.info(f'{client.user} logged in — building docs snapshot...')
    await docs.refresh(force=True)
    asyncio.create_task(background_refresh())
    logger.info('ZoBot ready')


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if not client.user.mentioned_in(message):
        return

    user_message = (
        message.content
        .replace(f'<@{client.user.id}>', '')
        .replace(f'<@!{client.user.id}>', '')
        .strip()
    )

    if not user_message:
        await message.reply("Hi! 👋 I'm here to help with **Zo Computer** questions. What would you like to know?")
        return

    # Rate limiting
    allowed, remaining = check_rate_limit(message.author.id)
    if not allowed:
        await message.reply(f"Give it {remaining:.0f}s before asking again!")
        return

    # Guard: snapshot still loading
    if not docs.ready:
        await message.reply("Still warming up — documentation is loading. Try again in a moment!")
        return

    logger.info(f'{message.author}: {user_message[:100]}')

    async with message.channel.typing():
        try:
            relevant = docs.search(user_message, top_k=4)
            system_prompt = build_system_prompt(relevant)

            response = await openai_client.chat.completions.create(
                model="grok-4-1-fast-reasoning",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.7,
                max_tokens=2000,
            )

            reply = response.choices[0].message.content
            reply = wrap_urls_for_discord(reply)

            if len(reply) > 2000:
                reply = reply[:1997] + "..."

            await message.reply(reply)
            logger.info(f'Replied ({len(reply)} chars)')

        except Exception as e:
            logger.error(f'Error: {e}', exc_info=True)
            await message.reply("Sorry, something went wrong. Try again!")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

client.run(DISCORD_TOKEN)
