from sse import parse_sse


lines = iter([
    ": keepalive\n",
    "event: message\n",
    "data: first\n",
    "data: second\n",
    "\n",
    "data: final\n",
])
assert parse_sse(lines) == ["first\nsecond", "final"]
assert parse_sse(["data: one\n", "\n", "data: [DONE]\n", "\n", "data: ignored\n"]) == ["one"]
