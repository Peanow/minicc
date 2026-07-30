from collections.abc import Iterable, Iterator


def iter_batches(items: Iterable[object], size: int) -> Iterator[list[object]]:
    return iter(())
