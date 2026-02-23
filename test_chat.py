"""Quick end-to-end test for the orchestrator agent."""
from __future__ import annotations

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from engine.llm.client import LLMClient
from engine.agent.orchestrator import OrchestratorAgent
from engine.streaming.event_emitter import EventEmitter


async def test_greeting():
    """Test a simple greeting — should respond without tools."""
    print("\n--- Test: Greeting ---")
    llm_client = LLMClient()
    orchestrator = OrchestratorAgent(llm_client)
    emitter = EventEmitter("test-conv-1")

    result = await orchestrator.handle_message(
        user_input="Hello!",
        conversation_id="test-conv-1",
        tenant_id="test-tenant",
        user_id="test-user",
        user_name="Alex",
        org_name="Acme Corp",
        event_emitter=emitter,
    )

    print(f"Response: {result.response[:500]}")
    print(f"Tokens: {result.token_usage}")
    print(f"Trajectory steps: {len(result.trajectory)}")
    print(f"Events: {len(emitter.get_events())}")

    await llm_client.close()
    return result


async def test_simple_question():
    """Test a simple knowledge question — should respond without tools."""
    print("\n--- Test: Simple Question ---")
    llm_client = LLMClient()
    orchestrator = OrchestratorAgent(llm_client)
    emitter = EventEmitter("test-conv-2")

    result = await orchestrator.handle_message(
        user_input="What is zero trust architecture?",
        conversation_id="test-conv-2",
        tenant_id="test-tenant",
        user_id="test-user",
        user_name="Alex",
        org_name="Acme Corp",
        event_emitter=emitter,
    )

    print(f"Response: {result.response[:500]}")
    print(f"Tokens: {result.token_usage}")
    print(f"Trajectory steps: {len(result.trajectory)}")

    await llm_client.close()
    return result


async def main():
    print("=== Axari POC End-to-End Test ===")

    try:
        await test_greeting()
        await test_simple_question()
        print("\n=== All tests passed ===")
    except Exception as e:
        print(f"\n=== Test failed: {e} ===")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
