"""
Context window management for conversation history.

LLMs have a fixed context window (e.g. 200k tokens). When conversation
history grows too large, this module trims older messages to stay within
budget. It uses a simple character-based heuristic to estimate token count
(~4 chars per token) and drops messages from the beginning of the
conversation, always preserving the most recent user message.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Rough heuristic: 1 token ~ 4 characters for English text.
# Not perfectly accurate, but sufficient for budgeting purposes.
CHARS_PER_TOKEN = 4


class ContextManager:
    """Manage context window limits to prevent overflow."""

    def __init__(self, max_tokens: int = 100000):
        # Default budget of 100k tokens — leaves room for the system prompt,
        # tool schemas, and the model's response within a 200k context window.
        self.max_tokens = max_tokens

    def truncate_messages(
        self, messages: list[dict], max_tokens: int | None = None
    ) -> list[dict]:
        """
        Keep most recent messages within token budget.

        Always preserves the last message (current user input).
        Trims from the beginning of the conversation (oldest first).

        This is a simple FIFO truncation strategy. A more sophisticated
        approach might summarize dropped messages instead.
        """
        limit = max_tokens or self.max_tokens

        # Estimate total tokens across all messages
        total_chars = sum(
            len(str(m.get("content", ""))) for m in messages
        )
        estimated_tokens = total_chars // CHARS_PER_TOKEN

        # If within budget, return as-is
        if estimated_tokens <= limit:
            return messages

        # Drop oldest messages one at a time until within budget.
        # Always keep at least 1 message (the latest user input).
        truncated = list(messages)
        while len(truncated) > 1:
            removed = truncated.pop(0)  # Remove the oldest message
            total_chars -= len(str(removed.get("content", "")))
            estimated_tokens = total_chars // CHARS_PER_TOKEN

            if estimated_tokens <= limit:
                break

        if len(truncated) < len(messages):
            logger.info(
                "Truncated conversation history",
                extra={
                    "original_messages": len(messages),
                    "kept_messages": len(truncated),
                    "estimated_tokens": estimated_tokens,
                },
            )

        return truncated
