# V1 Chat vs V2 Chat — Detailed Comparison

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Architecture Comparison](#architecture-comparison)
3. [Request Processing Pipeline](#request-processing-pipeline)
4. [Node-by-Node Mapping](#node-by-node-mapping)
5. [LLM Usage Comparison](#llm-usage-comparison)
6. [Tool Execution Model](#tool-execution-model)
7. [Streaming & Real-Time UI](#streaming--real-time-ui)
8. [State Management](#state-management)
9. [Code Complexity](#code-complexity)
10. [Performance Analysis](#performance-analysis)
11. [Feature Comparison Matrix](#feature-comparison-matrix)

---

## Executive Summary

| Aspect | V1 (LangGraph) | V2 (PoC ReAct) |
|--------|----------------|-----------------|
| **Architecture** | 11-node directed graph (LangGraph) | Single ReAct loop with meta-tools |
| **LLM calls per request** | 4-7 (fixed pipeline) | 1-N (adaptive) |
| **Framework** | LangGraph + DSPy + LangChain | Anthropic SDK (native) |
| **Tool execution** | DAG executor with dependency levels | `asyncio.gather()` per iteration |
| **Streaming** | AppSync (WebSocket) | SSE (Server-Sent Events) |
| **Intent handling** | Explicit classifier node (separate LLM call) | Extended thinking (implicit) |
| **Date extraction** | Separate node (separate LLM call) | Natural context in prompt |
| **Planning** | Explicit planner node (separate LLM call) | Extended thinking (implicit) |
| **Python files** | 80+ files across agents/ | ~20 files in engine/ |
| **State** | TypedDict with 20+ fields | Simple message list |

The V2 PoC achieves equivalent or better results by **collapsing the 11-node pipeline into a single adaptive loop**, leveraging Claude's extended thinking to internalize what V1 needed separate LLM calls for (intent classification, date extraction, complexity routing, planning).

---

## Architecture Comparison

### V1: 11-Node LangGraph Pipeline

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
          │                  │  └────────┬─────────┘
          │ ← LLM Call #2   │           │
          └────────┬─────────┘  ┌───────┴──────────┐
                   │            ▼                  ▼
                   │  ┌──────────────┐  ┌──────────────────┐
                   │  │ Clarify      │  │ Chat Mode        │ ← LLM Call #3
                   │  │ Timeframe    │  │ Decision         │
                   │  └──────┬───────┘  │ (quick/deep)     │
                   │         │          └───────┬──────────┘
                   │         │         ┌────────┴────────┐
                   │         │         ▼                 ▼
                   │         │  ┌─────────────┐  ┌────────────────┐
                   │         │  │ Quick       │  │ Intent         │ ← LLM Call #4
                   │         │  │ Answer      │  │ Extractor      │
                   │         │  │             │  └───────┬────────┘
                   │         │  │ ← ReAct     │         ▼
                   │         │  │   (1-3 LLM  │  ┌────────────────┐
                   │         │  │    calls)   │  │ Planner        │ ← LLM Call #5
                   │         │  └──────┬──────┘  └───────┬────────┘
                   │         │         │                 ▼
                   │         │         │         ┌────────────────┐
                   │         │         │         │ DAG Executor   │ ← LLM Calls #6-N
                   │         │         │         │ (parallel      │   (one per subtask)
                   │         │         │         │  subtasks)     │
                   │         │         │         └───────┬────────┘
                   │         │         │                 ▼
                   │         │         │         ┌────────────────┐
                   │         │         │         │ Report         │ ← LLM Call #N+1
                   │         │         │         │ Generator      │
                   │         │         │         └───────┬────────┘
                   ▼         ▼         ▼                 ▼
                              END
```

**Minimum LLM calls for a tool-using request:**

| Path | LLM Calls |
|------|-----------|
| Pleasantry (no tools) | 2 (intent classifier + direct response) |
| Quick answer (simple query) | 4-6 (init → classify → dates → mode → ReAct 1-3 calls) |
| Deep thinking (complex) | 7+ (init → classify → dates → mode → intent → planner → N subtasks → report) |

### V2: Single ReAct Loop

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

**LLM calls for the same requests:**

| Request Type | V1 LLM Calls | V2 LLM Calls | Reduction |
|-------------|-------------|-------------|-----------|
| Pleasantry | 2 | 1 | 50% |
| Simple query (1 tool) | 4-5 | 2 | 50-60% |
| Medium query (3 tools) | 5-6 | 2-3 | 50% |
| Complex query (5+ tools) | 7+ | 2-4 | 40-60% |

---

## Request Processing Pipeline

### V1: Sequential Multi-Node Flow

```
Message: "Show me my Jira tickets and today's calendar"

Step 1: Initializer (no LLM)
  → Fetch permission scope from DB
  → Build allowed_tools list
  → Set conversation_count

Step 2: Intent Classifier (LLM call)
  → Input: user message + chat history
  → Output: {intent_type: "data_request", can_fast_path: false, date_requirement: "reasonable_default"}
  → Route: → date_extractor

Step 3: Date Extractor (LLM call)
  → Input: user message + current datetime
  → Output: {start_date: "2026-02-14T00:00:00Z", end_date: "2026-02-14T23:59:59Z"}
  → Refined user input: "Show me my Jira tickets and today's calendar (from 2026-02-14 to 2026-02-14)"
  → Route: → chat_mode_decision

Step 4: Chat Mode Decision (LLM call)
  → Input: refined message + available tools + chat history
  → Output: {chat_mode: "quick_answer", reasoning: "Simple lookup needing 2 tools"}
  → Route: → quick_answer

Step 5: Quick Answer - ReAct Agent (2-3 LLM calls)
  → LLM call 1: Decide which tools to call → jira:search + calendar:fetch
  → Execute tools (may be sequential in DSPy ReAct)
  → LLM call 2: Get results, synthesize response
  → Output: formatted response

Total LLM calls: 5-6
Total wall time: ~15-25 seconds
```

### V2: Adaptive Single Loop

```
Message: "Show me my Jira tickets and today's calendar"

Step 1: Orchestrator setup (no LLM)
  → Query connected integrations
  → Build tool schemas + callables
  → Inject meta-tools
  → Build system prompt with worker context

Step 2: ReAct Iteration 1 (LLM call with extended thinking)
  → [Thinking]: "User wants Jira tickets and calendar for today.
     I'll call both tools in parallel with today's date range."
  → [Tool calls]: jira:search(...), calendar:fetch(...) — PARALLEL
  → Execute both concurrently via asyncio.gather()

Step 3: ReAct Iteration 2 (LLM call)
  → [Thinking]: "Got results from both. Let me synthesize."
  → [Response]: Formatted response with Axari persona

Total LLM calls: 2
Total wall time: ~5-10 seconds
```

---

## Node-by-Node Mapping

How each V1 node maps to V2:

### 1. Initializer → Orchestrator Setup

| V1 | V2 |
|----|-----|
| `initializer()` in `agents/nodes/initializer.py` | `OrchestratorAgent.handle_message()` top section |
| Queries DB via `IntegrationService` + SQLAlchemy sessions | Queries DB via `get_connected_integration_keys()` (direct SQL) |
| Uses `TOOL_REGISTRY` from DSPy | Uses `TOOL_REGISTRY` from native registry |
| Filters tools by permission scope | Filters tools by connected integration keys |
| Sets `conversation_count`, `allowed_tools` in state | No explicit state; history passed as messages |

### 2. Intent Classifier → Extended Thinking

| V1 | V2 |
|----|-----|
| Separate `IntentClassifier` LLM call | Claude's extended thinking (4000 token budget) |
| Outputs: `intent_type`, `can_fast_path`, `date_requirement` | No explicit output; Claude decides internally |
| Routes to `direct_no_tool_response` or `date_extractor` | Claude simply responds directly or calls tools |
| **Cost:** ~2K tokens per call | **Cost:** Included in main LLM call's thinking budget |

**V1 Intent Classification Output:**
```json
{
  "intent_type": "data_request",
  "can_fast_path": false,
  "date_requirement": "reasonable_default",
  "suggested_default": "last_7_days",
  "reasoning": "User is requesting Jira tickets which requires tool access",
  "thinking_message": "Let me pull up your tickets..."
}
```

**V2 Equivalent:** Claude's extended thinking block internally reasons: *"The user wants Jira tickets — I need to call jira:search with appropriate date range..."* — no separate classification step needed.

### 3. Date Extractor → Natural Context

| V1 | V2 |
|----|-----|
| Separate `DateExtractor` LLM call | Current datetime injected in system prompt |
| Rewrites user input with explicit ISO dates | Claude naturally interprets "today", "this week", etc. |
| Outputs `start_date`, `end_date`, `refined_user_input` | Claude passes appropriate dates to tool args directly |
| Handles timezone conversion (user → UTC) | User timezone provided in system prompt context |
| **Cost:** ~1.5K tokens per call | **Cost:** Zero (prompt context) |

### 4. Direct No-Tool Response → Natural End Turn

| V1 | V2 |
|----|-----|
| Separate `DirectNoToolResponder` LLM call | Claude returns text with no tool calls |
| Uses its own prompt and LLM configuration | Uses same orchestrator prompt and model |
| Routes to END | ReAct loop exits naturally (no tool_use blocks) |

### 5. Clarify Timeframe → System Prompt Default

| V1 | V2 |
|----|-----|
| Separate node that asks user for date range | System prompt instructs: "default to last 24 hours" |
| Triggers when `needs_timeframe_clarification = True` | Claude either uses default or asks naturally |
| Routes to END (user must resend) | Inline in conversation (no separate routing) |

### 6. Chat Mode Decision → Extended Thinking

| V1 | V2 |
|----|-----|
| Separate `ChatModeDecision` LLM call | Claude's extended thinking determines approach |
| Outputs `"quick_answer"` or `"deep_thinking"` | Claude adapts automatically (1-15 iterations) |
| 200+ line system prompt for routing rules | No routing needed; single adaptive loop |
| Routes to `quick_answer` or `intent_extractor` | All handled in same loop |
| **Cost:** ~1.5K tokens per call | **Cost:** Zero |

### 7. Quick Answer → ReAct Loop (1-2 iterations)

| V1 | V2 |
|----|-----|
| DSPy `CustomReactAgent` with `QuickAnswerSignature` | Same ReAct loop, just fewer iterations needed |
| Uses DSPy's text-based tool parsing | Uses Claude native `tool_use` blocks |
| Progress via AppSync `publish_update` | Progress via SSE `EventEmitter` |
| ~250 lines of code | Handled by the same ~300-line `react_loop.py` |

### 8. Intent Extractor → Not Needed

| V1 | V2 |
|----|-----|
| Separate `IntentExtractor` LLM call | Not needed |
| Extracts structured intent + context | Claude's thinking internalizes this |
| Feeds into Planner | Claude plans via extended thinking |
| **Cost:** ~2K tokens per call | **Cost:** Zero |

### 9. Planner → Extended Thinking

| V1 | V2 |
|----|-----|
| `AsyncPlannerAgent` — dedicated planning LLM call | Extended thinking handles planning |
| Outputs `execution_steps` with dependencies | Claude determines tool call order implicitly |
| Fetches business context from DB | Worker context injected in system prompt |
| Generates subtask definitions with dependency DAG | No explicit DAG; Claude calls tools in rounds |
| **Cost:** ~3-5K tokens per call | **Cost:** Included in thinking budget |

### 10. DAG Executor → asyncio.gather()

| V1 | V2 |
|----|-----|
| `node_dag_executor` with dependency levels | `asyncio.gather()` in `_execute_tool_calls()` |
| Computes DAG levels (topological sort) | Claude naturally sequences dependent calls across iterations |
| Level 0 (independent) runs in parallel | All tools in one LLM response run in parallel |
| Level N waits for Level N-1 | Claude sees results and decides next tools |
| Each subtask is a separate `SubtaskReActAgent` (own LLM calls) | Tools execute directly (no wrapper agent) |
| Publishes progress via AppSync | Publishes progress via SSE |

**V1 DAG execution example:**
```
Level 0 (parallel): [fetch_jira, fetch_calendar, fetch_email]
Level 1 (depends on L0): [correlate_jira_email]
Level 2 (depends on L1): [generate_insights]
```

**V2 equivalent:**
```
Iteration 1: Claude calls [jira:search, calendar:fetch, email:search] — parallel
Iteration 2: Claude sees results, calls [analyze] for correlation
Iteration 3: Claude synthesizes final response — no tool call, text output
```

### 11. Report Generator → Native Response

| V1 | V2 |
|----|-----|
| Separate `FinalOutputGenerator` LLM call | Claude generates the response directly in the ReAct loop |
| Takes all subtask results + plan as input | Claude has all tool results in conversation context |
| Separate prompt for report formatting | Orchestrator prompt includes response formatting rules |
| **Cost:** ~2-3K tokens per call | **Cost:** Included in final iteration |

---

## LLM Usage Comparison

### V1: Multiple Specialized Models

```python
# From agents/llm/model_config.py (v1)
MODEL_CONFIGS = {
    "intent_classifier": {"model": "gpt-4o-mini", ...},
    "date_extractor": {"model": "gpt-4o-mini", ...},
    "chat_mode_decision": {"model": "gpt-4o-mini", ...},
    "direct_no_tool_response": {"model": "claude-3-5-sonnet", ...},
    "quick_answer_task": {"model": "claude-3-5-sonnet", ...},
    "planner": {"model": "claude-3-5-sonnet", ...},
    "task": {"model": "claude-3-5-sonnet", ...},
    "final_output": {"model": "claude-3-5-sonnet", ...},
}
```

V1 uses **two model tiers**:
- **GPT-4o-mini** for classification/routing decisions (cheaper, faster)
- **Claude 3.5 Sonnet** for tool execution and generation (more capable)

### V2: Single Model with Extended Thinking

```python
# From config/models.py (v2)
MODEL_CONFIGS = {
    "orchestrator": {
        "model": "anthropic/claude-sonnet-4",
        "thinking": {"type": "enabled", "budget_tokens": 4000},
    },
    "worker": {
        "model": "anthropic/claude-sonnet-4",
    },
}
```

V2 uses **one model** (Claude Sonnet 4) for everything. Extended thinking replaces the need for separate classification/routing models.

### Token Usage Comparison (Estimated)

| Request Type | V1 Total Tokens | V2 Total Tokens | Savings |
|-------------|----------------|----------------|---------|
| Greeting | ~4K (2 LLM calls) | ~2K (1 LLM call) | ~50% |
| Simple query | ~12-15K (4-5 calls) | ~6-8K (2 calls) | ~50% |
| Complex query | ~25-40K (7+ calls) | ~12-20K (3-4 calls) | ~50% |

---

## Tool Execution Model

### V1: DSPy ReAct with Text Parsing

```python
# V1 tool execution (DSPy-based)
class CustomReactAgent:
    # DSPy ReAct: LLM generates text → parse tool calls from text → execute
    # Tool format: "Action: tool_name\nAction Input: {...}"
    # Result format: "Observation: ..."
```

**Limitations:**
- Text-based tool parsing is fragile (regex matching)
- DSPy ReAct may execute tools sequentially within an iteration
- Each subtask in DAG executor creates a new `SubtaskReActAgent` with its own LLM calls
- Tool schemas defined in DSPy format (different from Anthropic native format)

### V2: Claude Native tool_use

```python
# V2 tool execution (native)
# Claude returns structured tool_use content blocks:
# [
#   {"type": "tool_use", "id": "tc_1", "name": "jira:search", "input": {...}},
#   {"type": "tool_use", "id": "tc_2", "name": "calendar:fetch", "input": {...}},
# ]
# → All execute via asyncio.gather() → Results sent as tool_result blocks
```

**Advantages:**
- No text parsing — structured content blocks from the API
- Multiple tool calls per LLM response → true parallel execution
- Tool schemas in Anthropic's native format
- Argument type coercion (string → int/float/bool/datetime)
- Consistent error handling per tool call

---

## Streaming & Real-Time UI

### V1: AppSync WebSocket

```
V1 Streaming Flow:
  Agent Node → AppSyncClient.publish_update() → AWS AppSync → WebSocket → Frontend

  Events published:
  - node_planner: Planning steps
  - node_sequential_executor: Subtask results
  - node_generate_subtask: Subtask definitions
```

- **Infrastructure:** Requires AWS AppSync (managed GraphQL + WebSocket service)
- **Latency:** Additional hop through AWS
- **Events persisted:** Yes (saved to DB via `ChatService`)
- **Cost:** AppSync charges per message + connection

### V2: SSE (Server-Sent Events)

```
V2 Streaming Flow:
  ReAct Loop → EventEmitter._queue.put() → SSE Generator → HTTP Stream → Frontend

  Events streamed:
  - thinking: Extended thinking text
  - node_planner: Tool call progress (backward-compatible)
  - tool_result: Full tool result data (for detail panel)
  - response_chunk: Streaming response text
  - response_clear: Clear intermediate text
  - panel_note: Notes for panel
  - reminder: Reminders for panel
```

- **Infrastructure:** None (built into FastAPI)
- **Latency:** Direct TCP stream (no intermediary)
- **Events persisted:** No (PoC; production would persist)
- **Cost:** Zero additional cost

---

## State Management

### V1: TypedDict with 20+ Fields

```python
class ChatState(TypedDict):
    user_input: str
    refined_user_input: NotRequired[str]
    conversation_id: str
    chat_message_id: str
    tenant_id: str
    user_id: str
    user_name: NotRequired[str]
    org_name: NotRequired[str]
    chat_messages: Annotated[List[AnyMessage], add_messages]
    assistant_response: NotRequired[str]
    user_query_intent: NotRequired[Dict[str, Any]]
    intent_extractor: NotRequired[Dict[str, Any]]
    plan: NotRequired[Dict[str, Any]]
    subtasks: NotRequired[List[SubTaskType]]
    results: NotRequired[Annotated[List[Dict[str, Any]], results_reducer]]
    conversation_count: NotRequired[int]
    allowed_tools: List[str]
    current_datetime_user_iso: str
    start_date: NotRequired[str | None]
    end_date: NotRequired[str | None]
    chat_mode: NotRequired[str]
    chat_mode_reasoning: NotRequired[str]
    intent_classification: NotRequired[Dict[str, Any]]
    # ... and more
```

**Complexity:** Each node reads from and writes to this shared state. Fields accumulate as data flows through the pipeline. Custom reducers needed for list fields (`results_reducer`).

### V2: Simple Message List

```python
# The entire "state" is just the Anthropic messages list:
messages = [
    {"role": "user", "content": "Show my Jira tickets"},
    {"role": "assistant", "content": [tool_use_block, ...]},
    {"role": "user", "content": [tool_result_block, ...]},
    {"role": "assistant", "content": "Here are your tickets:..."},
]
```

**Simplicity:** No custom state schema. The conversation itself IS the state. Context (tenant_id, datetime, etc.) lives in the system prompt.

---

## Code Complexity

### File Count

| Category | V1 | V2 |
|----------|-----|-----|
| Node implementations | 11 files (`agents/nodes/`) | 0 (handled by ReAct loop) |
| LLM wrappers | 10+ files (`agents/llm/`) | 1 file (`engine/llm/client.py`) |
| Signatures/schemas | 10+ files (`agents/signatures/`) | 0 (auto-generated from functions) |
| Prompts | 5+ files (`agents/prompts/`) | 2 files (`prompts/`) |
| State/models | 3+ files (`agents/models/`) | 1 file (`api/models.py`) |
| Graph definition | 3 files (`agents/graph/`) | 0 (no graph) |
| Tool registry | 2 files (`agents/tools/`) | 4 files (`tools/`) |
| Streaming | 1 file + AppSync infra | 1 file (`engine/streaming/`) |
| **Total Python files** | **80+** | **~20** |
| **Estimated LoC** | **~5000+** | **~1500** |

### Dependency Footprint

| V1 Dependencies | V2 Dependencies |
|-----------------|-----------------|
| LangGraph | — |
| LangChain | — |
| DSPy | — |
| LangGraph MemorySaver | — |
| LangChain Messages (HumanMessage, AIMessage) | — |
| AWS AppSync SDK | — |
| Multiple LLM providers (OpenAI + Anthropic) | Anthropic SDK only |
| — | FastAPI (new) |
| SQLAlchemy (shared) | SQLAlchemy (shared) |
| asyncpg (shared) | asyncpg (shared) |

---

## Performance Analysis

### Latency Breakdown (Estimated)

**V1: Simple query ("Show my Jira tickets")**
```
Initializer:          ~200ms  (DB query)
Intent Classifier:    ~1-2s   (GPT-4o-mini LLM call)
Date Extractor:       ~1-2s   (GPT-4o-mini LLM call)
Chat Mode Decision:   ~1-2s   (GPT-4o-mini LLM call)
Quick Answer ReAct:   ~5-10s  (2-3 Claude LLM calls + tool execution)
─────────────────────────────
Total:                ~8-16s
```

**V2: Same query**
```
Orchestrator setup:   ~200ms  (DB queries)
ReAct Iteration 1:    ~3-5s   (1 Claude LLM call + parallel tool execution)
ReAct Iteration 2:    ~2-3s   (1 Claude LLM call, response generation)
─────────────────────────────
Total:                ~5-8s
```

**V1: Complex query ("Security posture report")**
```
Initializer:          ~200ms
Intent Classifier:    ~1-2s
Date Extractor:       ~1-2s
Chat Mode Decision:   ~1-2s
Intent Extractor:     ~2-3s
Planner:              ~3-5s
DAG Executor:         ~10-20s  (3-5 subtask agents, each with 2-3 LLM calls)
Report Generator:     ~3-5s
─────────────────────────────
Total:                ~20-40s
```

**V2: Same query**
```
Orchestrator setup:   ~200ms
ReAct Iteration 1:    ~4-6s   (thinking + 5-6 parallel tool calls)
ReAct Iteration 2:    ~3-4s   (analyze/correlate)
ReAct Iteration 3:    ~3-4s   (synthesize response)
─────────────────────────────
Total:                ~10-15s
```

### Streaming User Experience

| Aspect | V1 | V2 |
|--------|-----|-----|
| Time to first visible feedback | ~3-5s (after intent + date extraction) | ~1-2s (thinking text streams immediately) |
| Tool progress visibility | After planner completes (~6-8s) | Real-time as each tool starts (~2-3s) |
| Response streaming | Not streamed (complete response at end) | Token-by-token streaming |

---

## Feature Comparison Matrix

| Feature | V1 | V2 | Notes |
|---------|-----|-----|-------|
| Multi-integration tool calls | Yes | Yes | V2 is faster (native parallel) |
| Parallel tool execution | Yes (DAG levels) | Yes (asyncio.gather) | V2 is simpler |
| Intent classification | Explicit (LLM call) | Implicit (extended thinking) | V2 saves 1 LLM call |
| Date extraction | Explicit (LLM call) | Implicit (prompt context) | V2 saves 1 LLM call |
| Complexity routing | Explicit (LLM call) | Adaptive (loop iterations) | V2 saves 1 LLM call |
| Planning | Explicit (LLM call) | Implicit (extended thinking) | V2 saves 1 LLM call |
| Streaming responses | No (complete at end) | Yes (token-by-token) | V2 much better UX |
| Extended thinking | No | Yes | V2 exclusive |
| Tool result caching | No | Yes (5min TTL) | V2 exclusive |
| Dashboard | No | Yes (3-column grid) | V2 exclusive |
| Detail panel (Data/Notes/Reminders) | No | Yes | V2 exclusive |
| Take notes tool | No | Yes | V2 exclusive |
| Add reminder tool | No | Yes | V2 exclusive |
| Trigger playbook from chat | No | Yes (via SQS) | V2 exclusive |
| Worker context injection | No | Yes (AI Worker knowledge) | V2 exclusive |
| Conversation checkpoints | Yes (LangGraph MemorySaver) | No (in-memory) | V1 more robust |
| AppSync WebSocket | Yes | No (SSE instead) | Trade-off |
| Multi-model routing | Yes (GPT-4o-mini + Claude) | No (Claude only) | V2 simpler |
| Observability (Netra) | Yes | No (logging only) | V1 more mature |
| Database persistence | Yes (PostgreSQL) | Partial (PoC in-memory) | V1 more mature |
| Business context from DB | Yes (refined via LLM) | Yes (injected in prompt) | Different approach |
