"""Side-effect-free trace validation, replay summaries, and HTML reports."""

from __future__ import annotations

import html
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class ReplaySummary:
    run_id: str
    valid: bool
    status: str
    event_count: int
    llm_calls: int
    tool_calls: int
    prompt_tokens: int
    completion_tokens: int
    duration_ms: float
    changed_files: list[str] = field(default_factory=list)
    event_counts: dict[str, int] = field(default_factory=dict)
    validation_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def load_trace(path: str | Path) -> list[dict]:
    """Load and minimally validate an append-only JSONL trace."""
    trace_path = Path(path).expanduser().resolve()
    events: list[dict] = []
    for line_number, raw in enumerate(
        trace_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON at line {line_number}: {exc}") from exc
        if not isinstance(event, dict) or not event.get("event"):
            raise ValueError(f"invalid trace event at line {line_number}")
        events.append(event)
    if not events:
        raise ValueError("trace is empty")
    return events


def replay_trace(path: str | Path) -> ReplaySummary:
    """Validate lifecycle ordering and reconstruct aggregate run metrics.

    Replay never calls a model and never executes a tool.
    """
    events = load_trace(path)
    run_ids = {str(event.get("run_id", "")) for event in events}
    errors: list[str] = []
    if len(run_ids) != 1:
        errors.append(f"expected one run_id, found {len(run_ids)}")
    run_id = sorted(run_ids)[0] if run_ids else ""

    counts = Counter(str(event["event"]) for event in events)
    active_llm = 0
    active_tools: defaultdict[str, int] = defaultdict(int)
    pending_results: set[str] = set()
    prompt_tokens = 0
    completion_tokens = 0
    status = "incomplete"
    changed_files: set[str] = set()

    for index, event in enumerate(events):
        name = event["event"]
        data = event.get("data") or {}
        if name == "llm_started":
            active_llm += 1
        elif name == "llm_finished":
            if active_llm <= 0:
                errors.append(f"event {index}: llm_finished without llm_started")
            else:
                active_llm -= 1
            prompt_tokens += int(data.get("prompt_tokens") or 0)
            completion_tokens += int(data.get("completion_tokens") or 0)
            pending_results.update(
                str(call.get("id", ""))
                for call in data.get("tool_calls") or []
                if isinstance(call, dict) and call.get("id")
            )
        elif name == "tool_started":
            active_tools[str(data.get("tool", ""))] += 1
        elif name == "tool_finished":
            tool = str(data.get("tool", ""))
            if active_tools[tool] <= 0:
                errors.append(f"event {index}: tool_finished without tool_started ({tool})")
            else:
                active_tools[tool] -= 1
        elif name == "tool_result":
            tool_call_id = str(data.get("tool_call_id", ""))
            if tool_call_id not in pending_results:
                errors.append(
                    f"event {index}: unexpected tool_result ({tool_call_id})"
                )
            else:
                pending_results.remove(tool_call_id)
        elif name == "run_finished":
            status = str(data.get("status") or "unknown")
            changed_files.update(str(path) for path in data.get("changed_files") or [])

    if active_llm:
        errors.append(f"{active_llm} unfinished LLM call(s)")
    unfinished_tools = sum(active_tools.values())
    if unfinished_tools:
        errors.append(f"{unfinished_tools} unfinished tool call(s)")
    if pending_results:
        errors.append(f"{len(pending_results)} missing tool result(s)")
    if counts["run_started"] != counts["run_finished"]:
        errors.append(
            f"run lifecycle mismatch: {counts['run_started']} started, "
            f"{counts['run_finished']} finished"
        )

    timestamps = [
        float(event["timestamp"])
        for event in events
        if isinstance(event.get("timestamp"), (int, float))
    ]
    duration_ms = (
        round((max(timestamps) - min(timestamps)) * 1000, 2)
        if len(timestamps) >= 2
        else 0.0
    )
    return ReplaySummary(
        run_id=run_id,
        valid=not errors,
        status=status,
        event_count=len(events),
        llm_calls=counts["llm_finished"],
        tool_calls=counts["tool_result"] or counts["tool_finished"],
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        duration_ms=duration_ms,
        changed_files=sorted(changed_files),
        event_counts=dict(sorted(counts.items())),
        validation_errors=errors,
    )


def generate_html_report(
    trace_path: str | Path,
    output_path: str | Path,
) -> ReplaySummary:
    """Generate a dependency-free, self-contained single-run report."""
    events = load_trace(trace_path)
    summary = replay_trace(trace_path)
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    cards = [
        ("Status", summary.status),
        ("Valid replay", "yes" if summary.valid else "no"),
        ("LLM calls", summary.llm_calls),
        ("Tool calls", summary.tool_calls),
        ("Tokens", summary.prompt_tokens + summary.completion_tokens),
        ("Duration", f"{summary.duration_ms / 1000:.2f}s"),
    ]
    card_html = "".join(
        f'<div class="card"><span>{html.escape(str(label))}</span>'
        f"<strong>{html.escape(str(value))}</strong></div>"
        for label, value in cards
    )

    start = float(events[0].get("timestamp") or 0)
    timeline = []
    for event in events:
        offset = (float(event.get("timestamp") or start) - start) * 1000
        name = str(event["event"])
        data = json.dumps(
            event.get("data") or {},
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        timeline.append(
            '<details class="event">'
            f"<summary><code>+{offset:,.0f} ms</code>"
            f"<b>{html.escape(name)}</b></summary>"
            f"<pre>{html.escape(data)}</pre></details>"
        )

    error_html = ""
    if summary.validation_errors:
        items = "".join(
            f"<li>{html.escape(error)}</li>"
            for error in summary.validation_errors
        )
        error_html = f'<section class="errors"><h2>Validation errors</h2><ul>{items}</ul></section>'

    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CoreCoder Trace {html.escape(summary.run_id[:8])}</title>
<style>
:root {{ color-scheme: dark; --bg:#0b1020; --panel:#151c30; --line:#28324d;
--text:#e8ecf5; --muted:#98a2b8; --accent:#70d6b7; --bad:#ff8b8b; }}
* {{ box-sizing:border-box }} body {{ margin:0;background:var(--bg);color:var(--text);
font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace }}
main {{ max-width:1100px;margin:auto;padding:36px 22px 70px }}
h1 {{ margin:0 0 6px;font-size:28px }} .subtitle {{ color:var(--muted);margin-bottom:24px }}
.cards {{ display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px;margin:24px 0 }}
.card {{ background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:15px }}
.card span {{ color:var(--muted);display:block }} .card strong {{ font-size:22px;color:var(--accent) }}
.event {{ background:var(--panel);border:1px solid var(--line);border-radius:9px;margin:8px 0 }}
.event summary {{ cursor:pointer;padding:12px 14px;display:flex;gap:18px }}
.event summary code {{ color:var(--muted);min-width:105px }} pre {{ overflow:auto;margin:0;
padding:0 14px 14px;color:#cad3e8;white-space:pre-wrap }}
.errors {{ border-left:4px solid var(--bad);padding:1px 16px;color:#ffd0d0 }}
footer {{ color:var(--muted);margin-top:28px }}
</style>
</head>
<body><main>
<h1>CoreCoder execution trace</h1>
<div class="subtitle">Run {html.escape(summary.run_id)} · schema v1 · side-effect-free replay</div>
<div class="cards">{card_html}</div>
{error_html}
<h2>Timeline</h2>
{''.join(timeline)}
<footer>Generated locally by CoreCoder. Trace values were redacted before persistence.</footer>
</main></body></html>"""
    output.write_text(document, encoding="utf-8")
    return summary
