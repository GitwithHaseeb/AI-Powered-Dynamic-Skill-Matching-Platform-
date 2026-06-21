"""Task API models (Pydantic). Stored tasks always carry a non-empty description (server-generated when omitted)."""
from typing import List, Optional

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    """
    Create task. `description` may be omitted; the API fills it from live project data
    (title, SRS/description, require_skills) before persisting — every saved task has a full description.
    """

    title: str = Field(min_length=1, max_length=500)
    description: Optional[str] = Field(
        default=None,
        max_length=12000,
        description="Optional; if missing/blank, replaced by a description built from the project record.",
    )
    project_id: str = Field(min_length=1)
    assigned_to: str = Field(min_length=1)
    status: str = "assigned"
    priority: Optional[str] = "medium"
    skills_used: List[str] = Field(default_factory=list)
