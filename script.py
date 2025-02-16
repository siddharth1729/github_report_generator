#!/usr/bin/env python3
import os
from datetime import datetime
from git import Repo
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# Hardcoded start and end dates
START_DATE_STR = "2024-01-01"
END_DATE_STR = "2025-02-15"
start_dt = datetime.strptime(START_DATE_STR, "%Y-%m-%d")
end_dt = datetime.strptime(END_DATE_STR, "%Y-%m-%d")

def process_repo(repo_url, start_dt, end_dt, target_author):
    
    repo_name = repo_url.split('/')[-1].replace('.git', '')
    repo_dir = os.path.join(os.getcwd(), repo_name)

    # Clone if not present, else update the repository.
    if not os.path.exists(repo_dir):
        print(f"Cloning repository {repo_name}...")
        try:
            repo = Repo.clone_from(repo_url, repo_dir)
        except Exception as e:
            print(f"Failed to clone {repo_url}: {e}")
            return None
    else:
        try:
            print(f"Fetching latest changes for repository {repo_name}...")
            repo = Repo(repo_dir)
            repo.remotes.origin.pull()
        except Exception as e:
            print(f"Failed to update repository {repo_name}: {e}")
            return None

    repo_commits = []
    total_commits = 0

    # Iterate over each commit in the repository.
    for commit in repo.iter_commits():
        # Convert commit date to a naive datetime for proper comparison.
        commit_date = commit.committed_datetime.replace(tzinfo=None)
        if start_dt <= commit_date <= end_dt and commit.author.name == target_author:
            total_commits += 1
            repo_commits.append({
                'date': commit_date.strftime('%Y-%m-%d %H:%M:%S'),
                'hash': commit.hexsha[:7],
                'message': commit.message.strip(),
            })

    return {
        'repo_name': repo_name,
        'commits': repo_commits,
        'total_commits': total_commits,
    }

def generate_pdf(report_text, filename="report.pdf"):
    """
    Generate a PDF file from the given report text.
    """
    c = canvas.Canvas(filename, pagesize=letter)
    width, height = letter
    margin = 40
    x = margin
    y = height - margin
    line_height = 12
    c.setFont("Helvetica", 10)

    for line in report_text.splitlines():
        # Start a new page if the text reaches the bottom margin.
        if y < margin:
            c.showPage()
            c.setFont("Helvetica", 10)
            y = height - margin
        c.drawString(x, y, line)
        y -= line_height
    c.save()
    print(f"PDF report generated and saved as {filename}")

def main():
    developer_name = "Siddharth Sabron"
    target_author = "siddharth1729"
    repos = [
        "git@github.com:siddharth1729/my_website.git",
        "git@github.com:siddharth1729/cash_table.git",
        "git@github.com:siddharth1729/java_lld.git",
        "git@github.com:siddharth1729/the_art_of_multithreading.git"
    ]

    overall_commits = 0
    repo_reports = []

    for repo_url in repos:
        print(f"Processing repository: {repo_url}")
        result = process_repo(repo_url, start_dt, end_dt, target_author)
        if result is not None:
            overall_commits += result['total_commits']
            repo_reports.append(result)

    total_repos = len(repo_reports)
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Build a rich header for the report.
    header_lines = [
        "=" * 50,
        f"Developer Name           : {developer_name}",
        f"Report Generated On      : {current_time}",
        f"Date Range               : {START_DATE_STR} to {END_DATE_STR}",
        f"Total Repositories Worked: {total_repos}",
        f"Total Commits            : {overall_commits}",
        "=" * 50,
        ""
    ]

    # Build the detailed report.
    report_lines = []
    report_lines.append("===== OVERALL REPORT =====")
    report_lines.append(f"Total Commits: {overall_commits}")
    report_lines.append("")

    for repo in repo_reports:
        report_lines.append(f"===== Repository: {repo['repo_name']} =====")
        report_lines.append(f"Total Commits: {repo['total_commits']}")
        report_lines.append("Commits:")
        if repo['commits']:
            for idx, commit in enumerate(repo['commits'], 1):
                report_lines.append(
                    f"{idx}.  {commit['message']} ::[{commit['date']}]:: {commit['hash']}"
                )
        else:
            report_lines.append("  No commits found in this date range for the specified author.")
        report_lines.append("")

    final_report = "\n".join(header_lines + report_lines)
    
    # Print the report to console.
    print(final_report)
    
    # Save the report as a text file.
    with open("report.txt", "w") as f:
        f.write(final_report)
    print("Report saved to report.txt")
    
    # Generate PDF from the report.
    generate_pdf(final_report, "report.pdf")

if __name__ == "__main__":
    main()