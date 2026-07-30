from batches import iter_batches


consumed = []


def source():
    for value in range(5):
        consumed.append(value)
        yield value


batches = iter_batches(source(), 2)
assert consumed == []
assert next(batches) == [0, 1]
assert consumed == [0, 1]
assert list(batches) == [[2, 3], [4]]

try:
    list(iter_batches([], 0))
except ValueError:
    pass
else:
    raise AssertionError("size < 1 must be rejected")
