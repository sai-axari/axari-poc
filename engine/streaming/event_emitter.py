"""
Real-time event emission for streaming UI updates.

This module bridges the agent's internal processing with the frontend UI.
As the orchestrator thinks, calls tools, and generates responses, it emits
events through the EventEmitter. These events are consumed by the API layer
(via SSE — Server-Sent Events) and pushed to the frontend in real time,
enabling a live "thinking" experience.

Event types:
- thinking:       Extended thinking text (chain-of-thought)
- node_planner:   Tool call progress (shown as "thinking steps" in the UI)
- tool_result:    Full tool result data (shown in the detail side panel)
- response_chunk: Partial response text (streamed word-by-word)
- response:       Complete final response (for non-streaming consumers)
- response_clear: Signal to clear partially-streamed text (when a tool call
                  is found after streaming started)
- panel_note:     Notes content for the Notes tab
- reminder:       Reminder/commitment for the Reminders tab
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


def format_tool_as_human_readable(tool_name: str, thought: str) -> str:
    """
    Convert a tool call into a human-readable description for the UI.

    Prefers the agent's own "thought" (the text block emitted alongside the
    tool call) as the description, since it's more natural language.
    Falls back to formatting the tool name (e.g. "fetch_emails" -> "Fetch emails")
    if the thought is empty or too short to be useful.
    """
    if thought and len(thought.strip()) > 10:
        cleaned = thought.strip()

        # Strip any role-playing prefixes the model might add
        # (e.g. "I'm Atlas, your Chief of Staff. Let me check...")
        prefixes_to_remove = [
            "I'm Atlas, your Chief of Staff. ",
            "I'm Atlas. ",
            "As your Chief of Staff, ",
            "As Atlas, ",
        ]
        for prefix in prefixes_to_remove:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):]
                break

        # Ensure first letter is capitalized for consistent UI display
        if cleaned and cleaned[0].islower():
            cleaned = cleaned[0].upper() + cleaned[1:]

        return cleaned

    # Fallback: derive a readable label from the tool name itself.
    # Some tools use "integration:action" naming (e.g. "gmail:fetch_emails"),
    # so we take only the action part after the colon.
    if ":" in tool_name:
        _, action_part = tool_name.split(":", 1)
    else:
        action_part = tool_name

    return action_part.replace("_", " ").capitalize()


class EventEmitter:
    """
    Emits real-time events to the client via an async queue.

    The emitter is created per-conversation. Events are stored in a list
    (for retrospective access) and also pushed into an asyncio.Queue so
    the SSE endpoint can stream them as they arrive.

    POC: In-memory queue consumed via SSE.
    Production: Would publish to AWS AppSync for WebSocket delivery.
    """

    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        self.tool_call_idx = 0               # Auto-incrementing tool call counter
        self.events: list[dict] = []         # All events emitted (for retrospective access)
        self._queue: asyncio.Queue[dict | None] = asyncio.Queue()  # None = end sentinel

    async def emit_thinking(self, thinking_text: str):
        """Stream the orchestrator's extended thinking (chain-of-thought) to the UI."""
        await self._emit("thinking", {"text": thinking_text})

    async def emit_tool_call(self, tool_name: str, thought: str):
        """
        Emit a tool call event to show progress in the UI.

        Uses the "node_planner" event type with "planning_steps" format
        for backward compatibility with the existing frontend, which
        renders these as numbered thinking steps.
        """
        self.tool_call_idx += 1
        description = format_tool_as_human_readable(tool_name, thought)

        # Format as a planning step so the frontend's existing rendering works
        thinking_step = {
            "idx": str(self.tool_call_idx),
            "step name": "",
            "goal": description,
        }
        await self._emit("node_planner", {"planning_steps": [thinking_step]})

    async def emit_response(self, response: str):
        """Send the complete final response (used by the non-streaming endpoint)."""
        await self._emit("response", {"text": response})

    async def emit_response_chunk(self, chunk: str):
        """Stream a partial text chunk of the response (for word-by-word streaming)."""
        await self._emit("response_chunk", {"text": chunk})

    async def emit_tool_result(self, tool_name: str, tool_args: dict, result: str):
        """Send the full tool result to the detail side panel in the UI."""
        await self._emit("tool_result", {
            "tool": tool_name,
            "args": tool_args,
            "result": result,
        })

    async def emit_panel_note(self, content: str, mode: str = "append"):
        """Send notes content to the panel's Notes tab."""
        await self._emit("panel_note", {"content": content, "mode": mode})

    async def emit_reminder(self, title: str, due: str = "", context: str = ""):
        """Send a reminder/commitment to the panel's Reminders tab."""
        await self._emit("reminder", {
            "title": title,
            "due": due,
            "context": context,
        })

    async def emit_response_clear(self):
        """
        Signal the UI to clear any partially-streamed response text.

        This happens when the model starts streaming text, but then decides
        to make a tool call instead — the streamed text was a "thought",
        not the final response, so the UI should discard it.
        """
        await self._emit("response_clear", {})

    async def _emit(self, event_type: str, data: dict):
        """
        Internal method to emit an event.

        Stores the event in the events list (for get_events()) and pushes
        it into the async queue (for the stream() generator).
        """
        event = {
            "type": event_type,
            "data": data,
            "conversation_id": self.conversation_id,
        }
        self.events.append(event)
        await self._queue.put(event)

        logger.debug(
            "Event emitted",
            extra={"type": event_type, "conversation_id": self.conversation_id},
        )

    async def complete(self):
        """
        Signal that all processing is done.

        Pushes a None sentinel into the queue, which causes the stream()
        generator to stop yielding and return.
        """
        await self._queue.put(None)

    async def stream(self) -> AsyncIterator[dict]:
        """
        Async generator that yields events as they are emitted.

        Blocks on the queue until an event arrives. Stops when it receives
        the None sentinel (pushed by complete()). Used by the SSE endpoint
        to stream events to the frontend in real time.
        """
        while True:
            event = await self._queue.get()
            if event is None:  # End sentinel
                break
            yield event

    def get_events(self) -> list[dict]:
        """Get all events emitted so far (for retrospective access or debugging)."""
        return self.events
