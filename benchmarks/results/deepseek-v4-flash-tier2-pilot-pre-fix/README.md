# Reviewed Tier 2 pre-fix evidence

This nine-case run used runtime commit `ed3b0aa` and repeated the
python-diskcache pilot three times across `hybrid`, `truncate`, and `summary`.
Eight cases succeeded. The remaining summary case passed public and hidden
checks but ended with an incomplete Trace after context compaction split an
assistant tool call from its tool response.

This directory was produced by `corecoder evidence`. Trace bodies, agent logs,
memory databases, and temporary workspaces are excluded. Their SHA-256 hashes
and audited lifecycle metadata remain in `results.jsonl`.
