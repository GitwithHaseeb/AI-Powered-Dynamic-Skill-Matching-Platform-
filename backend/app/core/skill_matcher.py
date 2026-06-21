"""
AI skill matching service (SDS §1.3.2, §3.1 flows — team recommendation / ML engine).

Combines Scikit-learn cosine vectors over proficiency-weighted skill features
(see `app.ml.sklearn_vectors`) with char n‑gram TF‑IDF overlap for robustness,
and optionally re-ranks with RandomForest when enough candidates exist.
"""
from __future__ import annotations

import asyncio
from typing import List, Dict, Any, Optional, Tuple
import hashlib
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.feature_extraction.text import TfidfVectorizer

from app.core.match_explanation import human_match_explanation
from app.ml.sklearn_vectors import explain_sklearn_skill_match, maybe_rerank_random_forest
from app.services.team_roster import max_project_team_size
from app.utils.identity_normalize import normalize_identity_token


def _norm_person_name(value: str) -> str:
    return normalize_identity_token(str(value or ""))


# Extra vocabulary so UX/Figma/Design requirements match designers who store related skill names (e.g. "UI", "Figma").
_DESIGN_MATCH_ALIASES: List[str] = [
    "ux design",
    "ui design",
    "user experience",
    "user interface",
    "visual design",
    "interaction design",
    "figma",
    "adobe xd",
    "sketch",
    "wireframe",
    "prototype",
    "design systems",
    "usability",
    "accessibility",
    "tailwind css",
]

_TESTING_MATCH_ALIASES: List[str] = [
    "qa testing",
    "automation testing",
    "automation test",
    "api testing",
    "api test",
    "manual testing",
    "manual test",
    "manual tester",
    "selenium",
    "selenium testing",
    "postman",
    "bug tracking",
    "bug report",
    "bug fixing",
    "test cases",
    "test case",
]


def partition_design_and_tech_skills(skills: List[str]) -> Tuple[List[str], List[str]]:
    """
    Split project requirements so design/CSS/UX work is scored separately from backend/framework skills.
    Used for balanced matching and to surface UI/UX designers (e.g. Figma, UX Design) alongside engineers.
    """
    design: list[str] = []
    tech: list[str] = []
    for raw in skills or []:
        s = str(raw).strip()
        if not s:
            continue
        sl = s.lower()
        if _skill_is_design_track(sl):
            design.append(s)
        else:
            tech.append(s)
    return design, tech


def _skill_is_design_track(sl: str) -> bool:
    """Heuristic: styling / product design / research vs application code."""
    if any(
        k in sl
        for k in (
            "ux design",
            "ui design",
            "visual design",
            "design system",
            "design systems",
            "figma",
            "wireframe",
            "prototype",
            "tailwind",
            "css",
            "sass",
            "scss",
            "styling",
            "sketch",
            "adobe xd",
            "usability",
            "accessibility",
            "a11y",
            "brand",
            "layout",
        )
    ):
        return True
    if sl in ("html", "htm", "ux", "ui"):
        return True
    if "design" in sl and "fastapi" not in sl and "mongodb" not in sl:
        return True
    return False


def _premium_design_required_count(required_skills: List[str]) -> int:
    """Count explicit premium design rows in SRS (UI/UX/Visual/Figma/Design Systems)."""
    markers = (
        "ui design",
        "ux design",
        "visual design",
        "figma",
        "design system",
        "design systems",
    )
    n = 0
    for s in required_skills or []:
        sl = str(s).strip().lower()
        if any(m in sl for m in markers):
            n += 1
    return n


def _premium_testing_required_count(required_skills: List[str]) -> int:
    """Count explicit testing rows in SRS (QA/manual/automation/API/postman/bugs/test-cases)."""
    markers = (
        "qa testing",
        "automation testing",
        "automation test",
        "api testing",
        "api test",
        "manual testing",
        "manual test",
        "manual tester",
        "selenium",
        "postman",
        "bug tracking",
        "bug report",
        "bug fixing",
        "test cases",
        "test case",
        "quality assurance",
        "qa engineer",
        "automated testing",
        "test automation",
        "selenium webdriver",
    )
    n = 0
    for s in required_skills or []:
        sl = str(s).strip().lower()
        if any(m in sl for m in markers):
            n += 1
    return n


def _design_project_boost_points(
    n_premium: int,
    intrinsic_d: float,
    design_combined: float,
    avg_design_prof: float,
) -> tuple[float, float]:
    """
    Returns (design_project_boost, design_dominance_bonus).
    Final defense mode:
    - if >=1 premium design requirement exists: minimum +60
    - if >=3 premium design requirements: minimum +80
    - if average design proficiency >= 4.0: +20 dominance bonus
    """
    if n_premium < 1:
        return 0.0, 0.0
    strength = min(1.0, 0.44 * float(intrinsic_d) + 0.56 * float(design_combined))
    if strength <= 0.02:
        return 0.0, 0.0
    if n_premium >= 3:
        base = max(80.0, 80.0 + 6.0 * strength)
        dominance_bonus = 20.0 if float(avg_design_prof) >= 4.0 else 0.0
        return min(100.0, base + dominance_bonus), dominance_bonus
    base = max(60.0, 60.0 + 5.0 * strength)
    dominance_bonus = 20.0 if float(avg_design_prof) >= 4.0 else 0.0
    return min(100.0, base + dominance_bonus), dominance_bonus


def _design_first_sort_key(rec: Dict[str, Any]) -> tuple:
    """
    Hard design-first ordering for ultra design SRS:
    final_score = (design_skill_score * 0.95) + (overall_match_score * 0.05)
    """
    ds = float(rec.get("design_skill_score") or 0)
    ms = float(rec.get("match_score") or 0)
    final_score = 0.95 * ds + 0.05 * ms
    return (-final_score, -ds, -ms, str(rec.get("developer_id") or ""))


def apply_design_first_ranking(recs: List[Dict[str, Any]], required_skills: List[str]) -> bool:
    """Re-order ``recs`` for hard design-first mode when premium design requirements are 2+."""
    if _premium_design_required_count(required_skills) < 1:
        return False
    for r in recs:
        ds = float(r.get("design_skill_score") or 0)
        ms = float(r.get("match_score") or 0)
        r["design_first_final_score"] = round(0.95 * ds + 0.05 * ms, 2)
        r["ranking_method"] = "design_first_hard_priority"
    recs.sort(key=_design_first_sort_key)
    return True


