"""Public CLI facade.

Argument definitions, command handlers, and terminal interaction intentionally
live in separate modules so importing ``corecoder.cli`` has no side effects.
"""

from __future__ import annotations

from collections.abc import Sequence

from .commandline.handlers import dispatch
from .commandline.parser import parse_args


def _parse_args(argv: Sequence[str] | None = None):
    """Compatibility spelling for callers that inspect parsed arguments."""
    return parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run CoreCoder and return a process-compatible exit status."""
    return dispatch(parse_args(argv))


__all__ = ["main"]
