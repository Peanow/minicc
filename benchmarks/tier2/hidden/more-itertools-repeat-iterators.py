"""Evaluator-only regression for more-itertools PR #1125."""

import os
import sys

sys.path.insert(0, os.getcwd())

from more_itertools import gray_product, partial_product


def values():
    yield from "abc"


def suffixes():
    yield from "de"


for function in (gray_product, partial_product):
    expected = list(function("abc", "de", repeat=2))
    actual = list(function(values(), suffixes(), repeat=2))
    assert actual == expected, function.__name__

    expected_three = list(function("ab", repeat=3))
    actual_three = list(function(iter("ab"), repeat=3))
    assert actual_three == expected_three, f"{function.__name__} repeat=3"
