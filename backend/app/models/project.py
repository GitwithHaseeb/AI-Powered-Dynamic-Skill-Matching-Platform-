from datetime import datetime
from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field

class ProjectBase(BaseModel):
    title: str
    description: str
    require_skills: List[str] = []
    deadline: datetime
    department: str
    status: str = Field(default="planning", pattern="^(planning|in_progress|completed|on_hold)$")
    progress: int = Field(default=0, ge=0, le=100)
    team_size: int = Field(default=0, ge=0)

class ProjectCreate(ProjectBase):
    created_by: str
    srs_document: Optional[str] = None  # Path to uploaded SRS

class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    require_skills: Optional[List[str]] = None
    deadline: Optional[datetime] = None
    status: Optional[str] = None
    progress: Optional[int] = None
    team_size: Optional[int] = None
    assigned_team: Optional[List[str]] = None
    recommended_team: Optional[List[str]] = None
    final_team: Optional[List[str]] = None

class ProjectResponse(ProjectBase):
    id: str
    created_by: str
    created_by_name: Optional[str] = None
    assigned_team: List[str]
    created_at: datetime
    updated_at: datetime
    recommended_team: Optional[List[str]] = None
    final_team: Optional[List[str]] = None
    # Frontend / SDS §4.2 — optional derived fields for dashboards
    estimated_completion: Optional[str] = None
    days_until_deadline: Optional[int] = None
    skill_gap_percentage: Optional[float] = Field(
        default=None,
        description="Heuristic gap when requirements exceed simple team coverage (rough indicator).",
    )
    avg_match_accuracy_pct: Optional[float] = Field(
        default=None,
        description="Mean of top-5 SkillMatcher scores after SRS premium ranking (same as GET /projects/{id}/recommendations).",
    )

class DeveloperRecommendation(BaseModel):
    developer_id: str
    name: str
    email: Optional[str] = None
    match_score: float
    skills_match: List[str]
    experience_match: float
    availability: bool
    cgpa: float
    contact: str
    # 0.0–1.0 confidence (aligned with SDS); UI may still show match_score as %.
    confidence_score: Optional[float] = None
    # Fields used by the existing React UI
    skill_score: Optional[float] = None
    availability_score: Optional[float] = None
    matching_skills: List[str] = []
    all_skills: List[str] = []
    current_workload: Optional[int] = None
    sklearn_vector_cosine: Optional[float] = None
    char_based_skill_similarity: Optional[float] = None
    match_explanation: Optional[List[Dict[str, Any]]] = None
    ranking_method: Optional[str] = None
    # One-line narrative for PM UI (defense-friendly)
    explanation: Optional[str] = None
    # Set when diversifying suggestions across PMs / projects
    cross_project_overlap: Optional[int] = None
    design_skill_score: Optional[float] = None
    tech_skill_score: Optional[float] = None
    intrinsic_design_affinity: Optional[float] = None
    design_project_boost: Optional[float] = None
    design_dominance_boost: Optional[float] = None
    design_dominance_bonus: Optional[float] = None
    avg_design_proficiency: Optional[float] = None
    design_first_final_score: Optional[float] = None
    testing_boost: Optional[float] = None
    testing_project_boost: Optional[float] = None
    testing_dominance_bonus: Optional[float] = None
    testing_skill_score: Optional[float] = None
    avg_testing_proficiency: Optional[float] = None
    testing_first_final_score: Optional[float] = None
    balanced_design_testing_score: Optional[float] = None
    primary_track: Optional[str] = None

class ProjectRecommendations(BaseModel):
    project_id: str
    recommendations: List[DeveloperRecommendation]
    top_matches: List[str]  # IDs of top matches (up to 5)
    total_developers_evaluated: Optional[int] = None
    # Persisted pending batch for POST /recommendations/{id}/approve
    recommendation_record_id: Optional[str] = None