"""Evaluator-only regression for python-diskcache PR #288."""

import os
import shutil
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.getcwd())

from diskcache import Deque


directory = tempfile.mkdtemp(prefix="corecoder-diskcache-hidden-")
deque = Deque(directory=directory)
try:
    value = b"x" * 100_000
    deque.append(value)
    with mock.patch.object(deque._cache._disk, "remove") as remove:
        assert deque.peek() == value
        remove.assert_not_called()
    assert len(deque) == 1
finally:
    deque._cache.close()
    shutil.rmtree(directory, ignore_errors=True)
