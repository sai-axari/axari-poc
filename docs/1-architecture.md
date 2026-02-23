# Axari PoC — Architecture Document

## Table of Contents

1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [Directory Structure](#directory-structure)
4. [Core Components](#core-components)
   - [API Layer](#api-layer)
   - [Orchestrator Agent](#orchestrator-agent)
   - [ReAct Loop Engine](#react-loop-engine)
   - [Worker Agent](#worker-agent)
   - [LLM Client](#llm-client)
   - [Streaming & Event Emitter](#streaming--event-emitter)
   - [Memory Layer](#memory-layer)
   - [Tool System](#tool-system)
   - [Context Layer](#context-layer)
   - [Frontend (Chat UI)](#frontend-chat-ui)
5. [Data Flow](#data-flow)
6. [Streaming Architecture](#streaming-architecture)
7. [Tool Execution Model](#tool-execution-model)
8. [Configuration](#configuration)
9. [Infrastructure](#infrastructure)

---

## Overview

The Axari PoC is a **single-agent orchestrator** built on Claude's native `tool_use` API with extended thinking. It replaces the previous 11-node LangGraph pipeline with a unified ReAct (Reasoning + Acting) loop that handles the entire chat flow — from intent classification to tool execution to response synthesis — in a single, adaptive agent.

**Key design principles:**

- **Single agent, adaptive complexity** — One ReAct loop handles everything from simple greetings (0 tool calls) to complex cross-integration reports (10+ parallel tool calls)
- **Native Claude tool_use** — No text parsing; Claude returns structured `tool_use` content blocks
- **Extended thinking** — Claude's internal reasoning replaces explicit intent classification, date extraction, and planning nodes
- **Parallel tool execution** — Independent tool calls execute concurrently via `asyncio.gather()`
- **Real-time streaming** — Server-Sent Events (SSE) stream thinking, tool progress, and response chunks to the UI

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                           Frontend (Chat UI)                        │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────────────────┐  │
│  │ Chat     │  │ Dashboard    │  │ Detail Panel                 │  │
│  │ Messages │  │ (3-col grid) │  │ ┌──────┬─────────┬───────┐  │  │
│  │          │  │ • Priorities │  │ │ Data │Reminders│ Notes │  │  │
│  │          │  │ • Commits   │  │ │      │         │       │  │  │
│  │          │  │ • Meetings  │  │ └──────┴─────────┴───────┘  │  │
│  └──────────┘  └──────────────┘  └──────────────────────────────┘  │
│                    SSE Stream ↕ REST API                            │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        FastAPI Server (:8100)                       │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ API Router                                                    │  │
│  │  POST /v1/chat/stream  ──→  SSE streaming endpoint            │  │
│  │  POST /v1/chat/invoke  ──→  Synchronous endpoint              │  │
│  │  GET  /v1/dashboard    ──→  Dashboard data                    │  │
│  │  GET  /                ──→  Chat UI (static HTML)             │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│  ┌───────────────────────────▼──────────────────────────────────┐  │
│  │ Orchestrator Agent                                            │  │
│  │  ┌─────────────┐  ┌────────────┐  ┌───────────────────┐     │  │
│  │  │ System      │  │ Tool       │  │ Meta-Tools        │     │  │
│  │  │ Prompt      │  │ Registry   │  │ • analyze         │     │  │
│  │  │ (persona +  │  │ (integra-  │  │ • delegate_subtask│     │  │
│  │  │  context )  │  │  tions)    │  │ • take_notes      │     │  │
│  │  └─────────────┘  └────────────┘  │ • add_reminder    │     │  │
│  │                                   │ • trigger_resp.   │     │  │
│  │                                   └───────────────────┘     │  │
│  │  ┌──────────────────────────────────────────────────────┐   │  │
│  │  │                   ReAct Loop                         │   │  │
│  │  │  ┌─────────┐  ┌──────────┐  ┌────────────────────┐  │    │  │
│  │  │  │ LLM Call│──│ Parse    │──│ Execute Tools      │  │    │  │
│  │  │  │ (stream)│  │ Response │  │ (asyncio.gather)   │  │    │  │
│  │  │  └─────────┘  └──────────┘  └────────────────────┘  │    │  │
│  │  │       ↑                              │               │    │  │
│  │  │       └──────────────────────────────┘               │    │  │
│  │  │                (loop until done)                      │    │  │
│  │  └──────────────────────────────────────────────────────┘    │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│  ┌───────────────────────────▼──────────────────────────────────┐  │
│  │ Supporting Services                                           │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │  │
│  │  │ Conversation │  │ Context      │  │ Tool Result       │  │  │
│  │  │ Store        │  │ Manager      │  │ Cache (TTL)       │  │  │
│  │  │ (in-memory)  │  │ (100K tok)   │  │ (5min, 100 max)   │  │  │
│  │  └──────────────┘  └──────────────┘  └───────────────────┘  │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴──────────┐
                    ▼                    ▼
         ┌──────────────────┐  ┌──────────────────┐
         │   PostgreSQL     │  │   OpenRouter      │
         │   (core-svc DB)  │  │   (Claude API)    │
         │   • integrations │  │   • claude-sonnet  │
         │   • playbooks    │  │   • ext. thinking  │
         │   • executions   │  │                    │
         └──────────────────┘  └──────────────────┘
                    │
                    ▼
         ┌──────────────────┐
         │   Localstack     │
         │   (SQS)          │
         │   • playbook     │
         │     execution    │
         │     queue        │
         └──────────────────┘
```

---

## Directory Structure

```
axari-poc/
├── main.py                          # FastAPI entry point, registers tools on startup
├── requirements.txt                 # Python dependencies
├── .env                             # Environment variables (DB, API keys, SQS)
│
├── api/
│   ├── models.py                    # ChatRequest / ChatResponse Pydantic models
│   └── router.py                    # API routes: /v1/chat/stream, /v1/chat/invoke, /v1/dashboard
│
├── config/
│   ├── models.py                    # MODEL_CONFIGS: orchestrator (sonnet + thinking), worker (sonnet)
│   └── settings.py                  # Environment-based settings (API keys, limits, cache TTL)
│
├── engine/
│   ├── agent/
│   │   ├── orchestrator.py          # OrchestratorAgent: wires tools, prompts, and ReAct loop
│   │   ├── react_loop.py            # ReActLoop: core iteration engine with parallel tool execution
│   │   └── worker.py               # WorkerAgent: lightweight agent for delegate_subtask
│   │
│   ├── context/
│   │   ├── dashboard.py             # fetch_dashboard_data(): queries latest playbook results
│   │   ├── playbook_trigger.py      # trigger_responsibility(): runs playbooks from chat via SQS
│   │   └── worker_context.py        # fetch_worker_context(): injects AI Worker knowledge into prompt
│   │
│   ├── llm/
│   │   ├── client.py                # LLMClient: AsyncAnthropic via OpenRouter, streaming support
│   │   └── structured_output.py     # Structured output helpers
│   │
│   ├── memory/
│   │   ├── context_manager.py       # ContextManager: token budget truncation (100K tokens)
│   │   ├── conversation_store.py    # ConversationStore: in-memory conversation history
│   │   └── tool_cache.py            # ToolResultCache: TTL cache (5min, SHA256 keys)
│   │
│   └── streaming/
│       └── event_emitter.py         # EventEmitter: SSE event queue for real-time UI updates
│
├── prompts/
│   ├── orchestrator.py              # ORCHESTRATOR_SYSTEM_PROMPT: Axari persona, Eve/Janice team
│   └── worker.py                    # WORKER_SYSTEM_PROMPT: focused execution prompt
│
├── tools/
│   ├── registry.py                  # TOOL_REGISTRY: global tool store, schema/callable lookup
│   ├── connected.py                 # get_connected_integration_keys(): queries DB for tenant tools
│   ├── converter.py                 # function_to_tool_schema(): auto-generates Anthropic schemas
│   ├── integrations.py              # register_all_integration_tools(): scans integration modules
│   └── meta_tools.py               # analyze, delegate_subtask tool definitions
│
├── static/
│   └── index.html                   # Full chat UI: chat, dashboard, detail panel (Data/Reminders/Notes)
│
└── tests/
    └── test_chat.py                 # Integration tests
```

---

## Core Components

### API Layer

**File:** `api/router.py`

The FastAPI router exposes four endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/chat/stream` | POST | Primary chat endpoint — streams SSE events in real-time |
| `/v1/chat/invoke` | POST | Synchronous chat endpoint — returns complete response |
| `/v1/dashboard` | GET | Fetches latest playbook execution data for the dashboard |
| `/` | GET | Serves the static chat UI |

**Shared singletons** (initialized once, reused across requests):
- `ConversationStore` — in-memory conversation history
- `ContextManager` — token budget enforcement
- `ToolResultCache` — cross-request tool result deduplication

**Request flow (streaming):**

```
POST /v1/chat/stream
    │
    ├─→ Load conversation history from ConversationStore
    ├─→ Truncate to token budget via ContextManager
    ├─→ Create EventEmitter for this conversation
    ├─→ Create OrchestratorAgent
    ├─→ Launch orchestrator in asyncio.Task
    ├─→ Stream events from EventEmitter as SSE
    ├─→ After completion: emit trajectory + token_usage
    └─→ Save exchange to ConversationStore
```

**Request model (`ChatRequest`):**

```python
class ChatRequest(BaseModel):
    message: str                      # User's message
    conversation_id: str              # Unique conversation identifier
    tenant_id: str                    # Tenant ID for scoped tool access
    user_id: str                      # User ID
    user_name: str = ""               # Display name for persona context
    org_name: str = ""                # Organization name
    user_timezone: str = "UTC"        # User's timezone
    allowed_tools: list[str] = []     # Override: allowed tool names
    integration_constraints: str = "" # JSON constraints per integration
```

---

### Orchestrator Agent

**File:** `engine/agent/orchestrator.py`

The orchestrator is the **single entry point** for all chat processing. It replaces all 11 LangGraph nodes from the v1 system.

**Responsibilities:**

1. **Tool assembly** — Queries connected integrations, builds tool schemas + callables
2. **Meta-tool injection** — Adds `analyze`, `delegate_subtask`, `take_notes`, `add_reminder`, `trigger_responsibility`
3. **System prompt construction** — Injects persona, context, worker knowledge, and available tools
4. **ReAct loop execution** — Runs the agentic loop with streaming callbacks

```
handle_message()
    │
    ├─→ get_connected_integration_keys(tenant_id)
    ├─→ Build tool_schemas + tool_callables from registry
    ├─→ Inject meta-tools (analyze, delegate_subtask, take_notes, etc.)
    ├─→ fetch_worker_context(tenant_id)  →  AI Worker knowledge
    ├─→ build_orchestrator_prompt(...)   →  Full system prompt
    ├─→ ReActLoop.run(messages, callbacks)
    └─→ Return AgentResponse(response, trajectory, token_usage)
```

**Meta-tools registered by the orchestrator:**

| Tool | Purpose |
|------|---------|
| `analyze` | Structured analysis on collected data |
| `delegate_subtask` | Spawns a WorkerAgent for multi-step iterative subtasks |
| `take_notes` | Saves notes to the UI's Notes panel tab |
| `add_reminder` | Adds reminders/commitments to the UI's Reminders panel tab |
| `trigger_responsibility` | Triggers a playbook execution from chat (via SQS) |

---

### ReAct Loop Engine

**File:** `engine/agent/react_loop.py`

The core agentic iteration engine. This is the heart of the PoC.

```
┌─────────────────────────────────────────────────────────┐
│                     ReAct Loop                           │
│                                                          │
│  for iteration in range(max_iterations):     # max: 15  │
│    │                                                     │
│    ├─→ LLM streaming call (with extended thinking)       │
│    │     • Stream thinking_delta → on_thinking()         │
│    │     • Stream text_delta → on_response_chunk()       │
│    │     • Get final message                             │
│    │                                                     │
│    ├─→ Parse response content blocks:                    │
│    │     • thinking blocks (internal reasoning)          │
│    │     • text blocks (response text)                   │
│    │     • tool_use blocks (tool calls)                  │
│    │                                                     │
│    ├─→ If NO tool calls → DONE (return final_text)       │
│    │                                                     │
│    ├─→ If tool calls found:                              │
│    │     • Clear streamed text (it was intermediate)      │
│    │     • Add assistant message to conversation          │
│    │     • Execute ALL tool calls in parallel             │
│    │       └─→ asyncio.gather(*[run_one(tc) ...])        │
│    │     • Add tool results to conversation               │
│    │     • Continue loop                                  │
│    │                                                     │
│    └─→ If max_iterations reached → return partial result │
└─────────────────────────────────────────────────────────┘
```

**Key features:**

- **Streaming callbacks** — `on_thinking`, `on_response_chunk`, `on_tool_call`, `on_tool_result`, `on_response_clear`
- **Parallel execution** — All tool calls in a single LLM response run concurrently
- **Tool result caching** — Checks `ToolResultCache` before execution; skips meta-tools
- **Argument coercion** — Automatically converts string args from LLM to typed Python values (int, float, bool, datetime)
- **Observation truncation** — Full results stream to UI; truncated to `MAX_OBSERVATION_LENGTH` (10K chars) for LLM context
- **Error isolation** — Individual tool failures don't crash the loop; errors reported as tool results

---

### Worker Agent

**File:** `engine/agent/worker.py`

A lightweight ReAct agent spawned by the `delegate_subtask` meta-tool. Used for complex subtasks requiring iterative multi-step reasoning.

**Differences from Orchestrator:**

| Aspect | Orchestrator | Worker |
|--------|-------------|--------|
| Extended thinking | Yes (4000 token budget) | No |
| Max iterations | 15 | 8 |
| Streaming callbacks | Full (thinking, tool calls, response) | None |
| Tool set | All connected + meta-tools | Subset relevant to subtask |
| System prompt | Full Axari persona | Focused execution prompt |

---

### LLM Client

**File:** `engine/llm/client.py`

Unified async LLM client using the Anthropic SDK routed through OpenRouter.

```python
class LLMClient:
    def __init__(self):
        self.anthropic = AsyncAnthropic(
            api_key=OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api",
        )
```

**Two call patterns:**

1. **`create_message()`** — Non-streaming; returns complete `Message` response
2. **`create_message_stream()`** — Returns async streaming context manager for SSE

**Model configuration** (from `config/models.py`):

```python
MODEL_CONFIGS = {
    "orchestrator": {
        "model": "anthropic/claude-sonnet-4",
        "max_tokens": 16000,
        "temperature": 1.0,  # Required for extended thinking
        "thinking": {"type": "enabled", "budget_tokens": 4000},
    },
    "worker": {
        "model": "anthropic/claude-sonnet-4",
        "max_tokens": 10000,
        "temperature": 0,
    },
}
```

---

### Streaming & Event Emitter

**File:** `engine/streaming/event_emitter.py`

The `EventEmitter` bridges the agent loop and the SSE response stream. Events are queued in-memory and consumed by the FastAPI streaming response generator.

```
Agent Loop                    EventEmitter                    SSE Stream
    │                              │                              │
    ├─ thinking text ──→ emit_thinking() ──→ queue ──→ yield ──→ UI
    ├─ tool call ──────→ emit_tool_call() ──→ queue ──→ yield ──→ UI
    ├─ tool result ────→ emit_tool_result() ─→ queue ──→ yield ──→ UI
    ├─ response chunk ─→ emit_response_chunk() → queue → yield → UI
    ├─ response clear ─→ emit_response_clear() → queue → yield → UI
    ├─ panel note ─────→ emit_panel_note() ──→ queue ──→ yield ──→ UI
    ├─ reminder ───────→ emit_reminder() ────→ queue ──→ yield ──→ UI
    └─ complete ───────→ put(None) ──────────→ stops iteration
```

**Event types emitted:**

| Event | Data | Purpose |
|-------|------|---------|
| `thinking` | `{text}` | Extended thinking text |
| `node_planner` | `{planning_steps}` | Tool call progress (backward-compatible format) |
| `tool_result` | `{tool, args, result}` | Full un-truncated tool result for detail panel |
| `response_chunk` | `{text}` | Streaming response text delta |
| `response_clear` | `{}` | Clear partially-streamed text (tool calls found) |
| `response` | `{text}` | Complete final response |
| `panel_note` | `{content, mode}` | Notes for the panel's Notes tab |
| `reminder` | `{title, due, context}` | Reminder for the panel's Reminders tab |
| `trajectory` | `[...]` | Full agent trajectory (after completion) |
| `token_usage` | `{input, output, elapsed_seconds}` | Token usage stats |

---

### Memory Layer

#### ConversationStore (`engine/memory/conversation_store.py`)

In-memory conversation history storage (PoC implementation; production would use PostgreSQL).

- **`load_messages(conversation_id, limit=20)`** — Returns last N messages in Anthropic format
- **`save_exchange(conversation_id, user_msg, assistant_msg)`** — Saves a user-assistant pair
- **`get_state() / save_state()`** — Persist arbitrary state between turns

#### ContextManager (`engine/memory/context_manager.py`)

Prevents context window overflow by truncating conversation history.

- **Token budget:** 100,000 tokens (estimated at 4 chars/token)
- **Strategy:** Remove oldest messages first, always preserve the last message
- **Applied at:** Request entry in `api/router.py`, before passing history to orchestrator

#### ToolResultCache (`engine/memory/tool_cache.py`)

TTL-based in-memory cache for tool results. Prevents redundant API calls when the same tool+args are called within a short window.

- **TTL:** 300 seconds (5 minutes)
- **Max entries:** 100
- **Key generation:** SHA256 hash of `tool_name + json.dumps(args, sort_keys=True)`
- **Excluded tools:** `analyze`, `delegate_subtask` (non-deterministic meta-tools)
- **Eviction:** Lazy expiration on read + oldest-entry eviction at capacity

---

### Tool System

#### Tool Registry (`tools/registry.py`)

Global dictionary mapping tool names to `ToolEntry(func, schema)` pairs.

```python
TOOL_REGISTRY: dict[str, ToolEntry] = {}

def register_tool(name, func, schema=None):
    # Sanitizes name (: → __), auto-generates schema if needed

def get_schemas_for(names) -> list[dict]:      # Anthropic-format schemas
def get_callables_for(names) -> dict:           # name → async callable
def list_tools_for_integrations(keys) -> list:  # Filter by integration prefix
```

**Tool name convention:** `integration__method_name` (e.g., `microsoft_outlook__fetch_outlook_emails`)

#### Connected Integrations (`tools/connected.py`)

Queries the core-svc database for the tenant's connected integrations:

```sql
SELECT i.key FROM integrations i
JOIN organization_integrations oi ON oi.integration_id = i.id
WHERE oi.tenant_id = :tid
```

Returns integration keys like `["jira", "microsoft_outlook", "microsoft_teams"]`.

#### Integration Tool Registration (`tools/integrations.py`)

On startup (`main.py → register_all_integration_tools()`), scans integration modules and registers all discovered tools in the global registry.

#### Schema Auto-Generation (`tools/converter.py`)

Converts Python async functions into Anthropic `tool_use` schemas by inspecting function signatures, type hints, and docstrings.

---

### Context Layer

#### Worker Context (`engine/context/worker_context.py`)

Queries the core-svc database for AI Worker configurations and injects them into the orchestrator's system prompt.

**Data fetched:**
- AI Workers (name, role, description)
- Worker contexts (templatized business context)
- Playbooks (name, description, status: active/inactive)
- Latest playbook events (today's run summaries)

**Output:** Markdown string appended as `<worker_knowledge>` to the system prompt.

#### Dashboard Data (`engine/context/dashboard.py`)

Fetches the latest completed playbook execution results for the chat dashboard.

**Data returned:**
- `morning_brief` — Latest Morning Brief summary + result JSON
- `commitments` — Latest Commitments Radar suggestions (titles, descriptions, due dates)
- `meeting_prep` — Latest Meeting Prep summary + result JSON
- `last_updated` — Most recent execution timestamp

#### Playbook Trigger (`engine/context/playbook_trigger.py`)

Triggers playbook executions from chat:

```
trigger_responsibility(tenant_id, responsibility_name)
    │
    ├─→ Query all playbooks for tenant
    ├─→ Fuzzy-match by name
    ├─→ Check status (must be "active")
    ├─→ Create playbook_execution record (status: pending)
    └─→ Send SQS message to execution queue
```

**SQS message format:**
```json
{
    "type": "playbook_execution",
    "execution_id": "uuid",
    "playbook_id": "uuid",
    "tenant_id": "uuid",
    "execution_metadata": {"source": "chat"},
    "execution_mode": "parallel"
}
```

---

### Frontend (Chat UI)

**File:** `static/index.html`

A single-page application with three main areas:

```
┌─────────────────────────────────────────────────────────────────┐
│ Header (Axari branding, New Chat, Panel toggle, Settings)       │
├────────────────────────────────┬────────────────────────────────┤
│          Chat Column           │       Detail Panel (420px)     │
│  ┌──────────────────────────┐  │  ┌────────────────────────┐  │
│  │ Dashboard (3-col grid)   │  │  │ Tabs: Data|Reminders|  │  │
│  │ • Top Priorities         │  │  │        Notes           │  │
│  │ • Commitments            │  │  │                        │  │
│  │ • Meeting Prep           │  │  │ [Content per tab]      │  │
│  ├──────────────────────────┤  │  │                        │  │
│  │ Chat Messages            │  │  │                        │  │
│  │ • User messages          │  │  │                        │  │
│  │ • AI responses           │  │  │                        │  │
│  │ • Thinking steps         │  │  │                        │  │
│  │ • Trajectory toggle      │  │  │                        │  │
│  ├──────────────────────────┤  │  └────────────────────────┘  │
│  │ Input Area               │  │                                │
│  │ [textarea] [Send button] │  │                                │
│  └──────────────────────────┘  │                                │
└────────────────────────────────┴────────────────────────────────┘
```

**Key frontend features:**

1. **SSE streaming** — Real-time display of thinking steps, tool progress, and response text
2. **Dashboard** — Auto-loads latest playbook data on page load via `/v1/dashboard`
3. **Detail panel** — Three tabs:
   - **Data** — Auto-populates with collapsible tool result cards as they stream in
   - **Reminders** — Tracks commitments from Commitment Radar + user-added reminders
   - **Notes** — Persistent notepad (localStorage per conversation)
4. **Responsive layout** — Side-by-side on wide screens (>1200px), overlay on narrow screens
5. **Markdown rendering** — All AI responses and tool results rendered with markdown support

---

## Data Flow

### Complete Request Lifecycle

```
User types message
    │
    ▼
Frontend: POST /v1/chat/stream {message, conversation_id, tenant_id, ...}
    │
    ▼
Router: Load conversation history → Truncate to token budget
    │
    ▼
OrchestratorAgent.handle_message()
    ├─→ Query connected integrations for tenant
    ├─→ Build tool schemas + callables from registry
    ├─→ Add meta-tools (analyze, delegate_subtask, take_notes, etc.)
    ├─→ Fetch worker context from DB (AI Workers, playbooks, latest runs)
    ├─→ Build system prompt (persona + context + worker knowledge + tool list)
    │
    ▼
ReActLoop.run()
    │
    ├─→ Iteration 1: LLM call (with extended thinking)
    │     Claude thinks: "User wants their calendar and Jira tickets..."
    │     Claude returns: tool_use[calendar:fetch, jira:search] (parallel)
    │     │
    │     ├─→ asyncio.gather(calendar:fetch(...), jira:search(...))
    │     │     ├─→ Check cache → miss → execute → cache result
    │     │     └─→ Stream tool_result events to UI
    │     │
    │     └─→ Add tool results to conversation
    │
    ├─→ Iteration 2: LLM call (with tool results in context)
    │     Claude thinks: "Got calendar and Jira data, synthesizing..."
    │     Claude returns: text (final response)
    │     │
    │     └─→ Stream response chunks to UI
    │
    └─→ Return AgentResult(final_text, trajectory, token_usage)
    │
    ▼
Router: Save exchange to ConversationStore
    │
    ▼
SSE: Emit trajectory + token_usage + [DONE]
```

---

## Streaming Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  ReAct Loop  │     │ EventEmitter │     │  SSE Stream   │
│              │     │              │     │  Generator    │
│  LLM Call ───┤────→│ _queue.put() │────→│ _queue.get() │───→ Client
│  (thinking)  │     │              │     │ yield SSE     │
│              │     │              │     │               │
│  Tool Exec ──┤────→│ _queue.put() │────→│ _queue.get() │───→ Client
│  (results)   │     │              │     │ yield SSE     │
│              │     │              │     │               │
│  Response ───┤────→│ _queue.put() │────→│ _queue.get() │───→ Client
│  (chunks)    │     │              │     │ yield SSE     │
│              │     │              │     │               │
│  Done ───────┤────→│ _queue.put   │────→│ break         │
│              │     │   (None)     │     │ yield [DONE]  │
└──────────────┘     └──────────────┘     └──────────────┘
```

The `EventEmitter` uses an `asyncio.Queue` as a bridge between the agent task and the SSE response generator. This allows the agent to process asynchronously while events are streamed to the client in real-time.

---

## Tool Execution Model

### Parallel Execution

When Claude returns multiple `tool_use` blocks in a single response, they execute concurrently:

```python
results = await asyncio.gather(
    *[run_one(tc) for tc in tool_calls],
    return_exceptions=True,
)
```

**`run_one()` pipeline for each tool call:**

1. Emit `on_tool_call` event (UI shows "Fetching Jira tickets...")
2. Check `ToolResultCache` — return cached if available
3. Execute tool function with coerced arguments
4. Emit `on_tool_result` event (full result to detail panel)
5. Truncate result to `MAX_OBSERVATION_LENGTH` (10K chars) for LLM
6. Record in trajectory (truncated to 500 chars for trajectory log)
7. Return `tool_result` content block for LLM context

### Caching Strategy

```
Tool Call → Cache Key = SHA256(tool_name + sorted_args_json)
    │
    ├─→ Cache HIT (within TTL) → Return cached result (skip execution)
    └─→ Cache MISS → Execute → Store in cache → Return result
```

- Meta-tools (`analyze`, `delegate_subtask`) bypass the cache entirely
- Tenant isolation is implicit: `tenant_id` is part of tool args, so it's part of the cache key

---

## Configuration

### Environment Variables (`.env`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | — | OpenRouter API key for Claude access |
| `ASYNC_DATABASE_URL` | `postgresql+asyncpg://...` | Core-svc database connection |
| `LOG_LEVEL` | `INFO` | Logging level |
| `MAX_OBSERVATION_LENGTH` | `10000` | Max chars per tool result in LLM context |
| `MAX_REACT_ITERATIONS` | `15` | Max orchestrator ReAct loop iterations |
| `MAX_WORKER_ITERATIONS` | `8` | Max worker ReAct loop iterations |
| `TOOL_CACHE_TTL` | `300` | Tool result cache TTL in seconds |
| `TOOL_CACHE_MAX_ENTRIES` | `100` | Max cached tool results |
| `PLAYBOOK_EXECUTION_QUEUE_URL` | — | SQS queue URL for playbook triggers |
| `AWS_REGION` | `us-east-1` | AWS region |
| `USE_LOCALSTACK` | `false` | Use localstack for local SQS |
| `LOCALSTACK_ENDPOINT` | `http://localhost:4566` | Localstack endpoint |

---

## Infrastructure

### Local Development Stack

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ FastAPI Server  │     │ PostgreSQL       │     │ Localstack       │
│ :8100           │────→│ :5434            │     │ :4566            │
│                 │     │ axari_core_db    │     │ SQS queues       │
│                 │────→│                  │     │                  │
│                 │     └──────────────────┘     └──────────────────┘
│                 │                                      ↑
│                 │──────────────────────────────────────┘
│                 │     ┌──────────────────┐
│                 │────→│ OpenRouter       │
│                 │     │ Claude Sonnet    │
└─────────────────┘     └──────────────────┘
```

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `anthropic` | ≥0.45.0 | Claude API client (AsyncAnthropic) |
| `litellm` | ≥1.50.0 | LLM abstraction layer |
| `fastapi` | ≥0.115.0 | Web framework |
| `uvicorn` | ≥0.30.0 | ASGI server |
| `asyncpg` | ≥0.30.0 | Async PostgreSQL driver |
| `pydantic` | ≥2.0.0 | Data validation |
| `aiohttp` | ≥3.9.0 | Async HTTP client |
| `python-dotenv` | ≥1.0.0 | Environment variable loading |
| `aioboto3` | ≥12.0.0 | Async AWS SDK (SQS) |
| `structlog` | ≥24.0.0 | Structured logging |
