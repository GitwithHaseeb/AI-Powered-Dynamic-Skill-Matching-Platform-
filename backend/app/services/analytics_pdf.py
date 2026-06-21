"""
PDF exports for analytics: performance report and skill gap analysis (ReportLab).
"""
from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _esc(s: Any) -> str:
    x = str(s if s is not None else "")
    return (
        x.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _display_txt(s: Any) -> str:
    """Table cells: never show Python null or the literal 'none'."""
    if s is None:
        return "—"
    t = str(s).strip()
    if not t or t.lower() in ("none", "null", "undefined"):
        return "—"
    return t


def _skill_gap_developers_cell(s: Any) -> str:
    """Skill gap column: N: Name (x.x), … from API — block legacy error strings from cached PDFs."""
    t = _display_txt(s)
    if t == "—":
        return "0: (names unavailable)"
    low = t.lower()
    if any(
        x in low
        for x in (
            "no developer profiles",
            "profiles in users",
            "developer profiles in",
            "no profile match",
            "no user documents",
            "api connection",
            "database for this api",
            "0: team",
            "0: developer",
        )
    ):
        return "0: (names unavailable)"
    return t


PDF_REPORT_FORMAT_VERSION = "v30"  # rank tier-only; no Developer placeholder in skill-gap cells


def _period_caption(period: str) -> str:
    p = (period or "month").strip().lower()
    return {
        "week": "Rolling window: last 7 days (task activity in range)",
        "month": "Rolling window: last 30 days (task activity in range)",
        "quarter": "Rolling window: last 90 days (task activity in range)",
        "all": "All time (full task history)",
    }.get(p, p)


def build_performance_report_pdf(data: Dict[str, Any]) -> bytes:
    """Structured PDF: title, period, developer table, project table."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="Performance Report",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        name="PdfTitle",
        parent=styles["Title"],
        fontSize=20,
        spaceAfter=8,
        textColor=colors.HexColor("#0f172a"),
    )
    h2 = ParagraphStyle(
        name="PdfH2",
        parent=styles["Heading2"],
        fontSize=13,
        spaceBefore=16,
        spaceAfter=10,
        textColor=colors.HexColor("#1e3a5f"),
    )
    body = ParagraphStyle(
        name="PdfBody",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
    )
    period = data.get("period") or "month"
    story: list[Any] = []
    story.append(Paragraph("Performance Report", title_style))
    story.append(
        Paragraph(
            f"<font color='#b45309'><b>Report build {PDF_REPORT_FORMAT_VERSION}</b></font> — "
            f"Projects table uses <b>status + progress columns</b> (no separate Result column). "
            f"If layout differs, the app may be using a different API URL/port.",
            ParagraphStyle(
                name="PdfVerifyPerf",
                parent=body,
                fontSize=9,
                leading=12,
                spaceAfter=6,
                textColor=colors.HexColor("#9a3412"),
            ),
        )
    )
    story.append(
        Paragraph(
            f"<b>Report type:</b> Organization performance — developers and projects<br/>"
            f"<b>Selected period:</b> {_esc(period)} — {_esc(_period_caption(period))}<br/>"
            f"<b>Generated (UTC):</b> {_esc(data.get('generated_at'))}<br/>"
            f"<font size=8 color=\"#64748b\"><b>PDF format {PDF_REPORT_FORMAT_VERSION}</b> — "
            f"<b>Active / In progress</b> from tasks collection; "
            f"<b>Rank</b> = Excellent / Average / No tasks (any completed work is Average or better).</font>",
            body,
        )
    )
    ps, pe = data.get("period_start"), data.get("period_end")
    if ps:
        story.append(
            Paragraph(
                f"<b>Time bounds:</b> {_esc(ps)} through {_esc(pe)}",
                body,
            )
        )
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph("1. Developer performance", h2))
    story.append(
        Paragraph(
            "Per-developer task counts follow the same period rules as the API "
            "(scoped counts when a rolling window is selected).",
            body,
        )
    )
    story.append(Spacer(1, 3 * mm))

    cell_small = ParagraphStyle(
        name="PerfCell",
        parent=body,
        fontSize=8,
        leading=10,
    )
    dev_header = [
        "Name",
        "Email",
        "Tasks (scope)",
        "Done",
        "Active",
        "In progress",
        "Rank",
    ]
    dev_rows: list[list[Any]] = [dev_header]

    def _results_cell(drow: Dict[str, Any]) -> Paragraph:
        done_n = int(drow.get("tasks_completed") or drow.get("performance_rank_completed") or 0)
        disp = _display_txt(drow.get("performance_display") or drow.get("performance_label"))
        dl = str(disp).strip().lower()
        try:
            sc = int(drow.get("performance_score_pct") or drow.get("performance_score") or -1)
        except (TypeError, ValueError):
            sc = -1
        looks_like_score = (
            not dl
            or dl == "—"
            or "score" in dl
            or dl.isdigit()
            or (sc >= 0 and str(disp).strip() == str(sc))
        )
        if done_n > 0 and (
            dl in ("no tasks", "—", "-") or "no task" in dl or looks_like_score
        ):
            disp = "Average"
        if (disp == "—" or looks_like_score) and done_n > 0:
            disp = "Average"
        if done_n <= 0 and looks_like_score:
            disp = "No tasks"
        return Paragraph(f"<b>{_esc(disp)}</b>", cell_small)

    for d in data.get("developers") or []:
        dev_rows.append(
            [
                Paragraph(_esc(_display_txt(d.get("full_name"))), cell_small),
                Paragraph(_esc(_display_txt(d.get("email"))), cell_small),
                str(_display_txt(d.get("tasks_total"))),
                str(_display_txt(d.get("tasks_completed"))),
                str(_display_txt(d.get("tasks_active"))),
                str(_display_txt(d.get("tasks_in_progress"))),
                _results_cell(d),
            ]
        )
    if len(dev_rows) == 1:
        dev_rows.append(
            [
                Paragraph("—", cell_small),
                Paragraph("No developers in database", cell_small),
                "",
                "",
                "",
                "",
                "",
            ]
        )

    tw = doc.width
    dev_col = [
        tw * 0.16,
        tw * 0.20,
        tw * 0.10,
        tw * 0.08,
        tw * 0.09,
        tw * 0.10,
        tw * 0.27,
    ]
    t_dev = Table(dev_rows, colWidths=dev_col, repeatRows=1)
    t_dev.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (2, 0), (5, -1), "RIGHT"),
                ("ALIGN", (6, 0), (6, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t_dev)
    story.append(Spacer(1, 2 * mm))
    story.append(
        Paragraph(
            "<b>Done</b>, <b>Active</b>, and <b>In progress</b> use the <b>maximum</b> of Mongo aggregation and "
            "Python scans on live tasks (period + all-time where applicable). "
            "<b>Rank</b> is Excellent / Average / No tasks — developers with completed tasks are Average or better.",
            ParagraphStyle(
                name="PerfFoot",
                parent=body,
                fontSize=7,
                leading=10,
                textColor=colors.HexColor("#475569"),
            ),
        )
    )
    story.append(Spacer(1, 8 * mm))

    story.append(Paragraph("2. Projects", h2))
    story.append(
        Paragraph(
            "Project completion rates and task totals; team size from assigned or final team.",
            body,
        )
    )
    story.append(Spacer(1, 3 * mm))

    proj_cell = ParagraphStyle(
        name="ProjCell",
        parent=body,
        fontSize=8,
        leading=10,
    )
    proj_header = [
        "Project",
        "Status",
        "Progress %",
        "Completion %",
        "Tasks (done / total)",
        "Team size",
    ]
    proj_rows: list[list[Any]] = [proj_header]

    for p in data.get("projects") or []:
        proj_rows.append(
            [
                Paragraph(_esc(p.get("project_title") or "—"), proj_cell),
                Paragraph(_esc(p.get("project_status") or "—"), proj_cell),
                f"{p.get('progress_pct', 0)}%",
                f"{p.get('task_completion_pct', 0)}%",
                f"{p.get('tasks_completed', 0)} / {p.get('tasks_total', 0)}",
                str(p.get("team_size", "—")),
            ]
        )
    if len(proj_rows) == 1:
        proj_rows.append(
            [
                Paragraph("—", proj_cell),
                Paragraph("No projects in database", proj_cell),
                "",
                "",
                "",
                "",
            ]
        )

    proj_col = [
        tw * 0.28,
        tw * 0.12,
        tw * 0.10,
        tw * 0.12,
        tw * 0.22,
        tw * 0.16,
    ]
    t_proj = Table(proj_rows, colWidths=proj_col, repeatRows=1)
    t_proj.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (2, 0), (5, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t_proj)
    story.append(Spacer(1, 2 * mm))
    story.append(
        Paragraph(
            "<b>Status</b> and <b>Progress %</b> summarize each project; "
            "use <b>Completion %</b> for task-level progress in the same period rules as the API.",
            ParagraphStyle(
                name="ProjFoot",
                parent=body,
                fontSize=7,
                leading=10,
                textColor=colors.HexColor("#475569"),
            ),
        )
    )

    doc.build(story)
    return buf.getvalue()


def build_skill_gap_pdf(data: Dict[str, Any]) -> bytes:
    """PDF: required skills vs org coverage (landscape for wide developer list column)."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title="Skill Gap Analysis",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        name="PdfTitleGap",
        parent=styles["Title"],
        fontSize=20,
        spaceAfter=8,
        textColor=colors.HexColor("#0f172a"),
    )
    h2 = ParagraphStyle(
        name="PdfH2Gap",
        parent=styles["Heading2"],
        fontSize=13,
        spaceBefore=12,
        spaceAfter=10,
        textColor=colors.HexColor("#14532d"),
    )
    body = ParagraphStyle(
        name="PdfBodyGap",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
    )
    story: list[Any] = []
    story.append(Paragraph("Skill Gap Analysis", title_style))
    story.append(
        Paragraph(
            f"<font color='#b45309'><b>Report build {PDF_REPORT_FORMAT_VERSION}</b></font> — "
            f"Look for column <b>Developers (count + names)</b> (count bold, names below). "
            f"If missing, frontend <b>VITE_API_URL</b> is pointing at the wrong backend port.",
            ParagraphStyle(
                name="PdfVerifyGap",
                parent=body,
                fontSize=9,
                leading=12,
                spaceAfter=6,
                textColor=colors.HexColor("#9a3412"),
            ),
        )
    )
    n_req = data.get("required_skills_distinct", 0)
    story.append(
        Paragraph(
            f"<b>Report type:</b> Organization vs project-required skills<br/>"
            f"<b>Distinct required skills (across projects):</b> {n_req}<br/>"
            f"<b>Generated (UTC):</b> {_esc(data.get('generated_at'))}<br/>"
            f"<font size=8 color=\"#64748b\"><b>PDF format {PDF_REPORT_FORMAT_VERSION}</b> — developer names "
            f"with proficiency are listed per skill (live data from user profiles).</font>",
            body,
        )
    )
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph("1. Summary", h2))
    story.append(
        Paragraph(
            "Status: <b>missing</b> = no developer lists the skill in profile; "
            "<b>weak</b> = average mapped proficiency below 50 on 0–100; <b>ok</b> = adequate coverage. "
            "<b>Developers</b> column: <b>(Name1,Name2,...) N</b> from live users + tasks (roster fallback if needed).",
            body,
        )
    )
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("2. Skill coverage detail", h2))
    story.append(
        Paragraph(
            "The <b>Developers</b> column shows <b>(comma-separated names) total count</b> from MongoDB.",
            ParagraphStyle(name="GapHint", parent=body, fontSize=8, leading=11, textColor=colors.HexColor("#334155")),
        )
    )
    story.append(Spacer(1, 2 * mm))
    gap_cell = ParagraphStyle(
        name="GapCell",
        parent=body,
        fontSize=8,
        leading=10,
    )
    gap_header = [
        "Skill",
        "Status",
        "Developers (count + names)",
        "Avg prof. (0–100)",
        "Projects (titles)",
    ]
    gap_rows: List[List[Any]] = [gap_header]
    for g in data.get("gaps") or []:
        gap_disp = _skill_gap_developers_cell(
            g.get("developers_count_names_display")
            or g.get("developers_gap_display")
            or g.get("developers_with_proficiency")
        )
        dev_block = f"<b>{_esc(gap_disp)}</b>"
        avg_disp = g.get("avg_proficiency_0_100")
        if avg_disp is None:
            avg_disp = _display_txt(g.get("avg_proficiency"))
        else:
            avg_disp = _display_txt(avg_disp)
        proj_disp = g.get("projects_requiring_display")
        if not proj_disp or str(proj_disp).strip().lower() in ("—", "none"):
            proj_disp = str(g.get("projects_requiring") or "Project titles not recorded")
        gap_rows.append(
            [
                Paragraph(_esc(g.get("skill") or "—"), gap_cell),
                Paragraph(_esc(g.get("status") or "—"), gap_cell),
                Paragraph(dev_block, gap_cell),
                str(avg_disp),
                Paragraph(_esc(str(proj_disp)), gap_cell),
            ]
        )
    if len(gap_rows) == 1:
        gap_rows.append(
            [
                Paragraph("—", gap_cell),
                Paragraph("No required skills on projects", gap_cell),
                Paragraph("—", gap_cell),
                "",
                "",
            ]
        )

    tw = doc.width
    gap_col = [
        tw * 0.14,
        tw * 0.10,
        tw * 0.48,
        tw * 0.12,
        tw * 0.16,
    ]
    t_gap = Table(gap_rows, colWidths=gap_col, repeatRows=1)
    t_gap.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14532d")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (3, 0), (3, -1), "RIGHT"),
                ("ALIGN", (4, 0), (4, -1), "RIGHT"),
                ("ALIGN", (2, 0), (2, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0fdf4")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t_gap)

    doc.build(story)
    return buf.getvalue()
