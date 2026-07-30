from circuit import CircuitBreaker, CircuitOpenError


now = [100.0]
attempts = []
breaker = CircuitBreaker(2, 10, clock=lambda: now[0])


def fail():
    attempts.append("fail")
    raise TimeoutError("down")


for _ in range(2):
    try:
        breaker.call(fail)
    except TimeoutError:
        pass

try:
    breaker.call(lambda: attempts.append("must-not-run"))
except CircuitOpenError:
    pass
else:
    raise AssertionError("open circuit must reject calls")
assert "must-not-run" not in attempts

now[0] = 110.0
assert breaker.call(lambda: "recovered") == "recovered"
assert breaker.call(lambda: "closed") == "closed"

for _ in range(2):
    try:
        breaker.call(fail)
    except TimeoutError:
        pass
now[0] = 120.0
try:
    breaker.call(fail)
except TimeoutError:
    pass
try:
    breaker.call(lambda: "still-open")
except CircuitOpenError:
    pass
else:
    raise AssertionError("failed half-open trial must reopen the circuit")
