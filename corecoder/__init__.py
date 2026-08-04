"""CoreCoder - observable, policy-aware coding-agent experimentation runtime."""

__version__ = "0.3.0"

from corecoder.agent import Agent
from corecoder.llm import LLM
from corecoder.config import Config
from corecoder.tools import ALL_TOOLS, ToolRegistry
from corecoder.trace import (
    CompositeTraceSink,
    JsonlTraceSink,
    OpenTelemetryTraceSink,
    RunResult,
)
from corecoder.policy import ExecutionPolicy, PermissionMode, RiskClass
from corecoder.context import create_context_strategy
from corecoder.tokenizer import create_token_counter
from corecoder.replay import generate_html_report, replay_trace
from corecoder.eval import aggregate_records, load_manifest, plan_cases, run_evaluation
from corecoder.runtime_replay import runtime_replay
from corecoder.comparison import generate_comparison_report
from corecoder.evidence import export_evidence
from corecoder.observability import ObservabilityConfig

__all__ = [
    "Agent", "LLM", "Config", "ALL_TOOLS", "ToolRegistry",
    "CompositeTraceSink", "JsonlTraceSink", "OpenTelemetryTraceSink",
    "RunResult", "__version__",
    "ExecutionPolicy", "PermissionMode", "RiskClass",
    "create_context_strategy", "create_token_counter",
    "generate_html_report", "replay_trace",
    "aggregate_records", "load_manifest", "plan_cases", "run_evaluation",
    "runtime_replay",
    "generate_comparison_report",
    "export_evidence",
    "ObservabilityConfig",
]
