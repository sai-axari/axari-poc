"""Meta-tools: delegate_subtask."""
from __future__ import annotations

import json
import logging
from typing import Any

from tools.registry import ToolEntry

logger = logging.getLogger(__name__)


# --- Delegate Subtask Tool ---

DELEGATE_SUBTASK_SCHEMA = {
    "name": "delegate_subtask",
    "description": (
        "Delegate a complex subtask to a focused worker agent. "
        "Use this ONLY when a subtask requires multiple iterative tool calls "
        "with conditional logic. For example:\n"
        "- 'Find all incident tickets, then for each one look up related PRs'\n"
        "- 'Search emails about topic X, then based on findings search Slack for follow-ups'\n"
        "- 'Find all critical vulnerabilities, cross-reference with deployment logs'\n\n"
        "Do NOT use this for simple data fetching — call those tools directly instead. "
        "The worker will execute the subtask independently and return structured findings."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "subtask_description": {
                "type": "string",
                "description": (
                    "Detailed description of what the worker should accomplish, "
                    "including what tools to use and what logic to follow"
                ),
            },
            "tools_needed": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of tool names the worker needs access to",
            },
            "context": {
                "type": "string",
                "description": (
                    "Any context from previous results or the user's request "
                    "that the worker needs"
                ),
            },
        },
        "required": ["subtask_description", "tools_needed"],
    },
}


def build_delegate_subtask_tool(
    llm_client,
    allowed_tools: list[str],
    tenant_id: str,
    tool_cache=None,
) -> ToolEntry:
    """
    Build a delegate_subtask tool with bound context.

    The returned tool spawns a WorkerAgent with the specified tools
    and executes the subtask independently.
    """
    from engine.agent.worker import WorkerAgent
    from prompts.worker import WORKER_SYSTEM_PROMPT
    from tools.registry import get_schemas_for, get_callables_for

    async def delegate_subtask(
        subtask_description: str,
        tools_needed: list[str],
        context: str = "",
    ) -> str:
        # Filter tools to only those the worker needs AND tenant has access to
        worker_tool_names = [t for t in tools_needed if t in allowed_tools]

        if not worker_tool_names:
            return (
                f"No valid tools available for this subtask. "
                f"Requested: {tools_needed}, Available: {allowed_tools[:10]}..."
            )

        worker = WorkerAgent(
            llm_client=llm_client,
            tool_schemas=get_schemas_for(worker_tool_names),
            tool_callables=get_callables_for(worker_tool_names),
            system_prompt=WORKER_SYSTEM_PROMPT,
            tool_cache=tool_cache,
        )

        logger.info(
            "Delegating subtask to worker",
            extra={
                "subtask": subtask_description[:100],
                "tools": worker_tool_names,
                "tenant_id": tenant_id,
            },
        )

        result = await worker.execute(
            subtask_description=subtask_description,
            tenant_id=tenant_id,
            context=context,
        )

        return result.final_text

    return ToolEntry(func=delegate_subtask, schema=DELEGATE_SUBTASK_SCHEMA)
