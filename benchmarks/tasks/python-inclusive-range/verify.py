from range_utils import inclusive_sum


assert inclusive_sum(1, 3) == 6
assert inclusive_sum(-2, 2) == 0
assert inclusive_sum(5, 5) == 5
try:
    inclusive_sum(2, 1)
except ValueError:
    pass
else:
    raise AssertionError("start > end must raise ValueError")
