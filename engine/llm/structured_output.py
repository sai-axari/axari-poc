"""
Pydantic model extraction using Anthropic's tool_use schema trick.

This module provides a way to get structured (typed) output from the LLM
by leveraging Claude's tool_use feature. Instead of asking the model to
output raw JSON (which can be malformed), we define a fake "tool" whose
input_schema matches the desired Pydantic model. Claude fills in the tool
call arguments with properly structured data, which we then validate
into a Pydantic instance.
"""
from __future__ import annotations

import json
from typing import Type, TypeVar

from pydantic import BaseModel

from engine.llm.client import LLMClient

# Generic type variable bound to BaseModel — allows the function to return
# the exact Pydantic subclass the caller passes in
T = TypeVar("T", bound=BaseModel)


async def extract_structured(
    llm_client: LLMClient,
    component: str,
    prompt: str,
    output_model: Type[T],
    system: str | None = None,
) -> T:
    """
    Extract a Pydantic model from an LLM response using the tool_use trick.

    Instead of asking for JSON in the prompt (unreliable), we define a "tool"
    whose input_schema matches the Pydantic model. Claude will fill it in
    with structured data as a tool call.

    Args:
        llm_client: The LLM client to use
        component: Model config component name
        prompt: User prompt describing what to extract
        output_model: Pydantic model class to extract into
        system: Optional system prompt

    Returns:
        Instance of output_model populated from the LLM response
    """
    # Create a synthetic tool definition whose input_schema is derived from
    # the Pydantic model's JSON schema. Claude will "call" this tool with
    # the structured data we want.
    tool_schema = {
        "name": "extract_output",
        "description": f"Extract structured data as {output_model.__name__}",
        "input_schema": output_model.model_json_schema(),
    }

    # Send the prompt with the synthetic tool. Claude will respond with a
    # tool_use content block containing the structured data as arguments.
    response = await llm_client.create_message(
        component=component,
        messages=[{"role": "user", "content": prompt}],
        tools=[tool_schema],
        system=system,
    )

    # Scan through response content blocks to find our tool_use block.
    # The response may also contain text blocks (Claude's reasoning),
    # but we only care about the tool call with our structured data.
    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_output":
            # Validate and parse the raw dict into the Pydantic model
            return output_model.model_validate(block.input)

    # If Claude didn't produce a tool_use block, something went wrong
    # (e.g., the model decided to answer in text instead of calling the tool)
    raise ValueError(
        f"LLM did not return a tool_use block for {output_model.__name__}. "
        f"Response content types: {[b.type for b in response.content]}"
    )
