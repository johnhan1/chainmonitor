from __future__ import annotations

import random
from collections.abc import Callable


def retry_sleep_seconds(
    attempt: int,
    base_seconds: float,
    max_seconds: float,
) -> float:
    jitter = random.uniform(0.0, base_seconds)
    return min(max_seconds, base_seconds * (2 ** (attempt - 1)) + jitter)


RetryableCheck = Callable[[Exception], bool]
