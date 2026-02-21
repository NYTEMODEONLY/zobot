import discord
import openai
import os
import logging
import re
import asyncio
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin
from collections import defaultdict
from dotenv import load_dotenv
import aiohttp
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
XAI_API_KEY = os.getenv('XAI_API_KEY')

if not DISCORD_TOKEN or not XAI_API_KEY:
    print("Error: DISCORD_TOKEN and XAI_API_KEY required in environment")
    exit(1)

# Documentation configuration
DOCS_BASE_URL = "https://docs.zocomputer.com"
DOCS_SITEMAP_URL = f"{DOCS_BASE_URL}/sitemap.xml"
DOCS_INTRO_URL = f"{DOCS_BASE_URL}/intro"
SITEMAP_REFRESH_INTERVAL_HOURS = 12


class DocsIndex:
    """Manages an allowlist of valid documentation URLs from the sitemap."""
    
    def __init__(self):
        self.valid_urls = set()
        self.url_path_segments = defaultdict(list)  # path segments -> list of URLs
        self.last_refresh = None
        self.refresh_lock = asyncio.Lock()
        self.session = None
    
    async def _get_session(self):
        """Get or create aiohttp session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        return self.session
    
    async def refresh(self, force=False):
        """Fetch and parse the sitemap to update the allowlist."""
        async with self.refresh_lock:
            # Check if refresh is needed
            if not force and self.last_refresh:
                age = datetime.now() - self.last_refresh
                if age < timedelta(hours=SITEMAP_REFRESH_INTERVAL_HOURS):
                    logger.debug(f"Sitemap cache still fresh (age: {age})")
                    return
            
            logger.info("Refreshing documentation sitemap...")
            session = await self._get_session()
            
            try:
                async with session.get(DOCS_SITEMAP_URL) as response:
                    if response.status != 200:
                        logger.error(f"Failed to fetch sitemap: HTTP {response.status}")
                        return
                    
                    content = await response.text()
                    root = ET.fromstring(content)
                    
                    # Parse sitemap XML
                    namespace = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
                    urls = []
                    for url_elem in root.findall('.//ns:url', namespace):
                        loc_elem = url_elem.find('ns:loc', namespace)
                        if loc_elem is not None and loc_elem.text:
                            url = loc_elem.text.strip()
                            if url.startswith(DOCS_BASE_URL):
                                urls.append(url)
                    
                    # Update allowlist
                    self.valid_urls = set(urls)
                    
                    # Build searchable index by path segments
                    self.url_path_segments = defaultdict(list)
                    for url in self.valid_urls:
                        parsed = urlparse(url)
                        path = parsed.path.strip('/')
                        if path:
                            segments = path.split('/')
                            # Add full path and individual segments
                            for i in range(len(segments)):
                                key = '/'.join(segments[:i+1])
                                self.url_path_segments[key].append(url)
                    
                    self.last_refresh = datetime.now()
                    logger.info(f"Loaded {len(self.valid_urls)} valid documentation URLs")
                    
            except Exception as e:
                logger.error(f"Error refreshing sitemap: {str(e)}", exc_info=True)
    
    def is_valid_url(self, url):
        """Check if a URL is in the allowlist."""
        # Normalize URL for comparison
        normalized = url.split('#')[0].split('?')[0].rstrip('/')
        if normalized.endswith('/intro'):
            normalized = normalized[:-6]  # Remove /intro suffix
        return normalized in self.valid_urls or url in self.valid_urls
    
    def find_best_match(self, query_text):
        """Find best matching doc URLs based on query keywords."""
        query_lower = query_text.lower()
        query_words = set(re.findall(r'\b\w+\b', query_lower))
        
        # Score URLs based on keyword matches in path segments
        scored_urls = []
        for url in self.valid_urls:
            parsed = urlparse(url)
            path_lower = parsed.path.lower()
            score = 0
            for word in query_words:
                if len(word) > 2:  # Ignore very short words
                    if word in path_lower:
                        score += 1
                    # Bonus for exact segment match
                    if f'/{word}' in path_lower or path_lower.endswith(word):
                        score += 2
            
            if score > 0:
                scored_urls.append((score, url))
        
        # Sort by score (descending) and return top matches
        scored_urls.sort(reverse=True, key=lambda x: x[0])
        return [url for _, url in scored_urls[:5]]  # Top 5 matches
    
    async def close(self):
        """Close the HTTP session."""
        if self.session and not self.session.closed:
            await self.session.close()


class DocRetriever:
    """Retrieves and extracts text content from documentation pages."""
    
    def __init__(self, docs_index):
        self.docs_index = docs_index
        self.session = None
    
    async def _get_session(self):
        """Get or create aiohttp session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        return self.session
    
    async def fetch_page_content(self, url):
        """Fetch and extract readable text from a documentation page."""
        session = await self._get_session()
        
        try:
            async with session.get(url) as response:
                if response.status != 200:
                    logger.warning(f"Failed to fetch {url}: HTTP {response.status}")
                    return None
                
                html = await response.text()
                soup = BeautifulSoup(html, 'lxml')
                
                # Extract title
                title = ""
                title_elem = soup.find('title')
                if title_elem:
                    title = title_elem.get_text().strip()
                
                # Extract main content (look for common doc site structures)
                content_parts = []
                
                # Try to find main content area
                main_content = soup.find('main') or soup.find('article') or soup.find('div', class_=re.compile('content|main|article'))
                
                if main_content:
                    # Extract headings
                    for heading in main_content.find_all(['h1', 'h2', 'h3']):
                        text = heading.get_text().strip()
                        if text:
                            content_parts.append(f"{'#' * int(heading.name[1])} {text}")
                    
                    # Extract paragraphs (limit to first few for brevity)
                    paragraphs = main_content.find_all('p')
                    for p in paragraphs[:5]:  # Limit to first 5 paragraphs
                        text = p.get_text().strip()
                        if text and len(text) > 20:  # Skip very short paragraphs
                            content_parts.append(text)
                else:
                    # Fallback: extract all text
                    body = soup.find('body')
                    if body:
                        text = body.get_text(separator='\n', strip=True)
                        # Take first 1000 chars
                        content_parts.append(text[:1000])
                
                if not content_parts:
                    return None
                
                return {
                    'url': url,
                    'title': title,
                    'content': '\n\n'.join(content_parts)
                }
                
        except Exception as e:
            logger.error(f"Error fetching {url}: {str(e)}", exc_info=True)
            return None
    
    async def retrieve_relevant_docs(self, query_text, max_pages=3):
        """Retrieve relevant documentation pages based on query."""
        # Find best matching URLs
        candidate_urls = self.docs_index.find_best_match(query_text)
        
        if not candidate_urls:
            # Fallback to intro page
            candidate_urls = [DOCS_INTRO_URL]
        
        # Fetch content for top matches
        tasks = [self.fetch_page_content(url) for url in candidate_urls[:max_pages]]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        docs = []
        for result in results:
            if isinstance(result, dict) and result:
                docs.append(result)
            elif isinstance(result, Exception):
                logger.warning(f"Error retrieving doc: {result}")
        
        return docs
    
    async def close(self):
        """Close the HTTP session."""
        if self.session and not self.session.closed:
            await self.session.close()


