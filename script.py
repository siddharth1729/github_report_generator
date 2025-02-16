#!/usr/bin/env python3
import os
from datetime import datetime
from git import Repo
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch

# Hardcoded start and end dates
# ADD YOUR DATE
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
    Generate a beautifully formatted PDF file from the given report text.
    """
    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=72
    )

    # Container for the 'Flowable' objects
    elements = []
    
    # Define styles
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        textColor=colors.HexColor('#2E5A88')
    ))
    styles.add(ParagraphStyle(
        name='CustomHeading',
        parent=styles['Heading2'],
        fontSize=16,
        spaceAfter=12,
        textColor=colors.HexColor('#2E5A88')
    ))
    styles.add(ParagraphStyle(
        name='CustomBody',
        parent=styles['Normal'],
        fontSize=10,
        spaceAfter=6
    ))

    # Process the report text
    sections = report_text.split('\n\n')
    
    # Header section
    header_lines = sections[0].split('\n')
    title_data = []
    for line in header_lines:
        if '=' not in line:
            key, value = line.split(':', 1)
            title_data.append([Paragraph(key.strip(), styles['CustomBody']), 
                             Paragraph(value.strip(), styles['CustomBody'])])
    
    # Create header table
    header_table = Table(title_data, colWidths=[3*inch, 3*inch])
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F5F5F5')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#333333')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#CCCCCC'))
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 20))

    # Process each repository section
    for section in sections[2:]:  # Skip header and overall report
        if section.strip():
            lines = section.split('\n')
            if lines[0].startswith('====='):
                # Repository header
                repo_name = lines[0].replace('=', '').replace('Repository:', '').strip()
                elements.append(Paragraph(repo_name, styles['CustomHeading']))
                elements.append(Spacer(1, 10))
                
                # Commit count
                if len(lines) > 1:
                    elements.append(Paragraph(lines[1], styles['CustomBody']))
                    elements.append(Spacer(1, 10))
                
                # Commits table data
                if len(lines) > 3:
                    commit_data = []
                    commit_data.append(['#', 'Message', 'Date', 'Hash'])  # Header row
                    
                    for line in lines[3:]:
                        if line.strip() and line[0].isdigit():
                            try:
                                num, rest = line.split('.', 1)
                                message, rest = rest.rsplit('::[', 1)
                                date, hash_val = rest.rsplit(']::', 1)
                                commit_data.append([
                                    num.strip(),
                                    message.strip(),
                                    date.strip(),
                                    hash_val.strip()
                                ])
                            except ValueError:
                                continue
                    
                    if len(commit_data) > 1:  # If we have commits
                        table = Table(commit_data, colWidths=[0.4*inch, 3.5*inch, 1.5*inch, 1*inch])
                        table.setStyle(TableStyle([
                            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2E5A88')),
                            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                            ('FONTSIZE', (0, 0), (-1, 0), 10),
                            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
                            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                            ('FONTSIZE', (0, 1), (-1, -1), 8),
                            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#CCCCCC')),
                            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F5F5')])
                        ]))
                        elements.append(table)
                        elements.append(Spacer(1, 20))

    # Build the PDF
    doc.build(elements)
    print(f"PDF report generated and saved as {filename}")

def main():
    # ADD YOUR NAME 
    developer_name = "Siddharth Sabron"
    #  ADD YOUR GITHUB ID/USERNAME
    target_author = "siddharth1729"
    # ADD ALL YOUR GITHUB REPO WITH "," SEPERATED LIKE THIS GIVEN BELOW
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