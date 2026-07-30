"""Pluggable token counters for context budgeting."""

from __future__ import annotations

import json
from typing import Protocol


class TokenCounter(Protocol):
    name: str

    def count_text(self, text: str) -> int:
        ...

    def count_messages(self, messages: list[dict]) -> int:
        ...


class ApproxTokenCounter:
    """Dependency-free counter for unknown and non-OpenAI tokenizers."""

    name = "approx"

    def count_text(self, text: str) -> int:
        if not text:
            return 0
        return max(1, (len(text) + 2) // 3)

    def count_messages(self, messages: list[dict]) -> int:
        total = 0
        for message in messages:
            total += 4  # conservative role/message framing overhead
            total += self.count_text(str(message.get("content") or ""))
            if message.get("tool_calls"):
                total += self.count_text(
                    json.dumps(message["tool_calls"], ensure_ascii=False, default=str)
                )
        return total


class TiktokenCounter:
    """Exact counter for models supported by the optional tiktoken package."""

    def __init__(self, model: str):
        try:
            import tiktoken
        except ImportError as exc:
            raise RuntimeError(
                "tiktoken is not installed; install corecoder[tokenizer]"
            ) from exc
        try:
            self._encoding = tiktoken.encoding_for_model(model)
        except Exception as exc:
            raise RuntimeError(
                f"tiktoken encoding unavailable for model {model}: {exc}"
            ) from exc
        self.model = model
        self.name = f"tiktoken:{self._encoding.name}"

    def count_text(self, text: str) -> int:
        return len(self._encoding.encode(text))

    def count_messages(self, messages: list[dict]) -> int:
        # Message framing varies slightly by model. Counting a stable JSON
        # representation is exact for text pieces and conservative for framing.
        payload = json.dumps(messages, ensure_ascii=False, default=str)
        return self.count_text(payload)


def create_token_counter(
    provider: str = "auto",
    model: str = "",
) -> TokenCounter:
    """Create a counter, falling back explicitly for unsupported models."""
    if provider not in {"auto", "approx", "tiktoken"}:
        raise ValueError(f"unknown tokenizer provider: {provider}")
    if provider == "approx":
        return ApproxTokenCounter()
    try:
        return TiktokenCounter(model)
    except RuntimeError:
        if provider == "tiktoken":
            raise
        return ApproxTokenCounter()
