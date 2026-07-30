# Layered evaluation design

CoreCoder separates runtime engineering evidence from model trivia scores.
Each tier answers a different question and uses the same isolated runner,
append-only Trace, verifier-integrity checks, and commit-safe evidence export.

## Tier 1 — fast regression

`local-v1.json` contains 18 dependency-free tasks. It is designed for quick
runtime regression, policy checks, and controlled context-strategy comparison.
The default matrix runs every task three times with `hybrid`, `truncate`, and
`summary` under the same 32,000-token context budget. Budget accounting includes
the system prompt and tool schemas as well as conversation messages.

Tier 1 is not presented as a general coding-quality benchmark.

## Tier 2 — small real repositories

Tier 2 will contain 8–12 pinned, license-compatible repository snapshots.
The current pilot reproduces python-diskcache PR #288 from its pre-fix commit;
it retains the Apache-2.0 license and keeps the upstream regression assertion
outside the Agent workspace.

Every task must include:

- upstream repository URL, immutable commit, license, and issue/PR provenance;
- a repository-shaped fixture with at least two relevant source files;
- a verifier that is absent from the Agent workspace;
- explicit expected change paths and protected paths;
- one of these primary capabilities: multi-file editing, failure diagnosis,
  layered instructions, long context, permission conflict, or error recovery.

Repository snapshots must be reviewed before commit. Generated dependency
caches, upstream Git history, credentials, and proprietary sources are never
vendored.

## Tier 3 — external issue benchmark

Tier 3 is an adapter boundary for a pinned subset of SWE-bench Lite or public
open-source issues. The adapter must emit the same `EvalRecord` fields as the
local runner, including repetition, hidden-validation, edit-quality, recovery,
policy, and compaction metrics.

Tier 3 data should remain externally sourced and version-pinned. CoreCoder
should store only adapter configuration and reviewed result evidence unless
the source dataset's license explicitly permits vendoring.

## Required reporting

Every externally quoted comparison must state:

1. task tier and exact task count;
2. model and context strategy;
3. repetition count;
4. success and hidden-check pass rates;
5. edit precision and unrelated-file modification rate;
6. failure recovery rate and context compaction count;
7. manifest, fixture, hidden-check, and harness hashes.

Results with one run per configuration are smoke evidence, not quality claims.
