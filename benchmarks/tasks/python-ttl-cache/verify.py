from cache import TTLCache


now = [100.0]
cache = TTLCache(5, clock=lambda: now[0])
cache.set("token", "a")
assert cache.get("token") == "a"
now[0] = 104.0
cache.set("token", "b")
now[0] = 108.5
assert cache.get("token") == "b"
now[0] = 109.0
assert cache.get("token", "missing") == "missing"
assert "token" not in cache._values

immediate = TTLCache(0, clock=lambda: 1.0)
immediate.set("x", 1)
assert immediate.get("x") is None
