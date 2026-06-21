"""Regression tests for chatbot query coverage (English + Roman Urdu)."""
import asyncio

import pytest

from app.nlp.chat_engine import (
    _extract_project_hint,
    _extract_project_person_team_membership_query,
    _looks_like_list_projects_query,
    _roman_urdu_fold,
    answer_with_context,
)


def _sample_context():
    projects = [
        {
            "id": "p1",
            "title": "QuickBite",
            "status": "in_progress",
            "progress": 65,
            "deadline": "2026-05-01",
            "created_by": "u_pm",
            "assigned_team": ["u1", "u2"],
            "final_team": ["u1", "u2"],
        },
        {
            "id": "p2",
            "title": "KidsToy",
            "status": "active",
            "progress": 40,
            "deadline": "2026-06-15",
            "created_by": "u_pm",
            "assigned_team": ["u2"],
            "final_team": ["u2"],
        },
    ]
    tasks = [
        {
            "id": "t1",
            "title": "Figma UI design",
            "description": "Design app screens in Figma",
            "status": "completed",
            "assigned_to": "u1",
            "project_id": "p1",
            "skills_used": ["Figma", "UI"],
        },
        {
            "id": "t2",
            "title": "API integration",
            "description": "Connect frontend with backend APIs",
            "status": "in_progress",
            "assigned_to": "u2",
            "project_id": "p1",
            "skills_used": ["API Integration", "React"],
        },
    ]
    developers = [
        {"id": "u_pm", "full_name": "Rahim PM", "email": "rahim@example.com", "role": "manager"},
        {"id": "u1", "full_name": "Zain", "email": "zain@example.com", "role": "developer", "skills": ["Figma", "React"]},
        {"id": "u2", "full_name": "Shaheer", "email": "shaheer@example.com", "role": "developer", "skills": ["FastAPI", "MongoDB"]},
    ]
    user = {"id": "u_pm", "full_name": "Rahim PM", "skills": []}
    return user, tasks, projects, developers


def _ask(message: str) -> str:
    user, tasks, projects, developers = _sample_context()
    return _ask_with_context(message, user, tasks, projects, developers)


def _ask_with_context(
    message: str,
    user: dict,
    tasks: list[dict],
    projects: list[dict],
    developers: list[dict],
    activity_logs: list[dict] | None = None,
) -> str:
    return asyncio.run(
        answer_with_context(
            message,
            user=user,
            tasks=tasks,
            projects=projects,
            developers=developers,
            performance_snapshot=None,
            response_style=None,
            activity_logs=activity_logs if activity_logs is not None else [],
        )
    )


def test_extract_project_hint_core_variants():
    assert _extract_project_hint("KidsToy ka status kya hai?") == "KidsToy"
    assert _extract_project_hint("QuickBite ki deadline kab hai?") == "QuickBite"
    assert _extract_project_hint("QuickBite kis ne banaya?") == "QuickBite"
    assert _extract_project_hint("How many tasks on QuickBite?") == "QuickBite"


def test_list_projects_detection_plural_and_roman_urdu():
    q1 = "Saare projects dikhao"
    q2 = "running projects dikhao"
    assert _looks_like_list_projects_query(q1.lower(), _roman_urdu_fold(q1))
    assert _looks_like_list_projects_query(q2.lower(), _roman_urdu_fold(q2))


def test_extract_team_membership_english_variants():
    q1 = "Is Zain part of QuickBite team?"
    q2 = "Does QuickBite team include Zain?"
    assert _extract_project_person_team_membership_query(q1) == ("QuickBite", "Zain")
    assert _extract_project_person_team_membership_query(q2) == ("QuickBite", "Zain")


def test_answer_status_deadline_creator_and_task_count():
    status = _ask("What is the status of QuickBite?")
    deadline = _ask("QuickBite ki deadline kab hai?")
    creator = _ask("Who created QuickBite?")
    count = _ask("How many tasks on QuickBite?")
    assert "QuickBite" in status
    assert "deadline" in deadline.lower()
    assert "Rahim PM" in creator
    assert "tasks" in count.lower()


