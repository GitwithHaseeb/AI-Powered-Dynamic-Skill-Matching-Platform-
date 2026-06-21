"""
Human-readable match summaries for API responses (SDS demo / frontend one-liners).
"""
from __future__ import annotations

from typing import Any, Dict, List


# If any of these appear in matches, treat the gap label as covered (related UX/UI surface).
_GAP_SATISFIED_BY: dict[str, tuple[str, ...]] = {
    "visual design": ("figma", "sketch", "ux", "ui", "wireframe", "prototype", "adobe xd"),
    "ux design": ("figma", "usability", "user experience", "ui design", "wireframe", "prototype"),
    "ui design": ("figma", "ux design", "visual design", "tailwind", "css"),
    "tailwind": ("css", "scss", "sass", "html", "react", "javascript", "typescript"),
    "css": ("tailwind", "scss", "sass", "html", "material-ui", "mui"),
}


def _proficiency_by_skill(developer: Dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for s in developer.get("skills") or []:
        if isinstance(s, dict) and s.get("skill_name"):
            k = str(s["skill_name"]).strip()
            if k:
                out[k.lower()] = float(s.get("proficiency_level") or 1.0)
    return out


def human_match_explanation(
    developer: Dict[str, Any],
    required_skills: List[str],
    match_result: Dict[str, Any],
) -> str:
    """
    One-line narrative for PM dashboard / defense, e.g.:
    "Alice: 92% match — Strong in React (5.0) and MongoDB (4.0); gap: TensorFlow."
    """
    name = (match_result.get("name") or "Developer").strip() or "Developer"
    pct = int(round(float(match_result.get("match_score") or 0)))

    prof = _proficiency_by_skill(developer)
    matching: list[str] = list(dict.fromkeys(match_result.get("matching_skills") or []))

    strong_bits: list[str] = []
    seen_lower: set[str] = set()
    for sk in matching[:12]:
        lk = sk.strip().lower()
        if lk in seen_lower:
            continue
        seen_lower.add(lk)
        key = sk.strip().lower()
        lvl = prof.get(key)
        if lvl is None:
            for pk, pv in prof.items():
                if pk == key or key in pk or pk in key:
                    lvl = pv
                    break
        if lvl is not None:
            strong_bits.append(f"{sk} ({lvl:.1f})")
        else:
            strong_bits.append(sk)
        if len(strong_bits) >= 5:
            break

    if not strong_bits:
        strong_str = "relevant profile overlap"
    elif len(strong_bits) <= 2:
        strong_str = " and ".join(strong_bits)
    else:
        strong_str = ", ".join(strong_bits[:-1]) + ", and " + strong_bits[-1]

    # Required skills not clearly covered by matched labels (simple set diff on normalized names)
    req_clean = [str(r).strip() for r in required_skills if str(r).strip()]
    matched_l = {m.lower() for m in matching}
    gaps: list[str] = []
    for r in req_clean:
        rl = r.lower()
        if rl in matched_l:
            continue
        if any(rl in ml or ml in rl for ml in matched_l):
            continue
        ok_related = False
        for alias in _GAP_SATISFIED_BY.get(rl, ()):
            if alias in matched_l or any(alias in ml or ml in alias for ml in matched_l):
                ok_related = True
                break
        if ok_related:
            continue
        gaps.append(r)

    if not gaps:
        tail = "covers the current project skill list well."
    elif len(gaps) == 1:
        tail = f"missing only {gaps[0]}."
    else:
        tail = f"gaps to strengthen: {', '.join(gaps[:4])}{'…' if len(gaps) > 4 else ''}."

    return f"{name}: {pct}% match — Strong in {strong_str}; {tail}"
