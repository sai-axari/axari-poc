"""Query connected integrations for a tenant from the database."""
from __future__ import annotations

import logging
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger(__name__)

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        db_url = os.getenv(
            "ASYNC_DATABASE_URL",
            "postgresql+asyncpg://axari:axari@localhost:5434/axari_core_db",
        )
        _engine = create_async_engine(db_url, pool_pre_ping=True, pool_size=2)
    return _engine


async def get_connected_integration_keys(tenant_id: str) -> list[str]:
    """Return the list of integration keys connected for a tenant."""
    engine = _get_engine()
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT i.key FROM integrations i "
                    "JOIN organization_integrations oi ON oi.integration_id = i.id "
                    "WHERE oi.tenant_id = :tid"
                ),
                {"tid": tenant_id},
            )
            keys = [row[0] for row in result.fetchall()]
            logger.info(f"Connected integrations for tenant {tenant_id}: {keys}")
            return keys
    except Exception as e:
        logger.error(f"Failed to query connected integrations: {e}")
        return []
