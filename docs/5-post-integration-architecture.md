# Post-Integration Architecture

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture Diagram](#architecture-diagram)
3. [Request Flow](#request-flow)
4. [Component Inventory](#component-inventory)
5. [Directory Structure](#directory-structure)
6. [API and Messaging Contract](#api-and-messaging-contract)
7. [Infrastructure Changes](#infrastructure-changes)
8. [Dependency Cleanup](#dependency-cleanup)
9. [Database Impact](#database-impact)
10. [Monitoring and Observability](#monitoring-and-observability)
11. [Rollback Plan](#rollback-plan)

---

## System Overview

After migration, the system runs a **single chat engine** — the V2 ReAct-based orchestrator. There is no longer a V1/V2 split in routing, processing, or code.

**Key characteristics of the final system:**

- **One agent architecture:** A single `OrchestratorAgent` with a `ReActLoop` handles all chat requests, from simple greetings to complex cross-integration reports
- **One LLM model:** Claude Sonnet 4 for everything (orchestrator with extended thinking, worker without)
- **One message type:** `agent_chat_request` SQS messages, all routed to `AgentV2Processor`
- **One streaming path:** AppSync WebSocket via `EventEmitter`, with DB persistence of all events
- **Extended feature set:** Dashboard, meta-tools (analyze, delegate_subtask, take_notes, add_reminder, trigger_responsibility), behavior tracking, and playbook triggering from chat

The `agents/` directory no longer exists. The entire LangGraph pipeline, DSPy signatures, multi-model configurations, and the 11-node graph are removed.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                       Frontend (React App)                          │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────────────────┐  │
│  │ Chat     │  │ Dashboard    │  │ Detail Panel                 │  │
│  │ Messages │  │ (3-col grid) │  │ ┌──────┬─────────┬───────┐  │  │
│  │          │  │ • Priorities │  │ │ Data │Reminders│ Notes │  │  │
│  │          │  │ • Commits   │  │ │      │         │       │  │  │
│  │          │  │ • Meetings  │  │ └──────┴─────────┴───────┘  │  │
│  └──────────┘  └──────────────┘  └──────────────────────────────┘  │
│                    AppSync WebSocket ↕ REST API                     │
└─────────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴──────────┐
                    ▼                    ▼
         ┌──────────────────┐  ┌──────────────────┐
         │  Core-svc API    │  │  AWS AppSync      │
         │  (sends SQS)     │  │  (WebSocket hub)  │
         └────────┬─────────┘  └────────┬──────────┘
                  │                     │
                  ▼                     │
         ┌──────────────────┐           │
         │  SQS Queue       │           │
         │  (agent_chat_    │           │
         │   request)       │           │
         └────────┬─────────┘           │
                  │                     │
                  ▼                     │
┌─────────────────────────────────────────────────────────────────────┐
│                    axari-ai-agents Service                           │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ SQS Consumer                                                │    │
│  │  ProcessorFactory → AgentV2Processor                        │    │
│  └────────────────────────┬────────────────────────────────────┘    │
│                           │                                         │
│  ┌────────────────────────▼────────────────────────────────────┐    │
│  │ V2ChatService (services/v2_chat.py)                         │    │
│  │  1. Save user_input event to DB                             │    │
│  │  2. Load allowed tools (IntegrationService)                 │    │
│  │  3. Load conversation history (ChatService)                 │    │
│  │  4. Load worker context (AI Workers + playbooks)            │    │
│  │  5. Create EventEmitter (wired to AppSync) ──────────────────┼──→│
│  │  6. Run OrchestratorAgent                                   │    │
│  │  7. Emit final response                                     │    │
│  └────────────────────────┬────────────────────────────────────┘    │
│                           │                                         │
│  ┌────────────────────────▼────────────────────────────────────┐    │
│  │ OrchestratorAgent (engine/agent/orchestrator.py)            │    │
│  │  • Build tool schemas + callables from registry             │    │
│  │  • Inject meta-tools (analyze, delegate_subtask,            │    │
│  │    take_notes, add_reminder, trigger_responsibility)        │    │
│  │  • Build system prompt (persona + worker context)           │    │
│  │                                                             │    │
│  │  ┌───────────────────────────────────────────────────┐      │    │
│  │  │ ReActLoop (engine/agent/react_loop.py)            │      │    │
│  │  │                                                   │      │    │
│  │  │  LLM Call (Claude Sonnet 4 + extended thinking)   │      │    │
│  │  │      │                                            │      │    │
│  │  │      ├─→ No tool calls → Return response          │      │    │
│  │  │      └─→ tool_use blocks → Execute in parallel    │      │    │
│  │  │           │                                       │      │    │
│  │  │           ├─→ Integration tools (Jira, Outlook…)  │      │    │
│  │  │           ├─→ Meta-tools (analyze, delegate…)     │      │    │
│  │  │           └─→ Results → Next LLM iteration        │      │    │
│  │  │                                                   │      │    │
│  │  │  (up to 15 iterations)                            │      │    │
│  │  └───────────────────────────────────────────────────┘      │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                           │                                         │
│  ┌────────────────────────▼────────────────────────────────────┐    │
│  │ Supporting Components                                       │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │    │
│  │  │ LLMClient    │  │ ToolResult   │  │ ContextManager   │  │    │
│  │  │ (Anthropic   │  │ Cache (TTL)  │  │ (token budget)   │  │    │
│  │  │  SDK)        │  │              │  │                  │  │    │
│  │  └──────────────┘  └──────────────┘  └──────────────────┘  │    │
│  └──────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                  │                    │
         ┌────────┴────────┐  ┌────────┴────────┐
         ▼                 ▼  ▼                  ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│   PostgreSQL     │  │   OpenRouter /   │  │   SQS            │
│   (core-svc DB)  │  │   Anthropic API  │  │   (playbook      │
│   • chat_events  │  │   • Claude       │  │    execution      │
│   • integrations │  │     Sonnet 4     │  │    queue)         │
│   • playbooks    │  │                  │  │                   │
│   • ai_workers   │  │                  │  │                   │
└──────────────────┘  └──────────────────┘  └──────────────────┘
```

---

## Request Flow

### SQS Message to Response

```
1. Frontend sends user message via core-svc API
   │
2. Core-svc API creates chat_message record in DB
   │  Creates SQS message: { type: "agent_chat_request", message, conversation_id, ... }
   │
3. SQS Consumer picks up message
   │  ProcessorFactory.get_processor(message) → AgentV2Processor
   │
4. AgentV2Processor.process(message)
   │  Parses SQS body, validates tenant_id
   │  Sets Netra session/tenant IDs for observability
   │  Converts datetime to user's timezone
   │
5. V2ChatService.process_chat(...)
   │
   ├─→ 5a. Save user_input event to DB
   │        ChatService.insert_chat_event({ event_type: "user_input", data: { user_input } })
   │
   ├─→ 5b. Load allowed tools
   │        IntegrationService.fetch_permission_scope(tenant_id)
   │        → list_tools_for_integrations(integration_keys)
   │        → ["jira__search_issues", "microsoft_outlook__fetch_emails", ...]
   │
   ├─→ 5c. Load conversation history
   │        ChatService.get_messages_by_conversation(conversation_id)
   │        → For each message: get_chat_events_by_message()
   │        → Extract user_input + assistant_response events
   │        → Build Anthropic-format message list
   │
   ├─→ 5d. Load worker context
   │        fetch_worker_context(session, tenant_id)
   │        → AI Workers + playbooks + today's events → markdown string
   │
   ├─→ 5e. Create EventEmitter (wired to AppSync + DB)
   │
   └─→ 5f. OrchestratorAgent.handle_message(...)
            │
            ├─→ Build tool_schemas + tool_callables from registry
            ├─→ Add meta-tools (analyze, delegate_subtask, take_notes, ...)
            ├─→ Build system prompt (persona + worker context + capabilities)
            ├─→ Construct messages (history + current user message)
            │
            └─→ ReActLoop.run(messages, callbacks)
                 │
                 ├─→ Iteration 1: Stream LLM call
                 │     • thinking_delta → EventEmitter.emit_thinking() → AppSync
                 │     • tool_use blocks found → EventEmitter.emit_tool_call() → AppSync
                 │     • Execute tools in parallel (asyncio.gather)
                 │     • Add results to messages
                 │
                 ├─→ Iteration 2+: Stream LLM call with tool results
                 │     • More tools OR text response
                 │
                 └─→ Return AgentResult { final_text, trajectory, token_usage }
   │
6. V2ChatService calculates total_time
   │
7. EventEmitter.emit_response(final_text, total_time)
   │  → Save node_report_generator event to DB
   │  → Publish to AppSync → WebSocket → Frontend
   │
8. Frontend displays response
```

---

## Component Inventory

### What Stays

| Component | Path | Purpose |
|-----------|------|---------|
| **ReAct Loop** | `engine/agent/react_loop.py` | Core agentic iteration engine with parallel tool execution |
| **Orchestrator** | `engine/agent/orchestrator.py` | Entry point — wires tools, prompts, and ReAct loop |
| **Worker Agent** | `engine/agent/worker.py` | Lightweight agent for `delegate_subtask` |
| **LLM Client** | `engine/llm/client.py` | Unified async LLM client (Anthropic SDK via OpenRouter) |
| **Model Config** | `engine/llm/models.py` | Orchestrator + worker model configuration |
| **Event Emitter** | `engine/streaming/event_emitter.py` | AppSync + DB event delivery |
| **Tool Registry** | `engine/tools/registry.py` | Global tool store with schema/callable lookup |
| **Tool Integrations** | `engine/tools/integrations.py` | Auto-registration of integration tool modules |
| **Tool Converter** | `engine/tools/converter.py` | Python function → Anthropic tool schema |
| **Meta-Tools** | `engine/tools/meta_tools.py` | analyze, delegate_subtask |
| **Orchestrator Prompt** | `engine/prompts/orchestrator.py` | System prompt builder with persona and context |
| **Worker Prompt** | `engine/prompts/worker.py` | Focused execution prompt for workers |
| **Worker Context** | `engine/context/worker_context.py` | AI Worker + playbook knowledge injection |
| **Context Manager** | `engine/memory/context_manager.py` | Token budget enforcement (truncation) |
| **Tool Cache** | `engine/memory/tool_cache.py` | TTL-based tool result deduplication |
| **V2 Chat Service** | `services/v2_chat.py` | Orchestration layer (DB, tools, history, emitter) |
| **V2 Processor** | `core/queue_consumer/processors/agent_v2_processor.py` | SQS message handler |
| **Processor Factory** | `core/queue_consumer/processor_factory.py` | Message type → processor routing |
| **Chat Service** | `database/services/chat_service.py` | DB operations for chat events/messages |
| **Integration Service** | `database/services/integrations_service.py` | DB operations for tenant integrations |
| **AppSync Client** | `core/aws/appsync.py` | WebSocket publishing |
| **Integration Modules** | `integrations/` | Jira, Outlook, Teams, CrowdStrike, etc. |

### What's Removed

| Component | Path | Reason |
|-----------|------|--------|
| **Chat Graph** | `agents/graph/graph.py` | Replaced by ReAct loop |
| **Chat Node Files** | `agents/nodes/*.py` (14 files) | Each replaced by ReAct loop behavior |
| **Chat LLM Wrappers** | `agents/llm/*.py` (17 files) | Replaced by single `engine/llm/client.py` |
| **DSPy Signatures** | `agents/signatures/*.py` (12 files) | No longer needed |
| **V1 Prompts** | `agents/prompts/*.py` | Replaced by `engine/prompts/` |
| **ChatState Model** | `agents/models/state.py` | Replaced by Anthropic messages list |

**Note:** The responsibility graph code (`agents/graph/responsibility_graph.py`, `agents/graph/responsibility/`, `agents/graph/base.py`) is **retained** — it's used by `ResponsibilityProcessor` for playbook execution, which is separate from chat processing. Any `agents/llm/` or `agents/nodes/` files needed by responsibility execution are also kept.
| **V1 Streaming Service** | `services/stream.py` | Replaced by `services/v2_chat.py` |
| **V1 Processor** | `core/queue_consumer/processors/agent_processor.py` | Replaced by `agent_v2_processor.py` |
| **LangGraph Checkpointer** | `database/checkpointer.py` | No graph state to checkpoint |

### What's Added (from POC)

| Component | Source (POC) | Target (Production) | Purpose |
|-----------|-------------|---------------------|---------|
| **Dashboard Data Fetcher** | `axari-poc/engine/context/dashboard.py` | `engine/context/dashboard.py` | Query latest playbook execution data |
| **Playbook Trigger** | `axari-poc/engine/context/playbook_trigger.py` | `engine/context/playbook_trigger.py` | Trigger playbooks from chat via SQS |
| **Behavior Store** | `axari-poc/engine/memory/behavior_store.py` | `engine/memory/behavior_store.py` | User behavior tracking and personalization |
| **Meta-Tools (take_notes, add_reminder, trigger_responsibility)** | `axari-poc/tools/meta_tools.py` | `engine/tools/meta_tools.py` (extend) | Notes, reminders, playbook triggering |
| **Responsibility Instructions** | `axari-poc/config/responsibility_instructions.py` | `config/responsibility_instructions.py` | Playbook execution prompts |

---

## Directory Structure

Final clean state of the `axari-ai-agents` codebase after migration:

```
axari-ai-agents/
├── main.py                              # FastAPI entry point, tool registration
├── pyproject.toml                       # Dependencies (cleaned)
├── .env                                 # Environment variables
│
├── config/
│   ├── responsibility_instructions.py   # Playbook execution prompts (from POC)
│   └── ...
│
├── core/
│   ├── config.py                        # Application configuration
│   ├── aws/
│   │   └── appsync.py                   # AppSync WebSocket client
│   ├── queue_consumer/
│   │   ├── consumer.py                  # SQS polling loop
│   │   ├── message_processor.py         # Message processing pipeline
│   │   ├── processor_factory.py         # Message type → processor routing
│   │   └── processors/
│   │       ├── base_processor.py        # Base class
│   │       ├── agent_v2_processor.py    # Chat processing (the only chat processor)
│   │       ├── responsibility_processor.py  # Playbook execution
│   │       ├── document_processor.py    # Document ingestion
│   │       ├── slack_processor.py       # Slack vectorization
│   │       ├── newsletter_processor.py  # Newsletter generation
│   │       └── cleanup_processor.py     # Cleanup tasks
│   ├── decorators/
│   │   └── logging_decorators.py        # @with_consumer_context
│   └── logging_config.py               # Structured logging setup
│
├── database/
│   ├── session.py                       # SessionContext, get_session()
│   ├── models/                          # SQLAlchemy ORM models
│   └── services/
│       ├── chat_service.py              # Chat event/message DB operations
│       ├── integrations_service.py      # Integration/permission DB operations
│       ├── playbook_service.py          # Playbook execution DB operations
│       └── analytics_service.py         # Usage analytics tracking
│
├── engine/
│   ├── agent/
│   │   ├── orchestrator.py              # Main entry point — wires everything
│   │   ├── react_loop.py               # Core ReAct iteration engine
│   │   └── worker.py                   # Worker agent for delegate_subtask
│   ├── context/
│   │   ├── worker_context.py            # AI Worker knowledge for prompt
│   │   ├── dashboard.py                # Dashboard data queries (from POC)
│   │   └── playbook_trigger.py         # Trigger playbooks from chat (from POC)
│   ├── llm/
│   │   ├── client.py                    # Unified LLM client (Anthropic SDK)
│   │   └── models.py                   # Model configurations
│   ├── memory/
│   │   ├── context_manager.py           # Token budget truncation
│   │   ├── tool_cache.py               # TTL tool result cache
│   │   └── behavior_store.py           # User behavior tracking (from POC)
│   ├── prompts/
│   │   ├── orchestrator.py              # System prompt builder
│   │   └── worker.py                   # Worker execution prompt
│   ├── streaming/
│   │   └── event_emitter.py            # AppSync + DB event delivery
│   └── tools/
│       ├── registry.py                  # Global tool store
│       ├── integrations.py              # Integration tool auto-registration
│       ├── converter.py                 # Function → tool schema conversion
│       └── meta_tools.py               # analyze, delegate_subtask, take_notes,
│                                        # add_reminder, trigger_responsibility
│
├── integrations/                        # Integration tool modules (unchanged)
│   ├── jira/
│   ├── microsoft_outlook/
│   ├── microsoft_teams/
│   ├── microsoft_calendar/
│   ├── crowdstrike/
│   ├── microsoft_defender/
│   └── ...
│
├── services/
│   ├── v2_chat.py                       # V2 chat orchestration service
│   ├── chat.py                          # Shared chat utilities
│   └── document_ingestion.py            # Document processing
│
├── schemas/
│   ├── chat.py                          # ChatEventData, etc.
│   └── responsibility.py               # PlaybookEventData
│
├── exceptions/
│   ├── chat_processing_exception.py
│   ├── appsync_exception.py
│   └── database_exception.py
│
└── utils/
    └── date_utilities.py                # Timezone conversion helpers
```

**What's gone from `agents/`:** All chat-specific code — `agents/graph/graph.py`, `agents/nodes/`, `agents/llm/` (chat wrappers), `agents/signatures/`, `agents/prompts/`, `agents/models/`.

**What remains in `agents/`:** Responsibility graph code used by `ResponsibilityProcessor`:
```
agents/
├── graph/
│   ├── base.py                          # Base graph class (used by responsibility graphs)
│   ├── responsibility_graph.py          # Responsibility graph entry point
│   └── responsibility/
│       ├── base_responsibility_graph.py
│       ├── generic_responsibility_graph.py
│       └── morning_brief_graph.py
└── (any llm/ or nodes/ files needed by responsibility execution)
```

---

## API and Messaging Contract

### SQS Message Format (Unchanged)

The SQS message format remains the same. The only change is that `agent_chat_request` now routes to `AgentV2Processor`:

```json
{
    "type": "agent_chat_request",
    "message": "Show me my Jira tickets from this week",
    "conversation_id": "uuid",
    "chat_message_id": "uuid",
    "tenant_id": "uuid",
    "tenant_name": "Acme Corp",
    "created_by": "uuid",
    "user_name": "John",
    "user_time_zone": "America/New_York"
}
```

### AppSync Event Types (Unchanged)

The production V2 emits the same event types the frontend already handles:

| Event Type | Data | When Emitted |
|------------|------|-------------|
| `user_input` | `{ user_input }` | At the start of processing |
| `node_intent_extractor` | `{ thinking_text }` | During extended thinking |
| `node_planner` | `{ planning_steps: [{ idx, step name, goal }] }` | When a tool call starts |
| `node_report_generator` | `{ assistant_response, total_time }` | Final response |

**New event types** (added from POC features):

| Event Type | Data | When Emitted |
|------------|------|-------------|
| `panel_note` | `{ content, mode }` | When `take_notes` meta-tool is called |
| `reminder` | `{ title, due, context }` | When `add_reminder` meta-tool is called |

### Dashboard API (New)

```
GET /v1/dashboard?tenant_id=<uuid>

Response:
{
    "morning_brief": {
        "summary": "...",
        "result": { ... },
        "completed_at": "2026-02-17T08:00:00Z"
    },
    "commitments": {
        "summary": "...",
        "suggestions": [
            { "title": "...", "description": "...", "due_date": "...", "importance": "high" }
        ],
        "completed_at": "2026-02-17T08:00:00Z"
    },
    "meeting_prep": {
        "summary": "...",
        "result": { ... },
        "completed_at": "2026-02-17T08:00:00Z"
    },
    "last_updated": "2026-02-17T08:00:00Z"
}
```

---

## Infrastructure Changes

### What Changes

| Area | Before | After |
|------|--------|-------|
| **SQS routing** | Two message types (`agent_chat_request`, `agent_chat_v2_request`) | One message type (`agent_chat_request`) |
| **Container size** | Larger (includes LangGraph, DSPy, LangChain, multiple LLM SDKs) | Smaller (~40% fewer dependencies) |
| **LLM providers** | OpenRouter (routing to OpenAI, Anthropic, Google) | OpenRouter (Anthropic only) or direct Anthropic API |
| **Checkpoint DB** | PostgreSQL tables for LangGraph checkpoints | Not needed — remove checkpoint tables |
| **Memory usage** | Higher (multiple LM instances, graph state, DSPy caches) | Lower (single LLM client, simple message state) |

### What Doesn't Change

| Area | Status |
|------|--------|
| **PostgreSQL** | Same database, same tables, same schema |
| **SQS queues** | Same queues, same consumer |
| **AppSync** | Same WebSocket infrastructure |
| **Integration modules** | Unchanged (`integrations/` directory) |
| **Authentication** | Same JWT-based auth via SQS message context |
| **Deployment** | Same deployment pipeline (just smaller artifact) |
| **Playbook execution** | `ResponsibilityProcessor` unchanged |

---

## Dependency Cleanup

### Packages to Remove from `pyproject.toml`

| Package | Current Version | Why Remove |
|---------|----------------|------------|
| `langgraph` | ≥0.2.39 | V1 graph framework — no longer used |
| `langchain-core` | ≥0.3.0 | LangChain base (messages, tools) — replaced by Anthropic SDK |
| `langchain-openai` | (latest) | OpenAI LLM wrapper — V2 uses Anthropic directly |
| `dspy` | (latest) | Signature-based LLM framework — all signatures removed |
| `langgraph-checkpoint-postgres` | 2.0.24 | Graph state persistence — no graph to checkpoint |
| `langchain-text-splitters` | ≥0.3.11 | Document chunking — used by V1 RAG, may be used elsewhere |
| `google-genai` | ≥1.9.0 | Google AI SDK — V1 used Gemini, V2 doesn't |
| `langchain-google-genai` | ≥2.1.12 | LangChain Gemini wrapper — V1 only |

**Before removing `langchain-text-splitters`:** Check if `services/document_ingestion.py` or other non-chat code still uses it. If so, keep it.

### Packages to Keep

| Package | Purpose in V2 |
|---------|---------------|
| `anthropic` | LLM client (AsyncAnthropic) |
| `fastapi` | API server |
| `uvicorn` | ASGI server |
| `pydantic` | Request/response models |
| `sqlalchemy` | Database ORM |
| `asyncpg` | Async PostgreSQL driver |
| `aioboto3`, `boto3` | SQS messaging |
| `structlog` | Structured logging |
| `aiohttp` | Async HTTP client (integration API calls) |
| `netra-sdk` | Observability |
| `python-dotenv` | Environment variables |
| `psycopg[binary]` | PostgreSQL adapter (used by SQLAlchemy) |
| `redis` | Caching (if used outside V1) |
| `slack-sdk` | Slack integration |
| `beautifulsoup4`, `lxml` | HTML parsing (integration data) |
| `pyjwt[crypto]` | JWT validation |

### Estimated Impact

- **~8 packages removed** from dependencies
- **~40% reduction** in installed package count (transitive dependencies of LangGraph/LangChain/DSPy are substantial)
- **Faster container builds** (fewer packages to install)
- **Smaller attack surface** (fewer dependencies to audit)

---

## Database Impact

### No Schema Changes Needed

The V2 engine uses the **same database tables** as V1. No migrations required.

| Table | Used By V1 | Used By V2 | Change |
|-------|-----------|-----------|--------|
| `chat_messages` | Yes | Yes | None |
| `chat_events` | Yes | Yes | None |
| `conversations` | Yes | Yes | None |
| `integrations` | Yes | Yes | None |
| `organization_integrations` | Yes | Yes | None |
| `ai_workers` | Yes | Yes | None |
| `ai_worker_contexts` | Yes | Yes | None |
| `playbooks` | Yes | Yes | None |
| `playbook_executions` | Yes | Yes | None |
| `playbook_events` | Yes | Yes | None |
| `playbook_execution_suggestions` | No | Yes (dashboard) | None (table exists) |

### Tables to Clean Up (Optional)

| Table | Purpose | Action |
|-------|---------|--------|
| LangGraph checkpoint tables | LangGraph `MemorySaver` state | Can be dropped after migration confirmed stable |

### New Tables (If Behavior Store is DB-Backed)

If the behavior store is implemented with database persistence (rather than in-memory):

```sql
-- User behavior events for personalization
CREATE TABLE user_behavior_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    event_type VARCHAR(50) NOT NULL,  -- 'session_start', 'dash_action', 'chat_message', 'section_click'
    action TEXT,                       -- Action label or prompt text
    metadata JSONB,                    -- { hour, section, etc. }
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Index for efficient profile computation
    INDEX idx_behavior_tenant_user (tenant_id, user_id),
    INDEX idx_behavior_created (created_at)
);
```

This is optional — the behavior store can remain in-memory for the initial migration and be upgraded to DB-backed later.

---

## Monitoring and Observability

### Existing V2 Observability (Already Implemented)

The production V2 already has observability via Netra SDK:

| Feature | Implementation | File |
|---------|---------------|------|
| **Workflow tracing** | `@workflow(name="CISO NLP chat V2 Workflow")` decorator | `agent_v2_processor.py:27` |
| **Session tracking** | `Netra.set_session_id(conversation_id)` | `agent_v2_processor.py:86` |
| **Tenant tracking** | `Netra.set_tenant_id(tenant_name)` | `agent_v2_processor.py:87` |
| **Structured logging** | `structlog` with context fields | Throughout `engine/` |

### Key Metrics to Monitor Post-Migration

| Metric | Source | What to Watch |
|--------|--------|--------------|
| **Response latency** | `total_time` in `node_report_generator` event | Should decrease 50-60% vs V1 |
| **Token usage** | `token_usage` from `AgentResult` | Should decrease ~50% vs V1 |
| **Tool call count** | `trajectory` length from `AgentResult` | Typically 2-6 per request |
| **Error rate** | Exception count in `V2ChatService.process_chat()` | Should remain stable |
| **LLM retry rate** | Retry loop in `ReActLoop.run()` (lines 82-128) | Retries on 529/503/timeout |
| **Max iterations hit** | `stop_reason == "max_iterations"` | Should be rare (<1%) |
| **Tool cache hit rate** | `TOOL CACHE HIT` log entries | Higher = fewer redundant API calls |

### Logging Points

The V2 engine logs at these key points:

```
V2ChatService:
  - "V2 chat processing completed" (info) — trajectory steps, tokens, total_time
  - "Error in v2 chat processing" (error) — with full exception

OrchestratorAgent:
  - "Orchestrator completed" (info) — stop_reason, trajectory steps, tokens

ReActLoop:
  - "TOOL CALL: {name}" (info) — every tool execution
  - "TOOL RESULT: {name}" (info) — first 500 chars of result
  - "TOOL CACHE HIT: {name}" (info) — cache hits
  - "LLM call failed" (warning/error) — retries and failures
  - "ReAct iteration complete" (debug) — iteration count, tool count

EventEmitter:
  - "Event emitted" (debug) — every AppSync/DB event
  - "Failed to save event to DB" (error)
  - "Failed to publish event to AppSync" (error)
```

---

## Rollback Plan

### Quick Rollback (< 5 minutes)

If issues are detected after switching `agent_chat_request` to `AgentV2Processor`:

1. **Revert `processor_factory.py`:** Change `agent_chat_request` back to `AgentProcessor`
2. **Deploy:** Standard deployment pipeline
3. **Impact:** No data loss — both V1 and V2 write to the same `chat_events` table

```python
# Rollback: processor_factory.py
_processors = {
    'agent_chat_request': AgentProcessor,       # Reverted to V1
    'agent_chat_v2_request': AgentV2Processor,  # V2 still available
    ...
}
```

### Pre-Deletion Safety

Before deleting V1 code (Phase 3 of migration):

1. **Keep V1 code for at least 2 weeks** after switching all traffic to V2
2. **Monitor error rates, latency, and response quality** during this period
3. **Tag the last commit with V1 code:** `git tag v1-final-state`
4. **Only proceed with deletion** after confirming:
   - Error rate is stable or improved
   - Response latency meets targets (50%+ improvement)
   - No user-reported quality regressions
   - All POC features are ported and functional

### Post-Deletion Recovery

If V1 code has already been deleted and a critical regression is found:

1. **Revert to the tagged commit:** `git revert` to `v1-final-state`
2. **Or:** Check out the tag and cherry-pick only the `processor_factory.py` change
3. **Deploy with V1 restored**

### What Cannot Be Rolled Back

Once dependencies are removed from `pyproject.toml` and the lock file is regenerated:

- Reinstalling LangGraph/DSPy/LangChain is trivial but the lock file will differ
- LangGraph checkpoint tables can be recreated from the checkpoint schema
- No data is lost — chat events and conversation data persist in the same tables regardless of V1 or V2

### Rollback Decision Criteria

Trigger a rollback if any of these occur within the monitoring period:

| Criterion | Threshold |
|-----------|-----------|
| Error rate increase | >2x baseline for 15+ minutes |
| P95 latency increase | >50% increase vs V1 baseline |
| User-reported quality issues | >3 reports in 24 hours |
| LLM API failures | >5% of requests failing after retries |
| Missing responses | Any request that fails silently (no AppSync event) |