def test_answer_team_membership_and_module_completion_roman_urdu():
    team = _ask("Is Zain in QuickBite team?")
    figma = _ask("QuickBite project py figma waly task completed ha ya nai")
    assert "zain" in team.lower()
    assert any(x in team.lower() for x in ("yes", "haan"))
    assert "quickbite" in figma.lower()
    assert any(x in figma.lower() for x in ("figma", "completed", "done", "haan", "yes"))


def test_most_active_developer_spaced_sab_se_zyada_roman_urdu():
    """Regression: 'Sab se zyada active developer' must not fall through to neutral unmatched reply."""
    ans = _ask("Sab se zyada active developer kon hai?")
    low = ans.lower()
    assert "direct match nahi mila" not in low
    assert "active load" in low or "completed" in low
    assert any(x in low for x in ("zain", "shaheer"))


def test_most_completed_tasks_spaced_sab_se_zyada_roman_urdu():
    """Regression: Roman Urdu 'sab se zyada tasks kis ne complete' should hit leaderboard, not neutral fallback."""
    ans = _ask("Sab se zyada tasks kis ne complete kiye hain?")
    low = ans.lower()
    assert "direct match nahi mila" not in low
    assert "complete" in low or "done" in low


def test_most_active_developer_ignores_manager_activity_spam():
    """PM/manager must not win leaderboard from activity_logs while devs have real tasks."""
    user = {"id": "u_pm", "full_name": "Rahim PM", "skills": []}
    tasks = [
        {
            "id": "t1",
            "title": "API work",
            "description": "x",
            "status": "in_progress",
            "assigned_to": "u1",
            "project_id": "p1",
            "skills_used": ["FastAPI"],
        },
    ]
    projects = [
        {
            "id": "p1",
            "title": "DemoProj",
            "status": "active",
            "progress": 50,
            "deadline": "2026-06-01",
            "created_by": "u_pm",
            "assigned_team": ["u1"],
            "final_team": ["u1"],
        },
    ]
    developers = [
        {"id": "u_pm", "full_name": "Ghania Tanveer", "email": "pm@example.com", "role": "manager"},
        {"id": "u1", "full_name": "Zain Dev", "email": "z@example.com", "role": "developer"},
    ]
    activity_logs = [{"user_id": "u_pm"}] * 80
    ans = _ask_with_context(
        "Sab se zyada active developer kon hai?",
        user,
        tasks,
        projects,
        developers,
        activity_logs=activity_logs,
    )
    low = ans.lower()
    assert "ghania" not in low and "tanveer" not in low
    assert "zain" in low


@pytest.mark.parametrize(
    ("query", "expected_tokens"),
    [
        ("List all projects", ("projects", "quickbite")),
        ("running projects dikhao", ("projects", "quickbite")),
        ("Saare projects dikhao", ("projects", "kidstoy")),
        ("What is the status of QuickBite?", ("quickbite", "status")),
        ("QuickBite ka status kya hai?", ("quickbite", "status")),
        ("How is the project KidsToy going?", ("kidstoy", "status")),
        ("Quick summary of QuickBite", ("quickbite", "summary")),
        ("QuickBite ka summary jaldi batao", ("quickbite", "summary")),
        ("What is the deadline for QuickBite?", ("quickbite", "deadline")),
        ("QuickBite ki deadline kab hai?", ("quickbite", "deadline")),
        ("Who created QuickBite?", ("quickbite", "rahim")),
        ("QuickBite kis ne banaya?", ("quickbite", "rahim")),
        ("How many tasks on QuickBite?", ("quickbite", "tasks")),
        ("QuickBite par kitne tasks hain?", ("quickbite", "tasks")),
        ("Is Zain on QuickBite project team?", ("zain", "quickbite")),
        ("Does QuickBite team include Zain?", ("zain", "quickbite")),
        ("Who is working on QuickBite?", ("quickbite", "zain")),
        ("QuickBite py kon kam kar raha hai?", ("quickbite", "shaheer")),
        ("Open tasks in QuickBite?", ("quickbite", "open")),
        ("Who is responsible for API integration?", ("api", "shaheer")),
        ("Testing ka task kon kar raha hai?", ("testing", "assign")),
        ("Mere assigned tasks kya hain?", ("task",)),
        ("Mera next deadline kya hai?", ("deadline",)),
        ("Who knows React?", ("react", "zain")),
        ("Kis developer ko MongoDB skill hai?", ("mongodb", "shaheer")),
        ("What skills does Zain have?", ("zain", "figma")),
        ("Overall project performance kaisa hai?", ("project", "performance")),
        ("How are all our projects going?", ("quickbite", "kidstoy")),
        ("What can you help me with?", ("project", "deadline")),
        ("Kya kar sakte ho?", ("project", "tasks")),
    ],
)
def test_chatbot_wide_query_coverage(query: str, expected_tokens: tuple[str, ...]):
    answer = _ask(query).lower()
    for token in expected_tokens:
        assert token in answer, f"missing token '{token}' for query: {query}\nanswer: {answer}"


