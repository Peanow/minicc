# DeepSeek v4 Flash smoke evidence

This reviewed one-case run proves the end-to-end path from an
OpenAI-compatible DeepSeek request through workspace editing, policy checks,
verification, Trace replay, and commit-safe evidence export. It is a smoke
test, not a model-quality benchmark.

The case passed its protected verifier. Trace bodies, agent logs, memory
databases, and temporary workspaces are excluded; their SHA-256 hashes and
audited lifecycle metadata remain in `results.jsonl`.
