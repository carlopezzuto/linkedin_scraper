"""Command-line interface for linkedin_scraper."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

from .core.browser import BrowserManager
from .core.throttle import ThrottleConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _throttle_from_args(args: argparse.Namespace) -> ThrottleConfig:
    """Build a ThrottleConfig from CLI flags."""
    return ThrottleConfig(
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        max_requests_per_hour=args.max_per_hour,
        max_requests_per_session=args.max_per_session,
        proxy=args.proxy,
    )


def _output(data: str, outfile: str | None) -> None:
    """Print to stdout or write to file."""
    if outfile:
        Path(outfile).write_text(data, encoding="utf-8")
        print(f"Output saved to {outfile}")
    else:
        print(data)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

async def _cmd_login(args: argparse.Namespace) -> None:
    """Interactive login – opens a browser for manual authentication."""
    from . import wait_for_manual_login

    async with BrowserManager(headless=False, proxy=args.proxy) as browser:
        await browser.page.goto("https://www.linkedin.com/login")
        print("Log in to LinkedIn in the browser window (5 min timeout)...")
        await wait_for_manual_login(browser.page, timeout=300_000)
        await browser.save_session(args.session)
        print(f"Session saved to {args.session}")


async def _cmd_person(args: argparse.Namespace) -> None:
    from .scrapers.person import PersonScraper

    throttle = _throttle_from_args(args)
    async with BrowserManager(headless=True, proxy=args.proxy) as browser:
        await browser.load_session(args.session)
        scraper = PersonScraper(browser.page, throttle_config=throttle)
        person = await scraper.scrape(args.url)
        _output(person.to_json(indent=2), args.output)


async def _cmd_company(args: argparse.Namespace) -> None:
    from .scrapers.company import CompanyScraper

    throttle = _throttle_from_args(args)
    async with BrowserManager(headless=True, proxy=args.proxy) as browser:
        await browser.load_session(args.session)
        scraper = CompanyScraper(browser.page, throttle_config=throttle)
        company = await scraper.scrape(args.url)
        _output(company.to_json(indent=2), args.output)


async def _cmd_job(args: argparse.Namespace) -> None:
    from .scrapers.job import JobScraper

    throttle = _throttle_from_args(args)
    async with BrowserManager(headless=True, proxy=args.proxy) as browser:
        await browser.load_session(args.session)
        scraper = JobScraper(browser.page, throttle_config=throttle)
        job = await scraper.scrape(args.url)
        _output(job.to_json(indent=2), args.output)


async def _cmd_jobs(args: argparse.Namespace) -> None:
    from .scrapers.job_search import JobSearchScraper
    from .scrapers.job import JobScraper

    throttle = _throttle_from_args(args)
    async with BrowserManager(headless=True, proxy=args.proxy) as browser:
        await browser.load_session(args.session)

        search = JobSearchScraper(browser.page, throttle_config=throttle)
        urls = await search.search(
            keywords=args.keywords,
            location=args.location,
            limit=args.limit,
        )
        print(f"Found {len(urls)} jobs")

        if args.details:
            scraper = JobScraper(browser.page, throttle_config=throttle)
            results = []
            for url in urls:
                job = await scraper.scrape(url)
                results.append(json.loads(job.to_json()))
            _output(json.dumps(results, indent=2), args.output)
        else:
            _output(json.dumps(urls, indent=2), args.output)


async def _cmd_posts(args: argparse.Namespace) -> None:
    from .scrapers.company_posts import CompanyPostsScraper

    throttle = _throttle_from_args(args)
    async with BrowserManager(headless=True, proxy=args.proxy) as browser:
        await browser.load_session(args.session)
        scraper = CompanyPostsScraper(browser.page, throttle_config=throttle)
        posts = await scraper.scrape(args.url, limit=args.limit)
        data = [json.loads(p.to_json()) for p in posts]
        _output(json.dumps(data, indent=2), args.output)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linkedin-scraper",
        description="LinkedIn scraper CLI – scrape profiles, companies, jobs and posts.",
    )

    # Global options
    parser.add_argument(
        "-s", "--session",
        default="linkedin_session.json",
        help="Path to session file (default: linkedin_session.json)",
    )
    parser.add_argument("--proxy", default=None, help="Proxy URL (e.g. http://host:port)")
    parser.add_argument("--min-delay", type=float, default=2.0, help="Min delay between pages (s)")
    parser.add_argument("--max-delay", type=float, default=5.0, help="Max delay between pages (s)")
    parser.add_argument("--max-per-hour", type=int, default=60, help="Max requests per hour (0=unlimited)")
    parser.add_argument("--max-per-session", type=int, default=0, help="Max requests per session (0=unlimited)")

    sub = parser.add_subparsers(dest="command", required=True)

    # --- login ---
    sub.add_parser("login", help="Open browser for manual LinkedIn login")

    # --- person ---
    p = sub.add_parser("person", help="Scrape a person profile")
    p.add_argument("url", help="LinkedIn profile URL")
    p.add_argument("-o", "--output", default=None, help="Save JSON to file")

    # --- company ---
    p = sub.add_parser("company", help="Scrape a company page")
    p.add_argument("url", help="LinkedIn company URL")
    p.add_argument("-o", "--output", default=None, help="Save JSON to file")

    # --- job ---
    p = sub.add_parser("job", help="Scrape a single job posting")
    p.add_argument("url", help="LinkedIn job URL")
    p.add_argument("-o", "--output", default=None, help="Save JSON to file")

    # --- jobs (search) ---
    p = sub.add_parser("jobs", help="Search for jobs")
    p.add_argument("keywords", help="Search keywords")
    p.add_argument("-l", "--location", default="", help="Job location")
    p.add_argument("-n", "--limit", type=int, default=10, help="Max results")
    p.add_argument("--details", action="store_true", help="Also scrape full job details")
    p.add_argument("-o", "--output", default=None, help="Save JSON to file")

    # --- posts ---
    p = sub.add_parser("posts", help="Scrape company posts")
    p.add_argument("url", help="LinkedIn company URL")
    p.add_argument("-n", "--limit", type=int, default=10, help="Max posts")
    p.add_argument("-o", "--output", default=None, help="Save JSON to file")

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_COMMANDS = {
    "login": _cmd_login,
    "person": _cmd_person,
    "company": _cmd_company,
    "job": _cmd_job,
    "jobs": _cmd_jobs,
    "posts": _cmd_posts,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    handler = _COMMANDS[args.command]
    try:
        asyncio.run(handler(args))
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
