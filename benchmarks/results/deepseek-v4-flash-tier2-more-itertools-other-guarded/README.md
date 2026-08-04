# Reviewed more-itertools guarded strategy smoke

These truncate and summary cases used runtime commit `118bad2`; both passed
public and hidden checks. Truncate used one stagnation recovery and achieved
edit precision 0.5. Summary used one empty-response retry and achieved edit
precision 0.3333 because it left two unrelated verification files.

This directory was produced by `corecoder evidence`. Trace bodies, agent logs,
memory databases, and temporary workspaces are excluded. Their SHA-256 hashes
and audited lifecycle metadata remain in `results.jsonl`.
