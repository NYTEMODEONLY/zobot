# ZoBot Discord Bot - Task Tracking

## Completed Tasks

- ✅ **Docs Index Implementation** - Implemented sitemap fetch/parse + in-memory allowlist of valid docs URLs with automatic refresh
- ✅ **Doc Retrieval** - Implemented grounding by fetching/extracting text from top-matched docs pages and passing excerpts + canonical URLs to the model
- ✅ **Prompt Guardrails** - Updated system prompt to forbid invented URLs and require citations only from provided docs URLs
- ✅ **URL Validator** - Implemented validation and canonicalization of all outgoing URLs; replaces invalid doc links with best-match allowlisted URL or /intro fallback
- ✅ **Tracking File** - Created this TASKS.md file for ongoing bot improvements

## Current Status

The bot now:
- Fetches and maintains an allowlist of valid documentation URLs from the sitemap
- Retrieves relevant documentation pages based on user queries
- Provides documentation context to the AI model
- Validates all URLs before sending to Discord
- Replaces invalid documentation URLs with valid alternatives
- Refreshes the sitemap cache every 12 hours

## Future Improvements

- Consider adding rate limiting per channel to prevent spam
- Add more sophisticated content extraction from docs pages
- Implement caching of retrieved doc content to reduce API calls
- Add metrics/logging for URL validation failures
- Consider adding slash commands in addition to @mentions

