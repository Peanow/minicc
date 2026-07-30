from graph import dependency_order


graph = {
    "deploy": ["build", "test"],
    "test": ["build"],
    "build": ["lint"],
}
before = {key: list(value) for key, value in graph.items()}
assert dependency_order(graph) == ["lint", "build", "test", "deploy"]
assert graph == before
assert dependency_order({"b": [], "a": []}) == ["a", "b"]

try:
    dependency_order({"a": ["b"], "b": ["a"]})
except ValueError as exc:
    assert "cycle" in str(exc).lower()
else:
    raise AssertionError("cycles must be rejected")
