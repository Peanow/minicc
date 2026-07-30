"""Tests for pluggable context strategies and token counters."""

import sys
from types import SimpleNamespace

import pytest

from corecoder.context import (
    ContextManager,
    SummaryContextStrategy,
    TruncateContextStrategy,
    create_context_strategy,
    estimate_tokens,
)
from corecoder.llm import LLMResponse
from corecoder.tokenizer import ApproxTokenCounter, create_token_counter


class CharacterCounter:
    name = "characters"

    def count_text(self, text: str) -> int:
        return len(text)

    def count_messages(self, messages: list[dict]) -> int:
        return sum(len(str(message.get("content") or "")) for message in messages)


class SummaryLLM:
    calls = 0

    def chat(self, **kwargs):
        self.calls += 1
        return LLMResponse(content="Files touched: src/app.py; pending: run tests")


def _long_tool_messages(count=12):
    return [
        {
            "role": "tool",
            "tool_call_id": f"tool-{index}",
            "content": "\n".join(f"line {line} {'x' * 80}" for line in range(20)),
        }
        for index in range(count)
    ]


def test_approx_counter_handles_messages_and_tool_calls():
    counter = ApproxTokenCounter()
    messages = [{
        "role": "assistant",
        "content": "hello",
        "tool_calls": [{"function": {"name": "read_file"}}],
    }]
    assert counter.count_messages(messages) > counter.count_text("hello")
    assert estimate_tokens(messages, counter) == counter.count_messages(messages)


def test_auto_tokenizer_falls_back_for_unknown_model():
    counter = create_token_counter("auto", "definitely-unknown-model")
    assert counter.name in {"approx"} or counter.name.startswith("tiktoken:")


def test_unknown_tokenizer_provider_is_rejected():
    with pytest.raises(ValueError, match="unknown tokenizer"):
        create_token_counter("invalid", "model")


def test_tiktoken_counter_for_supported_model(monkeypatch):
    class FakeEncoding:
        name = "fake-base"

        def encode(self, text):
            return list(text.encode())

    monkeypatch.setitem(
        sys.modules,
        "tiktoken",
        SimpleNamespace(encoding_for_model=lambda model: FakeEncoding()),
    )
    counter = create_token_counter("tiktoken", "gpt-4o")
    assert counter.name == "tiktoken:fake-base"
    assert counter.count_text("hello world") == 11


def test_strategy_factory():
    counter = CharacterCounter()
    assert isinstance(create_context_strategy("truncate", 1000, counter), TruncateContextStrategy)
    assert isinstance(create_context_strategy("summary", 1000, counter), SummaryContextStrategy)
    assert isinstance(create_context_strategy("hybrid", 1000, counter), ContextManager)
    with pytest.raises(ValueError, match="unknown context strategy"):
        create_context_strategy("invalid", 1000, counter)


def test_truncate_strategy_never_calls_llm():
    class FailingLLM:
        def chat(self, **kwargs):
            raise AssertionError("truncate strategy must not call the LLM")

    messages = _long_tool_messages()
    strategy = TruncateContextStrategy(
        max_tokens=5000,
        token_counter=CharacterCounter(),
    )
    assert strategy.maybe_compress(messages, FailingLLM())
    assert "tool_snip" in strategy.last_operations
    assert strategy.count_messages(messages) < 5000


def test_fixed_prompt_tokens_participate_in_compaction_threshold():
    messages = _long_tool_messages(count=1)
    strategy = TruncateContextStrategy(
        max_tokens=5000,
        token_counter=CharacterCounter(),
    )
    raw_message_tokens = strategy.count_messages(messages)
    assert raw_message_tokens < strategy._snip_at

    assert strategy.maybe_compress(
        messages,
        fixed_tokens=strategy._snip_at,
    )
    assert "tool_snip" in strategy.last_operations


def test_summary_strategy_records_summary_operation():
    messages = [
        {"role": "user", "content": f"request {index} " + "x" * 100}
        for index in range(15)
    ]
    llm = SummaryLLM()
    strategy = SummaryContextStrategy(
        max_tokens=1800,
        token_counter=CharacterCounter(),
    )
    assert strategy.maybe_compress(messages, llm)
    assert "summary" in strategy.last_operations
    assert llm.calls >= 1
    assert any("Context compressed" in str(message.get("content")) for message in messages)


def test_hybrid_strategy_reports_operations():
    messages = _long_tool_messages()
    strategy = ContextManager(
        max_tokens=5000,
        token_counter=CharacterCounter(),
    )
    assert strategy.maybe_compress(messages, None)
    assert strategy.strategy_name == "hybrid"
    assert strategy.last_operations
