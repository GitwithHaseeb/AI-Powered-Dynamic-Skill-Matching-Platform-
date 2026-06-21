"""
Dynamic, project-specific task descriptions (Jira-style: intro + key considerations + closing).
All sentences are composed from Mongo project/task fields only.
"""
from __future__ import annotations

import re
from typing import Any, Optional


def _truncate_context(text: str, max_chars: int = 700) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return ""
    if len(t) <= max_chars:
        return t
    cut = t[:max_chars].rsplit(" ", 1)[0]
    return (cut or t[:max_chars]).rstrip(".,; ") + "…"


def _strip_title_suffix(title: str) -> str:
    t = (title or "").strip()
    return re.sub(r"\s*\(\d+\)\s*$", "", t).strip()


def _core_theme(title: str) -> str:
    t = _strip_title_suffix(title)
    t = re.sub(r"^\s*implement\s+", "", t, flags=re.I).strip()
    return t or _strip_title_suffix(title) or (title or "").strip()


def _uniq_preserve(items: list[str], cap: int = 16) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in items:
        s = str(x).strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= cap:
            break
    return out


def _first_sentence(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    for sep in ".!?\n":
        if sep in t:
            idx = t.find(sep)
            return t[: idx + 1].strip()
    return t[:200] + ("…" if len(t) > 200 else "")


def build_project_specific_task_description(
    project: dict[str, Any],
    task_title: str,
    skills_used: Optional[list[str]] = None,
) -> str:
    """
    Build a long-form, Jira-style description:
    - Opening paragraphs (project + task + SRS excerpt)
    - "Key considerations" with • **Label:** lines (labels from skills/require_skills)
    - Closing objective tied to project title
    """
    raw_title = str(project.get("title") or "").strip()
    pid = str(project.get("_id") or "").strip()
    p_title = raw_title or (pid if pid else "Project")

    t_full = _strip_title_suffix(str(task_title or "").strip()) or "Task"
    theme = _core_theme(t_full)

    req = _uniq_preserve([str(x) for x in (project.get("require_skills") or [])])
    skills_in = _uniq_preserve([str(x) for x in (skills_used or [])])
    skills = skills_in[:] if skills_in else req[:]
    if skills_in and req:
        skills = _uniq_preserve(skills_in + [x for x in req if x not in skills_in])

    dept = str(project.get("department") or "").strip()
    body_full = str(project.get("description") or "").strip()
    body = _truncate_context(body_full)
    body_first = _first_sentence(body_full) if body_full else ""

    req_join = ", ".join(req) if req else ""
    skills_join = ", ".join(skills) if skills else req_join

    # --- Intro (2 blocks, like Jira body copy) ---
    intro_a = (
        f"Work under «{t_full}» for «{p_title}» focuses on «{theme}»: design or implement the pieces needed "
        f"so this project’s features stay coherent, testable, and ready for review."
    )
    if body:
        intro_b = (
            f"From the project description on file: {body}"
        )
    elif req_join:
        intro_b = (
            f"Registered capability expectations for «{p_title}» include: {req_join}. "
            f"Your deliverables should map clearly to those areas."
        )
    else:
        intro_b = (
            f"Align implementation with «{p_title}» milestones and the agreed scope for «{theme}»."
        )

    # --- Key considerations: one bullet per skill (or req), labels = data ---
    bullet_sources = skills if skills else (req if req else [theme])
    bullets: list[str] = []
    action_rot = (
        "Deliver",
        "Verify",
        "Document",
        "Integrate",
        "Validate",
    )
    for i, item in enumerate(bullet_sources[:8]):
        act = action_rot[i % len(action_rot)]
        bullets.append(
            f"• **{item}:** {act} {item} for «{p_title}» with review-ready outputs (code, tests, or assets as applicable)."
        )

    if body_first and body:
        bullets.insert(
            0,
            f"• **Specification context:** {body_first} Apply this context when scoping acceptance criteria for «{theme}».",
        )

    if dept:
        bullets.append(
            f"• **{dept} — delivery norms:** Follow applicable standards and review practices for «{dept}» when shipping work for «{p_title}»."
        )

    if not bullets:
        bullets.append(
            f"• **Deliverables:** Complete «{theme}» for «{p_title}» with verifiable outputs and brief notes for reviewers."
        )

    considerations = "Key considerations\n\n" + "\n".join(bullets)

    # --- Closing (like the Cookie example outro) ---
    outro = (
        f"Overall, finishing «{t_full}» should move «{p_title}» forward with clear, integrated outcomes "
        f"that stakeholders can validate against the project brief"
        + (f" and the areas: {skills_join}." if skills_join else ".")
    )

    parts = [intro_a, intro_b, "", considerations, "", outro]
    text = "\n\n".join(parts).strip()
    return text
