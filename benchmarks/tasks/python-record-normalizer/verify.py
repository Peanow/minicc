from normalizer import normalize_records


source = """
# onboarding
 Alice , Engineer

Bob,Designer
"""
assert normalize_records(source) == [
    {"name": "Alice", "role": "Engineer"},
    {"name": "Bob", "role": "Designer"},
]

try:
    normalize_records("Ada,Engineer\nmalformed\nGrace,Manager")
except ValueError as exc:
    assert "line 2" in str(exc).lower()
else:
    raise AssertionError("malformed rows must raise ValueError")
