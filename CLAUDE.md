# LinkedIn Scraper — Agent Instructions

## When to use

When the user asks to research, look up, or find information about **people, companies, jobs, or posts on LinkedIn**, use the `linkedin-scraper` CLI.

## Prerequisites

A session file must exist at `linkedin_session.json`. If it doesn't, tell the user to run:
```bash
linkedin-scraper login
```

## Available commands

### Look up a person
```bash
linkedin-scraper person "https://www.linkedin.com/in/<username>/" -o result.json
```
Returns: name, location, about, experiences, educations, contacts, accomplishments.

### Look up a company
```bash
linkedin-scraper company "https://www.linkedin.com/company/<company>/" -o result.json
```
Returns: name, industry, size, headquarters, website, about, employees.

### Search for jobs
```bash
linkedin-scraper jobs "<keywords>" -l "<location>" -n <limit>
```
Returns: list of job URLs. Add `--details` to get full job descriptions.

### Scrape a single job posting
```bash
linkedin-scraper job "<job-url>"
```

### Get company posts
```bash
linkedin-scraper posts "https://www.linkedin.com/company/<company>/" -n <limit>
```

## Throttling options (use to avoid detection)

All commands accept these flags:
- `--min-delay 3 --max-delay 8` — randomized delay between pages (seconds)
- `--max-per-hour 30` — cap requests per hour
- `--proxy "http://host:port"` — route through a proxy

## Output

All commands output JSON to stdout. Use `-o filename.json` to save to a file.

## Examples

- "Find info about Satya Nadella on LinkedIn" → `linkedin-scraper person "https://www.linkedin.com/in/satyanadella/"`
- "Search ML engineer jobs in Berlin" → `linkedin-scraper jobs "ML engineer" -l "Berlin" -n 10 --details`
- "What does OpenAI post on LinkedIn?" → `linkedin-scraper posts "https://www.linkedin.com/company/openai/" -n 5`
- "Research Microsoft" → `linkedin-scraper company "https://www.linkedin.com/company/microsoft/"`
