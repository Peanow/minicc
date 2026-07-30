# CoreCoder evaluation harness

This directory contains reproducible coding-agent tasks and versioned manifests.
It is intentionally separate from the unit-test suite:

- a **fixture** is the exact unsolved workspace copied for each case;
- a **check** is a deterministic command that decides whether the task passed;
- a **model profile** contains public connection metadata and the name of an
  environment variable holding its API key;
- a **strategy profile** selects context, permission, and tokenizer behavior;
- a **case** is one task × model × strategy combination.

The benchmark is organized into Tier 1 fast regression, Tier 2 small real
repositories, and Tier 3 external issue benchmarks. See
[`TIERS.md`](TIERS.md) for the evidence standard and scope of each layer.

## Inspect the plan

Dry runs validate every fixture and protected path without loading an API key:

```bash
corecoder eval benchmarks/local-v1.json --dry-run
corecoder eval benchmarks/local-v1.json --dry-run \
  --task python-safe-path --strategy hybrid-workspace
```

`local-v1.json` contains eighteen deliberately unsolved local tasks. Its
default matrix repeats every task three times across `hybrid`, `truncate`, and
`summary` under the same context budget. Use `--repeat 1` only for smoke
checks. The comparison model stays disabled until its connection and cost
settings are supplied explicitly.

The first Tier 2 pilot is a pinned python-diskcache regression:

```bash
corecoder eval benchmarks/tier2-pilot.json --dry-run --repeat 1
```

Its curated snapshot records the upstream commit, PR, and Apache-2.0 license
in both the manifest and `UPSTREAM.md`.

## Run cases

```bash
corecoder eval benchmarks/local-v1.json \
  --task python-safe-path \
  --strategy hybrid-workspace \
  -o benchmarks/results/local-v1-smoke
```

The runner reads credentials only from each model profile's `api_key_env`. It
does not serialize the key or add it to process arguments. The agent receives
only the selected credential long enough to initialize its model client; tool
and verifier subprocesses run with credential-like environment variables
removed. Each case runs in a fresh temporary workspace with an isolated SQLite
memory database.

An output directory contains:

```text
manifest.snapshot.json
run.json                 # status, timestamps, plan, manifest/fixture/harness hashes
results.jsonl            # one append-only record per completed case
summary.json             # aggregate success, token, time, cost, safety metrics
cases/<case-id>/
  trace.jsonl
  agent.stdout.log
  agent.stderr.log
  memory.db
```

The runner refuses to append to an existing `results.jsonl`, preventing
accidental mixing of separate experiments.

## Replay and comparison

New traces contain a workspace-normalized SHA-256 fingerprint for each model
request. A recorded case can therefore drive the Agent Runtime without another
model call:

```bash
corecoder runtime-replay path/to/trace.jsonl \
  --fixture tasks/python-inclusive-range \
  -o ../.tmp/runtime-replay
```

The command copies the fixture, replays model responses, re-executes supported
file tools, and compares request fingerprints and tool results. It refuses
full-access recordings and recordings that actually executed Bash or a
sub-agent. Project shell hooks are disabled during replay.

Generate an offline comparison from one or more evidence directories:

```bash
corecoder compare results/run-a results/run-b -o ../.tmp/comparison.html
```

The HTML is self-contained and includes a profile summary plus a task/profile
matrix. Unknown or partial costs remain visibly unknown.

## Commit-safe evidence

Evaluation directories intentionally contain artifacts that must not be
committed. Audit a completed run and export a reviewed evidence bundle:

```bash
corecoder evidence ../.tmp/local-v1-run \
  -o results/local-v1-reviewed
```

The exporter:

1. validates run and summary consistency;
2. replays every Trace lifecycle and cross-checks token, status, and changed
   file metrics;
3. rejects credential-like result data and sanitizes the portable manifest;
4. replaces Trace/log paths with SHA-256 hashes and lifecycle metadata;
5. emits portable `results.jsonl`, `summary.json`, `manifest.json`,
   `evidence.json`, and `report.html`.

Each record also includes evaluator-hidden check outcomes, filesystem-observed
changes, edit precision, unrelated-file modification rate, tool-failure
recovery, and context-compaction counts. An `evaluation_measured` Trace event
records the same per-case measurements.

Trace bodies, stdout/stderr contents, SQLite databases, and temporary
workspaces remain in the ignored source directory and are never copied.

## Integrity rules

Every bundled task declares `protected_paths`, currently its `verify.py`.
The runner hashes protected files before and after the agent executes. A case
cannot pass if the verifier was changed, even when the changed verifier exits
successfully.

Checks are argument arrays, never shell strings. Fixture paths and protected
paths must remain inside the manifest directory and task fixture respectively;
external symlinks are rejected.

`hidden_checks` point to evaluator scripts outside the copied workspace. This
prevents ordinary prompt/workspace inspection from revealing assertions, but
it is not an OS sandbox: full host-process isolation remains out of scope.

## Metric policy

Success requires all of the following:

1. the agent process exits successfully;
2. Trace Replay reports one complete, valid run;
3. the run status is `completed`;
4. protected files are unchanged;
5. every deterministic check passes.

Token counts and lifecycle duration come from the trace; wall duration also
includes deterministic checks. Policy denials are grouped into read-only,
workspace-execution, network, destructive, shell-composition, and unknown risk
classes. Aggregate cost remains `null` unless every case has both input and
output prices in its model profile. This prevents partial, unknown, or outdated
pricing from being presented as measured total cost.
