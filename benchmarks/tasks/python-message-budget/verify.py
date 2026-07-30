from budget import select_messages


messages = [
    {"role": "system", "content": "rules", "cost": 3},
    {"role": "user", "content": "old", "cost": 4},
    {"role": "assistant", "content": "middle", "cost": 3},
    {"role": "user", "content": "latest", "cost": 2},
]
before = [dict(message) for message in messages]
selected = select_messages(messages, 8, lambda message: message["cost"])
assert selected == [messages[0], messages[2], messages[3]]
assert selected[0] is not messages[0]
assert messages == before
assert select_messages(messages, 2, lambda message: message["cost"]) == [
    {"role": "system", "content": "rules", "cost": 3},
]

try:
    select_messages(messages, -1, lambda message: message["cost"])
except ValueError:
    pass
else:
    raise AssertionError("negative budgets must be rejected")
