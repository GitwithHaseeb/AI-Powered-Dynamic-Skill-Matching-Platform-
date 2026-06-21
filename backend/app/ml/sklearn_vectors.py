"""
Scikit-learn skill matching (SDS §1.3.2 Objectives, §2.2 Functional Description).

Uses explicit feature vectors (multi-hot requirements × proficiency-weighted developer
skills) and cosine similarity, with optional RandomForest re-ranking over a small feature set.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any, List

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.ensemble import RandomForestRegressor

# --- Design-aware synonyms (SRS often says "Tailwind CSS"; profiles say "Tailwind") -------
_DESIGN_EQUIV_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"tailwind css", "tailwind", "tailwindcss"}),
    # UI Design ↔ UI / User Interface (canonical key = min(...) for stable vocab)
    frozenset(
        {
            "ui design",
            "user interface design",
            "user interface",
            "ui",
            "frontend design",
        }
    ),
    frozenset(
        {
            "ux design",
            "user experience design",
            "user experience",
            "ux",
        }
    ),
    frozenset({"visual design", "ui visual", "visual"}),
    frozenset({"figma"}),
    frozenset({"design systems", "design system"}),
    frozenset({"adobe xd", "xd"}),
    frozenset({"sketch"}),
    frozenset({"wireframe", "wireframing"}),
    frozenset({"prototype", "prototyping"}),
)

_TESTING_EQUIV_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"manual testing", "manual test", "manual tester"}),
    frozenset(
        {
            "automation testing",
            "automation test",
            "selenium testing",
            "automated testing",
            "test automation",
        }
    ),
    frozenset({"api testing", "api test", "postman", "postman api"}),
    frozenset({"bug tracking", "bug report", "bug fixing"}),
    frozenset({"qa testing", "qa", "quality assurance", "qa engineer"}),
    frozenset({"test cases", "test case"}),
    frozenset({"selenium", "selenium webdriver", "webdriver"}),
)

# Premium SRS rows: ~3.5–4× stronger emphasis vs non-design dims (see _term_dimension_weight).
_PREMIUM_DESIGN_FRAGMENTS = (
    "figma",
    "ux design",
    "ui design",
    "visual design",
    "design system",
    "design systems",
)

_SECONDARY_DESIGN_FRAGMENTS = (
    "sketch",
    "xd",
    "wireframe",
    "prototype",
    "usability",
    "tailwind",
    "css",
    "sass",
    "scss",
    "adobe xd",
)

_FIGMA_SUPER_MULTIPLIER = 3.0

_PREMIUM_TESTING_FRAGMENTS = (
    "qa testing",
    "automation testing",
    "api testing",
    "manual testing",
    "selenium",
    "postman",
    "bug tracking",
    "test case",
    "test cases",
    "quality assurance",
    "automated testing",
    "test automation",
    "webdriver",
)


def _term_dimension_weight(term: str) -> float:
    """
    Per-dimension weight before sqrt in weighted cosine.
    Target ~5–6× emphasis vs tech (weight 1): use ~25–36 so sqrt ratio ≈5–6.
    """
    t = str(term).strip().lower()
    if not t:
        return 1.0
    if "figma" in t:
        return 42.0 * _FIGMA_SUPER_MULTIPLIER
    # Premium testing: match design-tier emphasis (~32–36 ⇒ sqrt ratio ~5.6–6× vs weight 1.0).
    if any(f in t for f in _PREMIUM_TESTING_FRAGMENTS):
        return 36.0
    if any(f in t for f in _PREMIUM_DESIGN_FRAGMENTS):
        return 32.0
    if any(f in t for f in _SECONDARY_DESIGN_FRAGMENTS):
        return 11.0
    return 1.0


def _is_design_weighted_term(term: str) -> bool:
    return _term_dimension_weight(term) > 1.01


def _is_testing_weighted_term(term: str) -> bool:
    t = str(term).strip().lower()
    return bool(t) and any(f in t for f in _PREMIUM_TESTING_FRAGMENTS)


def _canonical_skill_key(raw: str) -> str:
    """Collapse equivalent labels (e.g. Tailwind CSS ↔ tailwind) to one vector dimension."""
    k = str(raw).strip().lower()
    if not k:
        return k
    for g in _DESIGN_EQUIV_GROUPS:
        if k in g:
            return min(g)
    for g in _TESTING_EQUIV_GROUPS:
        if k in g:
            return min(g)
    return k


def _fuzzy_threshold_for_requirement(req: str, default: float) -> float:
    """Slightly looser string match for design labels so "UX Design" ↔ "ux design" always fires."""
    if _is_design_weighted_term(req):
        return min(default, 0.52)
    if _is_testing_weighted_term(req):
        return min(default, 0.54)
    return default


def _spread_design_profile_aliases(m: dict[str, float]) -> None:
    """Copy proficiency across equivalent labels so 'UI' / 'Figma' profiles hit SRS wording."""
    for g in _DESIGN_EQUIV_GROUPS:
        mx = max((m.get(k, 0.0) for k in g), default=0.0)
        if mx <= 0:
            continue
        for k in g:
            m[k] = max(m.get(k, 0.0), mx)
    fk = "figma"
    if fk in m and m[fk] > 0:
        m[fk] = min(1.0, m[fk] * 1.15)
    for g in _TESTING_EQUIV_GROUPS:
        mx = max((m.get(k, 0.0) for k in g), default=0.0)
        if mx <= 0:
            continue
        for k in g:
            m[k] = max(m.get(k, 0.0), mx)


def _proficiency_map_from_skills(skills: List[Any]) -> dict[str, float]:
    """Map canonical + raw skill name -> max proficiency in [0, 1] (level/5)."""
    m: dict[str, float] = {}
    for s in skills or []:
        if isinstance(s, dict) and s.get("skill_name"):
            k = str(s["skill_name"]).strip().lower()
            if not k:
                continue
            lvl = float(s.get("proficiency_level") or 1.0) / 5.0
            lvl = min(1.0, lvl)
            canon = _canonical_skill_key(k)
            m[canon] = max(m.get(canon, 0.0), lvl)
            if k != canon:
                m[k] = max(m.get(k, 0.0), lvl)
        elif isinstance(s, str) and s.strip():
            k = s.strip().lower()
            canon = _canonical_skill_key(k)
            v = 0.25
            m[canon] = max(m.get(canon, 0.0), v)
            if k != canon:
                m[k] = max(m.get(k, 0.0), v)
    _spread_design_profile_aliases(m)
    return m


def explain_sklearn_skill_match(
    required_skills: List[str],
    developer_skills: List[Any],
    fuzzy_threshold: float = 0.62,
) -> dict[str, Any]:
    """
    Build explainable match evidence using cosine similarity on shared vocabulary vectors
    (SDS §1.3.2 — transparent AI / skill matching).

    Design-related requirements (Figma, UX/UI, Tailwind CSS, …) use:
    - Canonical aliases so SRS labels align with developer profile strings
    - Higher dimension weights in cosine so UX/UI fit is not washed out by a long tech list
    """
    prof_map = _proficiency_map_from_skills(developer_skills)
    req_l_raw = [str(r).strip() for r in (required_skills or []) if str(r).strip()]
    req_l = [_canonical_skill_key(r) for r in req_l_raw]
    if not req_l:
        return {
            "vector_cosine_similarity": 0.0,
            "matching_details": [],
            "matching_skills_unique": [],
        }

    vocab = sorted(set(req_l) | set(prof_map.keys()))
    if not vocab:
        return {
            "vector_cosine_similarity": 0.0,
            "matching_details": [],
            "matching_skills_unique": [],
        }

    req_set = set(req_l)
    dim_w = np.array(
        [_term_dimension_weight(term) ** 0.5 for term in vocab],
        dtype=np.float64,
    )
    proj_raw = np.array([[1.0 if term in req_set else 0.0 for term in vocab]], dtype=np.float64)
    dev_raw = np.array([[prof_map.get(term, 0.0) for term in vocab]], dtype=np.float64)
    proj_vec = proj_raw * dim_w
    dev_vec = dev_raw * dim_w

    pn = float(np.linalg.norm(proj_vec))
    dn = float(np.linalg.norm(dev_vec))
    if pn < 1e-12 or dn < 1e-12:
        vec_sim = 0.0
    else:
        vec_sim = float(cosine_similarity(proj_vec, dev_vec)[0, 0])

    matching_details: list[dict[str, Any]] = []
    matched_labels: list[str] = []

    for r_raw, r in zip(req_l_raw, req_l):
        thresh = _fuzzy_threshold_for_requirement(r, fuzzy_threshold)
        if r in prof_map:
            matching_details.append(
                {
                    "required_skill": r_raw,
                    "matched_developer_skill": r,
                    "match_type": "exact",
                    "weight": round(prof_map[r], 3),
                }
            )
            matched_labels.append(r)
            continue
        # Synonym group: any prof key in same equivalence group counts as exact
        hit_syn = False
        for g in (_DESIGN_EQUIV_GROUPS + _TESTING_EQUIV_GROUPS):
            if r not in g:
                continue
            for k, val in prof_map.items():
                if k in g or _canonical_skill_key(k) in g:
                    matching_details.append(
                        {
                            "required_skill": r_raw,
                            "matched_developer_skill": k,
                            "match_type": "alias",
                            "weight": round(val, 3),
                        }
                    )
                    matched_labels.append(k)
                    hit_syn = True
                    break
            if hit_syn:
                break
        if hit_syn:
            continue
        best_k, best_ratio = "", 0.0
        for k in prof_map:
            ratio = SequenceMatcher(None, r, k).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_k = k
        if best_ratio >= thresh:
            wmul = 1.22 if ("figma" in r or "figma" in best_k) else 1.0
            if wmul < 1.12 and (_is_testing_weighted_term(r) or _is_testing_weighted_term(best_k)):
                wmul = 1.12
            matching_details.append(
                {
                    "required_skill": r_raw,
                    "matched_developer_skill": best_k,
                    "match_type": "fuzzy",
                    "string_similarity": round(best_ratio, 3),
                    "weight": round(min(1.0, prof_map[best_k] * best_ratio * wmul), 3),
                }
            )
            matched_labels.append(best_k)

    unique_match = list(dict.fromkeys(matched_labels))
    return {
        "vector_cosine_similarity": round(vec_sim, 4),
        "matching_details": matching_details,
        "matching_skills_unique": unique_match,
    }


def maybe_rerank_random_forest(
    recommendations: List[dict[str, Any]],
    min_devs: int = 4,
) -> tuple[List[dict[str, Any]], str]:
    """
    Optional second-stage ranking (SDS §1.3.2 — ensemble / RF on skill features).
    Trained on-the-fly per request from the current candidate matrix (demo-safe).
    """
    if len(recommendations) < min_devs:
        return recommendations, "sklearn_cosine_char_blend"

    X = []
    y = []
    for r in recommendations:
        X.append(
            [
                float(r.get("sklearn_vector_cosine") or 0),
                float(r.get("skill_score") or 0) / 100.0,
                float(r.get("design_skill_score") or 0) / 100.0,
                float(r.get("tech_skill_score") or 0) / 100.0,
                float(r.get("intrinsic_design_affinity") or 0),
                float(r.get("experience_match") or 0),
                float(r.get("availability_score") or 0) / 100.0,
                float(r.get("cgpa") or 0) / 4.0,
            ]
        )
        y.append(float(r.get("match_score") or 0))
    X_arr = np.asarray(X, dtype=np.float64)
    y_arr = np.asarray(y, dtype=np.float64)
    try:
        rf = RandomForestRegressor(
            n_estimators=48,
            max_depth=6,
            random_state=42,
        )
        rf.fit(X_arr, y_arr)
        preds = rf.predict(X_arr)
        order = np.argsort(-preds)
        out = [recommendations[int(i)] for i in order]
        for r in out:
            r["ranking_method"] = "sklearn_random_forest_rerank+cosine_vectors"
        return out, "sklearn_random_forest_rerank+cosine_vectors"
    except Exception:
        return recommendations, "sklearn_cosine_char_blend"
