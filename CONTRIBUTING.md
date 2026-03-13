# Contributing to LinkedIn Scraper

This is a fork of [joeyism/linkedin_scraper](https://github.com/joeyism/linkedin_scraper). Contributions are welcome.

## Setup

```bash
git clone https://github.com/carlopezzuto/linkedin_scraper.git
cd linkedin_scraper
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
playwright install chromium
```

## Architecture notes

### PersonScraper (innerText-based)

The person scraper (`linkedin_scraper/scrapers/person.py`) uses **innerText parsing** instead of CSS selectors. LinkedIn uses obfuscated hash-based class names that change every deploy, so CSS/XPath selectors break constantly. The innerText approach parses the text structure of the page instead.

Key design decisions:

- **Date regex is language-agnostic**: matches year patterns (`\S+\s+20\d{2}\s*-\s*...`) rather than English month names, because LinkedIn randomly serves detail pages in different languages regardless of browser locale settings
- **Section headings are matched in 8+ languages**: About/Acerca de/Info/Über/Informazioni/Over, etc.
- **Noise detection uses structural patterns**: credential IDs, UI buttons, and footer content are detected by regex patterns (e.g., lines starting with "Credential"/"Identifiant"/"Legitimering") rather than exhaustive translated string lists
- **Entry boundaries use date anchoring**: experience entries are delimited by date-range lines, with backward walking for title/company and forward walking for location/description

If LinkedIn changes their text layout, `person.py` is the file to update. The other scrapers (company, jobs, posts) still use CSS selectors.

### Browser locale

`core/browser.py` sets `locale: "en-US"` and `Accept-Language: en-US,en;q=0.9` on the browser context. This helps but does not guarantee English rendering. The person scraper handles multi-language pages regardless.

## Testing

```bash
pytest
pytest tests/test_person.py -v
pytest --cov=linkedin_scraper
```

Note: most tests are integration tests that hit live LinkedIn. They require a valid session file and are not suitable for CI.

## Pull requests

1. Create a branch: `git checkout -b fix/your-change`
2. Make changes, test manually with `linkedin-scraper person <url>`
3. Commit with a descriptive message
4. Push and open a PR

Keep PRs focused. If LinkedIn's DOM changed and selectors broke, note which selectors and what the new structure looks like.

## Bug reports

Include:
- Python version and OS
- The LinkedIn URL that failed (or a description if private)
- The JSON output (or error traceback)
- What you expected vs what you got

## License

By contributing, you agree that your contributions will be licensed under GPL v3, consistent with the project's [LICENSE](LICENSE).
