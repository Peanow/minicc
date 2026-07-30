"""Offline multi-run evaluation comparison reports."""

from __future__ import annotations

import html
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass
class ProfileMetrics:
    profile: str
    cases: int
    successful: int
    success_rate: float
    total_tokens: int
    duration_ms: float
    wall_duration_ms: float
    estimated_cost_usd: float | None
    policy_denials: int
    policy_denials_by_risk: dict[str, int]
    integrity_failures: int
    hidden_pass_rate: float | None
    mean_edit_precision: float | None
    mean_unrelated_file_modification_rate: float | None
    failure_recovery_rate: float | None
    context_compactions: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ComparisonSummary:
    source_count: int
    record_count: int
    profiles: list[ProfileMetrics]
    tasks: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_count": self.source_count,
            "record_count": self.record_count,
            "profiles": [profile.to_dict() for profile in self.profiles],
            "tasks": self.tasks,
        }


def _result_path(path: str | Path) -> Path:
    source = Path(path).expanduser().resolve()
    return source / "results.jsonl" if source.is_dir() else source


def load_eval_records(paths: Iterable[str | Path]) -> tuple[list[dict], list[str]]:
    """Load result JSONL files without requiring their original workspaces."""
    records: list[dict] = []
    labels: list[str] = []
    for value in paths:
        source = _result_path(value)
        if not source.is_file():
            raise ValueError(f"evaluation results do not exist: {source}")
        label = source.parent.name if source.name == "results.jsonl" else source.stem
        labels.append(label)
        for line_number, raw in enumerate(
            source.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid JSON in {source.name} line {line_number}: {exc}"
                ) from exc
            required = {
                "task_id",
                "model_profile",
                "strategy_profile",
                "success",
                "prompt_tokens",
                "completion_tokens",
                "duration_ms",
            }
            if not isinstance(record, dict) or not required.issubset(record):
                raise ValueError(
                    f"invalid evaluation record in {source.name} line {line_number}"
                )
            record = dict(record)
            record["_source"] = label
            records.append(record)
    if not labels:
        raise ValueError("at least one evaluation result is required")
    if not records:
        raise ValueError("evaluation results are empty")
    return records, labels


def _profile_id(record: dict) -> str:
    return f"{record['model_profile']} / {record['strategy_profile']}"


def summarize_comparison(
    records: list[dict],
    *,
    source_count: int = 1,
) -> ComparisonSummary:
    groups: dict[str, list[dict]] = {}
    for record in records:
        groups.setdefault(_profile_id(record), []).append(record)
    profiles: list[ProfileMetrics] = []
    for profile, group in sorted(groups.items()):
        successful = sum(bool(record.get("success")) for record in group)
        costs_known = all(
            record.get("estimated_cost_usd") is not None for record in group
        )
        risk_counts: dict[str, int] = {}
        for record in group:
            for risk, count in (record.get("policy_denials_by_risk") or {}).items():
                risk_counts[str(risk)] = risk_counts.get(str(risk), 0) + int(count)
        profiles.append(ProfileMetrics(
            profile=profile,
            cases=len(group),
            successful=successful,
            success_rate=round(successful / len(group), 4),
            total_tokens=sum(
                int(record.get("prompt_tokens") or 0)
                + int(record.get("completion_tokens") or 0)
                for record in group
            ),
            duration_ms=round(
                sum(float(record.get("duration_ms") or 0) for record in group),
                2,
            ),
            wall_duration_ms=round(
                sum(
                    float(
                        record.get("wall_duration_ms")
                        or record.get("duration_ms")
                        or 0
                    )
                    for record in group
                ),
                2,
            ),
            estimated_cost_usd=(
                round(
                    sum(float(record.get("estimated_cost_usd") or 0) for record in group),
                    8,
                )
                if costs_known
                else None
            ),
            policy_denials=sum(int(record.get("policy_denials") or 0) for record in group),
            policy_denials_by_risk=dict(sorted(risk_counts.items())),
            integrity_failures=sum(
                not bool(record.get("protected_files_unchanged", True))
                for record in group
            ),
            hidden_pass_rate=_ratio(
                sum(
                    int(record.get("hidden_checks_passed") or 0)
                    for record in group
                ),
                sum(
                    int(record.get("hidden_checks_total") or 0)
                    for record in group
                ),
            ),
            mean_edit_precision=_mean(group, "edit_precision"),
            mean_unrelated_file_modification_rate=_mean(
                group,
                "unrelated_file_modification_rate",
            ),
            failure_recovery_rate=_ratio(
                sum(record.get("failure_recovered") is True for record in group),
                sum(int(record.get("tool_failures") or 0) > 0 for record in group),
            ),
            context_compactions=sum(
                int(record.get("context_compactions") or 0) for record in group
            ),
        ))
    return ComparisonSummary(
        source_count=source_count,
        record_count=len(records),
        profiles=profiles,
        tasks=sorted({str(record["task_id"]) for record in records}),
    )


def _format_cost(value: float | None) -> str:
    return "unknown" if value is None else f"${value:.4f}"


def _format_risks(values: dict[str, int]) -> str:
    return ", ".join(f"{risk}: {count}" for risk, count in values.items()) or "—"


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _mean(records: list[dict], field: str) -> float | None:
    values = [
        float(record[field])
        for record in records
        if record.get(field) is not None
    ]
    if not values:
        return None
    return round(
        sum(values) / len(values),
        4,
    )


