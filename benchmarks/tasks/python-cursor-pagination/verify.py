from pagination import collect_pages


calls = []
pages = {
    None: ([1, 2], "next"),
    "next": ([3], "last"),
    "last": ([4, 5], None),
}


def fetch(cursor):
    calls.append(cursor)
    return pages[cursor]


assert collect_pages(fetch) == [1, 2, 3, 4, 5]
assert calls == [None, "next", "last"]

try:
    collect_pages(lambda cursor: ([], "same"))
except ValueError as exc:
    assert "cursor" in str(exc).lower()
else:
    raise AssertionError("repeated cursors must be rejected")
