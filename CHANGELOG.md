# Changelog

All notable changes to this fork are documented here.

This project is a fork of [joeyism/linkedin_scraper](https://github.com/joeyism/linkedin_scraper). Changes below are relative to upstream v3.1.1.

## [Unreleased]

### Fixed
- **PersonScraper: full rewrite from CSS selectors to innerText parsing** — LinkedIn replaced human-readable CSS class names with obfuscated hashes that change every deploy. The scraper now parses page text structure instead of querying DOM classes. ([0f077dd])
  - Language-agnostic date regex (matches year patterns, not English month names)
  - Multi-language section heading detection (EN/FR/DE/ES/IT/NL/SV/PT)
  - Structural noise filtering for accomplishments (credential IDs, UI buttons, footer content detected by pattern)
  - Company group detection for nested positions under one employer
  - Education fallback for entries without date ranges
  - Contact extraction from dialog overlay
- **Browser locale forcing** — added `locale: "en-US"` and `Accept-Language: en-US,en;q=0.9` to browser context to reduce multi-language page rendering ([0f077dd])

### Added
- **CLI commands** — `linkedin-scraper person`, `company`, `jobs`, `job`, `posts`, `login` ([005593f])
- **LinkedInAgent facade** — simplified async interface for AI agent integration ([143feda])
- **Human-like behavior** — request throttling with randomized delays, configurable rate limits ([d3d0a0b])
- **CLAUDE.md** — agent instructions for using the CLI from Claude Code ([6e07795])

### Fixed
- Auth detection updated for current LinkedIn DOM — `is_logged_in()` uses URL-based detection instead of A/B-tested DOM elements ([55f2305], [9b73575], [7e8c2e1], [1b565d6])

## Upstream v3.1.1

Last upstream release before this fork diverged. See [joeyism/linkedin_scraper](https://github.com/joeyism/linkedin_scraper) for prior history.

[0f077dd]: https://github.com/carlopezzuto/linkedin_scraper/commit/0f077dd
[005593f]: https://github.com/carlopezzuto/linkedin_scraper/commit/005593f
[143feda]: https://github.com/carlopezzuto/linkedin_scraper/commit/143feda
[d3d0a0b]: https://github.com/carlopezzuto/linkedin_scraper/commit/d3d0a0b
[6e07795]: https://github.com/carlopezzuto/linkedin_scraper/commit/6e07795
[55f2305]: https://github.com/carlopezzuto/linkedin_scraper/commit/55f2305
[9b73575]: https://github.com/carlopezzuto/linkedin_scraper/commit/9b73575
[7e8c2e1]: https://github.com/carlopezzuto/linkedin_scraper/commit/7e8c2e1
[1b565d6]: https://github.com/carlopezzuto/linkedin_scraper/commit/1b565d6
