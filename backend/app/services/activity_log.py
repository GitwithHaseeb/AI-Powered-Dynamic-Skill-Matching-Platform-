from datetime import datetime
from typing import Any, Optional

from app.database import get_activity_logs_collection


async def log_activity(
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    col = get_activity_logs_collection()
    await col.insert_one(
        {
            "actor_id": actor_id,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "metadata": metadata or {},
            "created_at": datetime.utcnow(),
        }
    )