def _testing_first_rank_weights(required_skills: List[str]) -> tuple[float, float]:
    """Hard testing-first when SRS lists 2+ premium testing rows (parity with aggressive design mode)."""
    n = _premium_testing_required_count(required_skills)
    if n >= 2:
        return 0.90, 0.10
    return 0.95, 0.05


def apply_testing_first_ranking(recs: List[Dict[str, Any]], required_skills: List[str]) -> bool:
    """Prioritize testing_track candidates when testing requirements are present."""
    if _premium_testing_required_count(required_skills) < 1:
        return False
    w_t, w_m = _testing_first_rank_weights(required_skills)

    def _tkey(r: Dict[str, Any]) -> tuple:
        ts = float(r.get("testing_skill_score") or 0.0)
        ms = float(r.get("match_score") or 0.0)
        tb = float(r.get("testing_boost") or 0.0)
        final = w_t * ts + w_m * ms
        return (-final, -ts, -tb, -ms, str(r.get("developer_id") or ""))

    for r in recs:
        ts = float(r.get("testing_skill_score") or 0.0)
        ms = float(r.get("match_score") or 0.0)
        r["testing_first_final_score"] = round(w_t * ts + w_m * ms, 2)
        r["ranking_method"] = "testing_first_hard_priority"
    recs.sort(key=_tkey)
    return True


def apply_balanced_design_testing_ranking(recs: List[Dict[str, Any]], required_skills: List[str]) -> bool:
    """When SRS asks for both design and testing, avoid one ranking pass wiping the other."""
    if _premium_design_required_count(required_skills) < 1 or _premium_testing_required_count(required_skills) < 1:
        return False

    def _bkey(r: Dict[str, Any]) -> tuple:
        ds = float(r.get("design_skill_score") or 0.0)
        ts = float(r.get("testing_skill_score") or 0.0)
        ms = float(r.get("match_score") or 0.0)
        final = 0.45 * ds + 0.45 * ts + 0.10 * ms
        return (-final, -ds, -ts, -ms, str(r.get("developer_id") or ""))

    for r in recs:
        ds = float(r.get("design_skill_score") or 0.0)
        ts = float(r.get("testing_skill_score") or 0.0)
        ms = float(r.get("match_score") or 0.0)
        r["balanced_design_testing_score"] = round(0.45 * ds + 0.45 * ts + 0.10 * ms, 2)
        r["ranking_method"] = "balanced_design_testing_priority"
    recs.sort(key=_bkey)
    return True


def _average_design_proficiency(skills: List[Any]) -> float:
    """Average proficiency level (0..5) for design-facing developer skills."""
    vals: list[float] = []
    for s in skills or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("skill_name") or "").strip().lower()
        if not name or not _skill_is_design_track(name):
            continue
        vals.append(float(s.get("proficiency_level") or 1.0))
    if not vals:
        return 0.0
    return float(sum(vals) / len(vals))


def _average_testing_proficiency(skills: List[Any]) -> float:
    """Average proficiency (0..5) across QA/testing-oriented developer skills."""
    vals: list[float] = []
    for s in skills or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("skill_name") or "").strip().lower()
        if not name or not _skill_is_testing_track(name):
            continue
        vals.append(float(s.get("proficiency_level") or 1.0))
    if not vals:
        return 0.0
    return float(sum(vals) / len(vals))


def _char_row_weight_for_requirement(sl: str) -> float:
    """Char n-gram: premium design rows ~5–6× effective weight vs generic tech."""
    s = str(sl).strip().lower()
    if "figma" in s:
        return 6.0
    premium_markers = (
        "ui design",
        "ux design",
        "visual design",
        "design system",
        "design systems",
    )
    if any(m in s for m in premium_markers):
        return 5.5
    testing_markers = (
        "qa testing",
        "automation testing",
        "automation test",
        "api testing",
        "api test",
        "manual testing",
        "manual test",
        "manual tester",
        "selenium",
        "postman",
        "bug tracking",
        "bug report",
        "bug fixing",
        "test cases",
        "test case",
        "quality assurance",
        "qa engineer",
        "automated testing",
        "test automation",
        "selenium webdriver",
    )
    if any(m in s for m in testing_markers):
        return 5.5
    if _skill_is_design_track(s):
        return 3.0
    return 1.0


def _skill_is_testing_track(sl: str) -> bool:
    s = str(sl or "").strip().lower()
    if not s:
        return False
    return any(
        k in s
        for k in (
            "qa testing",
            "automation testing",
            "automation test",
            "api testing",
            "api test",
            "manual testing",
            "manual test",
            "manual tester",
            "selenium",
            "postman",
            "bug tracking",
            "bug report",
            "bug fixing",
            "test cases",
            "test case",
            "quality assurance",
            "qa engineer",
            "automated testing",
            "test automation",
            "selenium webdriver",
            "qa ",
        )
    )


def _testing_profile_strength(skill_names: List[str]) -> float:
    if not skill_names:
        return 0.0
    blob = " ".join(str(s).lower() for s in skill_names)
    score = 0.0
    for k in (
        "qa testing",
        "automation testing",
        "api testing",
        "manual testing",
        "automated testing",
        "test automation",
        "selenium",
        "webdriver",
        "postman",
        "bug tracking",
        "bug report",
        "test case",
        "quality assurance",
        "qa engineer",
    ):
        if k in blob:
            score += 0.16
    return min(1.0, score)


def _intrinsic_testing_affinity(skill_names: List[str]) -> float:
    """How strongly the profile reads as QA/testing (independent of vector overlap)."""
    if not skill_names:
        return 0.0
    blob = " ".join(str(s).strip().lower() for s in skill_names if str(s).strip())
    score = 0.0
    for m in (
        "manual testing",
        "automation testing",
        "qa testing",
        "api testing",
        "test case",
        "selenium",
        "webdriver",
        "postman",
        "bug tracking",
        "pytest",
        "jest",
        "cypress",
        "quality assurance",
    ):
        if m in blob:
            score += 0.22
    toks = set(blob.replace(",", " ").replace(".", " ").split())
    if "qa" in toks:
        score += 0.18
    return min(1.0, score)


