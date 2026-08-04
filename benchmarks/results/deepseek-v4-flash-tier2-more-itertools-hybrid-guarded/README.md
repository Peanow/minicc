# Reviewed more-itertools guarded hybrid smoke

This single hybrid case used runtime commit `118bad2`. After 12 tool rounds
without a source edit, one stagnation recovery prompted a focused fix. Public
and hidden checks passed. The model changed the expected source file and left
one temporary verification file, producing edit precision 0.5.

This directory was produced by `corecoder evidence`. Trace bodies, agent logs,
memory databases, and temporary workspaces are excluded. Their SHA-256 hashes
and audited lifecycle metadata remain in `results.jsonl`.
