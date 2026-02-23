"""
Fetch AI worker context and playbook data for injection into the orchestrator prompt.

The orchestrator needs to know what AI workers exist, what playbooks (responsibilities)
they have, and what those playbooks did today. This module queries PostgreSQL for that
information and formats it as a markdown string that gets injected into the system prompt.

Data flow:
1. Query ai_workers + ai_worker_contexts + playbooks tables (joined)
2. Query today's playbook_events for latest execution summaries
3. Build a markdown document with sections for each worker
4. Return the markdown string for prompt injection
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from sqlalchemy import text

from tools.connected import _get_engine

logger = logging.getLogger(__name__)

# Fetches all enabled AI workers for a tenant along with their playbooks
# and tenant-specific context. Uses LEFT JOINs so workers without playbooks
# or without context are still included.
_WORKER_CONTEXT_QUERY = text("""
    SELECT
        w.id, w.name, w.role, w.description,
        c.templatized_context,
        p.id AS playbook_id, p.name AS playbook_name, p.description AS playbook_description, p.status AS playbook_status
    FROM ai_workers w
    LEFT JOIN ai_worker_contexts c
        ON c.ai_worker_id = w.id AND c.tenant_id = w.tenant_id AND c.deleted_at IS NULL
    LEFT JOIN playbooks p
        ON p.ai_worker_id = w.id AND p.deleted_at IS NULL
    WHERE w.tenant_id = :tenant_id
        AND w.deleted_at IS NULL
        AND w.is_enabled = true
    ORDER BY w.name, p.name
""")

# Fetches today's playbook execution events (specifically the 'node_output_formatter'
# events, which contain the final formatted output of each playbook node).
# Ordered by playbook_id + created_at DESC so we can pick the latest event per playbook.
_PLAYBOOK_EVENTS_QUERY = text("""
    SELECT pe.playbook_id, pe.event_type, pe.created_at,
           px.summary AS execution_summary, px.status AS execution_status
    FROM playbook_events pe
    JOIN playbook_executions px ON px.id = pe.playbook_execution_id
    WHERE pe.tenant_id = :tenant_id
      AND pe.event_type = 'node_output_formatter'
      AND pe.deleted_at IS NULL
      AND pe.created_at >= :today_start
      AND pe.created_at < :tomorrow_start
    ORDER BY pe.playbook_id, pe.created_at DESC
""")


async def _fetch_playbook_events(engine, tenant_id: str) -> dict[str, dict]:
    """Fetch today's latest node_output_formatter event per playbook.

    Returns a mapping of playbook_id -> {summary, status, created_at}.
    Returns empty dict on failure so the main context still loads
    (the orchestrator can function without today's run summaries).
    """
    try:
        # Define "today" as midnight-to-midnight UTC
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)

        async with engine.connect() as conn:
            result = await conn.execute(
                _PLAYBOOK_EVENTS_QUERY,
                {
                    "tenant_id": tenant_id,
                    "today_start": today_start,
                    "tomorrow_start": tomorrow_start,
                },
            )
            rows = result.fetchall()

        # Because rows are ordered by (playbook_id, created_at DESC), the first
        # row we see for each playbook_id is the latest event. Skip duplicates.
        events: dict[str, dict] = {}
        for row in rows:
            pb_id = str(row[0])
            if pb_id not in events:  # Only keep the first (latest) event per playbook
                summary = row[3] or ""
                # Truncate long summaries to avoid bloating the prompt
                if len(summary) > 500:
                    summary = summary[:500] + "..."
                events[pb_id] = {
                    "summary": summary,
                    "status": row[4] or "unknown",
                    "created_at": row[2],
                }
        return events
    except Exception as e:
        logger.warning(f"Failed to fetch playbook events for tenant {tenant_id}: {e}")
        return {}


async def fetch_worker_context(tenant_id: str) -> str:
    """Query the core-svc DB for AI workers, their playbooks, and context.

    Returns a prompt-ready markdown string describing each worker's role,
    responsibilities (playbooks), tenant-specific context, and today's
    latest run summaries. The orchestrator injects this into its system
    prompt so it knows what capabilities and recent results are available.

    Returns empty string on failure so the agent still works without context.
    """
    engine = _get_engine()
    try:
        async with engine.connect() as conn:
            result = await conn.execute(_WORKER_CONTEXT_QUERY, {"tenant_id": tenant_id})
            rows = result.fetchall()

        if not rows:
            logger.info(f"No worker context found for tenant {tenant_id}")
            return ""

        # Fetch today's playbook events separately — this is non-blocking on
        # failure (returns empty dict), so the context still loads even if the
        # events query fails.
        playbook_events = await _fetch_playbook_events(engine, tenant_id)

        # Group the flat query rows by worker ID. Each row may have a different
        # playbook (from the LEFT JOIN), so we collect playbooks per worker.
        workers: dict[str, dict] = {}
        playbooks_by_worker: dict[str, list[dict]] = defaultdict(list)

        for row in rows:
            worker_id = str(row[0])
            if worker_id not in workers:
                workers[worker_id] = {
                    "name": row[1],
                    "role": row[2],
                    "description": row[3],
                    "templatized_context": row[4],
                }
            if row[5]:  # playbook_id is not null
                playbooks_by_worker[worker_id].append({
                    "id": str(row[5]),
                    "name": row[6],
                    "description": row[7],
                    "status": row[8],
                })

        # Build a markdown document with one section per worker.
        # Each section includes: header, description, playbooks, context, and
        # today's latest run summary (if available).
        sections = []
        for worker_id, w in workers.items():
            header = f"## {w['name']}"
            if w["role"]:
                header += f" — {w['role']}"
            lines = [header]

            if w["description"]:
                lines.append(w["description"])

            pbs = playbooks_by_worker.get(worker_id, [])
            if pbs:
                lines.append("")
                lines.append("### Responsibilities")
                for pb in pbs:
                    status = pb["status"] or "unknown"
                    entry = f"- **{pb['name']}** ({status})"
                    if pb["description"]:
                        entry += f": {pb['description']}"
                    lines.append(entry)

            if w["templatized_context"]:
                lines.append("")
                lines.append("### Context")
                lines.append(w["templatized_context"])

            # Append latest run info for each playbook that has events today
            for pb in pbs:
                event = playbook_events.get(pb["id"])
                if event:
                    ts = event["created_at"]
                    if hasattr(ts, "strftime"):
                        ts_str = ts.strftime("%Y-%m-%d %H:%M UTC")
                    else:
                        ts_str = str(ts)
                    lines.append("")
                    lines.append(f"### Latest Run ({pb['name']})")
                    lines.append(f"**Status:** {event['status']} | **Time:** {ts_str}")
                    if event["summary"]:
                        lines.append(event["summary"])

            sections.append("\n".join(lines))

        context_text = "\n\n".join(sections)
        worker_count = len(workers)
        playbook_count = sum(len(v) for v in playbooks_by_worker.values())
        event_count = len(playbook_events)
        logger.info(
            f"Loaded worker context for tenant {tenant_id}: "
            f"{worker_count} workers, {playbook_count} playbooks, {event_count} events"
        )
        return context_text

    except Exception as e:
        logger.error(f"Failed to fetch worker context for tenant {tenant_id}: {e}")
        return ""
