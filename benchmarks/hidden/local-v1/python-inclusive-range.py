"""Evaluator-only edge cases for python-inclusive-range."""

import os
import sys

sys.path.insert(0, os.getcwd())

from range_utils import inclusive_sum


assert inclusive_sum(-3, -1) == -6
assert inclusive_sum(7, 7) == 7
assert inclusive_sum(-2, 2) == 0
