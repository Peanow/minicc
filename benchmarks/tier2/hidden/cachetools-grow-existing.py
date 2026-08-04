"""Evaluator-only regression for cachetools PR #408."""

import os
import sys

sys.path.insert(0, os.path.join(os.getcwd(), "src"))

from cachetools import LRUCache


cache = LRUCache(maxsize=10, getsizeof=lambda value: value)
cache["unrelated"] = 3
cache["target"] = 3
assert cache["target"] == 3  # keep target most-recently-used

cache["target"] = 7
assert dict(cache.items()) == {"unrelated": 3, "target": 7}
assert cache.currsize == 10

cache["target"] = 7
assert dict(cache.items()) == {"unrelated": 3, "target": 7}
assert cache.currsize == 10

cache["target"] = 1
assert dict(cache.items()) == {"unrelated": 3, "target": 1}
assert cache.currsize == 4