def _format_rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def generate_comparison_report(
    inputs: Iterable[str | Path],
    output_path: str | Path,
) -> ComparisonSummary:
    """Generate a self-contained model/strategy comparison HTML report."""
    records, labels = load_eval_records(inputs)
    summary = summarize_comparison(records, source_count=len(labels))
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    profile_rows = "".join(
        "<tr>"
        f"<th>{html.escape(profile.profile)}</th>"
        f"<td>{profile.successful}/{profile.cases}</td>"
        f"<td>{profile.success_rate * 100:.1f}%</td>"
        f"<td>{profile.total_tokens:,}</td>"
        f"<td>{profile.wall_duration_ms / 1000:.2f}s</td>"
        f"<td>{html.escape(_format_cost(profile.estimated_cost_usd))}</td>"
        f"<td>{profile.policy_denials}</td>"
        f"<td>{html.escape(_format_risks(profile.policy_denials_by_risk))}</td>"
        f"<td>{profile.integrity_failures}</td>"
        f"<td>{html.escape(_format_rate(profile.hidden_pass_rate))}</td>"
        f"<td>{html.escape(_format_rate(profile.mean_edit_precision))}</td>"
        "<td>"
        f"{html.escape(_format_rate(profile.mean_unrelated_file_modification_rate))}"
        "</td>"
        f"<td>{html.escape(_format_rate(profile.failure_recovery_rate))}</td>"
        f"<td>{profile.context_compactions}</td>"
        "</tr>"
        for profile in summary.profiles
    )

    profile_names = [profile.profile for profile in summary.profiles]
    cells: dict[tuple[str, str], list[bool]] = {}
    for record in records:
        cells.setdefault(
            (str(record["task_id"]), _profile_id(record)),
            [],
        ).append(bool(record.get("success")))
    matrix_head = "".join(
        f"<th>{html.escape(profile)}</th>" for profile in profile_names
    )
    matrix_rows = []
    for task in summary.tasks:
        row = [f"<th>{html.escape(task)}</th>"]
        for profile in profile_names:
            outcomes = cells.get((task, profile), [])
            if not outcomes:
                row.append('<td class="missing">—</td>')
                continue
            passed = sum(outcomes)
            css = "pass" if passed == len(outcomes) else "fail"
            label = "pass" if len(outcomes) == 1 and passed else (
                "fail" if len(outcomes) == 1 else f"{passed}/{len(outcomes)}"
            )
            row.append(f'<td class="{css}">{html.escape(label)}</td>')
        matrix_rows.append("<tr>" + "".join(row) + "</tr>")

    sources = ", ".join(html.escape(label) for label in labels)
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CoreCoder evaluation comparison</title>
<style>
:root {{ color-scheme:dark;--bg:#0b1020;--panel:#151c30;--line:#28324d;
--text:#e8ecf5;--muted:#98a2b8;--good:#70d6b7;--bad:#ff8b8b }}
* {{ box-sizing:border-box }} body {{ margin:0;background:var(--bg);color:var(--text);
font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace }}
main {{ max-width:1280px;margin:auto;padding:36px 22px 70px }}
h1 {{ margin:0 0 6px;font-size:28px }} .subtitle {{ color:var(--muted);margin-bottom:26px }}
.table-wrap {{ overflow:auto;background:var(--panel);border:1px solid var(--line);
border-radius:10px;margin:12px 0 30px }} table {{ border-collapse:collapse;width:100%;
min-width:760px }} th,td {{ padding:11px 13px;border-bottom:1px solid var(--line);
text-align:right;white-space:nowrap }} th:first-child,td:first-child {{ text-align:left }}
thead th {{ color:var(--muted) }} tbody tr:last-child th,tbody tr:last-child td {{
border-bottom:0 }} .pass {{ color:var(--good);font-weight:700 }}
.fail {{ color:var(--bad);font-weight:700 }} .missing {{ color:var(--muted) }}
.note {{ color:var(--muted);border-left:3px solid var(--line);padding-left:12px }}
</style>
</head>
<body><main>
<h1>CoreCoder evaluation comparison</h1>
<div class="subtitle">{summary.record_count} records · {summary.source_count} sources · {sources}</div>
<h2>Profiles</h2>
<div class="table-wrap"><table>
<thead><tr><th>Model / strategy</th><th>Passed</th><th>Success</th>
<th>Tokens</th><th>Wall time</th><th>Cost</th><th>Policy denials</th>
<th>Denied risk classes</th><th>Integrity failures</th><th>Hidden pass</th>
<th>Edit precision</th><th>Unrelated edits</th><th>Failure recovery</th>
<th>Compactions</th></tr></thead>
<tbody>{profile_rows}</tbody>
</table></div>
<h2>Task matrix</h2>
<div class="table-wrap"><table>
<thead><tr><th>Task</th>{matrix_head}</tr></thead>
<tbody>{''.join(matrix_rows)}</tbody>
</table></div>
<p class="note">Cost is shown as unknown unless every record in a profile has
explicit model pricing. A comparison is evidence, not a quality claim, until
the underlying manifests, fixture hashes, and raw results are reviewed.</p>
</main></body></html>"""
    output.write_text(document, encoding="utf-8")
    return summary
