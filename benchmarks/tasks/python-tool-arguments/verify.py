from tool_schema import validate_arguments


schema = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "count": {"type": "integer"},
        "score": {"type": "number"},
        "enabled": {"type": "boolean"},
        "tags": {"type": "array"},
        "metadata": {"type": "object"},
    },
    "required": ["name", "count"],
    "additionalProperties": False,
}
assert validate_arguments(schema, {
    "name": "tool",
    "count": 2,
    "score": 1.5,
    "enabled": True,
    "tags": [],
    "metadata": {},
}) == []

errors = validate_arguments(schema, {
    "count": True,
    "score": False,
    "extra": 1,
})
assert errors == [
    "missing required field: name",
    "unexpected field: extra",
    "field count must be integer",
    "field score must be number",
]
