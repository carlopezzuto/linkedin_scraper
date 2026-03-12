"""Human-like behavior emulation and request throttling."""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Optional

from playwright.async_api import Page

from .exceptions import RateLimitError

logger = logging.getLogger(__name__)


@dataclass
class ThrottleConfig:
    """Configuration for human-like behavior and rate limiting.

    Args:
        min_delay: Minimum delay between page navigations (seconds)
        max_delay: Maximum delay between page navigations (seconds)
        max_requests_per_hour: Maximum page loads allowed per hour (0 = unlimited)
        max_requests_per_session: Maximum page loads per session (0 = unlimited)
        mouse_simulation: Enable random mouse movements on pages
        random_scrolling: Enable human-like random scroll patterns
        proxy: Proxy server URL (e.g. "http://user:pass@host:port")
        proxy_rotation: List of proxy URLs to rotate through
    """

    min_delay: float = 2.0
    max_delay: float = 5.0
    max_requests_per_hour: int = 60
    max_requests_per_session: int = 0
    mouse_simulation: bool = True
    random_scrolling: bool = True
    proxy: Optional[str] = None
    proxy_rotation: list = field(default_factory=list)


class RequestThrottle:
    """Tracks and enforces request rate limits."""

    def __init__(self, config: ThrottleConfig):
        self._config = config
        self._request_timestamps: list[float] = []
        self._session_count: int = 0

    @property
    def session_count(self) -> int:
        return self._session_count

    def _prune_old_timestamps(self) -> None:
        """Remove timestamps older than 1 hour."""
        cutoff = time.monotonic() - 3600
        self._request_timestamps = [
            ts for ts in self._request_timestamps if ts > cutoff
        ]

    def check_limits(self) -> None:
        """Raise RateLimitError if any limit is exceeded."""
        if (
            self._config.max_requests_per_session > 0
            and self._session_count >= self._config.max_requests_per_session
        ):
            raise RateLimitError(
                f"Session limit reached ({self._config.max_requests_per_session} requests). "
                "Create a new session to continue.",
                suggested_wait_time=0,
            )

        if self._config.max_requests_per_hour > 0:
            self._prune_old_timestamps()
            if len(self._request_timestamps) >= self._config.max_requests_per_hour:
                oldest = self._request_timestamps[0]
                wait = int(3600 - (time.monotonic() - oldest)) + 1
                raise RateLimitError(
                    f"Hourly limit reached ({self._config.max_requests_per_hour}/hr). "
                    f"Try again in ~{wait}s.",
                    suggested_wait_time=wait,
                )

    def record_request(self) -> None:
        """Record a new request."""
        self._request_timestamps.append(time.monotonic())
        self._session_count += 1
        logger.debug(
            "Request #%d (hourly: %d)",
            self._session_count,
            len(self._request_timestamps),
        )


class HumanBehavior:
    """Emulates human-like browsing patterns."""

    def __init__(self, config: Optional[ThrottleConfig] = None):
        self.config = config or ThrottleConfig()
        self.throttle = RequestThrottle(self.config)
        self._proxy_index = 0

    async def random_delay(self) -> None:
        """Wait a random duration between min_delay and max_delay."""
        delay = random.uniform(self.config.min_delay, self.config.max_delay)
        logger.debug("Human delay: %.2fs", delay)
        await asyncio.sleep(delay)

    async def pre_navigation(self) -> None:
        """Called before each page navigation. Enforces limits and adds delay."""
        self.throttle.check_limits()
        if self.throttle.session_count > 0:
            await self.random_delay()

    def post_navigation(self) -> None:
        """Called after each page navigation. Records the request."""
        self.throttle.record_request()

    async def simulate_mouse_movement(self, page: Page) -> None:
        """Move the mouse in a natural random pattern across the page."""
        if not self.config.mouse_simulation:
            return

        viewport = page.viewport_size
        if not viewport:
            return

        width = viewport["width"]
        height = viewport["height"]

        # 2-4 random movements
        num_moves = random.randint(2, 4)
        for _ in range(num_moves):
            x = random.randint(100, max(101, width - 100))
            y = random.randint(100, max(101, height - 100))
            # Human-like movement with steps
            await page.mouse.move(x, y, steps=random.randint(5, 15))
            await asyncio.sleep(random.uniform(0.1, 0.4))

        logger.debug("Mouse simulation: %d moves", num_moves)

    async def random_scroll(self, page: Page) -> None:
        """Scroll the page in a human-like, non-uniform pattern."""
        if not self.config.random_scrolling:
            return

        total_height = await page.evaluate("document.body.scrollHeight")
        viewport_height = (page.viewport_size or {}).get("height", 720)

        if total_height <= viewport_height:
            return

        current = 0
        # Scroll in 3-6 random chunks
        num_scrolls = random.randint(3, 6)
        chunk = total_height / num_scrolls

        for i in range(num_scrolls):
            # Add jitter to each scroll distance
            distance = chunk * random.uniform(0.7, 1.3)
            current = min(current + distance, total_height)

            await page.evaluate(f"window.scrollTo(0, {int(current)})")
            await asyncio.sleep(random.uniform(0.3, 1.2))

            # Occasionally scroll up slightly (mimics reading)
            if random.random() < 0.3 and current > viewport_height:
                backtrack = random.uniform(50, 200)
                current = max(0, current - backtrack)
                await page.evaluate(f"window.scrollTo(0, {int(current)})")
                await asyncio.sleep(random.uniform(0.2, 0.6))

        logger.debug("Random scroll: %d steps", num_scrolls)

    async def emulate_page_read(self, page: Page) -> None:
        """Simulate a human reading a page: mouse moves + random scroll."""
        await self.simulate_mouse_movement(page)
        await self.random_scroll(page)

    def get_next_proxy(self) -> Optional[str]:
        """Get the next proxy from the rotation list, or the single proxy."""
        if self.config.proxy_rotation:
            proxy = self.config.proxy_rotation[self._proxy_index % len(self.config.proxy_rotation)]
            self._proxy_index += 1
            return proxy
        return self.config.proxy
