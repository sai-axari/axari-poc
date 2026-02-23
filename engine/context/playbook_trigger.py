"""
Trigger playbook (responsibility) executions from chat.

When a user says "run my morning brief" or "trigger commitment radar", this
module handles the full lifecycle:
1. Looks up available playbooks for the tenant in the database
2. Fuzzy-matches the requested name against available playbook names
3. Checks if the matched playbook is active (not paused/disabled)
4. Creates a new execution record in the playbook_executions table
5. Sends an SQS message to kick off the actual playbook processing

The SQS message is picked up by the playbook execution engine (separate service)
which runs the playbook nodes and stores results back in the database.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from tools.connected import _get_engine

logger = logging.getLogger(__name__)

# Fetches all playbooks for a tenant (regardless of status) along with the
# owning AI worker's name. Used for fuzzy name matching and status checking.
_FIND_PLAYBOOK_QUERY = text("""
    SELECT p.id, p.name, p.status, p.ai_worker_id, w.name AS worker_name
    FROM playbooks p
    LEFT JOIN ai_workers w ON w.id = p.ai_worker_id
    WHERE p.tenant_id = :tenant_id
      AND p.deleted_at IS NULL
    ORDER BY p.name
""")

# Creates a new execution record with status='pending' and trigger_type='api'.
# The 'chat' value for created_by/updated_by indicates this was triggered from
# the chat interface (as opposed to a scheduled run or manual UI trigger).
_INSERT_EXECUTION = text("""
    INSERT INTO playbook_executions
        (id, tenant_id, playbook_id, status, trigger_type, execution_count, retry_count, checkpoint_cleanup, created_at, updated_at, created_by, updated_by)
    VALUES
        (:id, :tenant_id, :playbook_id, 'pending', 'api', 1, 0, false, :now, :now, 'chat', 'chat')
    RETURNING id
""")


async def trigger_responsibility(tenant_id: str, responsibility_name: str) -> str:
    """
    Trigger a responsibility (playbook) execution from chat.

    1. Looks up playbooks for the tenant
    2. Fuzzy-matches the requested name
    3. Checks if the playbook is active
    4. If active, creates an execution record and sends SQS message
    5. If inactive, returns a message to activate it

    Returns a human-readable status message.
    """
    engine = _get_engine()
    name_lower = responsibility_name.lower().strip()

    try:
        # 1. Find playbooks for tenant
        async with engine.connect() as conn:
            result = await conn.execute(_FIND_PLAYBOOK_QUERY, {"tenant_id": tenant_id})
            rows = result.fetchall()

        if not rows:
            return "No responsibilities found for this tenant. Please set up AI Workers first."

        # 2. Fuzzy match: check exact match, substring match (both directions).
        # This allows "morning brief" to match "Morning Brief" or
        # "morning" to match "Morning Brief", etc.
        matched = None
        for row in rows:
            pb_name = (row[1] or "").lower().strip()
            if pb_name == name_lower or name_lower in pb_name or pb_name in name_lower:
                matched = {
                    "id": str(row[0]),
                    "name": row[1],
                    "status": row[2],
                    "ai_worker_id": str(row[3]),
                    "worker_name": row[4] or "AI Worker",
                }
                break

        if not matched:
            available = ", ".join(f"'{r[1]}'" for r in rows)
            return (
                f"No responsibility matching '{responsibility_name}' was found. "
                f"Available responsibilities: {available}."
            )

        # 3. Check if active
        if matched["status"] != "active":
            return (
                f"The **{matched['name']}** responsibility is currently **{matched['status']}**. "
                f"Please activate it in the AI Workers page before triggering a run."
            )

        # 4. Create execution record
        execution_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        async with engine.begin() as conn:
            await conn.execute(
                _INSERT_EXECUTION,
                {
                    "id": execution_id,
                    "tenant_id": tenant_id,
                    "playbook_id": matched["id"],
                    "now": now,
                },
            )

        logger.info(
            f"Created playbook execution {execution_id} for '{matched['name']}' "
            f"(playbook_id={matched['id']}, tenant_id={tenant_id})"
        )

        # 5. Send SQS message (if configured)
        sqs_sent = await _send_sqs_message(
            execution_id=execution_id,
            playbook_id=matched["id"],
            tenant_id=tenant_id,
        )

        status_note = ""
        if not sqs_sent:
            status_note = " Note: The execution was queued in the database but the SQS notification could not be sent."

        return (
            f"Successfully triggered **{matched['name']}** responsibility (Worker: {matched['worker_name']}). "
            f"Execution ID: `{execution_id}`. The results will be available once processing completes.{status_note}"
        )

    except Exception as e:
        logger.error(f"Failed to trigger responsibility '{responsibility_name}': {e}", exc_info=True)
        return f"Failed to trigger the responsibility: {str(e)}"


async def _send_sqs_message(execution_id: uuid.UUID, playbook_id: str, tenant_id: str) -> bool:
    """
    Send an SQS message to trigger playbook processing.

    The playbook execution engine (separate service) polls this queue and
    processes executions. The message includes the execution_id so the
    engine knows which DB record to pick up.

    Returns True if the message was sent, False otherwise.
    """
    queue_url = os.getenv("PLAYBOOK_EXECUTION_QUEUE_URL", "")
    if not queue_url:
        logger.info("PLAYBOOK_EXECUTION_QUEUE_URL not configured, skipping SQS send")
        return False

    try:
        import aioboto3

        session = aioboto3.Session()
        client_config = {"region_name": os.getenv("AWS_REGION", "us-east-1")}

        # Support for LocalStack (local AWS emulation for development)
        use_localstack = os.getenv("USE_LOCALSTACK", "").lower() in ("true", "1", "yes")
        if use_localstack:
            client_config.update({
                "endpoint_url": os.getenv("LOCALSTACK_ENDPOINT", "http://localhost:4566"),
                "aws_access_key_id": "test",
                "aws_secret_access_key": "test",
            })

        message_body = {
            "type": "playbook_execution",
            "execution_id": str(execution_id),
            "playbook_id": playbook_id,
            "tenant_id": tenant_id,
            "tenant_name": "",
            "user_details": {},
            "execution_metadata": {"source": "chat"},
            "execution_mode": "parallel",
        }

        async with session.client("sqs", **client_config) as client:
            await client.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(message_body),
                DelaySeconds=3,
            )

        logger.info(f"Sent SQS message for execution {execution_id}")
        return True

    except ImportError:
        logger.info("aioboto3 not installed, skipping SQS send")
        return False
    except Exception as e:
        logger.warning(f"Failed to send SQS message: {e}")
        return False
