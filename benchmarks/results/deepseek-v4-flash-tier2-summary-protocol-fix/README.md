# Reviewed Tier 2 protocol-fix evidence

This three-case summary-strategy regression used runtime commit `1e14209`.
Every run completed without an OpenAI-compatible tool-message protocol error;
all 12 context compaction events reported `protocol_valid=true`. Two cases
passed the hidden task check. The remaining case completed normally but changed
the wrong source file, so it remains a model-quality failure.

This directory was produced by `corecoder evidence`. Trace bodies, agent logs,
memory databases, and temporary workspaces are excluded. Their SHA-256 hashes
and audited lifecycle metadata remain in `results.jsonl`.
