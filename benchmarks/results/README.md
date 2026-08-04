# Evaluation evidence

Place reviewed benchmark outputs in versioned subdirectories here. Do not add
API keys, private prompts, proprietary source fixtures, or results whose
manifest and fixture hashes cannot be reproduced.

Use `corecoder evidence` to create commit-safe subdirectories here. No
model-quality result is claimed until `results.jsonl`, `summary.json`,
`manifest.json`, and `evidence.json` are reviewed and committed together.
Generated Trace bodies and logs must remain outside Git.

Available reviewed evidence:

- `deepseek-v4-flash-smoke`: one successful end-to-end case. This validates
  the evaluation and evidence pipeline only; it is not a model-quality claim.
- `deepseek-v4-flash-tier2-pilot-pre-fix`: nine repeated real-repository
  cases from runtime commit `ed3b0aa`. Eight completed successfully; the
  remaining summary-strategy run exposed a tool-message compaction bug even
  though its public and hidden checks passed.
- `deepseek-v4-flash-tier2-summary-protocol-fix`: three summary-strategy
  regressions from runtime commit `1e14209`. All three runs completed without
  provider protocol errors and all 12 compaction events reported a valid tool
  protocol; two of three runs passed the hidden task check.

These Tier 2 results cover one pilot task and are engineering evidence, not a
general model-quality claim.

- `deepseek-v4-flash-tier2-cachetools-guarded-smoke`: one guarded hybrid run
  from runtime commit `118bad2`. The model exhausted two empty-response retries
  and failed explicitly with `empty_response`; this is recovery-boundary
  evidence, not a task-quality result.
- `deepseek-v4-flash-tier2-more-itertools-hybrid-guarded`: one successful
  guarded hybrid run. A stagnation recovery converted prolonged inspection into
  a focused source edit.
- `deepseek-v4-flash-tier2-more-itertools-other-guarded`: successful truncate
  and summary smoke cases. Truncate used stagnation recovery; summary used one
  empty-response retry.

The guarded more-itertools runs are one sample per strategy. They validate the
runtime and task harness but are not yet a repeated strategy comparison.
