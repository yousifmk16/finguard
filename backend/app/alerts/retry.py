"""
ALT-06: Alert retry and failure handling.

``RetryPolicy`` wraps any callable with exponential-backoff retries.  The
``sleep_fn`` parameter is injectable so tests can run without real delays.

Usage
-----
policy = RetryPolicy(max_attempts=3, backoff_base=1.0)
policy.execute(lambda: smtp_client.send(msg))   # retried up to 3× on failure

If all attempts fail the last exception is re-raised so the caller can mark
the alert as ``"failed"`` and persist an ``error_detail``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class RetryPolicy:
    """
    Exponential-backoff retry wrapper.

    Parameters
    ----------
    max_attempts:
        Total number of attempts (including the first).  Must be ≥ 1.
    backoff_base:
        Base sleep duration in seconds.  The sleep before attempt *k* is
        ``backoff_base * 2^(k-1)`` (0 s before attempt 1, ``backoff_base``
        before attempt 2, ``2*backoff_base`` before attempt 3, …).
    sleep_fn:
        Callable used for sleeping; defaults to ``time.sleep``.  Pass a
        no-op in tests to avoid real delays.
    """

    max_attempts: int = 3
    backoff_base: float = 1.0
    sleep_fn: Callable[[float], None] = field(default=time.sleep, repr=False)

    def execute(self, fn: Callable[[], T]) -> T:
        """
        Call ``fn()`` up to ``max_attempts`` times.

        Returns the return value of ``fn`` on success.  Re-raises the last
        exception if every attempt fails.
        """
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be ≥ 1")

        last_exc: BaseException | None = None
        for attempt in range(self.max_attempts):
            try:
                return fn()
            except Exception as exc:
                last_exc = exc
                if attempt < self.max_attempts - 1:
                    delay = self.backoff_base * (2.0 ** attempt)
                    logger.warning(
                        "Attempt %d/%d failed (%s); retrying in %.1fs",
                        attempt + 1,
                        self.max_attempts,
                        exc,
                        delay,
                    )
                    self.sleep_fn(delay)
                else:
                    logger.error(
                        "All %d attempts failed: %s", self.max_attempts, exc
                    )

        raise last_exc  # type: ignore[misc]
