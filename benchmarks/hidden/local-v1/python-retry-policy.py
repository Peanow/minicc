"""Evaluator-only stopping cases for python-retry-policy."""

import os
import sys

sys.path.insert(0, os.getcwd())

from retry import run_with_retry


error = RuntimeError("same object")
attempts = []
sleeps = []


def fail():
    attempts.append(1)
    raise error


try:
    run_with_retry(fail, 2, lambda exc: exc is error, lambda: sleeps.append(1))
except RuntimeError as caught:
    assert caught is error
else:
    raise AssertionError("expected original exception")

assert len(attempts) == 2
assert len(sleeps) == 1