def _testing_boost_points(
    n_testing: int,
    testing_combined: float,
    testing_strength: float,
    avg_testing_prof: float,
) -> tuple[float, float, float]:
    """
    Testing project boost (design-parity): min +50, or +70 floor when 3+ testing rows;
    +20 dominance when average testing proficiency >= 4.0.

    Returns (total_boost_for_match_score, testing_project_boost_base, testing_dominance_bonus).
    """
    if n_testing < 1:
        return 0.0, 0.0, 0.0
    strength = min(1.0, 0.58 * float(testing_combined) + 0.42 * float(testing_strength))
    if strength <= 0.03:
        return 0.0, 0.0, 0.0
    dominance = 20.0 if float(avg_testing_prof) >= 4.0 else 0.0
    if n_testing >= 3:
        base = max(70.0, 70.0 + 10.0 * strength)
    else:
        base = max(50.0, 50.0 + 14.0 * strength)
    total = min(100.0, base + dominance)
    return total, base, dominance


def _intrinsic_design_affinity(skill_names: List[str]) -> float:
    """
    Strength of design/UX craft in the developer profile alone (Figma, UX, systems, etc.).
    Used so real designers are not dropped by sparse vector cosine on mixed stacks, and so
    design strat picks can key off more than ``primary_track``.
    """
    if not skill_names:
        return 0.0
    blob = " ".join(str(s).strip().lower() for s in skill_names if str(s).strip())
    score = 0.0
    for m in (
        "figma",
        "sketch",
        "adobe xd",
        "ux design",
        "ui design",
        "visual design",
        "wireframe",
        "interaction design",
    ):
        if m in blob:
            score += 0.24
    if "design system" in blob or "design systems" in blob:
        score += 0.2
    if "prototype" in blob or "usability" in blob or "graphic design" in blob:
        score += 0.12
    toks = set(blob.replace(",", " ").replace(".", " ").split())
    if "figma" in toks or "ux" in toks:
        score += 0.12
    # Light UI styling signal (full-stack devs may have this without being designers)
    if any(k in blob for k in ("tailwind", "sass", "scss")) and "figma" not in blob:
        score += 0.06
    return min(1.0, score)


def _infer_primary_track(skill_names: List[str]) -> str:
    """
    Coarse bucket for stratified team suggestions (design / frontend / backend / ML / general).
    """
    if not skill_names:
        return "general"
    blob = " ".join(s.lower() for s in skill_names)

    data_kw = (
        "tensorflow",
        "pytorch",
        "nlp",
        "pandas",
        "keras",
        "scikit",
        "machine learning",
        "deep learning",
        "computer vision",
    )
    design_kw = (
        "figma",
        "sketch",
        "adobe xd",
        "ux design",
        "ui design",
        "visual design",
        "wireframe",
        "prototype",
        "design system",
        "usability",
        "graphic",
    )
    fe_kw = (
        "react",
        "vue",
        "angular",
        "svelte",
        "next.js",
        "nextjs",
        "tailwind",
        "javascript",
        "typescript",
        "html",
        "material-ui",
        "webpack",
        "vite",
        "sass",
        "scss",
        "css",
    )
    be_kw = (
        "python",
        "fastapi",
        "django",
        "flask",
        "mongodb",
        "postgres",
        "mysql",
        "redis",
        "java",
        "spring",
        "node.js",
        "express",
        "docker",
        "kubernetes",
        "c++",
        "go",
        "rust",
    )

    qa_kw = (
        "selenium",
        "manual testing",
        "automated testing",
        "jest",
        "cypress",
        "postman",
        "bug tracking",
        "test case",
        "qa testing",
        "api testing",
        "pytest",
    )

    def hits(kws: tuple[str, ...]) -> float:
        return float(sum(1 for k in kws if k in blob))

    scores = {
        "data_ml": hits(data_kw) * 1.15,
        "design": hits(design_kw) * 1.4,
        "frontend": hits(fe_kw),
        "backend": hits(be_kw),
        "qa": hits(qa_kw) * 1.08,
    }
    toks = set(blob.replace(",", " ").replace(".", " ").split())
    if any(t in toks for t in ("ux", "ui", "figma")):
        scores["design"] += 0.9
    if "user experience" in blob or "user interface" in blob:
        scores["design"] += 1.05
    if "visual design" in blob or "graphic design" in blob:
        scores["design"] += 1.0
    # UI-heavy surface skills often mean "design track" more than generic backend.
    ui_surface = hits(("tailwind", "css", "scss", "sass", "html", "wireframe", "prototype"))
    if ui_surface >= 2 and hits(be_kw) <= 2.5:
        scores["design"] += 0.65

    mx = max(scores.values())
    if mx < 0.5:
        return "general"
    tier = [k for k, v in scores.items() if v == mx]
    prio = ["design", "qa", "data_ml", "frontend", "backend"]
    for p in prio:
        if p in tier:
            return p
    return "general"


def _eligible_for_design_stratum(rec: Dict[str, Any], *, relaxed: bool) -> bool:
    """
    UX/UI people are often classified as ``frontend`` (React/Tailwind). Design slots use
    ``design_skill_score`` so true designers still enter the pool.
    """
    pt = str(rec.get("primary_track") or "general")
    ds = float(rec.get("design_skill_score") or 0.0)
    ia = float(rec.get("intrinsic_design_affinity") or 0.0)
    if pt == "design":
        return True
    # Strong craft skills in profile (Figma, UX, …) even if a frontend track “won”.
    if ia >= 0.45:
        return True
    if relaxed:
        if ia >= 0.22:
            return True
        if ds >= 18.0:
            return True
        if pt == "frontend" and ds >= 12.0:
            return True
        return False
    if ds >= 40.0:
        return True
    if pt == "frontend" and ds >= 26.0:
        return True
    if pt == "general" and ds >= 32.0:
        return True
    if ia >= 0.28 and ds >= 15.0:
        return True
    return False


