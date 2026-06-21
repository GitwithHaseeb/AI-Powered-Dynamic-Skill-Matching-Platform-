"""
ML & document intelligence routes (SDS §1.3.2, §1.4, §2.1, §3.1).

Skill matching uses Scikit-learn via `SkillMatcher` / `sklearn_vectors`.
"""
import hashlib
import os
import re
from typing import Any, Dict, List

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from pydantic import BaseModel, Field

from app.database import get_projects_collection, get_users_collection
from app.models.user import UserResponse
from app.routes.auth import get_current_user
from app.routes.projects import (
    _dedupe_developer_documents_for_matching,
    _fetch_active_open_task_counts,
    _MAX_ACTIVE_TASKS_PER_DEVELOPER,
)
from app.core.document_parser import DocumentParser
from app.core.skill_matcher import (
    SkillMatcher,
    _dedupe_ranked_recommendations,
    _premium_design_required_count,
    _premium_testing_required_count,
    apply_balanced_design_testing_ranking,
    apply_design_first_ranking,
    apply_testing_first_ranking,
    expand_required_skills_for_matching,
    _finalize_top5_stratified,
)
from app.utils.file_handler import save_uploaded_file
from app.config import settings
from app.utils.mongo_helpers import object_id_list

router = APIRouter(prefix="/ml", tags=["Machine Learning"])


def _looks_like_object_id_ml(s: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{24}", str(s or "").strip()))


async def _find_project_for_ml(projects_collection, project_id: str):
    """Same rules as projects._find_project_document — avoid 400 from to_object_id()."""
    sid = str(project_id or "").strip()
    if not sid:
        return None
    if _looks_like_object_id_ml(sid):
        try:
            oid = ObjectId(sid)
            p = await projects_collection.find_one({"_id": oid})
            if p:
                return p
        except Exception:
            pass
    return await projects_collection.find_one({"_id": sid})


document_parser = DocumentParser()
skill_matcher = SkillMatcher()

def _extract_skill_names(skills: List[Any]) -> List[str]:
    names: list[str] = []
    for s in skills or []:
        if isinstance(s, str):
            if s.strip():
                names.append(s.strip())
        elif isinstance(s, dict):
            n = s.get("skill_name")
            if n:
                names.append(str(n).strip())
        else:
            n = getattr(s, "skill_name", None)
            if n:
                names.append(str(n).strip())
    return names


class MatchDevelopersBody(BaseModel):
    required_skills: List[str] = Field(default_factory=list)
    min_match_score: float = 70.0


class ExtractSkillsTextBody(BaseModel):
    text: str = Field(min_length=1, max_length=500_000)


@router.post("/parse-srs")
async def parse_srs_document(
    file: UploadFile = File(...),
    current_user: UserResponse = Depends(get_current_user)
):
    """Parse SRS document and extract requirements"""
    
    # Check file extension
    file_extension = os.path.splitext(file.filename)[1].lower()
    if file_extension not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type not allowed. Allowed types: {settings.ALLOWED_EXTENSIONS}"
        )
    
    # Save file temporarily
    temp_path = await save_uploaded_file(file, settings.UPLOAD_DIR, "temp")
    
    try:
        # Parse document (must match approved FYP SRS layout).
        parsed_data = await document_parser.parse_srs_document(
            temp_path, require_srs_format=True
        )
        
        # Clean up temp file
        os.remove(temp_path)
        
        skills = list(parsed_data["requirements"].get("detected_skills") or [])
        return {
            "success": True,
            "data": parsed_data,
            "extracted_skills": skills,
            "extraction_note": "SDS §1.4 — keyword catalog + NLP extract_requirements()",
            "suggestions": {
                "team_size": parsed_data["requirements"]["team_size_suggestion"],
                "timeline": "6-8 weeks" if parsed_data["requirements"]["complexity_score"] > 70 else 
                           "3-4 weeks" if parsed_data["requirements"]["complexity_score"] > 40 else 
                           "1-2 weeks"
            }
        }
        
    except ValueError as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        # Clean up temp file on error
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error parsing document: {str(e)}"
        )

@router.post("/extract-skills-from-text")
async def extract_skills_from_text(
    body: ExtractSkillsTextBody,
    current_user: UserResponse = Depends(get_current_user),
):
    """SDS §1.4 / §2.1 — infer skills from pasted SRS/resume text (no file upload)."""
    req = await document_parser.extract_requirements(body.text)
    skills = list(req.get("detected_skills") or [])
    return {
        "detected_skills": skills,
        "complexity_score": req.get("complexity_score"),
        "team_size_suggestion": req.get("team_size_suggestion"),
        "source": "keyword_catalog_nlp",
    }


