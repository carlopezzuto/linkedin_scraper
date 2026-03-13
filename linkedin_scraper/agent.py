"""High-level async facade for AI agents to drive the LinkedIn scraper.

Usage (from an AI agent / tool-calling framework):

    agent = LinkedInAgent(session="linkedin_session.json")
    async with agent:
        person = await agent.scrape_person("https://linkedin.com/in/someone")
        company = await agent.scrape_company("https://linkedin.com/company/acme")
        jobs = await agent.search_jobs("ML engineer", location="NYC", limit=5)
        ...

Every public method returns plain Python dicts (JSON-serialisable) so they
slot directly into tool_use / function-calling responses.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .core.browser import BrowserManager
from .core.throttle import ThrottleConfig
from .scrapers.person import PersonScraper
from .scrapers.company import CompanyScraper
from .scrapers.job import JobScraper
from .scrapers.job_search import JobSearchScraper
from .scrapers.company_posts import CompanyPostsScraper

logger = logging.getLogger(__name__)


class LinkedInAgent:
    """Agent-friendly facade – one object, simple dict-in / dict-out methods.

    Args:
        session: Path to a linkedin_session.json file (created via ``linkedin-scraper login``).
        headless: Run browser headlessly (default True – agents don't need a GUI).
        throttle: Optional ThrottleConfig for rate-limiting / human emulation.
        proxy: Optional proxy URL forwarded to Playwright.
    """

    def __init__(
        self,
        session: str = "linkedin_session.json",
        headless: bool = True,
        throttle: Optional[ThrottleConfig] = None,
        proxy: Optional[str] = None,
    ):
        self._session_path = session
        self._throttle = throttle or ThrottleConfig()
        self._browser = BrowserManager(headless=headless, proxy=proxy)
        self._started = False

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "LinkedInAgent":
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def start(self) -> None:
        """Launch browser & load session."""
        await self._browser.start()
        await self._browser.load_session(self._session_path)
        self._started = True
        logger.info("LinkedInAgent started (session=%s)", self._session_path)

    async def close(self) -> None:
        """Shut down the browser."""
        await self._browser.close()
        self._started = False
        logger.info("LinkedInAgent closed")

    def _ensure_started(self) -> None:
        if not self._started:
            raise RuntimeError(
                "LinkedInAgent not started. Use `async with agent:` or call `await agent.start()`."
            )

    # ------------------------------------------------------------------
    # Scraping methods – all return plain dicts
    # ------------------------------------------------------------------

    async def scrape_person(self, url: str) -> Dict[str, Any]:
        """Scrape a LinkedIn profile.

        Args:
            url: Full LinkedIn profile URL (e.g. https://www.linkedin.com/in/someone)

        Returns:
            Dict with keys: name, location, about, open_to_work,
            experiences, educations, interests, accomplishments, contacts, …
        """
        self._ensure_started()
        scraper = PersonScraper(self._browser.page, throttle_config=self._throttle)
        person = await scraper.scrape(url)
        return person.to_dict()

    async def scrape_company(self, url: str) -> Dict[str, Any]:
        """Scrape a LinkedIn company page.

        Args:
            url: Full LinkedIn company URL (e.g. https://www.linkedin.com/company/acme)

        Returns:
            Dict with keys: name, about_us, industry, company_size,
            headquarters, website, employees, …
        """
        self._ensure_started()
        scraper = CompanyScraper(self._browser.page, throttle_config=self._throttle)
        company = await scraper.scrape(url)
        return company.to_dict()

    async def scrape_job(self, url: str) -> Dict[str, Any]:
        """Scrape a single LinkedIn job posting.

        Args:
            url: Full LinkedIn job URL

        Returns:
            Dict with keys: job_title, company, location, posted_date,
            applicant_count, job_description, benefits, …
        """
        self._ensure_started()
        scraper = JobScraper(self._browser.page, throttle_config=self._throttle)
        job = await scraper.scrape(url)
        return job.to_dict()

    async def search_jobs(
        self,
        keywords: str,
        location: str = "",
        limit: int = 10,
    ) -> List[str]:
        """Search for jobs and return a list of job URLs.

        Args:
            keywords: Search query (e.g. "software engineer")
            location: Location filter (e.g. "New York")
            limit: Max results to return

        Returns:
            List of LinkedIn job URLs.
        """
        self._ensure_started()
        scraper = JobSearchScraper(self._browser.page, throttle_config=self._throttle)
        return await scraper.search(keywords=keywords, location=location, limit=limit)

    async def search_and_scrape_jobs(
        self,
        keywords: str,
        location: str = "",
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search for jobs **and** scrape full details for each result.

        Args:
            keywords: Search query
            location: Location filter
            limit: Max results

        Returns:
            List of job dicts with full details.
        """
        urls = await self.search_jobs(keywords, location, limit)
        results = []
        for url in urls:
            job = await self.scrape_job(url)
            results.append(job)
        return results

    async def scrape_company_posts(
        self,
        url: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Scrape recent posts from a company page.

        Args:
            url: LinkedIn company URL
            limit: Max posts to return

        Returns:
            List of post dicts (text, reactions, comments, …).
        """
        self._ensure_started()
        scraper = CompanyPostsScraper(self._browser.page, throttle_config=self._throttle)
        posts = await scraper.scrape(url, limit=limit)
        return [p.to_dict() for p in posts]

    # ------------------------------------------------------------------
    # Tool definitions (for function-calling / tool_use agents)
    # ------------------------------------------------------------------

    @staticmethod
    def tool_definitions() -> List[Dict[str, Any]]:
        """Return Claude/OpenAI-compatible tool definitions for all methods.

        Pass these to your LLM's ``tools`` parameter so it can decide which
        scraping action to take.
        """
        return [
            {
                "name": "scrape_person",
                "description": "Scrape a LinkedIn person profile. Returns name, location, about, experiences, educations, contacts, etc.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "LinkedIn profile URL (e.g. https://www.linkedin.com/in/someone)",
                        }
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "scrape_company",
                "description": "Scrape a LinkedIn company page. Returns name, industry, size, headquarters, about, employees, etc.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "LinkedIn company URL (e.g. https://www.linkedin.com/company/acme)",
                        }
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "scrape_job",
                "description": "Scrape a single LinkedIn job posting. Returns title, company, location, description, benefits, etc.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "LinkedIn job URL",
                        }
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "search_jobs",
                "description": "Search LinkedIn for jobs by keywords and location. Returns a list of job URLs.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "keywords": {
                            "type": "string",
                            "description": "Search query (e.g. 'data scientist')",
                        },
                        "location": {
                            "type": "string",
                            "description": "Location filter (e.g. 'San Francisco')",
                            "default": "",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results (default 10)",
                            "default": 10,
                        },
                    },
                    "required": ["keywords"],
                },
            },
            {
                "name": "search_and_scrape_jobs",
                "description": "Search LinkedIn for jobs AND scrape full details for each result.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "keywords": {
                            "type": "string",
                            "description": "Search query",
                        },
                        "location": {
                            "type": "string",
                            "description": "Location filter",
                            "default": "",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results (default 10)",
                            "default": 10,
                        },
                    },
                    "required": ["keywords"],
                },
            },
            {
                "name": "scrape_company_posts",
                "description": "Scrape recent posts from a LinkedIn company page. Returns text, reactions, comments, reposts, images.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "LinkedIn company URL",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max posts (default 10)",
                            "default": 10,
                        },
                    },
                    "required": ["url"],
                },
            },
        ]

    async def dispatch_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> Any:
        """Dispatch a tool call from an LLM response.

        Args:
            tool_name: One of the tool names from tool_definitions().
            tool_input: The input dict from the LLM.

        Returns:
            The result (dict or list) ready to be sent back as tool_result.
        """
        dispatch = {
            "scrape_person": lambda i: self.scrape_person(i["url"]),
            "scrape_company": lambda i: self.scrape_company(i["url"]),
            "scrape_job": lambda i: self.scrape_job(i["url"]),
            "search_jobs": lambda i: self.search_jobs(
                i["keywords"], i.get("location", ""), i.get("limit", 10)
            ),
            "search_and_scrape_jobs": lambda i: self.search_and_scrape_jobs(
                i["keywords"], i.get("location", ""), i.get("limit", 10)
            ),
            "scrape_company_posts": lambda i: self.scrape_company_posts(
                i["url"], i.get("limit", 10)
            ),
        }

        handler = dispatch.get(tool_name)
        if not handler:
            raise ValueError(f"Unknown tool: {tool_name}. Valid: {list(dispatch)}")

        return await handler(tool_input)
