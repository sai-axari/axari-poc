# Features & Future Enhancements

## Table of Contents

1. [Current Features](#current-features)
   - [Core Agent Engine](#core-agent-engine)
   - [Chat Interface](#chat-interface)
   - [Dashboard](#dashboard)
   - [Detail Panel](#detail-panel)
   - [Meta-Tools](#meta-tools)
   - [Playbook Integration](#playbook-integration)
   - [Persona & UX](#persona--ux)
2. [Production Gaps](#production-gaps)
3. [Future Enhancements](#future-enhancements)
   - [Phase 1: Production Readiness](#phase-1-production-readiness)
   - [Phase 2: Intelligence & Memory](#phase-2-intelligence--memory)
   - [Phase 3: Advanced Agent Capabilities](#phase-3-advanced-agent-capabilities)
   - [Phase 4: Enterprise Features](#phase-4-enterprise-features)
4. [Enhancement Details](#enhancement-details)
5. [Technical Debt](#technical-debt)

---

## Current Features

### Core Agent Engine

#### Single ReAct Loop with Extended Thinking
The orchestrator uses a single adaptive ReAct (Reasoning + Acting) loop powered by Claude Sonnet 4 with extended thinking enabled (4000 token thinking budget). This replaces the previous 11-node LangGraph pipeline.

**Capabilities:**
- Handles requests from simple greetings (0 iterations) to complex cross-integration reports (up to 15 iterations)
- Extended thinking internalizes intent classification, date extraction, complexity routing, and planning — eliminating 4 separate LLM calls from V1
- Graceful degradation: returns partial results if max iterations reached

#### Parallel Tool Execution
All tool calls returned by Claude in a single response execute concurrently via `asyncio.gather()`. This maximizes throughput when fetching data from multiple integrations simultaneously.

```
Example: "Morning brief" triggers parallel calls to:
  - microsoft_outlook:fetch_emails
  - jira:search_issues
  - microsoft_calendar:fetch_events
  - microsoft_teams:fetch_messages
All execute simultaneously → results collected → synthesized
```

#### Tool Result Caching
An in-memory TTL cache (5-minute TTL, 100 entries max) deduplicates tool calls within a conversation. Cache keys are deterministic SHA256 hashes of `tool_name + sorted_args_json`. Meta-tools (`analyze`, `delegate_subtask`) bypass the cache.

#### Worker Agent Delegation
The `delegate_subtask` meta-tool spawns lightweight `WorkerAgent` instances for complex multi-step subtasks requiring iterative reasoning. Workers operate with:
- No extended thinking (focused execution)
- Limited tool set (only relevant tools)
- Shorter max iterations (8 vs 15)
- No streaming callbacks

#### Argument Type Coercion
The ReAct loop automatically coerces string arguments from Claude to match Python function signatures (int, float, bool, datetime), preventing common `TypeError` failures.

#### Dynamic Tool Discovery
On startup, the system scans integration modules and auto-registers all discovered tools. Per-request, it queries the database for the tenant's connected integrations and filters the tool set accordingly.

---

### Chat Interface

#### Real-Time SSE Streaming
Server-Sent Events stream multiple event types to the UI:

| Event | User Experience |
|-------|-----------------|
| `thinking` | Shows Claude's reasoning process in real-time |
| `node_planner` | Displays thinking steps as the agent works |
| `response_chunk` | Token-by-token response streaming |
| `response_clear` | Clears intermediate text when tool calls are detected |
| `tool_result` | Populates the detail panel with full tool data |
| `panel_note` | Adds notes to the Notes tab |
| `reminder` | Adds reminders to the Reminders tab |

#### Conversation History
In-memory conversation store maintains message history per conversation, with automatic context window management (100K token budget, oldest-first truncation).

#### Markdown Rendering
All AI responses render with full markdown support (headers, bold, code blocks, lists, blockquotes, tables) using a built-in markdown parser.

#### Settings Panel
Configurable tenant ID and user settings with localStorage persistence.

---

### Dashboard

#### Three-Column Grid Layout
The dashboard displays three playbook outputs in a responsive grid:

```
┌──────────────────┬──────────────────┬──────────────────┐
│  Top Priorities  │   Commitments    │   Meeting Prep   │
│  ────────────    │   ────────────   │   ────────────   │
│  • Priority 1    │   ○ Commitment 1 │   ▶ Meeting 1    │
│    Recommendation│     Due: Feb 15  │     10:00 AM     │
│                  │                  │     [Link]       │
│  • Priority 2    │   ○ Commitment 2 │   ▶ Meeting 2    │
│    Recommendation│     Due: Feb 20  │     2:00 PM      │
│                  │                  │     [Link]       │
└──────────────────┴──────────────────┴──────────────────┘
```

**Data sources:**
- **Top Priorities** — Parsed from Morning Brief's markdown output, extracting bold-title blocks from the "TOP PRIORITIES REQUIRING YOUR ATTENTION" section
- **Commitments** — Loaded from Commitment Radar's `playbook_execution_suggestions` table (structured data with titles, descriptions, due dates, importance levels)
- **Meeting Prep** — Parsed from Meeting Prep's `assistant_response.final_output.sections`, with meeting URLs extracted via regex, past meetings filtered out, sorted by time

**Features:**
- Auto-loads on page load via `GET /v1/dashboard?tenant_id=...`
- Card-based rendering with expandable details
- Clickable meeting cards that open the meeting link in a new tab
- Responsive: 3 columns on wide screens, single column on narrow screens
- Past meetings automatically filtered out

---

### Detail Panel

A slide-in side panel (420px width) with three tabs:

#### Data Tab
Auto-populates with collapsible tool result cards as they stream in during agent execution.

**Features:**
- Panel auto-opens when tool results arrive
- Each tool result rendered as a collapsible card with formatted tool name
- JSON results rendered with structured expandable viewer
- Non-JSON results rendered as preformatted text
- Cards cleared on new conversation

#### Reminders Tab
Tracks commitments and action items with optional due dates.

**Features:**
- **Global persistence** — Reminders persist across conversations (`reminders-global` localStorage key)
- **Auto-sync from dashboard** — Commitment Radar suggestions automatically populate as reminders with `source: 'commitment-radar'` label
- **Manual addition** — Users can add reminders via text input
- **AI-triggered** — The `add_reminder` meta-tool lets the agent add reminders from conversation context
- **Due date tracking** — Optional due dates displayed on each reminder
- **Source labels** — Shows origin (e.g., "Commitment Radar", "Chat")
- **Deduplication** — Dashboard sync checks for existing reminders by title to avoid duplicates
- **Individual dismissal** — Each reminder can be dismissed

#### Notes Tab
A persistent notepad for user notes.

**Features:**
- Per-conversation persistence via localStorage
- Full-height textarea with monospace font
- AI can write notes via the `take_notes` meta-tool (append or replace modes)
- Notes load automatically when switching conversations

#### Panel Behavior
- **Wide screens (>1200px):** Side-by-side layout; chat area resizes when panel opens
- **Narrow screens (≤1200px):** Overlay mode with backdrop; panel slides over chat
- **Toggle button** in header with panel state indicator
- Smooth CSS transitions on open/close

---

### Meta-Tools

Five meta-tools extend the agent's capabilities beyond integration data fetching:

#### 1. `analyze`
Performs structured analysis on collected data. Acts as a "thinking" tool — the LLM uses it to organize complex analysis within its reasoning loop. Returns the data and objective back to the LLM for processing.

**Use cases:** Correlate data from multiple tools, identify patterns, compare timelines, assess risks.

#### 2. `delegate_subtask`
Spawns a focused WorkerAgent for complex multi-step subtasks requiring iterative reasoning.

**Use cases:** "Find all incident tickets, then for each one look up related PRs." Subtasks that require conditional logic across multiple tool calls.

**How it works:**
1. Orchestrator provides subtask description + tools needed
2. WorkerAgent gets filtered tool set + focused prompt
3. Worker executes independently (up to 8 iterations)
4. Returns structured findings to orchestrator for synthesis

#### 3. `take_notes`
Saves notes to the UI's Notes panel tab. Supports `append` (default) and `replace` modes.

**Triggered by:** "Take notes on this," "Jot down the key points," "Save this for reference."

#### 4. `add_reminder`
Adds reminders with optional due dates and context to the Reminders panel tab.

**Triggered by:** "Remind me to follow up on X," "Set a reminder for Friday," or automatically extracted from conversation context (commitments, action items).

#### 5. `trigger_responsibility`
Triggers an AI Worker responsibility (playbook) execution on demand from chat.

**Triggered by:** "Run my morning brief," "Trigger commitment radar," "Execute meeting prep."

**How it works:**
1. Queries all playbooks for the tenant
2. Fuzzy-matches the requested name (case-insensitive, substring match)
3. Checks if the playbook is active
4. If active: creates execution record in DB + sends SQS message
5. If inactive: returns message directing user to activate in AI Workers page

---

### Playbook Integration

#### Dashboard Data Pipeline
```
Playbook Execution (via v1 system)
    │
    ├─→ Results stored in playbook_executions table
    │     • result (JSON)
    │     • summary (text)
    │     • completed_at
    │
    ├─→ Suggestions stored in playbook_execution_suggestions table
    │     • title, description, observation
    │     • recommendation_type, due_date, importance
    │
    ▼
GET /v1/dashboard → fetch_dashboard_data()
    │
    ├─→ Morning Brief: latest result + summary
    ├─→ Commitments: latest suggestions (structured data)
    ├─→ Meeting Prep: latest result + summary
    └─→ last_updated timestamp
    │
    ▼
Frontend renders dashboard cards
```

#### Worker Context Injection
AI Worker configurations are queried from the database and injected into the orchestrator's system prompt as `<worker_knowledge>`:

```
## Worker Name — Role
Description of the worker

### Responsibilities
- **Morning Brief** (active): Daily morning briefing
- **Commitment Radar** (active): Track commitments

### Context
{templatized business context}

### Latest Run (Morning Brief)
**Status:** success | **Time:** 2026-02-14 08:00 UTC
Summary of the latest run...
```

This gives the orchestrator awareness of available responsibilities, their status, and recent run results.

#### Playbook Triggering from Chat
The `trigger_responsibility` meta-tool creates a complete execution pipeline:

```
User: "Run my morning brief"
    │
    ▼
trigger_responsibility()
    ├─→ Query: SELECT * FROM playbooks WHERE tenant_id = :tid
    ├─→ Match: "Morning Brief" (fuzzy, case-insensitive)
    ├─→ Check: status == "active"?
    │     ├─→ No → "Please activate it in the AI Workers page"
    │     └─→ Yes → Continue
    ├─→ INSERT INTO playbook_executions (status: pending, trigger_type: api)
    └─→ SQS: send_message(playbook_execution_queue)
         │
         ▼
    ResponsibilityProcessor (v1 system) picks up → executes → stores results
```

---

### Persona & UX

#### Axari Chief of Staff Persona
The orchestrator operates as "Axari" — a Chief of Staff to the CISO with:

- **Adaptive tone** — Matches user's vibe (casual, professional, urgent)
- **Witty, economical style** — Dry humor, short sentences, no filler
- **Two team members** (narrative layer):
  - **Eve** (Executive Assistant) — Calendar, email, scheduling domain
  - **Janice** (Program Manager) — Jira, project tracking, deadlines domain
- **Data presentation pattern** — Lead-in → Data → So-what (never dumps raw data)
- **Anticipatory** — Surfaces insights and suggests next steps without being asked

#### First Interaction
On first contact (no conversation history), Axari introduces herself: *"Axari. Most people just call me chief."* — then gets to the request.

#### Default Time Ranges
If the user doesn't specify a time range and it can't be inferred from context, the system defaults to the **last 24 hours** and informs the user.

---

## Production Gaps

The following areas are PoC-quality and would need hardening for production:

| Area | PoC Status | Production Need |
|------|-----------|-----------------|
| Conversation storage | In-memory dict | PostgreSQL with proper schema |
| Authentication | None (tenant_id in request) | JWT/OAuth2 with middleware |
| Rate limiting | None | Per-tenant rate limiting |
| Streaming | SSE (single server) | AppSync WebSocket (scalable) |
| Event persistence | Not persisted | Save to DB for history replay |
| Error handling | Basic try/catch | Structured error types, retry logic |
| Observability | Python logging | Structured logging, metrics, tracing |
| Tool result storage | Cache only | Persist raw results for audit |
| Multi-tenancy | Implicit via args | Explicit tenant isolation |
| Frontend | Single HTML file | React/Next.js app |
| Testing | Minimal | Unit, integration, E2E tests |
| CI/CD | None | Pipeline with linting, tests, deploy |

---

## Future Enhancements

### Phase 1: Production Readiness

#### 1.1 PostgreSQL Conversation Store
Replace the in-memory `ConversationStore` with a PostgreSQL-backed implementation.

```
┌───────────────────────────────────────────────┐
│ conversations table                            │
├───────────────────────────────────────────────┤
│ id (UUID, PK)                                 │
│ tenant_id (UUID, FK)                          │
│ user_id (UUID)                                │
│ created_at (timestamp)                        │
│ updated_at (timestamp)                        │
│ metadata (JSONB) — settings, preferences      │
└───────────────────────────────────────────────┘

┌───────────────────────────────────────────────┐
│ conversation_messages table                    │
├───────────────────────────────────────────────┤
│ id (UUID, PK)                                 │
│ conversation_id (UUID, FK)                    │
│ role (enum: user, assistant)                  │
│ content (TEXT)                                │
│ content_blocks (JSONB) — tool_use blocks etc. │
│ token_count (INT)                             │
│ created_at (timestamp)                        │
└───────────────────────────────────────────────┘
```

#### 1.2 Authentication & Authorization
Add JWT-based authentication middleware:
- Validate tokens on every request
- Extract tenant_id, user_id from token claims
- Enforce tenant isolation at the database query level

#### 1.3 AppSync WebSocket Streaming
Replace SSE with AppSync for production-grade streaming:
- Supports multiple concurrent connections per user
- Built-in connection management and reconnection
- Compatible with the existing V1 frontend
- Persist events for history replay

#### 1.4 Structured Observability
Integrate structured logging and tracing:
- OpenTelemetry spans for each ReAct iteration
- Token usage metrics per tenant/model
- Tool execution latency histograms
- Error rate dashboards

#### 1.5 Rate Limiting & Cost Controls
- Per-tenant token budgets (daily/monthly limits)
- Request rate limiting (requests per minute)
- Tool call rate limiting (prevent runaway loops)
- Cost estimation before execution for complex requests

---

### Phase 2: Intelligence & Memory

#### 2.1 Long-Term Memory
Add persistent memory that the agent can reference across conversations:

```
┌────────────────────────────────────────────────┐
│ agent_memories table                            │
├────────────────────────────────────────────────┤
│ id (UUID, PK)                                  │
│ tenant_id (UUID)                               │
│ user_id (UUID)                                 │
│ memory_type (enum: preference, fact, pattern)  │
│ content (TEXT) — "User prefers calendar first"  │
│ source_conversation_id (UUID)                  │
│ importance (FLOAT)                             │
│ last_accessed (timestamp)                      │
│ access_count (INT)                             │
│ embedding (VECTOR) — for semantic search       │
│ created_at (timestamp)                         │
└────────────────────────────────────────────────┘
```

**How it works:**
1. After each conversation, the agent extracts memorable facts/preferences
2. Memories are embedded and stored with importance scores
3. On new conversations, relevant memories are retrieved via semantic search
4. Injected into the system prompt as `<user_memory>`
5. Importance scores decay over time; frequently accessed memories rank higher

**Examples:**
- "User always asks for Jira before calendar"
- "User's team lead is Sarah Chen"
- "User prefers concise bullet points over detailed prose"

#### 2.2 Conversation Summarization
For long conversations approaching the context limit, generate running summaries rather than simply truncating:

```
Messages 1-20 → Summary: "User asked about Q4 security posture..."
Messages 21-30 → [Full messages in context]
Current message → [User's latest input]
```

This preserves context better than the current oldest-first truncation.

#### 2.3 Proactive Insights
The agent should proactively surface insights without being asked:

```
On morning login:
  "Good morning. Three things before you dive in:
   1. That P1 from yesterday is still open — Sarah hasn't updated since 4pm.
   2. You have a board meeting in 2 hours — I pulled the pre-reads.
   3. Commitment radar flagged 2 items slipping this week."
```

**Implementation:**
- Background scheduled check (cron or on first message of the day)
- Query open items, overdue commitments, upcoming meetings
- Synthesize into a brief proactive message

#### 2.4 Semantic Tool Result Search
Index tool results in a vector database for cross-conversation retrieval:

```
User: "What did that email from John last week say about the audit?"
  → Semantic search over past tool results
  → Find matching email content
  → Respond without re-fetching from source
```

---

### Phase 3: Advanced Agent Capabilities

#### 3.1 Write Actions
Enable the agent to take actions (not just read data):

| Integration | Read (Current) | Write (Future) |
|-------------|----------------|----------------|
| Jira | Search issues | Create/update issues, add comments |
| Calendar | Fetch events | Create/cancel events, RSVP |
| Email | Fetch emails | Draft/send emails, reply |
| Teams | Fetch messages | Send messages, create channels |
| SharePoint | Search documents | Upload documents |

**Safety considerations:**
- Confirmation step before destructive actions
- Undo capability where possible
- Audit log of all write actions
- Per-tenant action permissions

#### 3.2 Multi-Turn Tool Workflows
Support complex multi-turn workflows where the agent maintains context across actions:

```
User: "Find the P1 Jira ticket from yesterday and assign it to Sarah"
  Iteration 1: jira:search(priority=P1, last_24h) → Found SEC-142
  Iteration 2: jira:update(SEC-142, assignee=sarah) → Done
  Response: "Assigned SEC-142 to Sarah. It was reported by Mike at 3pm yesterday."
```

#### 3.3 Custom Agent Personas
Allow tenants to customize the agent's persona, team members, and response style:

```json
{
  "persona_name": "Axari",
  "persona_title": "Chief of Staff",
  "team_members": [
    {"name": "Eve", "role": "Executive Assistant", "domain": "calendar,email"},
    {"name": "Janice", "role": "Program Manager", "domain": "jira,projects"}
  ],
  "tone": "professional",
  "response_length": "concise"
}
```

#### 3.4 Tool Result Feedback Loop
Allow users to rate tool results and agent responses:

```
Agent response → [👍 Helpful] [👎 Not helpful] [💬 Feedback]
```

Feedback is used to:
- Improve prompt engineering
- Tune tool selection heuristics
- Identify integration data quality issues

#### 3.5 Scheduled Agent Tasks
Allow users to schedule recurring agent tasks:

```
User: "Every Monday at 9am, run my morning brief and email me the summary"
  → Scheduled task stored in DB
  → Cron triggers the agent
  → Agent runs, generates response
  → Sends via email integration
```

#### 3.6 Multi-Agent Collaboration
For very complex requests, multiple specialized agents could collaborate:

```
User: "Prepare a board-level security report for Q4"

┌─────────────────┐
│  Orchestrator    │
├─────────────────┤
│ Spawns 3 agents │
│ in parallel:    │
└───┬───┬───┬─────┘
    │   │   │
    ▼   ▼   ▼
┌─────┐ ┌─────┐ ┌─────┐
│ Inc.│ │ Vuln│ │ Comp│
│Agent│ │Agent│ │Agent│
│     │ │     │ │     │
│Fetch│ │Fetch│ │Fetch│
│data │ │data │ │data │
└──┬──┘ └──┬──┘ └──┬──┘
   │       │       │
   └───────┼───────┘
           ▼
    ┌─────────────┐
    │ Synthesizer │
    │ Agent       │
    │ Combines    │
    │ all data    │
    └─────────────┘
```

---

### Phase 4: Enterprise Features

#### 4.1 Audit Trail & Compliance
Complete audit logging for regulated industries:

```
┌─────────────────────────────────────────────────┐
│ audit_log table                                  │
├─────────────────────────────────────────────────┤
│ id (UUID)                                       │
│ tenant_id (UUID)                                │
│ user_id (UUID)                                  │
│ action_type (enum: tool_call, response, config) │
│ tool_name (TEXT)                                │
│ tool_args (JSONB)                               │
│ tool_result_hash (TEXT) — SHA256 of result      │
│ model_used (TEXT)                               │
│ tokens_used (INT)                               │
│ cost_usd (DECIMAL)                              │
│ ip_address (INET)                               │
│ created_at (timestamp)                          │
└─────────────────────────────────────────────────┘
```

#### 4.2 Role-Based Access Control (RBAC)
Granular permissions for tools and data:

```
Roles:
  Admin → All tools, all data, configuration
  Manager → All read tools, write tools for own team
  Analyst → Read-only tools, specific integrations
  Viewer → Chat only, no tool execution
```

#### 4.3 Data Loss Prevention (DLP)
Prevent sensitive data from leaking through the agent:

- PII detection and redaction in tool results
- Configurable sensitivity levels per integration
- Audit alerts for high-sensitivity data access
- Data classification tags on tool results

#### 4.4 Multi-Language Support
Internationalization for the agent's responses and UI:

- System prompt localization
- Response language detection and matching
- UI translation (chat interface, dashboard labels)
- Timezone-aware date formatting per locale

#### 4.5 Custom Knowledge Base (RAG)
Allow tenants to upload documents that the agent can reference:

```
Upload: security_policy_2024.pdf
  → Extract text → Chunk → Embed → Store in vector DB

User: "What's our policy on third-party access?"
  → Semantic search over knowledge base
  → Retrieve relevant chunks
  → Agent synthesizes answer with citations
```

#### 4.6 Analytics Dashboard
Business intelligence on agent usage:

- Conversations per day/week/month
- Most used tools and integrations
- Average response latency
- Token usage and cost trends
- User satisfaction scores (from feedback)
- Common request categories
- Tool failure rates

#### 4.7 Webhook Integrations
Allow the agent to trigger external workflows:

```
Agent detects P1 incident →
  Webhook: POST https://pagerduty.com/api/trigger
  Webhook: POST https://slack.com/api/chat.postMessage (#security-alerts)
  Webhook: POST https://internal.api/escalation/create
```

---

## Enhancement Details

### Priority Matrix

| Enhancement | Impact | Effort | Priority |
|------------|--------|--------|----------|
| PostgreSQL conversation store | High | Low | P0 |
| Authentication | High | Medium | P0 |
| AppSync streaming | High | Medium | P0 |
| Structured observability | High | Medium | P0 |
| Rate limiting | Medium | Low | P1 |
| Long-term memory | High | High | P1 |
| Write actions | High | High | P1 |
| Conversation summarization | Medium | Medium | P1 |
| Proactive insights | High | Medium | P2 |
| Custom personas | Low | Medium | P2 |
| Scheduled tasks | Medium | Medium | P2 |
| Feedback loop | Medium | Low | P2 |
| Multi-agent collaboration | Medium | High | P3 |
| Audit trail | High (compliance) | Medium | P1 |
| RBAC | High (enterprise) | High | P2 |
| RAG knowledge base | Medium | High | P3 |
| Analytics dashboard | Medium | Medium | P3 |

---

## Technical Debt

### Current Technical Debt Items

| Item | Location | Description | Risk |
|------|----------|-------------|------|
| In-memory conversation store | `conversation_store.py` | All conversations lost on restart | High |
| No authentication | `api/router.py` | Anyone can impersonate any tenant | Critical |
| Hardcoded system prompt | `prompts/orchestrator.py` | Cannot customize per tenant | Low |
| Single HTML file frontend | `static/index.html` | Not maintainable at scale (~2000+ lines) | Medium |
| No request validation | `api/router.py` | Missing tenant_id validation against DB | Medium |
| Tool schema auto-generation | `tools/converter.py` | May miss edge cases in type hints | Low |
| No graceful shutdown | `main.py` | In-flight requests may be interrupted | Medium |
| No health check for dependencies | `/health` endpoint | Doesn't check DB or LLM connectivity | Low |
| Global tool cache | `tool_cache.py` | No per-tenant isolation in cache keys | Low (mitigated by tenant_id in args) |
| Synchronous tool registration | `main.py` startup | Blocks startup until all tools registered | Low |

### Recommended Cleanup

1. **Split `index.html`** into components (React/Vue) for maintainability
2. **Add integration tests** for the ReAct loop with mocked LLM responses
3. **Add request ID tracking** through the entire pipeline for debugging
4. **Externalize prompts** to configuration files or database
5. **Add connection pooling** configuration for the database engine
6. **Implement graceful shutdown** to drain in-flight SSE connections
7. **Add model fallback** — retry with a different model if primary fails
8. **Version the API** — current `/v1/` prefix should be enforced with deprecation policy
