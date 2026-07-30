from merge import deep_merge


base = {
    "service": {"host": "localhost", "ports": [80], "limits": {"cpu": 1}},
    "debug": False,
}
override = {
    "service": {"ports": [443], "limits": {"memory": 512}},
    "debug": True,
}
result = deep_merge(base, override)
assert result == {
    "service": {
        "host": "localhost",
        "ports": [443],
        "limits": {"cpu": 1, "memory": 512},
    },
    "debug": True,
}
result["service"]["limits"]["cpu"] = 99
assert base["service"]["limits"]["cpu"] == 1
assert override["service"]["limits"]["memory"] == 512
