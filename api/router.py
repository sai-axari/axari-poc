"""Chat API router."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from api.models import ChatRequest, ChatResponse, BehaviorEventRequest, BehaviorDismissRequest, ResponsibilityExecuteRequest
from engine.context.dashboard import fetch_dashboard_data
from engine.agent.orchestrator import OrchestratorAgent
from engine.llm.client import LLMClient
from engine.memory.behavior_store import BehaviorStore
from engine.memory.conversation_store import ConversationStore
from engine.memory.context_manager import ContextManager
from engine.memory.tool_cache import ToolResultCache
from engine.streaming.event_emitter import EventEmitter
from sqlalchemy import text
from config.responsibility_instructions import RESPONSIBILITY_INSTRUCTIONS
from tools.connected import _get_engine

logger = logging.getLogger(__name__)

router = APIRouter()

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# Shared instances (initialized once)
behavior_store = BehaviorStore()
conversation_store = ConversationStore()
context_manager = ContextManager()
tool_cache = ToolResultCache()

# In-memory store for background responsibility executions (POC only)
_responsibility_executions: dict[str, dict] = {}


@router.post("/v1/chat/invoke", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Process a chat message through the orchestrator agent.

    The orchestrator handles the entire flow:
    - Intent classification (via extended thinking)
    - Date extraction (naturally from context)
    - Tool execution (parallel when possible)
    - Response synthesis (with Axari persona)
    """
    llm_client = LLMClient()
    event_emitter = EventEmitter(request.conversation_id)

    try:
        # Load conversation history
        history = await conversation_store.load_messages(request.conversation_id)
        history = context_manager.truncate_messages(history)

        # Run the orchestrator
        orchestrator = OrchestratorAgent(llm_client)

        result = await orchestrator.handle_message(
            user_input=request.message,
            conversation_id=request.conversation_id,
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            allowed_tools=request.allowed_tools,
            conversation_history=history,
            integration_constraints=request.integration_constraints,
            user_name=request.user_name,
            org_name=request.org_name,
            user_timezone=request.user_timezone,
            event_emitter=event_emitter,
            tool_cache=tool_cache,
        )

        # Save exchange to memory
        await conversation_store.save_exchange(
            conversation_id=request.conversation_id,
            user_msg=request.message,
            assistant_msg=result.response,
        )

        return ChatResponse(
            response=result.response,
            conversation_id=request.conversation_id,
            trajectory=result.trajectory,
            token_usage=result.token_usage,
            events=event_emitter.get_events(),
        )

    except Exception as e:
        logger.error(f"Chat processing failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        await llm_client.close()


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@router.get("/")
async def chat_ui():
    """Serve the interactive chat UI."""
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/v1/dashboard")
async def dashboard(tenant_id: str):
    """
    Fetch the latest playbook execution data for the chat dashboard.

    Returns morning brief highlights, commitment radar items,
    and meeting prep summaries for the given tenant.
    """
    data = await fetch_dashboard_data(tenant_id)
    return data


@router.get("/v1/execution/{execution_id}/status")
async def execution_status(execution_id: str):
    """
    Get the current status of a playbook execution.

    Used by the frontend to poll for completion and show notifications.
    """
    engine = _get_engine()
    query = text("""
        SELECT px.status, px.completed_at, p.name AS playbook_name, w.name AS worker_name
        FROM playbook_executions px
        JOIN playbooks p ON p.id = px.playbook_id
        LEFT JOIN ai_workers w ON w.id = p.ai_worker_id
        WHERE px.id = :id
    """)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(query, {"id": execution_id})
            row = result.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Execution not found")

        return {
            "execution_id": execution_id,
            "status": row[0],
            "completed_at": row[1].isoformat() if row[1] else None,
            "playbook_name": row[2],
            "worker_name": row[3] or "AI Worker",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch execution status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/v1/behavior/event")
async def record_behavior(request: BehaviorEventRequest):
    """Record a user behavior event for adaptive dashboard learning."""
    behavior_store.record_event(request.tenant_id, request.user_id, request.event)
    return {"status": "ok"}


@router.get("/v1/behavior/profile")
async def behavior_profile(tenant_id: str, user_id: str):
    """Get computed behavioral profile for adaptive dashboard."""
    profile = behavior_store.get_profile(tenant_id, user_id)
    return profile


@router.post("/v1/behavior/dismiss")
async def dismiss_nudge(request: BehaviorDismissRequest):
    """Dismiss a nudge so it doesn't reappear this session."""
    behavior_store.dismiss_nudge(request.tenant_id, request.user_id, request.nudge_id)
    return {"status": "ok"}


@router.get("/v1/responsibilities")
async def list_responsibilities(tenant_id: str):
    """List all responsibilities (playbooks) for a tenant."""
    engine = _get_engine()
    query = text("""
        SELECT p.id, p.name, p.description, p.status, w.name AS worker_name
        FROM playbooks p
        LEFT JOIN ai_workers w ON w.id = p.ai_worker_id
        WHERE p.tenant_id = :tenant_id AND p.deleted_at IS NULL
        ORDER BY p.name
    """)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(query, {"tenant_id": tenant_id})
            rows = result.fetchall()
        return [
            {
                "id": str(r[0]),
                "name": r[1],
                "description": r[2] or "",
                "status": r[3],
                "worker_name": r[4] or "AI Worker",
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"Failed to list responsibilities: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/v1/responsibilities/execute")
async def execute_responsibility(request: ResponsibilityExecuteRequest):
    """
    Execute a responsibility (playbook) in the background.

    1. Looks up the playbook name by ID
    2. Matches instructions from config/responsibility_instructions.py
    3. Kicks off OrchestratorAgent.handle_message() as a background task
    4. Returns immediately with an execution_id for polling
    """
    engine = _get_engine()

    # Look up the playbook
    query = text("""
        SELECT p.name, p.status
        FROM playbooks p
        WHERE p.id = :id AND p.tenant_id = :tenant_id AND p.deleted_at IS NULL
    """)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                query,
                {"id": request.responsibility_id, "tenant_id": request.tenant_id},
            )
            row = result.fetchone()
    except Exception as e:
        logger.error(f"Failed to look up responsibility: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    if not row:
        raise HTTPException(status_code=404, detail="Responsibility not found")

    playbook_name = row[0]
    playbook_status = row[1]

    if playbook_status != "active":
        raise HTTPException(
            status_code=400,
            detail=f"Responsibility '{playbook_name}' is {playbook_status}. Activate it first.",
        )

    # Match instructions
    name_lower = playbook_name.lower().strip()
    instructions = RESPONSIBILITY_INSTRUCTIONS.get("__default__", "")
    for key, value in RESPONSIBILITY_INSTRUCTIONS.items():
        if key == "__default__":
            continue
        if key in name_lower or name_lower in key:
            instructions = value
            break

    user_message = (
        f"Execute the '{playbook_name}' responsibility by directly using your integration tools "
        f"(email, calendar, Jira, SIEM, messaging, etc.) to gather data and synthesize a response. "
        f"Do NOT use the trigger_responsibility tool — you must perform the work yourself.\n\n"
        f"{instructions.strip()}"
    )

    # Create execution record in-memory
    execution_id = str(uuid.uuid4())
    _responsibility_executions[execution_id] = {
        "status": "running",
        "playbook_name": playbook_name,
        "responsibility_id": request.responsibility_id,
        "started_at": time.time(),
        "response": None,
        "trajectory": [],
        "token_usage": {},
        "error": None,
    }

    # Launch background task
    asyncio.create_task(
        _run_responsibility_in_background(
            execution_id=execution_id,
            user_message=user_message,
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            user_name=request.user_name,
            org_name=request.org_name,
            user_timezone=request.user_timezone,
        )
    )

    return {
        "execution_id": execution_id,
        "status": "running",
        "playbook_name": playbook_name,
    }


async def _run_responsibility_in_background(
    execution_id: str,
    user_message: str,
    tenant_id: str,
    user_id: str,
    user_name: str,
    org_name: str,
    user_timezone: str,
):
    """Background coroutine that runs the orchestrator and stores results."""
    conversation_id = f"resp-{execution_id}"
    llm_client = LLMClient()
    event_emitter = EventEmitter(conversation_id)
    start_time = time.monotonic()

    try:
        orchestrator = OrchestratorAgent(llm_client)
        result = await orchestrator.handle_message(
            user_input=user_message,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
            allowed_tools=[],
            conversation_history=[],
            integration_constraints="",
            user_name=user_name,
            org_name=org_name,
            user_timezone=user_timezone,
            event_emitter=event_emitter,
            tool_cache=tool_cache,
            exclude_tools=["trigger_responsibility"],
        )

        elapsed = round(time.monotonic() - start_time, 2)
        _responsibility_executions[execution_id].update({
            "status": "completed",
            "response": result.response,
            "trajectory": result.trajectory,
            "token_usage": {**result.token_usage, "elapsed_seconds": elapsed},
        })
        logger.info(f"Responsibility execution {execution_id} completed in {elapsed}s")

    except Exception as e:
        elapsed = round(time.monotonic() - start_time, 2)
        logger.error(f"Responsibility execution {execution_id} failed: {e}", exc_info=True)
        _responsibility_executions[execution_id].update({
            "status": "failed",
            "error": str(e),
            "token_usage": {"elapsed_seconds": elapsed},
        })

    finally:
        await llm_client.close()


@router.get("/v1/responsibilities/execution/{execution_id}")
async def get_responsibility_execution(execution_id: str):
    """
    Poll for a background responsibility execution's status and results.

    Returns status, and when completed, the full response, trajectory, and token usage.
    """
    record = _responsibility_executions.get(execution_id)
    if not record:
        raise HTTPException(status_code=404, detail="Execution not found")

    resp = {
        "execution_id": execution_id,
        "status": record["status"],
        "playbook_name": record["playbook_name"],
    }

    if record["status"] == "completed":
        resp["response"] = record["response"]
        resp["trajectory"] = record["trajectory"]
        resp["token_usage"] = record["token_usage"]
    elif record["status"] == "failed":
        resp["error"] = record["error"]
        resp["token_usage"] = record.get("token_usage", {})

    return resp


@router.get("/v1/responsibilities/{responsibility_id}/result")
async def get_responsibility_latest_result(responsibility_id: str):
    """
    Get the latest completed execution result for a responsibility (playbook).

    Searches in-memory executions for the most recent completed run matching
    the given responsibility_id. Returns 404 if no completed result exists.
    """
    # Find all executions for this responsibility, pick the latest completed one
    latest = None
    latest_time = 0
    for exec_id, record in _responsibility_executions.items():
        if record["responsibility_id"] != responsibility_id:
            continue
        if record["status"] not in ("completed", "failed"):
            continue
        started = record.get("started_at", 0)
        if started > latest_time:
            latest_time = started
            latest = (exec_id, record)

    if not latest:
        raise HTTPException(status_code=404, detail="No execution results found")

    exec_id, record = latest
    resp = {
        "execution_id": exec_id,
        "status": record["status"],
        "playbook_name": record["playbook_name"],
    }

    if record["status"] == "completed":
        resp["response"] = record["response"]
        resp["trajectory"] = record["trajectory"]
        resp["token_usage"] = record["token_usage"]
    elif record["status"] == "failed":
        resp["error"] = record["error"]
        resp["token_usage"] = record.get("token_usage", {})

    return resp


@router.get("/v1/responsibilities/results")
async def get_all_completed_results():
    """
    Return all completed in-memory responsibility execution results.

    Used by the dashboard to overlay local execution results on top of DB data.
    Returns a dict keyed by playbook name (lowercased) with the latest completed result.
    """
    by_name: dict[str, dict] = {}
    for exec_id, record in _responsibility_executions.items():
        if record["status"] != "completed":
            continue
        name_key = record["playbook_name"].lower().strip()
        started = record.get("started_at", 0)
        if name_key not in by_name or started > by_name[name_key].get("started_at", 0):
            by_name[name_key] = {
                "execution_id": exec_id,
                "playbook_name": record["playbook_name"],
                "response": record["response"],
                "trajectory": record["trajectory"],
                "token_usage": record["token_usage"],
                "started_at": started,
            }
    return by_name


@router.post("/v1/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    Stream chat events via Server-Sent Events (SSE).

    Events emitted:
    - thinking: Extended thinking text
    - node_planner: Tool call progress (with goal description)
    - response: Final assistant response
    - trajectory: Tool call trajectory (after completion)
    - token_usage: Token usage breakdown (after completion)
    - error: Error details (if processing fails)
    - [DONE]: Stream termination signal
    """
    llm_client = LLMClient()
    event_emitter = EventEmitter(request.conversation_id)

    async def generate():
        start_time = time.monotonic()
        try:
            history = await conversation_store.load_messages(request.conversation_id)
            history = context_manager.truncate_messages(history)

            orchestrator = OrchestratorAgent(llm_client)

            async def run_and_complete():
                try:
                    return await orchestrator.handle_message(
                        user_input=request.message,
                        conversation_id=request.conversation_id,
                        tenant_id=request.tenant_id,
                        user_id=request.user_id,
                        allowed_tools=request.allowed_tools,
                        conversation_history=history,
                        integration_constraints=request.integration_constraints,
                        user_name=request.user_name,
                        org_name=request.org_name,
                        user_timezone=request.user_timezone,
                        event_emitter=event_emitter,
                        tool_cache=tool_cache,
                    )
                except Exception as exc:
                    await event_emitter._emit("error", {"detail": str(exc)})
                    raise
                finally:
                    await event_emitter.complete()

            task = asyncio.create_task(run_and_complete())

            # Stream events as they arrive
            async for event in event_emitter.stream():
                yield f"data: {json.dumps(event, default=str)}\n\n"

            # Orchestrator finished — get result
            result = await task

            # Send trajectory, token usage, and elapsed time
            elapsed = round(time.monotonic() - start_time, 2)
            yield f"data: {json.dumps({'type': 'trajectory', 'data': result.trajectory}, default=str)}\n\n"
            yield f"data: {json.dumps({'type': 'token_usage', 'data': {**result.token_usage, 'elapsed_seconds': elapsed}}, default=str)}\n\n"

            # Save exchange to memory
            await conversation_store.save_exchange(
                conversation_id=request.conversation_id,
                user_msg=request.message,
                assistant_msg=result.response,
            )

        except Exception as e:
            logger.error(f"Stream processing failed: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'data': {'detail': str(e)}})}\n\n"

        finally:
            await llm_client.close()
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
