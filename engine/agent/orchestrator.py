"""
Hybrid orchestrator agent — main entry point for chat processing.

This is the top-level agent that handles every user message. It:
1. Discovers which integration tools are available for the tenant
2. Registers meta-tools (delegate_subtask, take_notes, etc.)
3. Fetches AI worker context from the database for prompt injection
4. Builds a system prompt with all capabilities and context
5. Runs the ReAct loop with streaming callbacks wired to the EventEmitter

The orchestrator uses extended thinking (chain-of-thought) for complex queries
and can delegate multi-step subtasks to lightweight WorkerAgent instances.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from engine.agent.react_loop import AgentResult, ReActLoop
from engine.llm.client import LLMClient
from engine.memory.tool_cache import ToolResultCache
from engine.streaming.event_emitter import EventEmitter
from prompts.orchestrator import build_orchestrator_prompt
from tools.meta_tools import (
    build_delegate_subtask_tool,
)
from engine.context.worker_context import fetch_worker_context
from engine.context.playbook_trigger import trigger_responsibility
from tools.connected import get_connected_integration_keys
from tools.registry import get_callables_for, get_schemas_for, get_tools_with_descriptions, list_registered_tools, list_tools_for_integrations

logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    """
    Final response returned by the orchestrator to the API layer.

    Attributes:
        response:    The model's final text answer (what the user sees)
        trajectory:  List of thought/tool/observation steps (for debugging)
        token_usage: Cumulative input/output token counts across all ReAct iterations
    """
    response: str
    trajectory: list[dict]
    token_usage: dict


class OrchestratorAgent:
    """
    Hybrid orchestrator that handles the entire chat flow.

    - Simple/medium queries: calls integration tools directly (parallel when possible)
    - Complex queries: uses extended thinking to plan, calls tools in parallel rounds
    - Edge cases: delegates multi-step subtasks via delegate_subtask

    Replaces: ALL 11 LangGraph nodes from the existing system.
    One ReActLoop handles everything the old multi-node graph did.
    """

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    async def handle_message(
        self,
        user_input: str,
        conversation_id: str,
        tenant_id: str,
        user_id: str,
        allowed_tools: list[str] | None = None,
        conversation_history: list[dict] | None = None,
        integration_constraints: str = "",
        user_name: str = "",
        org_name: str = "",
        user_timezone: str = "UTC",
        event_emitter: EventEmitter | None = None,
        tool_cache: ToolResultCache | None = None,
        exclude_tools: list[str] | None = None,
    ) -> AgentResponse:
        """
        Process a user message end-to-end.

        Args:
            user_input: The user's message
            conversation_id: Unique conversation identifier
            tenant_id: Tenant ID for scoped tool access
            user_id: User ID
            allowed_tools: List of tool names this tenant can use
            conversation_history: Previous messages in Anthropic format
            integration_constraints: JSON string of constraints per integration
            user_name: User's name for persona context
            org_name: Organization name
            user_timezone: User's timezone (e.g., "America/New_York")
            event_emitter: Optional emitter for real-time streaming events
            exclude_tools: Optional list of tool names to exclude from the tool set

        Returns:
            AgentResponse with response text, trajectory, and token usage
        """
        # ──────────────────────────────────────────────────────────────
        # Step 0: Discover which integration tools the tenant can use.
        # Queries the DB for connected integrations (e.g., Gmail, Jira)
        # and maps them to the tool functions registered in the tool registry.
        # Falls back to ALL registered tools if no integrations are connected.
        # ──────────────────────────────────────────────────────────────
        if not allowed_tools:
            connected_keys = await get_connected_integration_keys(tenant_id)
            if connected_keys:
                allowed_tools = list_tools_for_integrations(connected_keys)
                logger.info(f"Loaded {len(allowed_tools)} tools for {len(connected_keys)} connected integrations")
            else:
                allowed_tools = list_registered_tools()
                logger.info("No connected integrations found, using all registered tools")
        conversation_history = conversation_history or []

        # ──────────────────────────────────────────────────────────────
        # Step 1: Build the tool list from integration tools + meta-tools.
        # tool_schemas = JSON schemas sent to the LLM (tells it what tools exist)
        # tool_callables = Python functions that actually execute the tools
        # ──────────────────────────────────────────────────────────────
        tool_schemas = get_schemas_for(allowed_tools)
        tool_callables = get_callables_for(allowed_tools)

        # -- Meta-tool: take_notes --
        # Writes content to the UI's Notes side panel (persisted for the session).
        TAKE_NOTES_SCHEMA = {
            "name": "take_notes",
            "description": (
                "Save notes to the user's notes panel in the UI. "
                "Use this when the user asks you to take notes, jot down key points, "
                "record information, create a summary for reference, or anything "
                "that should be saved as persistent notes. "
                "The notes appear in a dedicated Notes tab in the side panel. "
                "Supports markdown formatting."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The notes content to save. Use markdown for formatting (headers, bullets, bold, etc.).",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["append", "replace"],
                        "description": "Whether to append to existing notes or replace them entirely. Default: append.",
                    },
                },
                "required": ["content"],
            },
        }

        async def take_notes_func(content: str, mode: str = "append") -> str:
            if event_emitter:
                await event_emitter.emit_panel_note(content, mode)
                return "Notes saved to the user's notes panel successfully."
            return "Notes panel is not available in this session."

        tool_schemas.append(TAKE_NOTES_SCHEMA)
        tool_callables["take_notes"] = take_notes_func

        # -- Meta-tool: add_reminder --
        # Adds a trackable reminder/commitment to the UI's Reminders side panel.
        ADD_REMINDER_SCHEMA = {
            "name": "add_reminder",
            "description": (
                "Add a reminder or commitment to the user's reminders panel in the UI. "
                "Use this when the user asks you to set a reminder, track a commitment, "
                "follow up on something, or when you extract action items or commitments "
                "from tool results (e.g., commitment radar, emails, meetings, Jira tickets). "
                "Each reminder appears as a trackable item with an optional due date."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short title for the reminder (e.g., 'Follow up on Q3 security audit with John').",
                    },
                    "due": {
                        "type": "string",
                        "description": "Optional due date in ISO 8601 format (e.g., '2026-02-20'). Leave empty if no specific deadline.",
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional additional context (e.g., source of commitment, related ticket, background details).",
                    },
                },
                "required": ["title"],
            },
        }

        async def add_reminder_func(title: str, due: str = "", context: str = "") -> str:
            if event_emitter:
                await event_emitter.emit_reminder(title, due, context)
                return f"Reminder added: '{title}'" + (f" (due: {due})" if due else "")
            return "Reminders panel is not available in this session."

        tool_schemas.append(ADD_REMINDER_SCHEMA)
        tool_callables["add_reminder"] = add_reminder_func

        # -- Meta-tool: trigger_responsibility --
        # Allows the user to trigger a playbook execution from chat
        # (e.g., "run my morning brief"). Creates a DB record and sends an SQS message.
        TRIGGER_RESPONSIBILITY_SCHEMA = {
            "name": "trigger_responsibility",
            "description": (
                "Trigger an AI Worker responsibility (playbook) to run on demand. "
                "Use this when the user asks to run, trigger, or execute a responsibility "
                "such as 'run my morning brief', 'trigger commitment radar', or 'execute meeting prep'. "
                "If the responsibility is not active, the tool will inform the user to activate it "
                "in the AI Workers page."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "responsibility_name": {
                        "type": "string",
                        "description": (
                            "Name of the responsibility to trigger. "
                            "Examples: 'Morning Brief', 'Commitment Radar', 'Meeting Prep'."
                        ),
                    },
                },
                "required": ["responsibility_name"],
            },
        }

        async def trigger_responsibility_func(responsibility_name: str) -> str:
            return await trigger_responsibility(
                tenant_id=tenant_id,
                responsibility_name=responsibility_name,
            )

        tool_schemas.append(TRIGGER_RESPONSIBILITY_SCHEMA)
        tool_callables["trigger_responsibility"] = trigger_responsibility_func

        # -- Meta-tool: delegate_subtask --
        # Spawns a lightweight WorkerAgent to handle a focused subtask.
        # The worker gets its own ReAct loop with the same integration tools
        # but no streaming callbacks (it runs silently and returns a result).
        if allowed_tools:
            delegate_tool = build_delegate_subtask_tool(
                llm_client=self.llm_client,
                allowed_tools=allowed_tools,
                tenant_id=tenant_id,
                tool_cache=tool_cache,
            )
            tool_schemas.append(delegate_tool.schema)
            tool_callables[delegate_tool.schema["name"]] = delegate_tool.func

        # Remove excluded tools if specified (used to prevent certain tools
        # from being available, e.g., during testing or specific workflows)
        if exclude_tools:
            tool_schemas = [s for s in tool_schemas if s["name"] not in exclude_tools]
            for name in exclude_tools:
                tool_callables.pop(name, None)

        # ──────────────────────────────────────────────────────────────
        # Step 2: Build the system prompt with tenant-specific context.
        # Fetches AI worker context from the DB (worker roles, playbooks,
        # today's execution results) and injects it into the prompt so
        # the orchestrator knows what capabilities are available.
        # ──────────────────────────────────────────────────────────────
        current_datetime = datetime.now(timezone.utc).strftime("%A, %B %d, %Y at %I:%M %p UTC")

        # Fetch context about AI workers, their playbooks, and today's run results
        worker_context = await fetch_worker_context(tenant_id)

        system_prompt = build_orchestrator_prompt(
            user_name=user_name,
            org_name=org_name,
            current_datetime=current_datetime,
            user_timezone=user_timezone,
            integration_constraints=integration_constraints,
            capabilities=get_tools_with_descriptions(allowed_tools) if allowed_tools else "",
            tenant_id=tenant_id,
            worker_context=worker_context,
        )

        # ──────────────────────────────────────────────────────────────
        # Step 3: Build messages (history + current user message).
        # Copy the list to avoid mutating the caller's history.
        # ──────────────────────────────────────────────────────────────
        messages = list(conversation_history)
        messages.append({"role": "user", "content": user_input})

        # ──────────────────────────────────────────────────────────────
        # Step 4: Run the ReAct loop.
        # The loop streams thinking/text deltas to the UI via callbacks,
        # executes tool calls in parallel, and iterates until the model
        # produces a final text response (no more tool calls).
        # ──────────────────────────────────────────────────────────────
        react = ReActLoop(
            llm_client=self.llm_client,
            component="orchestrator",
            tools=tool_schemas,
            tool_callables=tool_callables,
            system_prompt=system_prompt,
            tool_cache=tool_cache,
        )

        # Streaming callbacks — wire the ReAct loop's events to the EventEmitter
        # so each thinking step, tool call, and text chunk is pushed to the UI in real time.
        async def on_tool_call(name, args, thought):
            if event_emitter:
                await event_emitter.emit_tool_call(name, thought)

        async def on_tool_result(name, args, result):
            if event_emitter:
                await event_emitter.emit_tool_result(name, args, result)

        async def on_thinking(text):
            if event_emitter:
                await event_emitter.emit_thinking(text)

        async def on_response_chunk(chunk):
            if event_emitter:
                await event_emitter.emit_response_chunk(chunk)

        async def on_response_clear():
            if event_emitter:
                await event_emitter.emit_response_clear()

        result = await react.run(
            messages=messages,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            on_thinking=on_thinking,
            on_response_chunk=on_response_chunk,
            on_response_clear=on_response_clear,
        )

        # ──────────────────────────────────────────────────────────────
        # Step 5: Emit the complete final response.
        # This is used by the non-streaming /v1/chat endpoint. The streaming
        # /v1/chat/stream endpoint already received the response word-by-word
        # via the on_response_chunk callback above.
        # ──────────────────────────────────────────────────────────────
        if event_emitter:
            await event_emitter.emit_response(result.final_text)

        logger.info(
            "Orchestrator completed",
            extra={
                "conversation_id": conversation_id,
                "stop_reason": result.stop_reason,
                "trajectory_steps": len(result.trajectory),
                "tokens": result.token_usage,
            },
        )

        return AgentResponse(
            response=result.final_text,
            trajectory=result.trajectory,
            token_usage=result.token_usage,
        )
