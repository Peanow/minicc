from events import deduplicate_events


events = [
    {"id": "a", "timestamp": 1, "value": "old"},
    {"id": "b", "timestamp": 5, "value": "only"},
    {"id": "a", "timestamp": 3, "value": "new"},
    {"id": "c", "timestamp": 2, "value": "tie-old"},
    {"id": "c", "timestamp": 2, "value": "tie-new"},
]
before = [dict(event) for event in events]
assert deduplicate_events(events) == [
    {"id": "a", "timestamp": 3, "value": "new"},
    {"id": "b", "timestamp": 5, "value": "only"},
    {"id": "c", "timestamp": 2, "value": "tie-new"},
]
assert events == before

try:
    deduplicate_events([{"id": "missing-time"}])
except ValueError:
    pass
else:
    raise AssertionError("invalid events must be rejected")
