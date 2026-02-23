"""
Core ReAct (Reason + Act) loop using Claude's native tool_use.

This is the heart of the agent system. It implements the classic ReAct pattern:
1. The LLM receives messages and available tools
2. It either responds with text (done) or calls one or more tools
3. Tool results are fed back as a new user message
4. Repeat until the LLM responds with text only, or max iterations reached

Key features:
- Uses Claude's native tool_use content blocks (no fragile text parsing)
- Executes multiple tool calls in parallel via asyncio.gather
- Streams thinking and response text to the UI via callbacks
- Caches tool results to avoid redundant API calls (via ToolResultCache)
- Coerces LLM-provided string arguments to match Python function signatures
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Union

from config.settings import MAX_OBSERVATION_LENGTH
from engine.memory.tool_cache import META_TOOLS, ToolResultCache

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """
    Result from a ReAct agent execution.

    Attributes:
        final_text:  The model's final text response (what the user sees)
        trajectory:  List of thought/tool/observation steps (for debugging)
        token_usage: Cumulative input/output token counts across all iterations
        stop_reason: Why the loop ended ("end_turn", "max_iterations", or "error")
    """
    final_text: str
    trajectory: list[dict] = field(default_factory=list)
    token_usage: dict = field(default_factory=lambda: {"input": 0, "output": 0})
    stop_reason: str = "end_turn"


class ReActLoop:
    """
    Core agentic loop using Claude's native tool_use.

    Used by both the OrchestratorAgent (with streaming callbacks and extended
    thinking) and WorkerAgent (without callbacks, simpler config).

    The loop iterates up to max_iterations times. Each iteration:
    1. Streams the LLM response (thinking deltas + text deltas go to callbacks)
    2. Checks if the response contains tool_use blocks
    3. If no tool calls -> done, return the text as final_text
    4. If tool calls found -> execute them in parallel, append results, continue
    """

    def __init__(
        self,
        llm_client,
        component: str,
        tools: list[dict],
        tool_callables: dict[str, Callable],
        system_prompt: str,
        max_iterations: int = 15,
        tool_cache: ToolResultCache | None = None,
    ):
        self.llm_client = llm_client
        self.component = component          # "orchestrator" or "worker" — selects model config
        self.tool_schemas = tools            # Tool definitions sent to the LLM
        self.tool_callables = tool_callables # Map of tool_name -> async callable
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations # Safety cap to prevent infinite loops
        self.tool_cache = tool_cache         # Optional cache to avoid duplicate API calls

    async def run(
        self,
        messages: list[dict],
        on_tool_call: Callable | None = None,
        on_tool_result: Callable | None = None,
        on_thinking: Callable | None = None,
        on_response_chunk: Callable | None = None,
        on_response_clear: Callable | None = None,
    ) -> AgentResult:
        """
        Execute the ReAct agent loop with streaming support.

        This is the main loop. Each iteration:
        1. Streams an LLM response (thinking + text deltas are pushed to callbacks)
        2. After streaming completes, inspects the response for tool_use blocks
        3. If no tool calls -> the text is the final answer, return it
        4. If tool calls -> execute them in parallel, feed results back, repeat

        Args:
            messages: Initial messages (conversation history + current user message)
            on_tool_call: Callback(tool_name, tool_input, thought) — notifies UI of tool use
            on_tool_result: Callback(tool_name, tool_args, result) — sends full results to UI panel
            on_thinking: Callback(thinking_text) — streams extended thinking to UI
            on_response_chunk: Callback(text_chunk) — streams response text to UI word-by-word
            on_response_clear: Callback() — tells UI to clear streamed text (see below)

        Returns:
            AgentResult with final_text, trajectory, token_usage
        """
        trajectory = []  # Records each thought/tool/observation for debugging
        total_tokens = {"input": 0, "output": 0}

        for iteration in range(self.max_iterations):
            # Track whether we've streamed any text to the UI in this iteration.
            # This matters because if the model starts writing text but then
            # decides to call a tool, that text was just a "thought" — not the
            # final response — and we need to tell the UI to clear it.
            has_streamed_text = False

            try:
                # Use streaming so we can push deltas to the UI in real time
                async with self.llm_client.create_message_stream(
                    component=self.component,
                    messages=messages,
                    tools=self.tool_schemas if self.tool_schemas else None,
                    system=self.system_prompt,
                ) as stream:
                    # Process streaming events as they arrive
                    async for event in stream:
                        if event.type == "content_block_delta":
                            # Extended thinking deltas (chain-of-thought)
                            if event.delta.type == "thinking_delta":
                                if on_thinking:
                                    await on_thinking(event.delta.thinking)
                            # Text response deltas (the actual answer)
                            elif event.delta.type == "text_delta":
                                has_streamed_text = True
                                if on_response_chunk:
                                    await on_response_chunk(event.delta.text)

                    # After all events, get the complete assembled message
                    response = await stream.get_final_message()

            except Exception as e:
                logger.error(f"LLM call failed: {e}", exc_info=True)
                return AgentResult(
                    final_text=f"I encountered an error processing your request: {str(e)}",
                    trajectory=trajectory,
                    token_usage=total_tokens,
                    stop_reason="error",
                )

            # Accumulate token usage across all iterations
            total_tokens["input"] += response.usage.input_tokens
            total_tokens["output"] += response.usage.output_tokens

            # Separate the response content blocks by type:
            # - thinking: Claude's chain-of-thought (only with extended thinking enabled)
            # - text: The model's text response
            # - tool_use: Tool calls the model wants to make
            thinking_blocks = [b for b in response.content if b.type == "thinking"]
            text_blocks = [b for b in response.content if b.type == "text"]
            tool_calls = [b for b in response.content if b.type == "tool_use"]

            # If no tool calls, the agent is done — the text is the final answer.
            # (It was already streamed to the UI via on_response_chunk.)
            if not tool_calls:
                final_text = "\n".join(b.text for b in text_blocks)
                return AgentResult(
                    final_text=final_text,
                    trajectory=trajectory,
                    token_usage=total_tokens,
                    stop_reason=response.stop_reason,
                )

            # Tool calls found. If we had streamed text to the UI, that text was
            # the model's intermediate reasoning (not the final response). Tell
            # the UI to clear it so the user doesn't see a partial, incomplete answer.
            if has_streamed_text and on_response_clear:
                await on_response_clear()

            # Append the full assistant message (thinking + text + tool_use blocks)
            # to the conversation so the model has context in the next iteration
            messages.append({"role": "assistant", "content": response.content})

            # Execute all tool calls in parallel and collect results
            tool_results = await self._execute_tool_calls(
                tool_calls, text_blocks, trajectory, on_tool_call, on_tool_result
            )

            # Feed tool results back as a user message (Anthropic's format for
            # returning tool results uses role=user with tool_result content blocks)
            messages.append({"role": "user", "content": tool_results})

            logger.debug(
                "ReAct iteration complete",
                extra={
                    "iteration": iteration + 1,
                    "tool_calls": len(tool_calls),
                    "total_tokens": total_tokens,
                },
            )

        # Safety: if we hit max_iterations, return a graceful message
        return AgentResult(
            final_text="I've reached the maximum number of processing steps. Here's what I found so far.",
            trajectory=trajectory,
            token_usage=total_tokens,
            stop_reason="max_iterations",
        )

    async def _execute_tool_calls(
        self,
        tool_calls: list,
        text_blocks: list,
        trajectory: list,
        on_tool_call: Callable | None,
        on_tool_result: Callable | None = None,
    ) -> list[dict]:
        """
        Execute all tool calls from a single LLM response in parallel.

        Each tool call is run concurrently via asyncio.gather. Results are
        formatted as Anthropic tool_result content blocks, ready to be
        appended to the conversation as a user message.

        The full (un-truncated) result is sent to the UI panel, while a
        truncated version is sent back to the LLM to stay within context limits.
        """
        # The model's text block serves as the "thought" in the trajectory —
        # it explains why the model chose to call these tools
        thought = text_blocks[0].text if text_blocks else ""

        async def run_one(tc) -> dict:
            """Execute a single tool call with UI callbacks and caching."""
            # Notify the UI that a tool is being called (shows a spinner/step)
            if on_tool_call:
                try:
                    await on_tool_call(tc.name, tc.input, thought)
                except Exception as e:
                    logger.warning(f"Tool call callback failed: {e}")

            # Execute the tool and get the full result
            logger.info(f"TOOL CALL: {tc.name} | Args: {json.dumps(tc.input, default=str)}")
            full_result = await self._execute_single_tool(tc.name, tc.input)
            logger.info(f"TOOL RESULT: {tc.name} | {full_result[:500]}")

            # Send the full (un-truncated) result to the UI's detail panel
            # so the user can inspect complete tool output
            if on_tool_result:
                try:
                    await on_tool_result(tc.name, tc.input, full_result)
                except Exception as e:
                    logger.warning(f"Tool result callback failed: {e}")

            # Truncate the result before sending it back to the LLM to avoid
            # blowing up the context window with large tool outputs
            result = full_result
            if len(result) > MAX_OBSERVATION_LENGTH:
                result = result[:MAX_OBSERVATION_LENGTH] + "\n... [truncated due to length]"

            # Record in the trajectory for debugging/observability
            trajectory.append({
                "thought": thought,
                "tool": tc.name,
                "args": tc.input,
                "observation": result[:500] if len(result) > 500 else result,
            })

            # Return in Anthropic's tool_result format
            return {
                "type": "tool_result",
                "tool_use_id": tc.id,  # Links this result back to the tool call
                "content": result,
            }

        # Execute all tool calls concurrently for speed.
        # return_exceptions=True prevents one failed tool from crashing all others.
        results = await asyncio.gather(
            *[run_one(tc) for tc in tool_calls],
            return_exceptions=True,
        )

        # Post-process: convert any exceptions into error tool_result blocks
        # so the LLM can see what failed and adjust its approach
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Tool execution raised exception: {result}")
                processed_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_calls[i].id,
                    "content": f"Tool execution error: {str(result)}",
                    "is_error": True,  # Tells Claude this tool call failed
                })
            else:
                processed_results.append(result)

        return processed_results

    async def _execute_single_tool(self, tool_name: str, tool_input: dict) -> str:
        """
        Execute a single tool by name with error handling and optional caching.

        Flow:
        1. Check the cache for a recent result (skip for meta-tools)
        2. Look up the callable by name
        3. Coerce string arguments from the LLM to match Python types
        4. Call the async function and serialize the result to a string
        5. Store the result in the cache for future hits
        """
        # Check cache first — if we've recently called this tool with
        # the same arguments, return the cached result to avoid a redundant API call
        if self.tool_cache and tool_name not in META_TOOLS:
            cached = self.tool_cache.get(tool_name, tool_input)
            if cached is not None:
                logger.info(f"TOOL CACHE HIT: {tool_name}")
                return cached

        # Look up the Python function for this tool
        func = self.tool_callables.get(tool_name)
        if not func:
            return f"Error: Unknown tool '{tool_name}'. Available tools: {list(self.tool_callables.keys())}"

        try:
            # The LLM sometimes sends arguments as strings (e.g. "42" instead of 42).
            # Coerce them to match the function's type hints before calling.
            coerced_input = self._coerce_args(func, tool_input)
            result = await func(**coerced_input)

            # Tool results must be strings for the LLM context.
            # If the tool returned a dict/list/etc, serialize it as JSON.
            if isinstance(result, str):
                output = result
            else:
                output = json.dumps(result, default=str, ensure_ascii=False)

            # Cache the full result for future cache hits (skip meta-tools)
            if self.tool_cache and tool_name not in META_TOOLS:
                self.tool_cache.put(tool_name, tool_input, output)

            return output

        except TypeError as e:
            # Common when tool_input keys/types don't match the function signature
            return f"Tool argument error in {tool_name}: {str(e)}"
        except Exception as e:
            logger.error(
                f"Tool execution failed: {tool_name}",
                extra={"error": str(e), "tool_args": tool_input},
                exc_info=True,
            )
            return f"Tool execution error in {tool_name}: {str(e)}"

    @staticmethod
    def _coerce_args(func: Callable, tool_input: dict) -> dict:
        """
        Coerce string arguments from the LLM to match the function's type hints.

        The LLM sometimes sends values as strings even when the Python function
        expects int, float, bool, or datetime. This method inspects the function's
        type hints and converts string values to the expected types.

        Handles Optional[X] by unwrapping to X before checking.
        """
        from datetime import datetime
        from typing import get_type_hints
        try:
            hints = get_type_hints(func)
        except Exception:
            # If we can't inspect type hints, pass arguments through unchanged
            return tool_input

        coerced = {}
        for key, value in tool_input.items():
            expected = hints.get(key)
            # Only coerce if we know the expected type AND the value is a string
            if expected is None or not isinstance(value, str):
                coerced[key] = value
                continue
            # Unwrap Optional[X] (Union[X, None]) -> X
            origin = getattr(expected, "__origin__", None)
            if origin is Union:
                type_args = [a for a in expected.__args__ if a is not type(None)]
                expected = type_args[0] if type_args else expected
            # Convert the string to the expected type
            if expected is int:
                coerced[key] = int(value)
            elif expected is float:
                coerced[key] = float(value)
            elif expected is bool:
                coerced[key] = value.lower() in ("true", "1", "yes")
            elif expected is datetime:
                coerced[key] = datetime.fromisoformat(value)
            else:
                coerced[key] = value
        return coerced