def wrap_urls_for_discord(text):
    """Wrap bare URLs in angle brackets to prevent embeds, but don't double-wrap already wrapped URLs or markdown links."""
    # Match URLs not already wrapped in <> and not in markdown link format [text](url)
    # Look for http:// or https:// followed by non-whitespace, but not already in <>
    pattern = r'(?<!<)(https?://[^\s<>\)]+)(?!>)'
    wrapped = re.sub(pattern, r'<\1>', text)
    return wrapped


def extract_urls_from_text(text):
    """Extract all URLs from text."""
    # Match URLs in various formats
    patterns = [
        r'https?://[^\s<>\)]+',  # Bare URLs
        r'<https?://[^\s<>\)]+>',  # Wrapped URLs
        r'\[([^\]]+)\]\(<?(https?://[^\s<>\)]+)>?\)',  # Markdown links
    ]
    
    urls = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            if isinstance(match, tuple):
                urls.append(match[1])  # URL from markdown link
            else:
                # Remove angle brackets if present
                url = match.strip('<>')
                urls.append(url)
    
    return list(set(urls))  # Deduplicate


async def validate_url(session, url):
    """Validate a URL by checking if it's accessible."""
    try:
        # Normalize URL
        normalized = url.split('#')[0].split('?')[0].rstrip('/')
        
        # Try HEAD first (lighter)
        async with session.head(normalized, allow_redirects=True) as response:
            if response.status == 200:
                return True, normalized
            elif response.status == 404:
                return False, None
        
        # Fallback to GET if HEAD doesn't work
        async with session.get(normalized, allow_redirects=True) as response:
            if response.status == 200:
                return True, normalized
            else:
                return False, None
                
    except Exception as e:
        logger.debug(f"Error validating URL {url}: {str(e)}")
        return False, None


