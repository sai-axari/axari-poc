"""
Fetch latest playbook execution data for the chat dashboard.

The dashboard shows three sections derived from playbook executions:
1. Morning Brief — a summary of the day's priorities and context
2. Commitments — action items and commitments detected across integrations
3. Meeting Prep — upcoming meetings with attendees, agendas, and links

Each section shows data from the most recent *successful* execution of its
respective playbook. The data is served via the /v1/dashboard API endpoint
and rendered by the frontend (static/index.html).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import text

from tools.connected import _get_engine

logger = logging.getLogger(__name__)

# Uses DISTINCT ON (p.name) to get exactly one row per playbook name — the one
# with the latest completed_at timestamp. This gives us the most recent
# successful execution for each playbook (Morning Brief, Meeting Prep, etc.).
_LATEST_EXECUTIONS_QUERY = text("""
    SELECT DISTINCT ON (p.name)
        p.name AS playbook_name,
        px.id AS execution_id,
        px.result,
        px.summary,
        px.status,
        px.completed_at,
        px.start_time
    FROM playbook_executions px
    JOIN playbooks p ON p.id = px.playbook_id
    WHERE px.tenant_id = :tenant_id
      AND px.deleted_at IS NULL
      AND p.deleted_at IS NULL
      AND px.status = 'success'
    ORDER BY p.name, px.completed_at DESC NULLS LAST
""")

# Fetches structured suggestions (commitments, action items) that were extracted
# during a specific playbook execution. These are separate rows in the
# playbook_execution_suggestions table, each with a title, description,
# importance level, and optional due date.
_SUGGESTIONS_QUERY = text("""
    SELECT
        s.title,
        s.description,
        s.observation,
        s.recommendation_type,
        s.due_date,
        s.importance,
        s.created_at
    FROM playbook_execution_suggestions s
    WHERE s.playbook_execution_id = :execution_id
      AND s.deleted_at IS NULL
    ORDER BY s.created_at ASC
""")


async def fetch_dashboard_data(tenant_id: str) -> dict:
    """
    Fetch the latest playbook execution data for the dashboard.

    Returns a dict with keys:
    - morning_brief: latest Morning Brief result + summary
    - commitments: latest Commitments Radar suggestions
    - meeting_prep: latest Meeting Prep result + summary
    - last_updated: timestamp of the most recent execution
    """
    engine = _get_engine()
    dashboard = {
        "morning_brief": None,
        "commitments": None,
        "meeting_prep": None,
        "last_updated": None,
    }

    try:
        async with engine.connect() as conn:
            # 1. Get latest execution per playbook
            result = await conn.execute(
                _LATEST_EXECUTIONS_QUERY,
                {"tenant_id": tenant_id},
            )
            rows = result.fetchall()

        # Index executions by lowercase playbook name for easy lookup below.
        # Each entry contains the execution_id (needed for fetching suggestions),
        # the result JSON blob, and the summary text.
        executions_by_name = {}
        for row in rows:
            playbook_name = row[0] or ""
            executions_by_name[playbook_name.lower().strip()] = {
                "playbook_name": row[0],
                "execution_id": str(row[1]),
                "result": row[2],
                "summary": row[3],
                "status": row[4],
                "completed_at": row[5],
                "start_time": row[6],
            }

        # Track the most recent completed_at across all executions
        # to show "Updated X ago" in the dashboard header
        latest_ts = None
        for ex in executions_by_name.values():
            ts = ex.get("completed_at")
            if ts and (latest_ts is None or ts > latest_ts):
                latest_ts = ts

        if latest_ts:
            dashboard["last_updated"] = latest_ts.isoformat() if hasattr(latest_ts, "isoformat") else str(latest_ts)

        # 2. Morning Brief
        mb = executions_by_name.get("morning brief")
        if mb:
            dashboard["morning_brief"] = {
                "summary": mb["summary"] or "",
                "result": mb["result"] or {},
                "completed_at": mb["completed_at"].isoformat() if mb["completed_at"] and hasattr(mb["completed_at"], "isoformat") else str(mb["completed_at"] or ""),
            }

        # 3. Meeting Prep
        mp = executions_by_name.get("meeting prep")
        if mp:
            dashboard["meeting_prep"] = {
                "summary": mp["summary"] or "",
                "result": mp["result"] or {},
                "completed_at": mp["completed_at"].isoformat() if mp["completed_at"] and hasattr(mp["completed_at"], "isoformat") else str(mp["completed_at"] or ""),
            }

        # 4. Commitments Radar — fetch structured suggestions from the DB.
        # The playbook name might be "Commitments Radar" or "Commitment Radar",
        # so we check both variants.
        cr = executions_by_name.get("commitments radar") or executions_by_name.get("commitment radar")
        if cr:
            suggestions = []
            try:
                async with engine.connect() as conn:
                    result = await conn.execute(
                        _SUGGESTIONS_QUERY,
                        {"execution_id": cr["execution_id"]},
                    )
                    sug_rows = result.fetchall()
                    for srow in sug_rows:
                        suggestions.append({
                            "title": srow[0],
                            "description": srow[1] or "",
                            "observation": srow[2] or "",
                            "recommendation_type": srow[3] or "",
                            "due_date": srow[4].isoformat() if srow[4] and hasattr(srow[4], "isoformat") else str(srow[4] or ""),
                            "importance": srow[5] or "",
                        })
            except Exception as e:
                logger.warning(f"Failed to fetch commitment suggestions: {e}")

            dashboard["commitments"] = {
                "summary": cr["summary"] or "",
                "result": cr["result"] or {},
                "suggestions": suggestions,
                "completed_at": cr["completed_at"].isoformat() if cr["completed_at"] and hasattr(cr["completed_at"], "isoformat") else str(cr["completed_at"] or ""),
            }

        logger.info(
            f"Dashboard data fetched for tenant {tenant_id}: "
            f"morning_brief={'yes' if dashboard['morning_brief'] else 'no'}, "
            f"commitments={'yes' if dashboard['commitments'] else 'no'}, "
            f"meeting_prep={'yes' if dashboard['meeting_prep'] else 'no'}"
        )

    except Exception as e:
        logger.error(f"Failed to fetch dashboard data for tenant {tenant_id}: {e}")

    return dashboard
