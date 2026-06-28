"""Sample script with intentional bugs — use CoreCoder to find and fix them."""


def calculate_average(numbers):
    """Calculate the average of a list of numbers."""
    total = 0
    for i in range(1, len(numbers)):  # Bug: should start from 0
        total += numbers[i]
    return total / len(numbers)


def fibonacci(n):
    """Return the nth Fibonacci number."""
    if n <= 0:
        return 0
    if n == 1:
        return 1
    return fibonacci(n - 1) + fibonacci(n - 2)  # Bug: no memoization, very slow


def read_config(path):
    """Read a config file and return key-value pairs."""
    config = {}
    with open(path) as f:  # Bug: no encoding specified
        for line in f:
            key, value = line.strip().split("=")  # Bug: no handling for comments or blank lines
            config[key] = value
    return config


def merge_sorted(a, b):
    """Merge two sorted lists into one sorted list."""
    result = []
    i = j = 0
    while i < len(a) and j < len(b):
        if a[i] <= b[j]:
            result.append(a[i])
            i += 1
        else:
            result.append(b[j])
            j += 1
    result.extend(a[i:])  # Bug: missing result.extend(b[j:])


if __name__ == "__main__":
    nums = [10, 20, 30, 40, 50]
    print(f"Average: {calculate_average(nums)}")

    print(f"fib(10) = {fibonacci(10)}")

    print(f"Merge [1,3,5] + [2,4,6] = {merge_sorted([1, 3, 5], [2, 4, 6])}")
