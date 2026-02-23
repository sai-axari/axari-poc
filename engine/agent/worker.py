"""
Lightweight worker agent for delegate_subtask execution.

When the orchestrator encounters a complex, multi-step subtask that would
benefit from focused execution, it delegates it to a WorkerAgent via the
`delegate_subtask` meta-tool. Each worker runs its own ReAct loop with a
limited tool set and fewer iterations, returning structured findings back
to the orchestrator for final synthesis.
"""
from __future__ import annotations

import logging

from engine.agent.react_loop import AgentResult, ReActLoop
from engine.memory.tool_cache import ToolResultCache

logger = logging.getLogger(__name__)


class WorkerAgent:
    """
    Lightweight ReAct agent for executing a delegated subtask.

    Workers are focused: they get a specific subtask, specific tools,
    and execute independently. They return structured findings to the
    orchestrator, which handles synthesis.

    Key differences from orchestrator:
    - No extended thinking (focused execution, not planning)
    - Limited tool set (only tools relevant to the subtask)
    - Shorter max_iterations (focused tasks shouldn't need many rounds)
    - No streaming callbacks (orchestrator handles UI updates)
    """

    def __init__(
        self,
        llm_client,
        tool_schemas: list[dict],
        tool_callables: dict,
        system_prompt: str,
        max_iterations: int = 8,
        tool_cache: ToolResultCache | None = None,
    ):
        # Create a ReAct loop configured for the "worker" component.
        # The "worker" component uses a different (usually cheaper/faster)
        # model config than the orchestrator, and has no extended thinking.
        self.react = ReActLoop(
            llm_client=llm_client,
            component="worker",  # Uses the "worker" entry in MODEL_CONFIGS
            tools=tool_schemas,
            tool_callables=tool_callables,
            system_prompt=system_prompt,
            max_iterations=max_iterations,  # Lower cap than orchestrator (8 vs 15)
            tool_cache=tool_cache,
        )

    async def execute(
        self,
        subtask_description: str,
        tenant_id: str,
        context: str = "",
    ) -> AgentResult:
        """
        Execute a delegated subtask.

        Constructs a user message from the subtask description and context,
        then runs the ReAct loop to completion. The worker will call tools
        as needed to gather data, then return its findings.

        Args:
            subtask_description: What the worker should accomplish
            tenant_id: Tenant ID for scoped tool calls
            context: Any context from previous results

        Returns:
            AgentResult with the worker's findings
        """
        # Build the user message that tells the worker what to do.
        # Includes the tenant_id so tools can scope their queries,
        # and any context from prior subtask results for continuity.
        user_message = f"""Execute this subtask:

{subtask_description}

Tenant ID: {tenant_id}
{"Context: " + context if context else ""}

Return your findings as structured, factual data. Do not fabricate information.
If a tool returns no data, report 'NO DATA AVAILABLE' for that part."""

        logger.info(
            "Worker executing subtask",
            extra={"subtask": subtask_description[:100], "tenant_id": tenant_id},
        )

        # Run the ReAct loop without any streaming callbacks — the orchestrator
        # handles all UI updates; the worker just returns its result.
        result = await self.react.run(
            messages=[{"role": "user", "content": user_message}]
        )

        logger.info(
            "Worker completed subtask",
            extra={
                "stop_reason": result.stop_reason,
                "trajectory_steps": len(result.trajectory),
                "tokens": result.token_usage,
            },
        )

        return result
