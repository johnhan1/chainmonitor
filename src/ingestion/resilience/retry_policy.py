from __future__ import annotations

import random
from datetime import datetime
from email.utils import parsedate_to_datetime

import httpx
from src.shared.resilience.retry import retry_sleep_seconds  # noqa: F401


class RetryPolicy:
    @staticmethod
    def is_retryable_exception(exc: Exception) -> bool:
        if isinstance(exc, httpx.TimeoutException):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code if exc.response is not None else 0
            return code in {429, 500, 502, 503, 504}
        if isinstance(exc, httpx.HTTPError):
            return True
        return False

    @staticmethod
    def error_reason(exc: Exception) -> str:
        if isinstance(exc, httpx.TimeoutException):
            return "timeout"
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code if exc.response is not None else 0
            if code == 429:
                return "rate_limited"
            if 500 <= code <= 599:
                return "upstream_5xx"
            return f"http_{code}"
        if isinstance(exc, httpx.HTTPError):
            return "transport_error"
        return "parse_error"

    @staticmethod
    def retry_after_seconds(response: httpx.Response | None) -> float | None:
        if response is None:
            return None
        raw = response.headers.get("Retry-After")
        if raw is None:
            return None
        raw = raw.strip()
        if not raw:
            return None
        try:
            value = float(raw)
        except ValueError:
            try:
                retry_after_dt = parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                return None
            if retry_after_dt.tzinfo is None:
                retry_after_dt = retry_after_dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
            value = (retry_after_dt - datetime.now(tz=retry_after_dt.tzinfo)).total_seconds()
        if value <= 0:
            return None
        return value

    @classmethod
    def retry_sleep_seconds(  # noqa: F811
        cls,
        exc: Exception,
        base_backoff: float,
        attempt: int,
        max_sleep_seconds: float,
    ) -> float:
        retry_after_seconds: float | None = None
        if (
            isinstance(exc, httpx.HTTPStatusError)
            and exc.response is not None
            and exc.response.status_code == 429
        ):
            retry_after_seconds = cls.retry_after_seconds(exc.response)
        if retry_after_seconds is not None:
            return min(max_sleep_seconds, retry_after_seconds)
        jitter = random.uniform(0.0, base_backoff)
        return min(max_sleep_seconds, base_backoff * (2 ** (attempt - 1)) + jitter)
