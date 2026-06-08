#!/usr/bin/env python3
"""GitHub Report Generator.

Reads a list of repositories from a text file, walks commit history within a
configurable date range for a specific author, and emits a plain-text plus a
professionally styled PDF report.
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from git import GitCommandError, InvalidGitRepositoryError, Repo
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


# Modern deep-navy / slate palette
NAVY = colors.HexColor("#1F2A44")
SLATE = colors.HexColor("#475569")
SLATE_LIGHT = colors.HexColor("#94A3B8")
BG_LIGHT = colors.HexColor("#F1F5F9")
ROW_ALT = colors.HexColor("#F8FAFC")
TEXT_DARK = colors.HexColor("#0F172A")
GREEN = colors.HexColor("#16A34A")
RED = colors.HexColor("#DC2626")

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CACHE_DIR = PROJECT_ROOT / ".cache"
DEFAULT_REPOS_FILE = PROJECT_ROOT / "repos.txt"

logger = logging.getLogger("github_report")


# ---------- Data model ----------
@dataclass
class CommitRecord:
    date: str
    timestamp: datetime
    hash: str
    message: str
    insertions: int
    deletions: int


@dataclass
class RepoReport:
    repo_name: str
    repo_url: str
    commits: list[CommitRecord] = field(default_factory=list)

    @property
    def total_commits(self) -> int:
        return len(self.commits)

    @property
    def total_insertions(self) -> int:
        return sum(c.insertions for c in self.commits)

    @property
    def total_deletions(self) -> int:
        return sum(c.deletions for c in self.commits)


# ---------- Input loading ----------
def load_repo_urls(path: Path) -> list[str]:
    """Read repo URLs from a file. One URL per line; blank lines and '#' comments ignored."""
    if not path.exists():
        raise FileNotFoundError(f"Repository list not found: {path}")
    urls: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    if not urls:
        raise ValueError(f"No repository URLs found in {path}")
    return urls


def derive_repo_name(repo_url: str) -> str:
    name = repo_url.rstrip("/").split("/")[-1]
    return name[:-4] if name.endswith(".git") else name


# ---------- Repo processing ----------
def open_or_clone(repo_url: str, clone_root: Path) -> Repo | None:
    repo_name = derive_repo_name(repo_url)
    if not repo_name:
        logger.error("Malformed repository URL (could not derive name): %r", repo_url)
        return None

    repo_dir = clone_root / repo_name
    try:
        if repo_dir.exists():
            logger.info("Updating existing clone: %s", repo_dir.name)
            repo = Repo(repo_dir)
            try:
                repo.remotes.origin.pull()
            except GitCommandError as e:
                logger.warning("Pull failed for %s (using local state): %s",
                               repo_dir.name, e)
            return repo

        logger.info("Cloning %s -> %s", repo_url, repo_dir)
        clone_root.mkdir(parents=True, exist_ok=True)
        return Repo.clone_from(repo_url, repo_dir)
    except (GitCommandError, InvalidGitRepositoryError) as e:
        logger.error("Failed to open or clone %s: %s", repo_url, e)
        return None


def process_repo(
    repo_url: str,
    start_dt: datetime,
    end_dt: datetime,
    target_author: str,
    clone_root: Path,
) -> RepoReport | None:
    """Walk a repository's commit history and return a structured RepoReport.

    `start_dt` and `end_dt` MUST be timezone-aware. Commit timestamps are
    converted to UTC before comparison, so no naive/aware mixing occurs.
    """
    if start_dt.tzinfo is None or end_dt.tzinfo is None:
        raise ValueError("start_dt and end_dt must be timezone-aware")

    repo = open_or_clone(repo_url, clone_root)
    if repo is None:
        return None

    report = RepoReport(repo_name=derive_repo_name(repo_url), repo_url=repo_url)
    try:
        for commit in repo.iter_commits():
            commit_dt = commit.committed_datetime.astimezone(timezone.utc)
            if not (start_dt <= commit_dt <= end_dt):
                continue
            if commit.author.name != target_author:
                continue

            try:
                stats = commit.stats.total
                insertions = int(stats.get("insertions", 0))
                deletions = int(stats.get("deletions", 0))
            except Exception as e:
                logger.warning("Stats unavailable for %s in %s: %s",
                               commit.hexsha[:7], report.repo_name, e)
                insertions = deletions = 0

            first_line = commit.message.strip().splitlines()
            report.commits.append(CommitRecord(
                date=commit_dt.strftime("%Y-%m-%d %H:%M"),
                timestamp=commit_dt,
                hash=commit.hexsha[:7],
                message=first_line[0] if first_line else "(empty)",
                insertions=insertions,
                deletions=deletions,
            ))
    except Exception as e:
        logger.error("Error walking commits in %s: %s", report.repo_name, e)

    report.commits.sort(key=lambda c: c.timestamp, reverse=True)
    return report


# ---------- Plain-text report ----------
def build_text_report(
    developer_name: str,
    start_date: str,
    end_date: str,
    repo_reports: list[RepoReport],
) -> str:
    stats = _compute_stats(repo_reports)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    first_str = (
        stats["first_commit"].strftime("%Y-%m-%d")
        if stats["first_commit"] else "-"
    )
    last_str = (
        stats["last_commit"].strftime("%Y-%m-%d")
        if stats["last_commit"] else "-"
    )
    most_active = (
        f"{stats['most_active'].repo_name} "
        f"({stats['most_active'].total_commits} commits)"
        if stats["most_active"] else "-"
    )
    most_prolific = (
        f"{stats['most_prolific'].repo_name} "
        f"({stats['most_prolific'].total_insertions + stats['most_prolific'].total_deletions:,} lines)"
        if stats["most_prolific"] else "-"
    )

    lines = [
        "=" * 60,
        f"Developer Name           : {developer_name}",
        f"Report Generated On      : {now_str}",
        f"Date Range               : {start_date} to {end_date}",
        f"Total Repositories       : {stats['n_repos']}",
        f"Total Commits            : {stats['total_commits']}",
        f"Total Lines Added        : +{stats['total_ins']}",
        f"Total Lines Deleted      : -{stats['total_del']}",
        "=" * 60,
        "",
        "----- Consolidated Statistics -----",
        f"Total lines changed             : {stats['total_changed']:,}",
        f"Net change                      : {stats['net']:+,}",
        f"Avg commits per repository      : {stats['avg_commits_per_repo']:.1f}",
        f"Avg lines added per commit      : +{stats['avg_ins_per_commit']:.1f}",
        f"Avg lines deleted per commit    : -{stats['avg_del_per_commit']:.1f}",
        f"Most active repository          : {most_active}",
        f"Most prolific repository        : {most_prolific}",
        f"First commit in range (UTC)     : {first_str}",
        f"Latest commit in range (UTC)    : {last_str}",
        f"Unique active days              : {stats['active_days']}",
        "",
    ]
    for repo_idx, r in enumerate(repo_reports, 1):
        lines.append(f"----- 4.{repo_idx} {r.repo_name} -----")
        lines.append(
            f"Commits: {r.total_commits}  |  "
            f"+{r.total_insertions} / -{r.total_deletions}"
        )
        for idx, c in enumerate(r.commits, 1):
            lines.append(
                f"{idx:>3}. {c.date}  {c.hash}  "
                f"(+{c.insertions}/-{c.deletions})  {c.message}"
            )
        lines.append("")
    return "\n".join(lines)


# ---------- PDF helpers ----------
def _page_decorations(canvas, doc):
    if canvas.getPageNumber() == 1:
        return
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(SLATE)
    canvas.drawString(18 * mm, 12 * mm, "GitHub Activity Report")
    canvas.drawRightString(
        doc.pagesize[0] - 18 * mm, 12 * mm,
        f"Page {canvas.getPageNumber()}",
    )
    canvas.setStrokeColor(SLATE_LIGHT)
    canvas.setLineWidth(0.4)
    canvas.line(18 * mm, 15 * mm, doc.pagesize[0] - 18 * mm, 15 * mm)
    canvas.restoreState()


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle(
            "CoverTitle", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=34, leading=40, textColor=NAVY, alignment=1, spaceAfter=12,
        ),
        "cover_subtitle": ParagraphStyle(
            "CoverSubtitle", parent=base["Normal"], fontName="Helvetica",
            fontSize=14, leading=20, textColor=SLATE, alignment=1, spaceAfter=6,
        ),
        "cover_meta": ParagraphStyle(
            "CoverMeta", parent=base["Normal"], fontName="Helvetica",
            fontSize=12, leading=18, textColor=TEXT_DARK, alignment=1,
        ),
        "h1": ParagraphStyle(
            "H1", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=18, leading=22, textColor=NAVY, spaceBefore=6, spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "H2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=14, leading=18, textColor=NAVY, spaceBefore=12, spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "Body", parent=base["Normal"], fontName="Helvetica",
            fontSize=10, leading=13, textColor=TEXT_DARK,
        ),
        "cell": ParagraphStyle(
            "Cell", parent=base["Normal"], fontName="Helvetica",
            fontSize=9, leading=11, textColor=TEXT_DARK,
        ),
        "cell_mono": ParagraphStyle(
            "CellMono", parent=base["Normal"], fontName="Courier",
            fontSize=9, leading=11, textColor=SLATE,
        ),
    }


def _cover_page(elements, styles, developer_name, start_date, end_date, now_str):
    elements.append(Spacer(1, 60 * mm))
    elements.append(Paragraph("GitHub Activity Report", styles["cover_title"]))
    elements.append(Paragraph("A summary of commit activity",
                              styles["cover_subtitle"]))
    elements.append(Spacer(1, 30 * mm))
    elements.append(Paragraph(
        f"Prepared for<br/><b>{escape(developer_name)}</b>",
        styles["cover_meta"],
    ))
    elements.append(Spacer(1, 10 * mm))
    elements.append(Paragraph(
        f"Date range<br/><b>{escape(start_date)} &nbsp;&rarr;&nbsp; "
        f"{escape(end_date)}</b>",
        styles["cover_meta"],
    ))
    elements.append(Spacer(1, 10 * mm))
    elements.append(Paragraph(
        f"Generated on {escape(now_str)}", styles["cover_subtitle"]
    ))
    elements.append(PageBreak())


def _summary_table(repo_reports):
    total_commits = sum(r.total_commits for r in repo_reports)
    total_ins = sum(r.total_insertions for r in repo_reports)
    total_del = sum(r.total_deletions for r in repo_reports)
    data = [
        ["Metric", "Value"],
        ["Total repositories", str(len(repo_reports))],
        ["Total commits", str(total_commits)],
        ["Total lines added", f"+{total_ins:,}"],
        ["Total lines deleted", f"-{total_del:,}"],
        ["Net change", f"{total_ins - total_del:+,}"],
    ]
    tbl = Table(data, colWidths=[70 * mm, 70 * mm], hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 11),
        ("ALIGN", (1, 1), (1, -1), "RIGHT"),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT_DARK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
        ("GRID", (0, 0), (-1, -1), 0.5, SLATE_LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return tbl


def _compute_stats(repo_reports: list[RepoReport]) -> dict:
    """Compute aggregate metrics and highlight repos across the whole report."""
    all_commits = [c for r in repo_reports for c in r.commits]
    n_repos = len(repo_reports)
    total_commits = len(all_commits)
    total_ins = sum(c.insertions for c in all_commits)
    total_del = sum(c.deletions for c in all_commits)

    most_active = (
        max(repo_reports, key=lambda r: r.total_commits)
        if repo_reports else None
    )
    most_prolific = (
        max(repo_reports,
            key=lambda r: r.total_insertions + r.total_deletions)
        if repo_reports else None
    )

    if all_commits:
        first = min(c.timestamp for c in all_commits)
        last = max(c.timestamp for c in all_commits)
        active_days = len({c.timestamp.date() for c in all_commits})
    else:
        first = last = None
        active_days = 0

    return {
        "n_repos": n_repos,
        "total_commits": total_commits,
        "total_ins": total_ins,
        "total_del": total_del,
        "total_changed": total_ins + total_del,
        "net": total_ins - total_del,
        "avg_commits_per_repo": (total_commits / n_repos) if n_repos else 0.0,
        "avg_ins_per_commit": (total_ins / total_commits) if total_commits else 0.0,
        "avg_del_per_commit": (total_del / total_commits) if total_commits else 0.0,
        "most_active": most_active,
        "most_prolific": most_prolific,
        "first_commit": first,
        "last_commit": last,
        "active_days": active_days,
    }


def _consolidated_stats_table(stats: dict, styles):
    """Richer stats panel: totals, averages, highlights, date span."""
    if stats["most_active"]:
        ma = stats["most_active"]
        most_active = f"{ma.repo_name}  ({ma.total_commits} commits)"
    else:
        most_active = "-"

    if stats["most_prolific"]:
        mp = stats["most_prolific"]
        most_prolific = (
            f"{mp.repo_name}  "
            f"({mp.total_insertions + mp.total_deletions:,} lines changed)"
        )
    else:
        most_prolific = "-"

    first_str = (
        stats["first_commit"].strftime("%Y-%m-%d")
        if stats["first_commit"] else "-"
    )
    last_str = (
        stats["last_commit"].strftime("%Y-%m-%d")
        if stats["last_commit"] else "-"
    )

    data = [
        ["Metric", "Value"],
        ["Total lines changed", f"{stats['total_changed']:,}"],
        ["Net change (added - deleted)", f"{stats['net']:+,}"],
        ["Average commits per repository", f"{stats['avg_commits_per_repo']:.1f}"],
        ["Average lines added per commit", f"+{stats['avg_ins_per_commit']:.1f}"],
        ["Average lines deleted per commit", f"-{stats['avg_del_per_commit']:.1f}"],
        ["Most active repository", most_active],
        ["Most prolific repository", most_prolific],
        ["First commit in range",
            Paragraph(f"{first_str} &nbsp; <font color='#94A3B8'>UTC</font>",
                      styles["cell"])],
        ["Latest commit in range",
            Paragraph(f"{last_str} &nbsp; <font color='#94A3B8'>UTC</font>",
                      styles["cell"])],
        ["Unique active days", str(stats["active_days"])],
    ]
    tbl = Table(data, colWidths=[80 * mm, 94 * mm], hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), SLATE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 11),
        ("ALIGN", (1, 1), (1, -1), "LEFT"),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT_DARK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
        ("GRID", (0, 0), (-1, -1), 0.5, SLATE_LIGHT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return tbl


def _per_repo_overview(repo_reports, styles):
    data = [["Repository", "Commits", "+ Added", "- Deleted"]]
    for r in repo_reports:
        data.append([
            Paragraph(escape(r.repo_name), styles["cell"]),
            str(r.total_commits),
            f"+{r.total_insertions:,}",
            f"-{r.total_deletions:,}",
        ])
    tbl = Table(
        data,
        colWidths=[80 * mm, 25 * mm, 30 * mm, 30 * mm],
        hAlign="LEFT",
        repeatRows=1,
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
        ("TEXTCOLOR", (2, 1), (2, -1), GREEN),
        ("TEXTCOLOR", (3, 1), (3, -1), RED),
        ("GRID", (0, 0), (-1, -1), 0.5, SLATE_LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return tbl


def _repo_section(report: RepoReport, styles, section_num: str = "") -> list:
    elements: list = []
    heading = (
        f"{section_num} {report.repo_name}".strip()
        if section_num else report.repo_name
    )
    elements.append(Paragraph(escape(heading), styles["h2"]))
    elements.append(Paragraph(
        f"Commits: <b>{report.total_commits}</b> &nbsp; "
        f"<font color='#16A34A'>+{report.total_insertions:,}</font> / "
        f"<font color='#DC2626'>-{report.total_deletions:,}</font>",
        styles["body"],
    ))
    elements.append(Spacer(1, 4 * mm))

    if not report.commits:
        elements.append(Paragraph(
            "<i>No commits in this date range for the specified author.</i>",
            styles["body"],
        ))
        elements.append(Spacer(1, 8 * mm))
        return [KeepTogether(elements)]

    data = [["#", "Date (UTC)", "Hash", "Message", "+", "-"]]
    for idx, c in enumerate(report.commits, 1):
        data.append([
            str(idx),
            Paragraph(escape(c.date), styles["cell"]),
            Paragraph(escape(c.hash), styles["cell_mono"]),
            Paragraph(escape(c.message), styles["cell"]),
            f"+{c.insertions:,}",
            f"-{c.deletions:,}",
        ])
    # Widths sum to exactly 174 mm (A4 210mm - 2x18mm margins).
    tbl = Table(
        data,
        colWidths=[10 * mm, 32 * mm, 22 * mm, 74 * mm, 18 * mm, 18 * mm],
        hAlign="LEFT",
        repeatRows=1,
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (4, 0), (5, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
        ("TEXTCOLOR", (4, 1), (4, -1), GREEN),
        ("TEXTCOLOR", (5, 1), (5, -1), RED),
        ("GRID", (0, 0), (-1, -1), 0.4, SLATE_LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(tbl)
    elements.append(Spacer(1, 8 * mm))
    return elements


def generate_pdf(
    repo_reports: list[RepoReport],
    developer_name: str,
    start_date: str,
    end_date: str,
    filename: str = "report.pdf",
) -> None:
    """Render structured RepoReport data into a professional PDF."""
    doc = BaseDocTemplate(
        filename,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title="GitHub Activity Report",
        author=developer_name,
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main",
    )
    doc.addPageTemplates([
        PageTemplate(id="main", frames=frame, onPage=_page_decorations),
    ])

    styles = _styles()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elements: list = []

    _cover_page(elements, styles, developer_name, start_date, end_date, now_str)

    stats = _compute_stats(repo_reports)

    # ---- Page 2: stats dashboard ----
    elements.append(Paragraph("1. Overall Summary", styles["h1"]))
    elements.append(_summary_table(repo_reports))
    elements.append(Spacer(1, 8 * mm))

    elements.append(Paragraph("2. Consolidated Statistics", styles["h1"]))
    elements.append(_consolidated_stats_table(stats, styles))
    elements.append(PageBreak())

    # ---- Page 3: per-repository overview ----
    elements.append(Paragraph("3. Per-Repository Overview", styles["h1"]))
    elements.append(_per_repo_overview(repo_reports, styles))
    elements.append(PageBreak())

    # ---- Page 4+: per-repo commit details, numbered 4.1, 4.2, ... ----
    elements.append(Paragraph("4. Commit Details", styles["h1"]))
    for idx, r in enumerate(repo_reports, 1):
        elements.extend(_repo_section(r, styles, section_num=f"4.{idx}"))

    doc.build(elements)
    logger.info("PDF report generated and saved as %s", filename)


# ---------- CLI ----------
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Generate a PDF + text report of your commits across multiple repos. "
            "Repository URLs are read from a text file (one URL per line; blank "
            "lines and lines starting with '#' are ignored)."
        ),
    )
    p.add_argument("--developer-name", default="Your Name",
                   help="Display name on the cover page.")
    p.add_argument("--author", required=True,
                   help="Exact git commit author name to filter on.")
    p.add_argument("--start-date", default="2024-01-01",
                   help="Inclusive start date (YYYY-MM-DD, interpreted as UTC).")
    p.add_argument("--end-date",
                   default=datetime.now().strftime("%Y-%m-%d"),
                   help="Inclusive end date (YYYY-MM-DD, interpreted as UTC).")
    p.add_argument("--repos-file", type=Path, default=DEFAULT_REPOS_FILE,
                   help="Path to a text file with one repo URL per line.")
    p.add_argument("--clone-root", type=Path, default=DEFAULT_CACHE_DIR,
                   help="Directory where repositories are cloned.")
    p.add_argument("--pdf-output", default="report.pdf",
                   help="Output PDF path.")
    p.add_argument("--txt-output", default="report.txt",
                   help="Output text path.")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p.parse_args(argv)


def _parse_date_utc(s: str, *, end_of_day: bool = False) -> datetime:
    """Parse YYYY-MM-DD into a timezone-aware UTC datetime."""
    try:
        d = datetime.strptime(s, "%Y-%m-%d")
    except ValueError as e:
        raise SystemExit(f"Invalid date '{s}': expected YYYY-MM-DD") from e
    if end_of_day:
        d = d.replace(hour=23, minute=59, second=59)
    return d.replace(tzinfo=timezone.utc)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    start_dt = _parse_date_utc(args.start_date)
    end_dt = _parse_date_utc(args.end_date, end_of_day=True)
    if start_dt > end_dt:
        logger.error("Start date must be on or before end date.")
        return 2

    try:
        repo_urls = load_repo_urls(args.repos_file)
    except FileNotFoundError as e:
        logger.error("%s - create a 'repos.txt' with one URL per line.", e)
        return 2
    except ValueError as e:
        logger.error("%s", e)
        return 2

    logger.info("Loaded %d repository URL(s) from %s",
                len(repo_urls), args.repos_file)

    repo_reports: list[RepoReport] = []
    for url in repo_urls:
        try:
            report = process_repo(
                url, start_dt, end_dt, args.author, args.clone_root,
            )
        except KeyboardInterrupt:
            logger.warning("Interrupted by user.")
            return 130
        except Exception as e:
            logger.error("Unhandled error processing %s: %s", url, e)
            continue
        if report is not None:
            repo_reports.append(report)

    if not repo_reports:
        logger.error("No repositories processed successfully. Nothing to report.")
        return 1

    text_report = build_text_report(
        args.developer_name, args.start_date, args.end_date, repo_reports,
    )
    try:
        Path(args.txt_output).write_text(text_report, encoding="utf-8")
        logger.info("Text report saved to %s", args.txt_output)
    except OSError as e:
        logger.error("Failed to write text report: %s", e)

    try:
        generate_pdf(
            repo_reports,
            developer_name=args.developer_name,
            start_date=args.start_date,
            end_date=args.end_date,
            filename=args.pdf_output,
        )
    except Exception as e:
        logger.exception("Failed to generate PDF report: %s", e)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
