from collections.abc import Callable


def run_with_retry(
    operation: Callable[[], object],
    max_attempts: int,
    should_retry: Callable[[Exception], bool],
    sleeper: Callable[[], None],
):
    return operation()
