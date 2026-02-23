"""
Unified async LLM client using the Anthropic API directly.

This module provides a single LLMClient class that wraps the Anthropic SDK
(routed through OpenRouter) and is used by both the orchestrator and worker
agents to make LLM calls. It supports non-streaming, streaming, tool_use,
and extended thinking — all configured per-component via MODEL_CONFIGS.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from anthropic import AsyncAnthropic

# MODEL_CONFIGS maps component names (e.g. "orchestrator", "worker") to their
# model settings (model ID, max_tokens, temperature, thinking config, etc.)
from config.models import MODEL_CONFIGS
from config.settings import LLM_PROVIDER, OPENROUTER_API_KEY, ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

# Provider-specific client configuration
_PROVIDER_SETTINGS = {
    "openrouter": {
        "api_key": OPENROUTER_API_KEY,
        "base_url": "https://openrouter.ai/api",
    },
    "anthropic": {
        "api_key": ANTHROPIC_API_KEY,
        # No base_url — uses the default Anthropic endpoint
    },
}


class LLMClient:
    """
    Unified async LLM client using the Anthropic API.

    Uses the Anthropic SDK directly with all native features:
    tool_use, extended thinking, streaming.

    Connects to either OpenRouter or Anthropic directly based on
    the LLM_PROVIDER env var.
    """

    def __init__(self):
        settings = _PROVIDER_SETTINGS[LLM_PROVIDER]
        self.anthropic = AsyncAnthropic(**settings)
        logger.info(f"LLMClient initialized with provider: {LLM_PROVIDER}")

    async def create_message(
        self,
        component: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        stream: bool = False,
    ):
        """
        Create an LLM message using the config for the given component.

        This is the main entry point for non-streaming calls. It looks up the
        model configuration for the given component name and delegates to the
        Anthropic SDK.

        Args:
            component: Key in MODEL_CONFIGS (e.g., "orchestrator", "worker")
            messages: Conversation messages in Anthropic format
            tools: Tool schemas in Anthropic format
            system: System prompt string
            stream: Whether to return a streaming response

        Returns:
            Anthropic Message response (or stream context manager if stream=True)
        """
        config = MODEL_CONFIGS[component]
        return await self._call_anthropic(config, messages, tools, system, stream)

    def _build_kwargs(
        self,
        config: dict,
        messages: list[dict],
        tools: list[dict] | None,
        system: str | None,
    ) -> dict[str, Any]:
        """
        Build the kwargs dict for Anthropic API calls.

        Assembles model, max_tokens, messages, system prompt, temperature,
        thinking config, and tools into a single dict that can be unpacked
        into either `messages.create()` or `messages.stream()`.
        """
        kwargs: dict[str, Any] = {
            "model": config["model"],
            "max_tokens": config["max_tokens"],
            "messages": messages,
        }

        # System prompt must be wrapped in the content-block format
        if system:
            kwargs["system"] = [{"type": "text", "text": system}]

        # Extended thinking (Claude's chain-of-thought feature) requires
        # temperature=1.0 per the Anthropic API spec
        if config.get("thinking"):
            kwargs["thinking"] = config["thinking"]
            kwargs["temperature"] = 1.0  # Required with extended thinking
        else:
            kwargs["temperature"] = config.get("temperature", 0)

        # Only include tools if provided (omitting the key entirely when empty
        # avoids an API validation error)
        if tools:
            kwargs["tools"] = list(tools)

        return kwargs

    async def _call_anthropic(
        self,
        config: dict,
        messages: list[dict],
        tools: list[dict] | None,
        system: str | None,
        stream: bool,
    ):
        """
        Make the actual Anthropic SDK call.

        If `stream=True`, returns a streaming context manager (caller must use
        `async with` and iterate events). Otherwise, awaits the full response.
        """
        kwargs = self._build_kwargs(config, messages, tools, system)

        # For streaming, return the context manager directly — the caller
        # (e.g. ReActLoop) will iterate over the events
        if stream:
            return self.anthropic.messages.stream(**kwargs)

        # Non-streaming: await the full response
        response = await self.anthropic.messages.create(**kwargs)

        # Log token usage and stop reason for observability/cost tracking
        logger.info(
            "LLM call complete",
            extra={
                "model": config["model"],
                # Reverse-lookup the component name from the config dict
                "component": next(
                    (k for k, v in MODEL_CONFIGS.items() if v is config), "unknown"
                ),
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "stop_reason": response.stop_reason,
            },
        )

        return response

    def create_message_stream(
        self,
        component: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
    ):
        """
        Return an async streaming context manager for the given component.

        This is a convenience method used by the ReActLoop to stream responses.
        The caller uses it with `async with client.create_message_stream(...) as stream:`.
        """
        config = MODEL_CONFIGS[component]
        kwargs = self._build_kwargs(config, messages, tools, system)
        return self.anthropic.messages.stream(**kwargs)

    async def close(self):
        """Close the underlying HTTP client to free connections."""
        await self.anthropic.close()
