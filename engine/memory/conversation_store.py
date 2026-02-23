"""
In-memory conversation memory store.

This module manages per-conversation message history and state. In this POC
implementation, everything is stored in Python dicts (lost on restart).
A production version would persist to PostgreSQL via asyncpg.

The store is used by the API layer to load conversation history before
passing it to the orchestrator, and to save the user/assistant exchange
after each turn.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ConversationStore:
    """
    Stores and retrieves conversation history.

    POC implementation uses in-memory storage.
    Production would use PostgreSQL via asyncpg.
    """

    def __init__(self):
        # Maps conversation_id -> list of message dicts (Anthropic format)
        self._messages: dict[str, list[dict]] = {}
        # Maps conversation_id -> arbitrary state dict for multi-turn context
        # (e.g., extracted dates, user preferences from prior turns)
        self._state: dict[str, dict] = {}

    async def load_messages(
        self, conversation_id: str, limit: int = 20
    ) -> list[dict]:
        """
        Load the most recent messages for a conversation.

        Returns messages in Anthropic format: {"role": "user"|"assistant", "content": "..."}.
        The `limit` parameter caps how many messages are returned (from the end),
        which helps keep the context window within budget.
        """
        messages = self._messages.get(conversation_id, [])
        # Slice from the end to keep the most recent messages
        return messages[-limit:]

    async def save_exchange(
        self, conversation_id: str, user_msg: str, assistant_msg: str
    ):
        """
        Save a complete user-assistant exchange (both messages at once).

        This is called after the orchestrator finishes processing a message,
        appending both the user input and the assistant response to history.
        """
        if conversation_id not in self._messages:
            self._messages[conversation_id] = []

        self._messages[conversation_id].append(
            {"role": "user", "content": user_msg}
        )
        self._messages[conversation_id].append(
            {"role": "assistant", "content": assistant_msg}
        )

        logger.debug(
            "Saved exchange",
            extra={
                "conversation_id": conversation_id,
                "total_messages": len(self._messages[conversation_id]),
            },
        )

    async def get_state(self, conversation_id: str) -> dict | None:
        """Load persisted state (dates, preferences) for multi-turn context."""
        return self._state.get(conversation_id)

    async def save_state(self, conversation_id: str, state: dict):
        """Persist arbitrary state between conversation turns."""
        self._state[conversation_id] = state

    async def clear(self, conversation_id: str):
        """Clear both message history and state for a conversation."""
        self._messages.pop(conversation_id, None)
        self._state.pop(conversation_id, None)