def _finalize_top5_stratified(
    recs: List[Dict[str, Any]],
    original_required_skills: List[str],
    task_counts: Optional[Dict[str, int]] = None,
    project_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Build top-5 from *different capability buckets* so the same FastAPI+MDB devs do not own every slot.
    Picks explicit design / frontend / backend / data + flex when requirements call for it.
    Within each bucket, when several candidates score nearly the same, pick is salted by
    ``project_id`` so different projects (and skill sets on synthetic match) do not all surface
    the same names.
    """
    if not recs:
        return []

    tc_map = task_counts or {}
    proj_key = str(project_id or "").strip() or "default"
    premium_n = _premium_design_required_count(original_required_skills)
    testing_n = _premium_testing_required_count(original_required_skills)
    hard_design_mode = premium_n >= 1
    design_reqs, tech_reqs = partition_design_and_tech_skills(original_required_skills)
    req_blob = " ".join(str(x).lower() for x in (original_required_skills or []))
    wants_qa = any(
        k in req_blob
        for k in (
            "manual testing",
            "automated testing",
            "testing",
            "qa ",
            "quality assurance",
            "selenium",
            "jest",
            "cypress",
            "pytest",
            "test automation",
        )
    )
    picked: list[dict[str, Any]] = []
    picked_ids: set[str] = set()

    def _choose_from_pool(
        pool: list[Dict[str, Any]],
        bucket_key: str,
        sort_mode: str = "match",
    ) -> Optional[Dict[str, Any]]:
        if not pool:
            return None
        wl = lambda r: int(tc_map.get(str(r.get("developer_id") or ""), 0))

        def sort_key_match(r: Dict[str, Any]) -> tuple:
            return (-float(r.get("match_score") or 0), wl(r))

        def sort_key_design(r: Dict[str, Any]) -> tuple:
            return (
                -float(r.get("design_skill_score") or 0),
                -float(r.get("intrinsic_design_affinity") or 0),
                -float(r.get("match_score") or 0),
                wl(r),
            )

        def sort_key_tech(r: Dict[str, Any]) -> tuple:
            ts = float(r.get("tech_skill_score") or 0)
            if ts <= 0.0:
                return (-float(r.get("match_score") or 0), wl(r))
            return (-ts, -float(r.get("match_score") or 0), wl(r))

        def sort_key_testing(r: Dict[str, Any]) -> tuple:
            ts = float(r.get("testing_skill_score") or 0)
            if ts <= 0.0:
                return (-float(r.get("match_score") or 0), wl(r))
            return (-ts, -float(r.get("match_score") or 0), wl(r))

        if sort_mode == "design_skill":
            pool.sort(key=sort_key_design)
            best_primary = float(pool[0].get("design_skill_score") or 0)
            rel_floor = best_primary * 0.9
            abs_floor = best_primary - 10.0
            floor = max(0.0, rel_floor, abs_floor)
            band = [r for r in pool if float(r.get("design_skill_score") or 0) >= floor]
        elif sort_mode == "tech_skill":
            pool.sort(key=sort_key_tech)
            best_t = float(pool[0].get("tech_skill_score") or 0)
            if best_t > 0.0:
                floor = max(0.0, best_t * 0.92, best_t - 12.0)
                band = [r for r in pool if float(r.get("tech_skill_score") or 0) >= floor]
            else:
                best_m = float(pool[0].get("match_score") or 0)
                floor = max(0.0, best_m * 0.975, best_m - 2.5)
                band = [r for r in pool if float(r.get("match_score") or 0) >= floor]
        elif sort_mode == "testing_skill":
            pool.sort(key=sort_key_testing)
            best_t = float(pool[0].get("testing_skill_score") or 0)
            if best_t > 0.0:
                floor = max(0.0, best_t * 0.90, best_t - 14.0)
                band = [r for r in pool if float(r.get("testing_skill_score") or 0) >= floor]
            else:
                best_m = float(pool[0].get("match_score") or 0)
                floor = max(0.0, best_m * 0.975, best_m - 2.5)
                band = [r for r in pool if float(r.get("match_score") or 0) >= floor]
        else:
            pool.sort(key=sort_key_match)
            best_score = float(pool[0].get("match_score") or 0)
            rel_floor = best_score * 0.975
            abs_floor = best_score - 2.5
            floor = max(0.0, rel_floor, abs_floor)
            band = [r for r in pool if float(r.get("match_score") or 0) >= floor]

        if len(band) == 1:
            return band[0]

        def tie_key(r: Dict[str, Any]) -> tuple:
            digest = hashlib.sha256(
                f"{proj_key}|{bucket_key}|{r.get('developer_id')}".encode("utf-8")
            ).hexdigest()
            if sort_mode == "design_skill":
                return (
                    -float(r.get("design_skill_score") or 0),
                    -float(r.get("intrinsic_design_affinity") or 0),
                    -float(r.get("match_score") or 0),
                    wl(r),
                    digest,
                )
            use_ts = sort_mode == "tech_skill" and float(band[0].get("tech_skill_score") or 0) > 0
            if use_ts:
                return (
                    -float(r.get("tech_skill_score") or 0),
                    -float(r.get("match_score") or 0),
                    wl(r),
                    digest,
                )
            use_q = sort_mode == "testing_skill" and float(band[0].get("testing_skill_score") or 0) > 0
            if use_q:
                return (
                    -float(r.get("testing_skill_score") or 0),
                    -float(r.get("match_score") or 0),
                    wl(r),
                    digest,
                )
            return (
                -float(r.get("match_score") or 0),
                wl(r),
                digest,
            )

        return min(band, key=tie_key)

    def take_one(
        tracks: Optional[set[str]],
        bucket_key: str,
        sort_mode: str = "match",
    ) -> None:
        pool: list[Dict[str, Any]] = []
        for r in recs:
            did = str(r.get("developer_id") or "").strip()
            if not did or did in picked_ids:
                continue
            pt = str(r.get("primary_track") or "general")
            if tracks is not None and pt not in tracks:
                continue
            pool.append(r)
        best_r = _choose_from_pool(pool, bucket_key, sort_mode=sort_mode)
        if not best_r:
            return
        picked.append(best_r)
        picked_ids.add(str(best_r["developer_id"]))

    def take_design_slot(bucket_key: str) -> None:
        if not design_reqs:
            return
        pool: list[Dict[str, Any]] = []
        for relaxed in (False, True):
            pool = []
            for r in recs:
                did = str(r.get("developer_id") or "").strip()
                if not did or did in picked_ids:
                    continue
                if not _eligible_for_design_stratum(r, relaxed=relaxed):
                    continue
                pool.append(r)
            if pool:
                break
        if not pool:
            pool = [
                r
                for r in recs
                if str(r.get("developer_id") or "").strip()
                and str(r.get("developer_id") or "").strip() not in picked_ids
                and (
                    float(r.get("design_skill_score") or 0) > 0.5
                    or float(r.get("intrinsic_design_affinity") or 0) >= 0.35
                )
            ]
        best_r = _choose_from_pool(pool, bucket_key, sort_mode="design_skill")
        if not best_r:
            return
        picked.append(best_r)
        picked_ids.add(str(best_r["developer_id"]))

    if design_reqs and tech_reqs:
        if hard_design_mode:
            take_design_slot("d_a")
            take_design_slot("d_b")
            take_design_slot("d_c")
            if testing_n >= 1:
                take_one({"qa"}, "qa_a", sort_mode="testing_skill")
                take_one({"frontend"}, "fe", sort_mode="tech_skill")
            else:
                take_one({"frontend"}, "fe", sort_mode="tech_skill")
                take_one({"backend"}, "be", sort_mode="tech_skill")
        else:
            take_design_slot("d_a")
            take_design_slot("d_b")
            take_one({"frontend"}, "fe", sort_mode="tech_skill")
            take_one({"backend"}, "be", sort_mode="tech_skill")
        if wants_qa:
            take_one({"qa"}, "qa", sort_mode="testing_skill" if testing_n >= 1 else "match")
        else:
            take_one(None, "flex")
    elif design_reqs:
        if hard_design_mode:
            take_design_slot("d_a")
            take_design_slot("d_b")
            take_design_slot("d_c")
            if testing_n >= 1:
                take_one({"qa"}, "qa_d", sort_mode="testing_skill")
            else:
                take_one({"frontend", "design"}, "fe_d", sort_mode="design_skill")
            take_one(None, "flex")
        else:
            take_design_slot("d_a")
            take_design_slot("d_b")
            take_one({"frontend", "design"}, "fe_d", sort_mode="design_skill")
            take_one({"frontend", "general"}, "fe_g", sort_mode="match")
            take_one(None, "flex")
    else:
        take_one({"backend"}, "be_a")
        take_one({"frontend"}, "fe")
        if wants_qa:
            take_one({"qa"}, "qa", sort_mode="testing_skill" if testing_n >= 1 else "match")
        else:
            take_one({"data_ml"}, "ml")
        take_one({"backend"}, "be_b")
        take_one(None, "flex")

    fill_i = 0
    while len(picked) < 5:
        remaining = [
            r
            for r in recs
            if str(r.get("developer_id") or "").strip()
            and str(r.get("developer_id") or "").strip() not in picked_ids
        ]
        if not remaining:
            break
        best_r = _choose_from_pool(remaining, f"fill_{fill_i}")
        if not best_r:
            break
        picked.append(best_r)
        picked_ids.add(str(best_r["developer_id"]))
        fill_i += 1

    return picked[:5]


def _finalize_full_roster(
    recs: List[Dict[str, Any]],
    original_required_skills: List[str],
    task_counts: Optional[Dict[str, int]] = None,
    project_id: Optional[str] = None,
    max_size: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Stratified top-5 first (role diversity), then remaining developers by match score
    and workload — full cohort for PM approve / assign (not only five names).
    """
    if not recs:
        return []
    cap = max_size if max_size is not None else max_project_team_size()
    tc_map = task_counts or {}
    front = _finalize_top5_stratified(
        recs, original_required_skills, task_counts=tc_map, project_id=project_id
    )
    picked_ids = {str(r.get("developer_id") or "").strip() for r in front if r.get("developer_id")}
    rest = [
        r
        for r in recs
        if str(r.get("developer_id") or "").strip()
        and str(r.get("developer_id") or "").strip() not in picked_ids
    ]

    def _rest_key(r: Dict[str, Any]) -> tuple:
        wl = int(tc_map.get(str(r.get("developer_id") or ""), 0))
        return (-float(r.get("match_score") or 0), wl)

    rest.sort(key=_rest_key)
    return (front + rest)[:cap]


def expand_required_skills_for_matching(required_skills: List[str]) -> List[str]:
    """
    Widen requirement terms for vector/TF-IDF scoring only (does not change stored project.require_skills).
    When PM lists UX/Figma/Design skills, designers with related profile skills rank higher.
    """
    base = [str(s).strip() for s in (required_skills or []) if str(s).strip()]
    if not base:
        return base
    lower_blob = " ".join(b.lower() for b in base)
    triggers = (
        "design",
        "figma",
        "ux",
        "ui",
        "visual",
        "prototype",
        "wireframe",
        "system",
        "xd",
        "sketch",
        "tailwind",
        "css",
        "qa",
        "testing",
        "selenium",
        "postman",
        "bug",
    )
    extra: list[str] = []
    if any(t in lower_blob for t in triggers):
        extra = list(_DESIGN_MATCH_ALIASES + _TESTING_MATCH_ALIASES)
    seen: set[str] = set()
    out: list[str] = []
    for s in base + extra:
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out[:48]


def _dedupe_skills_case_insensitive(skills: List[Any]) -> List[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in skills or []:
        raw = str(s).strip()
        if not raw:
            continue
        k = raw.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(raw)
    return out


def _dedupe_ranked_recommendations(recs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    One row per developer_id, email, or normalized display name (best score first).
    """
    ordered = sorted(recs, key=lambda x: float(x.get("match_score") or 0), reverse=True)
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    seen_emails: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in ordered:
        did = str(r.get("developer_id") or "").strip()
        nm = _norm_person_name(str(r.get("name") or ""))
        em = normalize_identity_token(str(r.get("email") or ""))
        if did and did in seen_ids:
            continue
        if em and em in seen_emails:
            continue
        if nm and nm in seen_names:
            continue
        if did:
            seen_ids.add(did)
        if nm:
            seen_names.add(nm)
        if em:
            seen_emails.add(em)
        out.append(r)
    return out


class SkillMatcher:
    def __init__(self):
        self._tfidf = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))
        
        # Skill categories and weights
        self.skill_categories = {
            "programming_languages": 0.3,
            "frameworks": 0.25,
            "databases": 0.15,
            "tools": 0.15,
            "soft_skills": 0.1,
            "domain_knowledge": 0.05
        }
        
    def _extract_skill_names(self, skills: List[Any]) -> List[str]:
        """Normalize developer `skills` into a list of `skill_name` strings."""
        names: list[str] = []
        for s in skills or []:
            if isinstance(s, str):
                v = s.strip()
                if v:
                    names.append(v)
            elif isinstance(s, dict):
                n = s.get("skill_name")
                if n is not None:
                    v = str(n).strip()
                    if v:
                        names.append(v)
            else:
                n = getattr(s, "skill_name", None)
                if n is not None:
                    v = str(n).strip()
                    if v:
                        names.append(v)
        return names

    def calculate_skill_similarity(self, required_skills: List[str], developer_skills: List[str]) -> float:
        """Calculate similarity between required skills and developer skills"""
        if not required_skills or not developer_skills:
            return 0.0

        req_norm = [s.lower().strip() for s in required_skills]
        row_weights = np.array(
            [_char_row_weight_for_requirement(s) for s in req_norm],
            dtype=np.float64,
        )
        wsum = float(np.sum(row_weights)) or 1.0

        corpus = [s.lower().strip() for s in (required_skills + developer_skills)]
        vectors = self._tfidf.fit_transform(corpus)
        req_vectors = vectors[: len(required_skills)]
        dev_vectors = vectors[len(required_skills) :]

        similarity_matrix = cosine_similarity(req_vectors, dev_vectors)
        max_similarities = np.max(similarity_matrix, axis=1)
        weighted = float(np.dot(row_weights, max_similarities) / wsum)
        return weighted
    
    def calculate_experience_match(self, project_complexity: float, developer_experience: float) -> float:
        """
        Map years-of-experience to project difficulty. ``complexity_score`` is 0–100, not years —
        dividing years by it crushed juniors (e.g. 2/55) and hid designers unfairly.
        """
        c = float(project_complexity) if project_complexity is not None else 50.0
        years = float(developer_experience) if developer_experience is not None else 1.0
        c = max(25.0, min(90.0, c))
        expected_years = 0.9 + (c - 25.0) / 65.0 * 5.25
        if years >= expected_years:
            return 1.0
        ratio = years / expected_years
        return float(max(0.48, min(1.0, ratio)))
    
    def calculate_availability_score(self, developer_availability: bool, current_workload: int) -> float:
        """Calculate availability score"""
        if not developer_availability:
            return 0.0
        
        # Reduce score based on current workload
        workload_penalty = min(0.5, current_workload * 0.1)
        return 1.0 - workload_penalty
    
    def calculate_cgpa_score(self, cgpa: float) -> float:
        """Normalize CGPA score"""
        # Scale CGPA to 0-1 range (assuming 0-4 scale)
        return min(1.0, cgpa / 4.0)
    
    def calculate_performance_score(self, performance_history: List[float]) -> float:
        """Calculate performance score from history"""
        if not performance_history:
            return 0.7  # Default score
        
        # Weight recent performance more heavily
        weights = np.linspace(0.1, 1.0, len(performance_history))
        weights = weights / np.sum(weights)
        
        weighted_score = np.dot(performance_history, weights)
        return float(weighted_score / 5.0)  # Normalize to 0-1
    
    def match_developer_to_project(
        self,
        developer: Dict[str, Any],
        project: Dict[str, Any],
        required_skills: List[str],
        hard_design_mode: bool = False,
    ) -> Dict[str, Any]:
        """Match a single developer to a project"""
        
        # Calculate individual scores (design vs tech — mixed projects need designers in top picks)
        developer_skill_names = self._extract_skill_names(developer.get("skills", []))

        sk_explain = explain_sklearn_skill_match(
            required_skills, developer.get("skills", [])
        )
        char_sim = (
            0.0
            if hard_design_mode
            else self.calculate_skill_similarity(
                required_skills,
                developer_skill_names,
            )
        )
        vector_cos = float(sk_explain["vector_cosine_similarity"])
        baseline_combined = vector_cos if hard_design_mode else (0.55 * vector_cos + 0.45 * float(char_sim))

        design_reqs, tech_reqs = partition_design_and_tech_skills(required_skills)
        testing_reqs = [s for s in required_skills if _skill_is_testing_track(str(s).lower())]
        tech_reqs = [s for s in tech_reqs if not _skill_is_testing_track(str(s).lower())]
        design_combined = 0.0
        tech_combined = 0.0
        testing_combined = 0.0
        intrinsic_d = _intrinsic_design_affinity(developer_skill_names)
        avg_design_prof = _average_design_proficiency(developer.get("skills", []))
        avg_testing_prof = _average_testing_proficiency(developer.get("skills", []))
        testing_strength = _testing_profile_strength(developer_skill_names)
        early_test_n = _premium_testing_required_count(required_skills)

        if design_reqs and (tech_reqs or testing_reqs):
            sk_d = explain_sklearn_skill_match(design_reqs, developer.get("skills", []))
            char_d = (
                0.0
                if hard_design_mode
                else self.calculate_skill_similarity(design_reqs, developer_skill_names)
            )
            design_combined = float(sk_d["vector_cosine_similarity"]) if hard_design_mode else (0.55 * float(sk_d["vector_cosine_similarity"]) + 0.45 * float(char_d))
            if tech_reqs:
                sk_t = explain_sklearn_skill_match(tech_reqs, developer.get("skills", []))
                char_t = (
                    0.0
                    if hard_design_mode
                    else self.calculate_skill_similarity(tech_reqs, developer_skill_names)
                )
                tech_combined = float(sk_t["vector_cosine_similarity"]) if hard_design_mode else (0.55 * float(sk_t["vector_cosine_similarity"]) + 0.45 * float(char_t))
            if testing_reqs:
                sk_q = explain_sklearn_skill_match(testing_reqs, developer.get("skills", []))
                char_q = (
                    0.0
                    if hard_design_mode
                    else self.calculate_skill_similarity(testing_reqs, developer_skill_names)
                )
                testing_combined = (
                    float(sk_q["vector_cosine_similarity"])
                    if hard_design_mode
                    else (0.55 * float(sk_q["vector_cosine_similarity"]) + 0.45 * float(char_q))
                )
            # Never let ML noise zero out obvious designers when the project asks for UX/visual.
            design_combined = max(float(design_combined), intrinsic_d * 0.92)
            if intrinsic_d >= 0.5:
                design_combined = min(1.0, max(float(design_combined), 0.58))
            wd, wt, wq = float(len(design_reqs)), float(len(tech_reqs)), float(len(testing_reqs))
            # Effective slot count strongly favors design when SRS mixes UI stack with engineering.
            wd_eff = wd * 4.65
            wq_eff = wq * 5.05
            wsum = wd_eff + wt + wq_eff
            combined_skill_sim = (
                (wd_eff * design_combined + wt * tech_combined + wq_eff * testing_combined) / wsum if wsum else 0.0
            )
            n_tot = max(len(required_skills), 1)
            design_share = float(len(design_reqs)) / float(n_tot)
            prem_n = _premium_design_required_count(required_skills)
            test_n = _premium_testing_required_count(required_skills)
            design_intensity = min(1.0, prem_n / 5.0)
            testing_intensity = min(1.0, test_n / 5.0)
            combined_skill_sim = min(
                1.0,
                float(combined_skill_sim)
                + (0.16 + 0.06 * design_intensity)
                * design_share
                * float(design_combined)
                + 0.09 * design_share * float(intrinsic_d),
            )
            if test_n >= 1:
                combined_skill_sim = min(
                    1.0,
                    float(combined_skill_sim)
                    + 0.24 * testing_intensity * float(testing_combined)
                    + 0.12 * testing_intensity * float(testing_strength),
                )
            if intrinsic_d >= 0.42 and float(design_combined) >= 0.48:
                combined_skill_sim = max(
                    float(combined_skill_sim),
                    0.44 * float(design_combined) + 0.18 * float(tech_combined) + 0.12,
                )
            if prem_n >= 2 and intrinsic_d >= 0.35:
                combined_skill_sim = min(
                    1.0,
                    float(combined_skill_sim) + 0.05 * float(design_combined) * design_intensity,
                )
        elif design_reqs and not tech_reqs:
            combined_skill_sim = baseline_combined
            design_combined = max(float(baseline_combined), intrinsic_d * 0.92)
            if intrinsic_d >= 0.5:
                design_combined = min(1.0, max(float(design_combined), 0.55))
            combined_skill_sim = max(float(combined_skill_sim), float(design_combined) * 0.98)
        elif testing_reqs:
            sk_q = explain_sklearn_skill_match(testing_reqs, developer.get("skills", []))
            char_q = (
                0.0
                if hard_design_mode
                else self.calculate_skill_similarity(testing_reqs, developer_skill_names)
            )
            testing_combined = (
                float(sk_q["vector_cosine_similarity"])
                if hard_design_mode
                else (0.55 * float(sk_q["vector_cosine_similarity"]) + 0.45 * float(char_q))
            )
            combined_skill_sim = max(float(baseline_combined), 0.84 * float(testing_combined))
        else:
            combined_skill_sim = baseline_combined
            tech_combined = baseline_combined
            if tech_reqs and intrinsic_d >= 0.45:
                blob_req = " ".join(str(x).lower() for x in required_skills)
                if any(k in blob_req for k in ("react", "vue", "angular", "next", "frontend", "tailwind")):
                    combined_skill_sim = min(
                        1.0, float(combined_skill_sim) + 0.06 * intrinsic_d
                    )

        prem_test_n = _premium_testing_required_count(required_skills)
        intrinsic_q = _intrinsic_testing_affinity(developer_skill_names)
        if prem_test_n >= 1:
            testing_combined = max(
                float(testing_combined),
                float(intrinsic_q) * 0.92,
                float(testing_strength) * 0.88,
            )

        skill_score = combined_skill_sim
        # Developers with no skills entered still get a modest baseline so they can fill flex slots.
        if not developer_skill_names:
            skill_score = max(float(skill_score), 0.38)
            combined_skill_sim = skill_score

        primary_track = (
            _infer_primary_track(developer_skill_names) if developer_skill_names else "general"
        )

        experience_score = self.calculate_experience_match(
            project.get("complexity_score", 50),
            developer.get("experience_years", 1)
        )
        
        availability_score = self.calculate_availability_score(
            developer.get("availability", True),
            developer.get("current_workload", 0)
        )
        
        cgpa_score = self.calculate_cgpa_score(
            developer.get("cgpa", 2.5)
        )
        
        performance_score = self.calculate_performance_score(
            developer.get("performance_history", [3.5])
        )
        
        # Weight total toward skill match more when SRS explicitly lists design + engineering
        if design_reqs and tech_reqs:
            if early_test_n >= 2:
                weights = {
                    "skill": 0.60,
                    "experience": 0.12,
                    "availability": 0.11,
                    "cgpa": 0.09,
                    "performance": 0.08,
                }
            else:
                weights = {
                    "skill": 0.58,
                    "experience": 0.13,
                    "availability": 0.12,
                    "cgpa": 0.10,
                    "performance": 0.07,
                }
        elif design_reqs and not tech_reqs:
            weights = {
                "skill": 0.52,
                "experience": 0.15,
                "availability": 0.13,
                "cgpa": 0.12,
                "performance": 0.08,
            }
        elif early_test_n >= 2 and tech_reqs and not design_reqs:
            weights = {
                "skill": 0.54,
                "experience": 0.16,
                "availability": 0.13,
                "cgpa": 0.10,
                "performance": 0.07,
            }
        else:
            weights = {
                "skill": 0.4,
                "experience": 0.2,
                "availability": 0.15,
                "cgpa": 0.15,
                "performance": 0.1,
            }

        total_score = (
            skill_score * weights["skill"] +
            experience_score * weights["experience"] +
            availability_score * weights["availability"] +
            cgpa_score * weights["cgpa"] +
            performance_score * weights["performance"]
        )

        prem_n = _premium_design_required_count(required_skills)
        test_n = _premium_testing_required_count(required_skills)
        dcomb_for_boost = float(design_combined) if design_reqs else 0.0
        design_project_boost, design_dom_bonus = _design_project_boost_points(
            prem_n, intrinsic_d, dcomb_for_boost, avg_design_prof
        )
        testing_boost, testing_project_boost_base, testing_dom_bonus = _testing_boost_points(
            test_n, testing_combined, testing_strength, avg_testing_prof
        )
        match_score_pct = min(
            100.0, total_score * 100.0 + design_project_boost + testing_boost
        )

        # Legacy TF-IDF name matches (supplement vector explanations)
        matching_skills: list[str] = _dedupe_skills_case_insensitive(
            list(sk_explain.get("matching_skills_unique") or [])
        )
        dev_skills_lower = [s.lower() for s in developer_skill_names]
        for req_skill in required_skills:
            req_skill_lower = req_skill.lower()
            if req_skill_lower in dev_skills_lower:
                if req_skill_lower not in {x.lower() for x in matching_skills}:
                    matching_skills.append(req_skill)
            else:
                for dev_skill_name in developer_skill_names:
                    if self.are_skills_similar(req_skill, dev_skill_name):
                        if dev_skill_name.lower() not in {x.lower() for x in matching_skills}:
                            matching_skills.append(dev_skill_name)
                        break

        matching_skills = _dedupe_skills_case_insensitive(matching_skills)

        oid = developer.get("_id")
        dev_id = str(oid) if oid is not None else ""
        display_name = developer.get("full_name") or developer.get("name") or developer.get("username", "")
        dev_email = str(developer.get("email") or "").strip()
        conf = round(float(total_score), 4)
        result: Dict[str, Any] = {
            "developer_id": dev_id,
            "name": display_name,
            "email": dev_email,
            "confidence_score": conf,
            "match_score": round(match_score_pct, 2),
            "design_project_boost": round(design_project_boost, 2),
            "design_dominance_boost": round(design_project_boost, 2),
            "design_dominance_bonus": round(float(design_dom_bonus), 2),
            "testing_boost": round(float(testing_boost), 2),
            "testing_project_boost": round(float(testing_project_boost_base), 2),
            "testing_dominance_bonus": round(float(testing_dom_bonus), 2),
            "skills_match": matching_skills,
            "experience_match": float(experience_score),
            "availability": bool(developer.get("availability", True)),
            "cgpa": float(developer.get("cgpa") or 0),
            "contact": str(developer.get("contact") or ""),
            "skill_score": round(combined_skill_sim * 100, 2),
            "design_skill_score": round(design_combined * 100, 2) if design_reqs else 0.0,
            "tech_skill_score": round(tech_combined * 100, 2) if tech_reqs else 0.0,
            "testing_skill_score": round(testing_combined * 100, 2) if prem_test_n >= 1 else 0.0,
            "intrinsic_design_affinity": round(float(intrinsic_d), 4),
            "avg_design_proficiency": round(float(avg_design_prof), 3),
            "avg_testing_proficiency": round(float(avg_testing_prof), 3),
            "primary_track": primary_track,
            "availability_score": round(availability_score * 100, 2),
            "matching_skills": matching_skills,
            "all_skills": developer_skill_names,
            "current_workload": developer.get("current_workload", 0),
            "sklearn_vector_cosine": sk_explain["vector_cosine_similarity"],
            "char_based_skill_similarity": round(float(char_sim), 4),
            "match_explanation": sk_explain["matching_details"],
            "ranking_method": "sklearn_cosine_char_blend",
        }
        result["explanation"] = human_match_explanation(
            developer, required_skills, result
        )
        return result
    
    def are_skills_similar(self, skill1: str, skill2: str, threshold: float = 0.7) -> bool:
        """Check if two skills are similar using TF-IDF cosine similarity"""
        s1 = (skill1 or "").lower().strip()
        s2 = (skill2 or "").lower().strip()
        if not s1 or not s2:
            return False

        vectors = self._tfidf.fit_transform([s1, s2])
        similarity = cosine_similarity(vectors[0:1], vectors[1:2])[0][0]
        return float(similarity) > threshold
    
    def get_recommendations_sync(
        self,
        project_id: str,
        required_skills: List[str],
        developers: List[Dict[str, Any]],
        project_complexity: float = 50.0,
        cross_project_load: Optional[Dict[str, int]] = None,
        active_task_counts: Optional[Dict[str, int]] = None,
        max_open_tasks: int = 10,
    ) -> Dict[str, Any]:
        """
        CPU-heavy sklearn / TF-IDF path — run via ``asyncio.to_thread`` from ``get_recommendations``
        so the FastAPI event loop stays responsive for other requests.
        """
        project_data = {
            "complexity_score": project_complexity
        }
        req_for_scoring = expand_required_skills_for_matching(required_skills)
        hard_design_mode = _premium_design_required_count(required_skills) >= 1
        load_map = cross_project_load or {}
        task_map = active_task_counts or {}

        recommendations = []
        evaluated = 0
        seen_oids: set[str] = set()
        for developer in developers:
            if developer.get("role") != "developer":
                continue

            did = str(developer.get("_id") or "").strip()
            if not did or did in seen_oids:
                continue
            at_cap = max_open_tasks > 0 and int(task_map.get(did, 0)) >= max_open_tasks

            match_result = self.match_developer_to_project(
                developer,
                project_data,
                req_for_scoring,
                hard_design_mode=hard_design_mode,
            )
            seen_oids.add(did)
            evaluated += 1
            load = int(load_map.get(did, 0))
            old = float(match_result.get("match_score") or 0)
            if load > 0:
                pen = min(0.26, 0.065 * load)
                old = max(0.0, old * (1.0 - pen))
                match_result["cross_project_overlap"] = load
            else:
                old = min(100.0, old * 1.06)
            match_result["match_score"] = round(old, 2)
            if at_cap:
                match_result["at_active_task_cap"] = True

            recommendations.append(match_result)

        premium_design_n = _premium_design_required_count(required_skills)
        premium_testing_n = _premium_testing_required_count(required_skills)
        design_srs = premium_design_n >= 1
        testing_srs = premium_testing_n >= 1
        if not design_srs and not testing_srs:
            recommendations, rank_method = maybe_rerank_random_forest(recommendations)
            if rank_method == "sklearn_cosine_char_blend":
                try:
                    from app.ml.tensorflow_rank import rank_indices

                    scores = [float(r["match_score"]) for r in recommendations]
                    order = rank_indices(scores)
                    recommendations = [recommendations[i] for i in order]
                except Exception:
                    recommendations.sort(key=lambda x: x["match_score"], reverse=True)

        recommendations = _dedupe_ranked_recommendations(recommendations)
        if design_srs and testing_srs:
            apply_balanced_design_testing_ranking(recommendations, required_skills)
        elif testing_srs:
            apply_testing_first_ranking(recommendations, required_skills)
        elif design_srs or hard_design_mode:
            apply_design_first_ranking(recommendations, required_skills)
        cap = max_project_team_size()
        roster = _finalize_full_roster(
            recommendations,
            required_skills,
            task_counts=task_map,
            project_id=project_id,
            max_size=cap,
        )
        top_matches = list(
            dict.fromkeys(
                str(rec["developer_id"])
                for rec in roster
                if rec.get("developer_id")
            )
        )

        return {
            "project_id": project_id,
            "recommendations": roster,
            "top_matches": top_matches,
            "total_developers_evaluated": evaluated,
        }

    async def get_recommendations(
        self,
        project_id: str,
        required_skills: List[str],
        developers: List[Dict[str, Any]],
        project_complexity: float = 50.0,
        cross_project_load: Optional[Dict[str, int]] = None,
        active_task_counts: Optional[Dict[str, int]] = None,
        max_open_tasks: int = 10,
    ) -> Dict[str, Any]:
        """
        Get recommendations for a project.
        cross_project_load: developer_id -> count of other active projects where they already appear
        on assigned/final/recommended team (used to diversify AI picks across PMs).
        Developers at max_open_tasks active (non-completed / non-submitted) workload are skipped.

        Every developer document returned by the caller is evaluated (typically all available
        developers in the DB, not a short shortlist).
        """
        return await asyncio.to_thread(
            self.get_recommendations_sync,
            project_id,
            required_skills,
            developers,
            project_complexity,
            cross_project_load,
            active_task_counts,
            max_open_tasks,
        )