from redaction import redact_secrets


source = (
    "Authorization: Bearer abc.DEF-123\n"
    "api_key=secret-value token: another_secret PASSWORD = p@ss\n"
    "tokenizer=approx ordinary passwordless text"
)
redacted = redact_secrets(source)
assert "abc.DEF-123" not in redacted
assert "secret-value" not in redacted
assert "another_secret" not in redacted
assert "p@ss" not in redacted
assert redacted.count("[REDACTED]") == 4
assert "tokenizer=approx" in redacted
assert "passwordless" in redacted