async def validate_and_fix_urls(text, docs_index, session):
    """Validate all URLs in text and replace invalid doc URLs with valid ones."""
    urls = extract_urls_from_text(text)
    replacements = {}
    
    for url in urls:
        parsed = urlparse(url)
        
        # Check if it's a docs URL
        if parsed.netloc == 'docs.zocomputer.com' or parsed.netloc.endswith('.zocomputer.com'):
            # Check allowlist first
            if not docs_index.is_valid_url(url):
                logger.warning(f"Invalid docs URL not in allowlist: {url}")
                # Find best replacement
                # Try to extract keywords from context around the URL
                context_start = max(0, text.find(url) - 50)
                context_end = min(len(text), text.find(url) + len(url) + 50)
                context = text[context_start:context_end]
                
                replacement_urls = docs_index.find_best_match(context)
                if replacement_urls:
                    replacement = replacement_urls[0]
                else:
                    replacement = DOCS_INTRO_URL
                
                replacements[url] = replacement
                logger.info(f"Replacing {url} with {replacement}")
            else:
                # Validate it's actually accessible
                is_valid, normalized = await validate_url(session, url)
                if not is_valid:
                    logger.warning(f"Docs URL failed validation: {url}")
                    replacement_urls = docs_index.find_best_match(url)
                    if replacement_urls:
                        replacement = replacement_urls[0]
                    else:
                        replacement = DOCS_INTRO_URL
                    replacements[url] = replacement
                elif normalized and normalized != url:
                    replacements[url] = normalized
        
        # For non-docs URLs, validate best-effort
        else:
            is_valid, normalized = await validate_url(session, url)
            if not is_valid:
                logger.debug(f"Non-docs URL failed validation: {url}")
                # Remove or replace with a note
                # For now, we'll leave it but could be more aggressive
    
    # Apply replacements
    fixed_text = text
    for old_url, new_url in replacements.items():
        # Replace in various formats
        fixed_text = fixed_text.replace(old_url, new_url)
        fixed_text = fixed_text.replace(f'<{old_url}>', f'<{new_url}>')
        fixed_text = re.sub(
            r'\[([^\]]+)\]\(<?' + re.escape(old_url) + r'>?\)',
            rf'[\1](<{new_url}>)',
            fixed_text
        )
    
    return fixed_text


# Global instances
docs_index = DocsIndex()
doc_retriever = DocRetriever(docs_index)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

openai_client = openai.AsyncOpenAI(
    api_key=XAI_API_KEY,
    base_url="https://api.x.ai/v1"
)


