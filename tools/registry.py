"""Tool registry for Anthropic tool_use format."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from tools.converter import function_to_tool_schema

logger = logging.getLogger(__name__)


@dataclass
class ToolEntry:
    """A registered tool with its callable and schema."""
    func: Callable
    schema: dict


# Global tool registry
TOOL_REGISTRY: dict[str, ToolEntry] = {}


def _sanitize_name(name: str) -> str:
    """Sanitize tool name to match Anthropic's pattern: ^[a-zA-Z0-9_-]{1,128}$"""
    return name.replace(":", "__")


def register_tool(name: str, func: Callable, schema: dict | None = None):
    """
    Register a tool with the registry.

    Args:
        name: Tool name (e.g., "jira:search_jira_issues")
        func: The async callable to execute
        schema: Optional pre-built Anthropic tool schema. If None, auto-generated.
    """
    safe_name = _sanitize_name(name)
    if schema is None:
        schema = function_to_tool_schema(func, safe_name)
    else:
        schema = {**schema, "name": safe_name}
    TOOL_REGISTRY[safe_name] = ToolEntry(func=func, schema=schema)
    logger.debug(f"Registered tool: {safe_name}")


def get_schemas_for(names: list[str]) -> list[dict]:
    """Get Anthropic tool schemas for a list of tool names."""
    schemas = []
    for name in names:
        entry = TOOL_REGISTRY.get(name)
        if entry:
            schemas.append(entry.schema)
        else:
            logger.warning(f"Tool not found in registry: {name}")
    return schemas


def get_callables_for(names: list[str]) -> dict[str, Callable]:
    """Get callable functions for a list of tool names."""
    callables = {}
    for name in names:
        entry = TOOL_REGISTRY.get(name)
        if entry:
            callables[name] = entry.func
        else:
            logger.warning(f"Tool not found in registry: {name}")
    return callables


def get_tools_with_descriptions(names: list[str] | None = None) -> str:
    """
    Get a formatted string of tool names and descriptions.

    Args:
        names: Optional list of tool names. If None, returns all tools.

    Returns:
        Formatted string like "- jira:search_jira_issues: Search for Jira issues"
    """
    if names is None:
        names = list(TOOL_REGISTRY.keys())

    lines = []
    for name in names:
        entry = TOOL_REGISTRY.get(name)
        if entry:
            desc = entry.schema.get("description", "No description")
            # Truncate long descriptions
            if len(desc) > 100:
                desc = desc[:100] + "..."
            lines.append(f"- {name}: {desc}")
    return "\n".join(lines)


def list_registered_tools() -> list[str]:
    """Return all registered tool names."""
    return list(TOOL_REGISTRY.keys())


def list_tools_for_integrations(integration_keys: list[str]) -> list[str]:
    """Return registered tool names that belong to the given integration keys.

    Tool names follow the pattern 'integration_key__method_name'.
    This filters to only tools whose prefix matches a connected integration.
    """
    sanitized_keys = {_sanitize_name(k) for k in integration_keys}
    matched = []
    for tool_name in TOOL_REGISTRY:
        prefix = tool_name.split("__")[0] if "__" in tool_name else tool_name
        if prefix in sanitized_keys:
            matched.append(tool_name)
    return matched
