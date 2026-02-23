# V1 → V2 Migration Guide

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Architecture Comparison](#architecture-comparison)
3. [Component-by-Component Mapping](#component-by-component-mapping)
4. [What Makes V2 Better](#what-makes-v2-better)
5. [What Needs to Change](#what-needs-to-change)
6. [POC Features Not Yet in Production V2](#poc-features-not-yet-in-production-v2)
7. [POC Changes Needed for Production](#poc-changes-needed-for-production)
8. [Step-by-Step Migration Checklist](#step-by-step-migration-checklist)

---

## Executive Summary

The Axari AI agent system currently runs **two chat engines side-by-side** in production:

- **V1** — An 11-node LangGraph directed graph pipeline, triggered by `agent_chat_request` SQS messages, processed by `AgentProcessor`
- **V2** — A single ReAct loop (adapted from the axari-poc), triggered by `agent_chat_v2_request` SQS messages, processed by `AgentV2Processor`

**Why we're migrating:** V2 achieves equivalent or better results with 50% fewer LLM calls, ~50% lower token costs, 50-60% faster response times, and a fraction of the code complexity. V1's 11-node pipeline requires 4-7 sequential LLM calls per request where V2 needs 1-3. V2 eliminates the LangGraph, DSPy, and LangChain dependencies entirely, using Claude's native `tool_use` API and extended thinking to replace separate intent classification, date extraction, complexity routing, and planning nodes.

The goal is to **fully replace V1 with V2**, remove all V1-specific code, and port remaining POC features (dashboard, behavior store, meta-tools) into the production V2 engine.

---

## Architecture Comparison

### V1: 11-Node LangGraph Pipeline

**Entry point:** `services/stream.py` → `AppSyncStreamingService.process_chat_with_appsync()`
**Graph definition:** `agents/graph/graph.py` → `ChatGraph`

```
START
  │
  ▼
┌─────────────┐     ┌─────────────────────┐
│ Initializer │────→│ Intent Classifier   │ ← LLM Call #1
└─────────────┘     │ (classify intent)   │
                    └─────────┬───────────┘
                              │
                    ┌─────────┴───────────┐
                    ▼                     ▼
          ┌──────────────────┐  ┌──────────────────┐
          │ Direct No-Tool   │  │ Date Extractor   │ ← LLM Call #2
          │ Response         │  │ (extract dates)  │
          │ ← LLM Call #2   │  └────────┬─────────┘
          └────────┬─────────┘           │
                   │            ┌────────┴─────────┐
                   │            ▼                   ▼
                   │  ┌──────────────┐  ┌──────────────────┐
                   │  │ Clarify      │  │ Chat Mode        │ ← LLM Call #3
                   │  │ Timeframe    │  │ Decision         │
                   │  └──────────────┘  └───────┬──────────┘
                   │                    ┌───────┴───────┐
                   │                    ▼               ▼
                   │         ┌──────────────┐  ┌────────────────┐
                   │         │ Quick Answer │  │ Intent         │ ← LLM Call #4
                   │         │ (ReAct 1-3   │  │ Extractor      │
                   │         │  LLM calls)  │  └───────┬────────┘
                   │         └──────┬───────┘          ▼
                   │                │          ┌────────────────┐
                   │                │          │ Planner        │ ← LLM Call #5
                   │                │          └───────┬────────┘
                   │                │                  ▼
                   │                │          ┌────────────────┐
                   │                │          │ DAG Executor   │ ← LLM Calls #6-N
                   │                │          └───────┬────────┘
                   │                │                  ▼
                   │                │          ┌────────────────┐
                   │                │          │ Report         │ ← LLM Call #N+1
                   │                │          │ Generator      │
                   │                │          └───────┬────────┘
                   ▼                ▼                  ▼
                                   END
```

**V1 uses multiple model tiers** (from `agents/llm/model_config.py`):
- GPT-5-mini for summarization, date extraction
- Claude 3.7 Sonnet for intent classification, intent extraction, direct responses
- Claude Sonnet 4 for planning, business context, chat mode decision, subtask execution
- Gemini 2.5 Pro for subtask grouping, final output, task execution
- Gemini 2.5 Flash for write actions

**V1 state management:** A `ChatState` TypedDict with 20+ fields flows through the graph, accumulating data at each node.

### V2: Single ReAct Loop

**Entry point:** `services/v2_chat.py` → `V2ChatService.process_chat()`
**Core loop:** `engine/agent/react_loop.py` → `ReActLoop`

```
User Message
  │
  ▼
┌──────────────────────────────────────────────┐
│             Orchestrator Agent                │
│                                              │
│  System Prompt ← worker context + persona    │
│  Tools ← integration tools + meta-tools      │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │           ReAct Loop                    │  │
│  │                                        │  │
│  │  Iteration 1:                          │  │
│  │    LLM (extended thinking)             │  │
│  │      Think: classify, plan, decide     │  │
│  │      Act: tool_use[] (parallel)        │  │
│  │                                        │  │
│  │  Iteration 2:                          │  │
│  │    LLM (with tool results)             │  │
│  │      Think: synthesize, check          │  │
│  │      Act: more tools OR final text     │  │
│  │                                        │  │
│  │  ... (up to 15 iterations)             │  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
  │
  ▼
Response
```

**V2 uses a single model** (from `engine/llm/models.py`):
- Claude Sonnet 4 for everything (orchestrator with extended thinking, worker without)

**V2 state management:** The Anthropic messages list IS the state. No custom schema needed.

---

## Component-by-Component Mapping

This section expands on `docs/2-v1-vs-v2-comparison.md` with exact file paths.

### 1. Initializer → V2ChatService + OrchestratorAgent Setup

| Aspect | V1 | V2 |
|--------|-----|-----|
| **File** | `agents/nodes/initializer.py` | `services/v2_chat.py` lines 44-115 |
| **Purpose** | Fetch permissions, build tool list, set state | Load tools, history, worker context, create emitter |
| **DB queries** | Via `IntegrationService` (SQLAlchemy ORM) | Via `IntegrationService.fetch_permission_scope()` |
| **Output** | Populates `ChatState.allowed_tools`, `conversation_count` | Passes `allowed_tools`, `conversation_history`, `worker_context` to orchestrator |

### 2. Intent Classifier → Extended Thinking

| Aspect | V1 | V2 |
|--------|-----|-----|
| **File** | `agents/nodes/intent_classifier_node.py` | No equivalent file — handled by Claude's thinking |
| **LLM** | `agents/llm/intent_classifier.py` using Claude 3.7 Sonnet | Included in orchestrator's thinking budget (4000 tokens) |
| **Output** | `{intent_type, can_fast_path, date_requirement}` — routes to different nodes | Claude internally decides whether to call tools or respond directly |
| **Cost** | Separate LLM call (~500 max tokens) | Zero — folded into the main call |

### 3. Date Extractor → Natural Context in System Prompt

| Aspect | V1 | V2 |
|--------|-----|-----|
| **File** | `agents/nodes/date_extractor_node.py`, `agents/llm/date_extractor.py` | No equivalent — datetime in system prompt |
| **LLM** | GPT-5-mini (separate call) | Zero — Claude reads datetime from system prompt context |
| **Output** | `start_date`, `end_date`, `refined_user_input` | Claude passes dates directly to tool arguments |
| **Cost** | Separate LLM call (~750 max tokens) | Zero |

### 4. Direct No-Tool Response → Natural End Turn

| Aspect | V1 | V2 |
|--------|-----|-----|
| **File** | `agents/nodes/direct_no_tool_response_node.py`, `agents/llm/direct_no_tool_responder.py` | `engine/agent/react_loop.py` line 139-146 |
| **LLM** | Claude 3.7 Sonnet (separate call) | Same orchestrator call — if no `tool_use` blocks, loop exits |
| **Routing** | Explicit route from intent classifier | Implicit — no tool calls means done |

### 5. Clarify Timeframe → System Prompt Default Behavior

| Aspect | V1 | V2 |
|--------|-----|-----|
| **File** | `agents/nodes/clarify_timeframe.py` | `engine/prompts/orchestrator.py` (default time range instruction) |
| **Mechanism** | Separate node that responds asking for dates | System prompt instructs "default to last 24 hours" |

### 6. Chat Mode Decision → Extended Thinking

| Aspect | V1 | V2 |
|--------|-----|-----|
| **File** | `agents/nodes/chat_mode_decision.py` | No equivalent — handled by extended thinking |
| **LLM** | Claude Sonnet 4 (separate call, max 600 tokens) | Zero — Claude adapts iteration count naturally |
| **Output** | Routes to `quick_answer` or `intent_extractor` → `planner` → `dag_executor` | Single loop handles both simple and complex queries |

### 7. Quick Answer → ReAct Loop (1-2 Iterations)

| Aspect | V1 | V2 |
|--------|-----|-----|
| **File** | `agents/nodes/quick_answer.py` + DSPy signatures | `engine/agent/react_loop.py` (same loop, fewer iterations) |
| **LLM** | DSPy `CustomReactAgent` with text-parsed tool calls | Claude native `tool_use` content blocks |
| **Tool exec** | Potentially sequential within DSPy ReAct | Always parallel via `asyncio.gather()` |

### 8. Intent Extractor → Not Needed

| Aspect | V1 | V2 |
|--------|-----|-----|
| **File** | `agents/nodes/intent_node.py`, `agents/llm/intent_extractor.py` | Eliminated |
| **LLM** | Claude 3.7 Sonnet (separate call, max 2000 tokens) | Zero — extended thinking handles intent extraction |

### 9. Planner → Extended Thinking

| Aspect | V1 | V2 |
|--------|-----|-----|
| **File** | `agents/nodes/planner_node.py`, `agents/signatures/planner_signature.py` | Eliminated |
| **LLM** | Claude Sonnet 4 (separate call, max 16000 tokens) | Zero — Claude plans via extended thinking |
| **Output** | `execution_steps` with dependency DAG | Claude determines tool call order across iterations |

### 10. DAG Executor → asyncio.gather()

| Aspect | V1 | V2 |
|--------|-----|-----|
| **File** | `agents/nodes/dag_executor.py`, `agents/nodes/dag_utils.py`, `agents/nodes/run_subtask.py` | `engine/agent/react_loop.py` lines 181-238 |
| **Mechanism** | Topological sort into dependency levels, each level runs in parallel, each subtask is a full `SubtaskReActAgent` with its own LLM calls | All tool calls in one LLM response run via `asyncio.gather()`. Next iteration sees results and calls more tools if needed |
| **Cost** | Each subtask = 2-3 LLM calls | Tools execute directly, no wrapper agent |

### 11. Report Generator → Native Response

| Aspect | V1 | V2 |
|--------|-----|-----|
| **File** | `agents/nodes/report_generator.py`, `agents/llm/final_output_generator.py`, `agents/signatures/final_output.py` | Eliminated — response is the final text block |
| **LLM** | Gemini 2.5 Pro (separate call, max 15000 tokens) | Included in the last ReAct iteration |

### Streaming

| Aspect | V1 | V2 |
|--------|-----|-----|
| **File** | `services/stream.py` → `AppSyncStreamingService` | `engine/streaming/event_emitter.py` → `EventEmitter` |
| **Transport** | AppSync WebSocket | AppSync WebSocket (same) |
| **DB persistence** | Yes — `ChatService.insert_chat_event()` per node | Yes — `ChatService.insert_chat_event()` per event |
| **Event mapping** | Node names mapped to event types (lines 250-269) | `EventEmitter` maps to same event types for backward compat |

---

## What Makes V2 Better

### 1. LLM Call Reduction

| Request Type | V1 LLM Calls | V2 LLM Calls | Reduction |
|-------------|-------------|-------------|-----------|
| Greeting / pleasantry | 2 | 1 | 50% |
| Simple query (1 tool) | 4-5 | 2 | 50-60% |
| Medium query (3 tools) | 5-6 | 2-3 | 50% |
| Complex query (5+ tools) | 7+ | 2-4 | 40-60% |

V1 burns 3-4 LLM calls on overhead (intent classification, date extraction, mode decision, planning) before any tool execution begins. V2 skips all of that — Claude's extended thinking handles classification, planning, and date interpretation in the same call that triggers tool execution.

### 2. Token Cost Savings (~50%)

| Request Type | V1 Total Tokens | V2 Total Tokens | Savings |
|-------------|----------------|----------------|---------|
| Greeting | ~4K (2 calls) | ~2K (1 call) | ~50% |
| Simple query | ~12-15K (4-5 calls) | ~6-8K (2 calls) | ~50% |
| Complex query | ~25-40K (7+ calls) | ~12-20K (3-4 calls) | ~50% |

Every eliminated LLM call saves both its input tokens (repeated system prompt + context) and output tokens. V1 re-sends context to each node; V2 maintains a single conversation.

### 3. Latency Improvement (50-60% Faster)

**V1: Simple query** ("Show my Jira tickets")
```
Initializer:          ~200ms
Intent Classifier:    ~1-2s   (LLM call)
Date Extractor:       ~1-2s   (LLM call)
Chat Mode Decision:   ~1-2s   (LLM call)
Quick Answer ReAct:   ~5-10s  (2-3 LLM calls + tools)
────────────────────────────
Total:                ~8-16s
```

**V2: Same query**
```
Setup:                ~200ms
ReAct Iteration 1:    ~3-5s   (LLM call + parallel tools)
ReAct Iteration 2:    ~2-3s   (LLM call, response)
────────────────────────────
Total:                ~5-8s
```

### 4. Code Complexity Reduction

| Category | V1 Files | V2 Files |
|----------|---------|---------|
| Node implementations | 14 files (`agents/nodes/`) | 0 (handled by ReAct loop) |
| LLM wrappers | 17 files (`agents/llm/`) | 1 file (`engine/llm/client.py`) |
| Signatures/schemas | 12 files (`agents/signatures/`) | 0 (auto-generated) |
| Prompts | 2 files (`agents/prompts/`) | 2 files (`engine/prompts/`) |
| Graph definition | 4 files (`agents/graph/`) | 0 (no graph) |
| Streaming | 1 file + AppSync infra | 1 file (`engine/streaming/event_emitter.py`) |
| **Total** | **~50+ agent-specific files** | **~15 engine files** |
| **Estimated LoC** | **~5000+** | **~1500** |

### 5. Dependency Elimination

| V1-Only Dependency | Purpose | Removed in V2 |
|-------------------|---------|---------------|
| `langgraph` | Graph execution framework | Yes |
| `langchain-core` | Message types, base classes | Yes |
| `langchain-openai` | OpenAI LLM wrapper | Yes |
| `dspy` | Signature-based LLM programming | Yes |
| `langgraph-checkpoint-postgres` | Graph state checkpointing | Yes |
| `langchain-text-splitters` | Document chunking | Yes |
| `langchain-google-genai` | Google Gemini LLM wrapper | Yes |
| `google-genai` | Google AI SDK | Yes |

### 6. Native tool_use vs Text Parsing

V1 uses DSPy's text-based ReAct which requires parsing tool calls from natural language output (regex matching `Action: tool_name`, `Action Input: {...}`). This is fragile and error-prone.

V2 uses Claude's native `tool_use` content blocks — structured JSON returned directly by the API. No parsing needed, no format errors possible.

### 7. Extended Thinking Replaces 4 Nodes

Claude's extended thinking (4000 token budget) replaces what V1 needed four separate LLM calls for:

| V1 Node (Separate LLM Call) | V2 Equivalent |
|-----------------------------|---------------|
| Intent Classifier | Extended thinking: "User wants X, I should..." |
| Date Extractor | Extended thinking: "Today is Feb 17, user said 'this week', so..." |
| Chat Mode Decision | Extended thinking: "This needs 3 tools, I'll call them directly" |
| Planner | Extended thinking: "I'll first fetch A and B in parallel, then analyze" |

---

## What Needs to Change

### V1 Code to Remove

The entire `agents/` directory tree and V1-specific services:

```
agents/
├── graph/
│   ├── graph.py              # ChatGraph (LangGraph definition)
│   ├── base.py               # BaseGraph class
│   └── responsibility_graph.py  # Responsibility graph (keep? see note)
├── nodes/
│   ├── initializer.py
│   ├── intent_classifier_node.py
│   ├── date_extractor_node.py
│   ├── direct_no_tool_response_node.py
│   ├── clarify_timeframe.py
│   ├── chat_mode_decision.py
│   ├── quick_answer.py
│   ├── intent_node.py
│   ├── planner_node.py
│   ├── dag_executor.py
│   ├── dag_utils.py
│   ├── run_subtask.py
│   ├── report_generator.py
│   └── wait.py
├── llm/
│   ├── model_config.py        # Multi-model config (7+ models)
│   ├── intent_classifier.py
│   ├── date_extractor.py
│   ├── direct_no_tool_responder.py
│   ├── intent_extractor.py
│   ├── final_output_generator.py
│   ├── business_context_refiner.py
│   ├── subtask_grouper.py
│   ├── integration_data_summarizer.py
│   ├── configure_llm.py
│   ├── dynamic_ui_output_generator.py
│   ├── write_action_generator.py
│   ├── responsibility_recommendation.py
│   ├── governance_compliance_summarizer.py
│   ├── team_structure_summarizer.py
│   ├── slack_data_summarizer.py
│   └── rag_query_refiner.py
├── signatures/
│   ├── planner_signature.py
│   ├── subtask_signature.py
│   ├── subtask_executor.py
│   ├── sequential_subtask_executor.py
│   ├── quick_answer_signature.py
│   ├── final_output.py
│   ├── intent_signature.py
│   ├── group_subtasks_signature.py
│   ├── business_context_refiner_signature.py
│   ├── governance_compliance_summarizer_signature.py
│   ├── rss_signature.py
│   └── team_structure_summarizer_signature.py
├── prompts/
│   ├── business_context_to_prompt.py
│   └── intent_to_prompt.py
└── models/
    ├── __init__.py
    └── state.py (ChatState, etc.)
```

**Additional V1 files to remove:**

| File | Reason |
|------|--------|
| `services/stream.py` | V1's `AppSyncStreamingService` — replaced by `services/v2_chat.py` |
| `core/queue_consumer/processors/agent_processor.py` | V1's `AgentProcessor` — replaced by `agent_v2_processor.py` |
| `database/checkpointer.py` (if exists) | LangGraph checkpointer manager — no longer needed |

**Important:** The responsibility graphs (`agents/graph/responsibility_graph.py`, `agents/graph/responsibility/`) are still used by `ResponsibilityProcessor` for playbook execution. **Do NOT remove these.** Only the chat-specific graph (`ChatGraph` in `agents/graph/graph.py`) and chat-specific nodes/LLM wrappers are removed. The `agents/graph/base.py` may also be needed by the responsibility graphs — verify before removing.

### SQS Message Type Routing

**Current state** (`core/queue_consumer/processor_factory.py`):

```python
_processors = {
    'agent_chat_request': AgentProcessor,      # V1
    'agent_chat_v2_request': AgentV2Processor,  # V2
    ...
}
```

**After migration:**

```python
_processors = {
    'agent_chat_request': AgentV2Processor,     # V2 handles both
    'agent_chat_v2_request': AgentV2Processor,  # Backward compat
    ...
}
```

Phase 1: Point both message types to `AgentV2Processor`. Phase 2: Update the frontend/API to only send `agent_chat_request`. Phase 3: Remove the `agent_chat_v2_request` entry.

### Processor Factory Update

In `core/queue_consumer/processor_factory.py`:
1. Remove the `AgentProcessor` import
2. Map `agent_chat_request` to `AgentV2Processor`
3. Keep `agent_chat_v2_request` temporarily for backward compatibility

### Dependencies Cleanup

Remove from `pyproject.toml`:

```
langgraph>=0.2.39
langchain-core>=0.3.0
dspy
langchain-openai
langgraph-checkpoint-postgres==2.0.24
langchain-text-splitters>=0.3.11
google-genai>=1.9.0
langchain-google-genai>=2.1.12
```

**Keep:**
- `anthropic` — used by V2's LLM client
- `sqlalchemy`, `asyncpg` — database access
- `aioboto3`, `boto3` — SQS messaging
- `structlog` — logging
- `fastapi`, `uvicorn` — API server
- `pydantic` — data validation
- `netra-sdk` — observability (already integrated in V2)

---

## POC Features Not Yet in Production V2

The following features exist in the axari-poc but have not yet been ported to the production V2 engine:

### 1. Dashboard (3-Column Grid)

**POC file:** `axari-poc/engine/context/dashboard.py`
**What it does:** Queries the database for the latest successful playbook executions (Morning Brief, Commitment Radar, Meeting Prep) and returns structured data for a 3-column dashboard grid.
**Production adaptation:** The DB queries are already production-compatible (uses the same `playbook_executions` and `playbook_execution_suggestions` tables). Needs an API endpoint and the `V2ChatService` would need to wire it up. The POC uses raw SQLAlchemy engine; production should use `SessionContext` for consistency.

### 2. Behavior Store

**POC file:** `axari-poc/engine/memory/behavior_store.py`
**What it does:** Tracks user interaction patterns (actions used, time-of-day usage, dashboard clicks) in-memory. Computes behavioral profiles for personalized greetings, reordered quick-action buttons, and proactive nudges.
**Production adaptation:** Replace in-memory storage with a database-backed implementation. Add tenant isolation. Consider privacy implications of behavior tracking.

### 3. Meta-Tools: take_notes, add_reminder, trigger_responsibility

**POC file:** `axari-poc/tools/meta_tools.py` (defines `take_notes`, `add_reminder`), `axari-poc/engine/context/playbook_trigger.py` (defines `trigger_responsibility`)
**What they do:**
- `take_notes` — Saves notes to the UI's Notes panel (append or replace modes)
- `add_reminder` — Adds reminders with optional due dates to the Reminders panel
- `trigger_responsibility` — Triggers playbook executions from chat via SQS

**Production adaptation:** The production V2 currently only has `analyze` and `delegate_subtask` meta-tools (`engine/tools/meta_tools.py`). These three need to be added. `trigger_responsibility` already uses production-compatible DB queries and SQS messaging. `take_notes` and `add_reminder` need a persistence layer (the POC streams them via SSE to the frontend's localStorage — production would need DB persistence + AppSync delivery).

### 4. Playbook Trigger from Chat

**POC file:** `axari-poc/engine/context/playbook_trigger.py`
**What it does:** Full lifecycle: query playbooks → fuzzy-match name → check status → create execution record → send SQS message. Already uses raw SQL against the production schema.
**Production adaptation:** Replace raw SQLAlchemy engine with `SessionContext`. Wire into the orchestrator as a meta-tool. Already sends the correct SQS message format for `ResponsibilityProcessor`.

### 5. Worker Context (POC Version)

**POC file:** `axari-poc/engine/context/worker_context.py`
**What it does:** Queries AI workers, playbooks, and today's events. Builds a markdown `<worker_knowledge>` section for the system prompt.
**Production status:** Already ported — `engine/context/worker_context.py` exists in production. The POC version uses a raw engine; production uses `SessionContext`.

### 6. Responsibility Execution via Chat

**POC file:** `axari-poc/config/responsibility_instructions.py`
**What it does:** Maps playbook names to execution instructions (morning brief, commitment radar, meeting prep). Used by an execute endpoint that runs playbooks using the agent's own tools.
**Production adaptation:** This is a secondary feature. The primary trigger mechanism (`playbook_trigger.py` → SQS → `ResponsibilityProcessor`) is more appropriate for production. These instructions could be used for a "preview" mode where the agent summarizes what a playbook would do.

### 7. Conversation Store (In-Memory)

**POC file:** `axari-poc/engine/memory/conversation_store.py`
**What it does:** In-memory conversation history storage with `load_messages()`, `save_exchange()`, `get_state()`, `save_state()`.
**Production status:** Not needed — production V2 already loads conversation history from the database via `ChatService.get_messages_by_conversation()` and `ChatService.get_chat_events_by_message()` in `V2ChatService._load_conversation_history()`.

---

## POC Changes Needed for Production

### Already Done in Production V2

These POC concerns are already resolved in the production V2 implementation:

| Area | POC (SSE/In-Memory) | Production V2 (Already Done) |
|------|---------------------|------------------------------|
| **Streaming** | SSE via `asyncio.Queue` | AppSync WebSocket via `EventEmitter` → `AppSyncClient` |
| **Event persistence** | Not persisted | Saved to DB via `ChatService.insert_chat_event()` |
| **Conversation history** | In-memory `ConversationStore` | DB-backed via `ChatService` |
| **Observability** | Python logging only | Netra SDK integration (`@workflow` decorator, session/tenant tracking) |
| **Tool permissions** | `tenant_id` in request | `IntegrationService.fetch_permission_scope()` → filtered tool list |
| **LLM client** | Raw `AsyncAnthropic` | `LLMClient` with provider abstraction (OpenRouter or direct Anthropic) |

### Still Needs to Be Done

| Area | Current State | What's Needed |
|------|---------------|---------------|
| **Dashboard API** | POC has `/v1/dashboard` endpoint | Add endpoint to production API, wire `dashboard.py` queries with `SessionContext` |
| **take_notes / add_reminder** | POC-only meta-tools | Port to `engine/tools/meta_tools.py`, add AppSync delivery for panel events |
| **trigger_responsibility** | POC-only meta-tool | Port to production, integrate with `engine/tools/meta_tools.py` |
| **Behavior store** | POC in-memory | Design DB schema, implement tracking, add API endpoints |
| **Authentication** | Missing in POC, present in prod (JWT via SQS message context) | No change needed — production already authenticates via the SQS message pipeline |
| **Rate limiting** | Missing in both | Add per-tenant token budgets and request rate limiting |
| **Frontend** | POC: single HTML file; Prod: separate React app | No action — production frontend is separate |
| **Response streaming** | POC: token-by-token SSE; Prod: complete response only | Consider adding incremental AppSync updates for long responses |

---

## Step-by-Step Migration Checklist

### Phase 1: Redirect V1 Traffic to V2

- [ ] In `processor_factory.py`, point `agent_chat_request` to `AgentV2Processor`
- [ ] Monitor for regressions (compare response quality, latency, error rates)
- [ ] Keep V1 code in place as fallback (feature flag if needed)
- [ ] Update frontend to send `agent_chat_v2_request` for new conversations

### Phase 2: Port POC Features

- [ ] Port `trigger_responsibility` meta-tool to `engine/tools/meta_tools.py`
  - Replace raw SQLAlchemy engine with `SessionContext`
  - Wire into `OrchestratorAgent.handle_message()` tool assembly
- [ ] Port `take_notes` and `add_reminder` meta-tools
  - Add `emit_panel_note()` and `emit_reminder()` methods to `EventEmitter`
  - Add AppSync delivery for these event types
- [ ] Port `dashboard.py` to `engine/context/dashboard.py`
  - Replace raw engine with `SessionContext`
  - Add API endpoint for dashboard data
- [ ] Port `behavior_store.py` with DB-backed persistence
  - Design database schema for behavior events
  - Add API endpoints for profile retrieval
- [ ] Port `responsibility_instructions.py` to `config/`

### Phase 3: Remove V1 Code

- [ ] Delete chat-specific agent code:
  - `agents/nodes/` (all 14 node files)
  - `agents/llm/` (all 17 LLM wrapper files)
  - `agents/signatures/` (all 12 signature files)
  - `agents/prompts/` (both prompt files)
  - `agents/graph/graph.py` (ChatGraph only)
  - `agents/models/` (`ChatState` in `state.py`) — verify no other code references it
- [ ] **Keep responsibility graph code** (used by `ResponsibilityProcessor`):
  - `agents/graph/responsibility_graph.py`
  - `agents/graph/responsibility/` (all files)
  - `agents/graph/base.py` (if needed by responsibility graphs)
  - Any `agents/llm/` or `agents/nodes/` files used by responsibility execution
- [ ] Delete `services/stream.py` (`AppSyncStreamingService`)
- [ ] Delete `core/queue_consumer/processors/agent_processor.py`
- [ ] Remove `AgentProcessor` import from `processor_factory.py`
- [ ] Delete `database/checkpointer.py` (LangGraph checkpoint manager)

### Phase 4: Clean Up Dependencies

- [ ] Remove from `pyproject.toml`:
  - `langgraph`, `langchain-core`, `langchain-openai`, `dspy`
  - `langgraph-checkpoint-postgres`
  - `langchain-text-splitters`, `langchain-google-genai`, `google-genai`
- [ ] Run `uv sync` to clean the lock file
- [ ] Verify all tests pass without removed dependencies
- [ ] Check for any remaining imports of removed packages

### Phase 5: Finalize

- [ ] Remove `agent_chat_v2_request` from processor factory (keep only `agent_chat_request`)
- [ ] Update API documentation
- [ ] Update deployment scripts (smaller container, fewer dependencies)
- [ ] Performance benchmarking: confirm latency and cost improvements match expectations
- [ ] Update monitoring dashboards for V2 metrics