def build_system_prompt(docs_context=None):
    """Build the system prompt with optional documentation context."""
    base_prompt = """You are the Zo Computer support bot. Answer ONLY questions about Zo Computer (https://www.zo.computer/).

RESPONSE STYLE:
- Keep it brief and conversational (2-3 short paragraphs max)
- Be friendly and encouraging
- Format URLs with angle brackets: <https://example.com> to prevent Discord embeds
- Use proper markdown links: [text](<url>)
- Avoid walls of text or numbered lists
- Get straight to the answer

CRITICAL URL RULES:
- NEVER invent or guess documentation URLs
- ONLY use documentation URLs that are explicitly provided to you in the context below
- If you need to reference documentation but don't have a specific URL, use: <https://docs.zocomputer.com/intro>
- All documentation links MUST be to https://docs.zocomputer.com/ pages only
- For non-documentation links (like zo.computer main site), you may include them if clearly relevant

KNOWLEDGE:
You know about: websites/apps creation, AI integrations, file management, automations, hosting, pricing, troubleshooting, documentation at <https://docs.zocomputer.com/>

If it's not about Zo Computer, politely say: "I'm specifically here to help with Zo Computer questions. Got any questions about building with Zo?"
"""
    
    if docs_context:
        context_text = "\n\nRELEVANT DOCUMENTATION CONTEXT:\n"
        for doc in docs_context:
            context_text += f"\n--- {doc['title']} ({doc['url']}) ---\n"
            context_text += doc['content'][:800]  # Limit content length
            context_text += "\n"
        
        context_text += "\n\nVALID DOCUMENTATION URLS YOU MAY REFERENCE:\n"
        valid_urls_list = sorted(list(docs_index.valid_urls))[:20]  # Show first 20
        for url in valid_urls_list:
            context_text += f"- {url}\n"
        
        base_prompt += context_text
    
    return base_prompt


@client.event
async def on_ready():
    logger.info(f'{client.user} logged in successfully')
    logger.info(f'Zo Computer Support Bot ready - Using grok-4-1-fast-reasoning')
    
    # Refresh docs index on startup
    await docs_index.refresh(force=True)


@client.event
async def on_message(message):
    logger.debug(f'Message received from {message.author}: {message.content}')
    
    if message.author == client.user:
        logger.debug('Ignoring own message')
        return

    if client.user.mentioned_in(message):
        logger.info(f'Bot mentioned by {message.author}')
        user_message = message.content.replace(f'<@{client.user.id}>', '').replace(f'<@!{client.user.id}>', '').strip()
        
        if not user_message:
            logger.debug('Empty message after removing mention')
            await message.reply("Hi! 👋 I'm here to help with **Zo Computer** questions. What would you like to know about the platform?")
            return

        logger.info(f'Processing message: {user_message[:100]}')
        
        async with message.channel.typing():
            try:
                # Ensure docs index is fresh
                await docs_index.refresh()
                
                # Retrieve relevant documentation
                logger.debug('Retrieving relevant documentation...')
                relevant_docs = await doc_retriever.retrieve_relevant_docs(user_message, max_pages=3)
                logger.info(f'Retrieved {len(relevant_docs)} relevant doc pages')
                
                # Build system prompt with docs context
                system_prompt = build_system_prompt(relevant_docs if relevant_docs else None)
                
                logger.debug('Calling xAI API for Zo support')
                response = await openai_client.chat.completions.create(
                    model="grok-4-1-fast-reasoning",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    temperature=0.7,
                    max_tokens=2000
                )
                logger.debug('API response received')
                ai_reply = response.choices[0].message.content
                logger.info(f'Reply generated: {len(ai_reply)} characters')
                
                # Validate and fix URLs
                logger.debug('Validating URLs in reply...')
                session = await doc_retriever._get_session()
                ai_reply = await validate_and_fix_urls(ai_reply, docs_index, session)
                
                # Wrap URLs in angle brackets to prevent Discord embeds
                ai_reply = wrap_urls_for_discord(ai_reply)
                
                if len(ai_reply) > 2000:
                    ai_reply = ai_reply[:1997] + "..."
                
                await message.reply(ai_reply)
                logger.info('Reply sent successfully')
            except Exception as e:
                logger.error(f'Error: {str(e)}', exc_info=True)
                await message.reply(f"Sorry, I encountered an error: {str(e)}")


# Cleanup on shutdown
async def cleanup():
    await docs_index.close()
    await doc_retriever.close()


# Register cleanup
import atexit
atexit.register(lambda: asyncio.run(cleanup()))

client.run(DISCORD_TOKEN)
