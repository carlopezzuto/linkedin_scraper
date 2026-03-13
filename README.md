# LinkedIn Scraper

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

Async LinkedIn scraper built with Playwright for extracting profile, company, and job data from LinkedIn.

> **Fork of [joeyism/linkedin_scraper](https://github.com/joeyism/linkedin_scraper)** by Joey Sham. Original work licensed under GPL v3. This fork adds resilient parsing, CLI tooling, and AI agent integration.

## Changes from upstream

### innerText-based person scraper (v3.1.1+)

LinkedIn replaced human-readable CSS class names (`.pvs-list__container`, `.pv-top-card-profile-picture`) with obfuscated hash-based classes (`ba8b842d`, `_201f6edb`) that change every deploy. The upstream scraper's CSS selectors no longer match any elements.

This fork rewrites `PersonScraper` to use **innerText parsing with structural pattern matching**:

- **Language-agnostic date regex**: matches year structure (`\S+\s+20\d{2}\s*-\s*...`) instead of English month names, so experience/education extraction works regardless of what language LinkedIn serves the page in
- **Section heading detection**: multi-language h2 matching (About/Acerca de/Info/Über/Informazioni/Over/etc.)
- **Structural noise filtering**: detects credential IDs, UI buttons, and footer content by pattern rather than hardcoded translations
- **Company group detection**: handles LinkedIn's nested position layout (multiple roles under one employer)
- **Browser locale forcing**: sets `locale: "en-US"` and `Accept-Language` header to reduce (not eliminate) multi-language rendering

### Other additions

- **CLI commands**: `linkedin-scraper person <url>`, `linkedin-scraper company <url>`
- **LinkedInAgent facade**: simplified interface for AI agent integration
- **Human-like behavior**: request throttling and emulation
- **Auth fixes**: updated login detection for current LinkedIn DOM

## Quick Start

### Installation

```bash
# From this fork
pip install git+https://github.com/carlopezzuto/linkedin_scraper.git

# Install Playwright browsers
playwright install chromium
```

### Create a session

```python
import asyncio
from linkedin_scraper import BrowserManager, wait_for_manual_login

async def create_session():
    async with BrowserManager(headless=False) as browser:
        await browser.page.goto("https://www.linkedin.com/login")
        print("Please log in to LinkedIn...")
        await wait_for_manual_login(browser.page, timeout=300)
        await browser.save_session("session.json")
        print("Session saved!")

asyncio.run(create_session())
```

### Scrape a profile

```python
import asyncio
from linkedin_scraper import BrowserManager, PersonScraper

async def main():
    async with BrowserManager() as browser:
        await browser.load_session("session.json")
        scraper = PersonScraper(browser.page)
        person = await scraper.scrape("https://linkedin.com/in/williamhgates/")

        print(f"Name: {person.name}")
        print(f"Location: {person.location}")
        print(f"Experiences: {len(person.experiences)}")
        print(f"Education: {len(person.educations)}")

asyncio.run(main())
```

### CLI usage

```bash
# Create session (opens browser for manual login)
linkedin-scraper login

# Scrape a person profile (outputs JSON)
linkedin-scraper person "https://linkedin.com/in/williamhgates/"

# Scrape a company page
linkedin-scraper company "https://linkedin.com/company/microsoft/"
```

## Features

- **Person Profiles**: name, headline, location, about, experiences, education, accomplishments, contacts
- **Company Pages**: overview, industry, size, headquarters
- **Company Posts**: content, reactions, comments, reposts
- **Job Listings**: details, requirements, application links
- **Async/Await**: modern async Python with Playwright
- **Type Safety**: Pydantic models for all data
- **Progress Callbacks**: track scraping progress
- **Session Management**: reuse authenticated sessions

## Data Models

### Person

```python
class Person(BaseModel):
    name: str
    headline: Optional[str]
    location: Optional[str]
    about: Optional[str]
    open_to_work: bool
    linkedin_url: str
    experiences: List[Experience]
    educations: List[Education]
    accomplishments: List[Accomplishment]
    contacts: List[Contact]
```

### Experience

```python
class Experience(BaseModel):
    position_title: Optional[str]
    institution_name: Optional[str]
    linkedin_url: Optional[str]
    from_date: Optional[str]
    to_date: Optional[str]
    duration: Optional[str]
    location: Optional[str]
    description: Optional[str]
```

## Advanced Usage

### Browser Configuration

```python
browser = BrowserManager(
    headless=False,              # Show browser window
    slow_mo=100,                 # Slow down operations (ms)
    viewport={"width": 1920, "height": 1080},
    user_agent="Custom User Agent",
    proxy="http://user:pass@host:port",
)
```

### Error Handling

```python
from linkedin_scraper import (
    AuthenticationError,
    RateLimitError,
    ProfileNotFoundError,
)

try:
    person = await scraper.scrape(url)
except AuthenticationError:
    print("Not logged in or session expired")
except RateLimitError:
    print("Rate limited by LinkedIn")
except ProfileNotFoundError:
    print("Profile not found or private")
```

## Known limitations

- LinkedIn serves detail pages (experience, certifications, languages) in **random languages** per navigation, ignoring the `Accept-Language` header. The parser handles this via language-agnostic patterns, but dates and locations may appear in the served locale (e.g., "févr. 2026" instead of "Feb 2026").
- Accomplishment pages (certifications, courses, projects) use `<div>` containers instead of `<ul><li>`, so parsing relies on text structure rather than DOM hierarchy.
- LinkedIn's DOM changes frequently. While innerText parsing is more resilient than CSS selectors, major layout changes could still require updates.

## Requirements

- Python 3.8+
- Playwright
- Pydantic 2.0+
- aiofiles
- python-dotenv (optional)

## Credits

This is a fork of [linkedin_scraper](https://github.com/joeyism/linkedin_scraper) by [Joey Sham](https://github.com/joeyism). The original project provided the async Playwright architecture, data models, authentication handling, and company/job scrapers that this fork builds on.

## License

GPL v3. See [LICENSE](LICENSE) for details.

## Disclaimer

This tool is for educational purposes only. Comply with LinkedIn's Terms of Service and use responsibly. The authors are not responsible for any misuse.
