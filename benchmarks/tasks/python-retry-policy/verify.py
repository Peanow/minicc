from retry import run_with_retry


attempts = []
sleeps = []


def flaky():
    attempts.append(len(attempts) + 1)
    if len(attempts) < 3:
        raise TimeoutError("temporary")
    return "ok"


assert run_with_retry(flaky, 3, lambda exc: isinstance(exc, TimeoutError), lambda: sleeps.append(1)) == "ok"
assert attempts == [1, 2, 3]
assert sleeps == [1, 1]

fatal = ValueError("fatal")
try:
    run_with_retry(lambda: (_ for _ in ()).throw(fatal), 5, lambda exc: False, lambda: None)
except ValueError as exc:
    assert exc is fatal
else:
    raise AssertionError("non-retriable exception must be re-raised")

try:
    run_with_retry(lambda: None, 0, lambda exc: True, lambda: None)
except ValueError:
    pass
else:
    raise AssertionError("max_attempts < 1 must be rejected")
