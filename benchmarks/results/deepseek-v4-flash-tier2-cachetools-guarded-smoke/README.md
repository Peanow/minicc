# Reviewed cachetools guarded smoke

This single hybrid case used runtime commit `118bad2`. DeepSeek returned three
consecutive empty responses after initial inspection. The runtime recorded two
retries, exhausted the configured recovery budget, and finished explicitly as
`empty_response`; no source file was modified and the hidden check failed.

This directory was produced by `corecoder evidence`. Trace bodies, agent logs,
memory databases, and temporary workspaces are excluded. Their SHA-256 hashes
and audited lifecycle metadata remain in `results.jsonl`.