def test_dynamic_data_not_tied_to_specific_project_or_developer_names():
    user = {"id": "pm_a", "full_name": "Manager One", "skills": []}
    projects = [
        {
            "id": "px1",
            "title": "NovaFlow",
            "status": "active",
            "progress": 55,
            "deadline": "2026-09-20",
            "created_by": "pm_a",
            "assigned_team": ["dev_a", "dev_b"],
            "final_team": ["dev_a", "dev_b"],
        }
    ]
    tasks = [
        {
            "id": "tx1",
            "title": "Authentication API integration",
            "description": "Implement auth endpoints",
            "status": "in_progress",
            "assigned_to": "dev_b",
            "project_id": "px1",
            "skills_used": ["FastAPI", "MongoDB"],
        }
    ]
    developers = [
        {"id": "pm_a", "full_name": "Manager One", "email": "pm@example.com"},
        {"id": "dev_a", "full_name": "Areeba", "email": "areeba@example.com", "skills": ["React"]},
        {"id": "dev_b", "full_name": "Umair", "email": "umair@example.com", "skills": ["FastAPI", "MongoDB"]},
    ]

    status = _ask_with_context("NovaFlow ka status kya hai?", user, tasks, projects, developers).lower()
    creator = _ask_with_context("Who created NovaFlow?", user, tasks, projects, developers).lower()
    owner = _ask_with_context("Who is responsible for API integration?", user, tasks, projects, developers).lower()

    assert "novaflow" in status
    assert "manager one" in creator
    assert "umair" in owner
    assert "fittrack" not in (status + creator + owner)
    assert "quickbite" not in (status + creator + owner)


def test_gender_aware_person_module_completion_reply():
    user = {"id": "pm1", "full_name": "Manager", "skills": []}
    projects = [
        {
            "id": "p1",
            "title": "DesignHub",
            "status": "active",
            "progress": 70,
            "deadline": "2026-08-01",
            "created_by": "pm1",
            "assigned_team": ["u_f", "u_m"],
            "final_team": ["u_f", "u_m"],
        }
    ]
    tasks = [
        {
            "id": "t_f",
            "title": "Figma screens",
            "description": "Figma workflow and screens",
            "status": "completed",
            "assigned_to": "u_f",
            "project_id": "p1",
            "skills_used": ["Figma"],
        },
        {
            "id": "t_m",
            "title": "API integration",
            "description": "Integrate APIs",
            "status": "completed",
            "assigned_to": "u_m",
            "project_id": "p1",
            "skills_used": ["API Integration"],
        },
    ]
    developers = [
        {"id": "pm1", "full_name": "Manager"},
        {"id": "u_f", "full_name": "Eman", "gender": "female"},
        {"id": "u_m", "full_name": "Haseeb", "gender": "male"},
    ]

    female = _ask_with_context(
        "Eman ne figma ka task kiya hai kya?",
        user,
        tasks,
        projects,
        developers,
    ).lower()
    male = _ask_with_context(
        "Haseeb ne api integration ka task kiya hai kya?",
        user,
        tasks,
        projects,
        developers,
    ).lower()

    assert "eman ne" in female
    assert "kar di hai" in female
    assert "haseeb ne" in male
    assert "kar diya hai" in male
