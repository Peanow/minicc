"""Evaluator-only escape cases for python-safe-path."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.getcwd())

from archive import resolve_member


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / "root"
    root.mkdir()
    assert resolve_member(root, "nested/./file.txt") == (
        root / "nested" / "file.txt"
    ).resolve()
    for unsafe in ("../root-other/file.txt", "../../escape", "/absolute"):
        try:
            resolve_member(root, unsafe)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted unsafe member: {unsafe}")
