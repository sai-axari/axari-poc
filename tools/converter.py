"""Auto-convert Python async functions to Anthropic tool schemas."""
from __future__ import annotations

import inspect
import re
from typing import Any, get_type_hints


def python_type_to_json_type(py_type: Any) -> str:
    """Convert a Python type hint to a JSON Schema type string."""
    if py_type is None:
        return "string"

    origin = getattr(py_type, "__origin__", None)

    if origin is list:
        return "array"
    if origin is dict:
        return "object"

    type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }

    return type_map.get(py_type, "string")


def extract_param_doc(docstring: str, param_name: str) -> str:
    """Extract parameter description from a docstring."""
    if not docstring:
        return param_name

    # Match patterns like `:param name: description` or `param_name: description`
    # Also handles Google-style `Args:` sections
    patterns = [
        rf":param\s+{param_name}\s*:\s*(.+?)(?=\n\s*:|$)",
        rf"{param_name}\s*(?:\([^)]*\))?\s*:\s*(.+?)(?=\n\s*\w+\s*:|$)",
    ]

    for pattern in patterns:
        match = re.search(pattern, docstring, re.DOTALL)
        if match:
            desc = match.group(1).strip()
            # Clean up multi-line descriptions
            desc = re.sub(r"\s+", " ", desc)
            return desc

    return param_name


def function_to_tool_schema(func: callable, name: str) -> dict:
    """
    Convert a Python async function into an Anthropic tool schema by inspecting
    its signature, type hints, and docstring.

    Args:
        func: The callable to convert
        name: The tool name (e.g., "jira:search_jira_issues")

    Returns:
        Anthropic tool schema dict with name, description, input_schema
    """
    sig = inspect.signature(func)
    try:
        hints = get_type_hints(func)
    except Exception:
        hints = {}

    doc = inspect.getdoc(func) or ""

    properties = {}
    required = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue

        json_type = python_type_to_json_type(hints.get(param_name, str))
        prop: dict[str, Any] = {"type": json_type}

        # Extract description from docstring
        desc = extract_param_doc(doc, param_name)
        prop["description"] = desc

        # Handle array items type
        if json_type == "array":
            args = getattr(hints.get(param_name), "__args__", None)
            if args:
                prop["items"] = {"type": python_type_to_json_type(args[0])}
            else:
                prop["items"] = {"type": "string"}

        properties[param_name] = prop

        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    # Use first paragraph of docstring as tool description
    description = doc.split("\n\n")[0].strip() if doc else f"Tool: {name}"

    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }
