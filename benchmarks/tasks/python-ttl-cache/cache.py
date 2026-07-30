import time
from collections.abc import Callable


class TTLCache:
    def __init__(self, ttl_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._values: dict[str, object] = {}

    def set(self, key: str, value: object) -> None:
        self._values[key] = value

    def get(self, key: str, default=None):
        return self._values.get(key, default)
