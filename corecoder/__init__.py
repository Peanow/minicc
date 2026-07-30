"""CoreCoder - Minimal AI coding agent inspired by Claude Code's architecture."""

__version__ = "0.3.0"

from corecoder.agent import Agent
from corecoder.llm import LLM
from corecoder.config import Config
from corecoder.tools import ALL_TOOLS, ToolRegistry
from corecoder.trace import JsonlTraceSink, RunResult
from corecoder.policy import ExecutionPolicy, PermissionMode
from corecoder.context import create_context_strategy
from corecoder.tokenizer import create_token_counter
from corecoder.replay import generate_html_report, replay_trace

__all__ = [
    "Agent", "LLM", "Config", "ALL_TOOLS", "ToolRegistry",
    "JsonlTraceSink", "RunResult", "__version__",
    "ExecutionPolicy", "PermissionMode",
    "create_context_strategy", "create_token_counter",
    "generate_html_report", "replay_trace",
]