@router.post("/match-developers")
async def match_developers_to_skills(
    body: MatchDevelopersBody,
    current_user: UserResponse = Depends(get_current_user),
):
    """
    SDS §1.3.2 — rank developers with Scikit-learn skill vectors + blend metrics
    (same core engine as GET /projects/{id}/recommendations).
    """
    required_skills = body.required_skills
    min_match_score = body.min_match_score

    if current_user.role not in ("manager", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only managers or admins can access this endpoint",
        )

    users_collection = get_users_collection()
    
    # Get all available developers
    cursor = users_collection.find({
        "role": "developer",
        "availability": True
    })
    
    developers = await cursor.to_list(length=500)
    developers = _dedupe_developer_documents_for_matching(developers)

    req_expanded = expand_required_skills_for_matching(required_skills)
    task_counts = await _fetch_active_open_task_counts()

    hard_design_mode = _premium_design_required_count(required_skills) >= 1

    # Match developers to skills
    matches = []
    for developer in developers:
        did = str(developer.get("_id") or "").strip()
        if (
            _MAX_ACTIVE_TASKS_PER_DEVELOPER > 0
            and int(task_counts.get(did, 0)) >= _MAX_ACTIVE_TASKS_PER_DEVELOPER
        ):
            continue
        match_result = skill_matcher.match_developer_to_project(
            developer=developer,
            project={"complexity_score": 50},  # Default complexity
            required_skills=req_expanded,
            hard_design_mode=hard_design_mode,
        )
        
        if match_result["match_score"] >= min_match_score:
            matches.append(match_result)

    premium_design_n = _premium_design_required_count(required_skills)
    premium_testing_n = _premium_testing_required_count(required_skills)
    design_srs = premium_design_n >= 1
    testing_srs = premium_testing_n >= 1
    hard_design_mode = premium_design_n >= 1
    if not design_srs and not testing_srs:
        from app.ml.sklearn_vectors import maybe_rerank_random_forest

        matches, _rank_m = maybe_rerank_random_forest(matches)
        if _rank_m == "sklearn_cosine_char_blend":
            matches.sort(key=lambda x: x["match_score"], reverse=True)

    matches = _dedupe_ranked_recommendations(matches)
    # Ranking (see skill_matcher): design+testing → 0.45*D + 0.45*T + 0.10*M; testing-only → 0.90*T + 0.10*M when ≥2 premium testing rows else 0.95/0.05.
    if design_srs and testing_srs:
        apply_balanced_design_testing_ranking(matches, required_skills)
    elif testing_srs:
        apply_testing_first_ranking(matches, required_skills)
    elif hard_design_mode or design_srs:
        apply_design_first_ranking(matches, required_skills)
    synth_proj = hashlib.sha256(
        "|".join(sorted(s.lower() for s in required_skills)).encode("utf-8")
    ).hexdigest()[:24]
    stratified_top = _finalize_top5_stratified(
        matches,
        required_skills,
        task_counts=task_counts,
        project_id=f"ml-synthetic-{synth_proj}",
    )
    top_ids = [
        str(x["developer_id"]) for x in stratified_top[:3] if x.get("developer_id")
    ]

    return {
        "required_skills": required_skills,
        "matches": matches,
        "total_matches": len(matches),
        "top_matches": top_ids or [str(m.get("developer_id")) for m in matches[:3]],
        "ranking_engine": "sklearn_vectors_stratified_buckets",
    }

@router.get("/skill-analysis")
async def analyze_skill_gap(
    project_id: str,
    current_user: UserResponse = Depends(get_current_user)
):
    """Analyze skill gaps for a project"""
    
    if current_user.role not in ("manager", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only managers or admins can access this endpoint",
        )

    projects_collection = get_projects_collection()
    users_collection = get_users_collection()

    project = await _find_project_for_ml(projects_collection, project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    team_oids = object_id_list(project.get("assigned_team"))
    assigned_developers = []
    if team_oids:
        assigned_developers = await users_collection.find({
            "_id": {"$in": team_oids}
        }).to_list(length=50)
    
    # Analyze skill coverage
    required_skills = project.get("require_skills", [])
    covered_skills = []
    missing_skills = []
    
    for skill in required_skills:
        skill_covered = False
        for developer in assigned_developers:
            dev_skills = developer.get("skills", [])
            if skill.lower() in [s.lower() for s in _extract_skill_names(dev_skills)]:
                skill_covered = True
                break
        
        if skill_covered:
            covered_skills.append(skill)
        else:
            missing_skills.append(skill)
    
    # Calculate coverage percentage
    coverage_percentage = (len(covered_skills) / len(required_skills) * 100) if required_skills else 0
    
    # Find developers who can cover missing skills
    suggested_developers = []
    if missing_skills:
        dev_query: Dict[str, Any] = {"role": "developer", "availability": True}
        if team_oids:
            dev_query["_id"] = {"$nin": team_oids}
        cursor = users_collection.find(dev_query)
        
        all_developers = await cursor.to_list(length=50)
        
        for developer in all_developers:
            matching_missing_skills = []
            dev_skills_lower = [s.lower() for s in _extract_skill_names(developer.get("skills", []))]
            
            for missing_skill in missing_skills:
                if missing_skill.lower() in dev_skills_lower:
                    matching_missing_skills.append(missing_skill)
            
            if matching_missing_skills:
                suggested_developers.append({
                    "developer_id": str(developer["_id"]),
                    "name": developer.get("full_name")
                    or developer.get("name")
                    or developer.get("username", ""),
                    "matching_skills": matching_missing_skills,
                    "total_skills": developer.get("skills", []),
                    "cgpa": developer.get("cgpa", 0)
                })
    
    return {
        "project_id": project_id,
        "project_title": project.get("title", ""),
        "project_status": project.get("status", ""),
        "required_skills": required_skills,
        "covered_skills": covered_skills,
        "missing_skills": missing_skills,
        "coverage_percentage": round(coverage_percentage, 2),
        "skill_gap_percentage": round(max(0.0, 100.0 - coverage_percentage), 2),
        "assigned_team_size": len(assigned_developers),
        "suggested_developers": suggested_developers[:5],  # Top 5 suggestions
        "recommendations": [
            f"Skill coverage: {round(coverage_percentage)}%",
            f"Missing skills: {', '.join(missing_skills[:3])}" if missing_skills else "All skills covered",
            f"Consider adding {len(suggested_developers)} developers to cover missing skills" if suggested_developers else "Team composition looks good"
        ]
    }