"""Health-check polling for deployment verification.

Provides :func:`wait_for_healthy` which polls a health endpoint until it
returns HTTP 200 or the timeout expires. Used by the live deploy path to
confirm a newly deployed application is responding correctly.
"""

from __future__ import annotations

import logging
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


def wait_for_healthy(
    url: str,
    *,
    timeout: float = 120,
    interval: float = 5,
) -> bool:
    """Poll *url* until it returns HTTP 200 or *timeout* expires.

    Args:
        url: Health endpoint URL (e.g. ``http://localhost:8080/healthz``).
        timeout: Maximum seconds to wait. Defaults to 120.
        interval: Seconds between polls. Defaults to 5.

    Returns:
        bool: ``True`` if the endpoint returned 200 within *timeout*,
        ``False`` otherwise.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            req = Request(url, method="GET")
            with urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    logger.info("health check passed: %s", url)
                    return True
        except (URLError, OSError):
            pass
        remaining = deadline - time.monotonic()
        if remaining > interval:
            time.sleep(interval)
        elif remaining > 0:
            time.sleep(remaining)
            break

    logger.warning("health check timed out: %s", url)
    return False
