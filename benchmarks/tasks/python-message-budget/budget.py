from collections.abc import Callable


def select_messages(
    messages: list[dict],
    budget: int,
    counter: Callable[[dict], int],
) -> list[dict]:
    return messages
