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
