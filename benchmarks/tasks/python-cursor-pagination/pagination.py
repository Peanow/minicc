from collections.abc import Callable


def collect_pages(
    fetch_page: Callable[[str | None], tuple[list[object], str | None]],
) -> list[object]:
    items, _ = fetch_page(None)
    return items
