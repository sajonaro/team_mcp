"""Output and artifacts management for Team MCP."""

from datetime import datetime
from pathlib import Path
from typing import Optional

from .types import Task, TaskComplete, RoleType, Submission, OutputConfig


class OutputManager:
    """Manages output artifacts for task runs."""

    def __init__(self, config: OutputConfig):
        self.config = config
        self.runs_dir = Path(config.runs_dir)

    def _ensure_run_dir(self, task_id: str) -> Path:
        """Ensure run directory exists and return path."""
        run_dir = self.runs_dir / task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def create_run(self, task: Task) -> None:
        """Create initial run artifacts."""
        run_dir = self._ensure_run_dir(task.id)

        # Create task.md
        task_md = f"""# Task

{task.description}

**Started:** {task.created_at.strftime("%Y-%m-%d %H:%M:%S")}
**Task ID:** {task.id}
"""
        (run_dir / "task.md").write_text(task_md)

        # Create iterations directory
        (run_dir / "iterations").mkdir(exist_ok=True)

    def write_requirements(self, task: Task) -> None:
        """Write requirements from BA."""
        if not task.confirmed_requirements:
            return

        run_dir = self._ensure_run_dir(task.id)
        requirements_md = f"""# Requirements

**Confirmed by:** BA
**Date:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

{task.confirmed_requirements}
"""
        (run_dir / "requirements.md").write_text(requirements_md)

    def write_design(self, task: Task) -> None:
        """Write design from Architect."""
        if not task.current_design:
            return

        run_dir = self._ensure_run_dir(task.id)
        design_md = f"""# Design

**Created by:** Architect
**Date:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

{task.current_design}
"""
        (run_dir / "design.md").write_text(design_md)

    def write_iteration(self, task: Task, submission: Submission) -> None:
        """Write iteration artifact."""
        run_dir = self._ensure_run_dir(task.id)
        iterations_dir = run_dir / "iterations"

        # Format filename
        filename = f"{submission.iteration:02d}_{submission.role}.md"
        filepath = iterations_dir / filename

        # Build content based on role type
        content = f"""# {submission.role.upper()} - Iteration {submission.iteration}

**Role Type:** {submission.role_type.value}
**Timestamp:** {submission.timestamp.strftime("%Y-%m-%d %H:%M:%S")}
**Outcome:** {submission.outcome or "N/A"}

"""

        if submission.role_type == RoleType.IMPLEMENTER:
            content += f"""## Summary

{submission.data.get("summary", "N/A")}

## Files Changed

"""
            files = submission.data.get("files_changed", [])
            for file in files:
                content += f"- {file}\n"

            content += f"""
## Proof

```
{submission.data.get("proof", "N/A")}
```

"""
            if "concerns" in submission.data:
                content += f"""## Concerns

{submission.data["concerns"]}
"""

        elif submission.role_type == RoleType.GATEKEEPER:
            approved = submission.data.get("approved", False)
            content += f"""## Decision

**Approved:** {"✅ Yes" if approved else "❌ No"}

## Reason

{submission.data.get("reason", "N/A")}

"""
            if not approved and "issues" in submission.data:
                content += """## Issues

"""
                for issue in submission.data["issues"]:
                    content += f"- {issue}\n"

        elif submission.role_type == RoleType.DESIGNER:
            content += f"""## Design

{submission.data.get("design", "N/A")}

## Patterns

"""
            for pattern in submission.data.get("patterns", []):
                content += f"- {pattern}\n"

            if "warnings" in submission.data:
                content += "\n## Warnings\n\n"
                for warning in submission.data["warnings"]:
                    content += f"- {warning}\n"

        elif submission.role_type == RoleType.ANALYST:
            if "questions" in submission.data:
                content += "## Questions\n\n"
                for question in submission.data["questions"]:
                    content += f"- {question}\n"
            elif "confirmed_requirements" in submission.data:
                content += f"""## Confirmed Requirements

{submission.data["confirmed_requirements"]}
"""

        filepath.write_text(content)

    def write_summary(self, task: Task, result: TaskComplete) -> None:
        """Write final summary."""
        run_dir = self._ensure_run_dir(task.id)

        # Build iterations table
        iterations_table = "| # | Role | Outcome |\n|---|------|---------|\n"

        # Group submissions by role type for summary
        for sub in task.submissions:
            if sub.role_type == RoleType.ANALYST:
                iterations_table += (
                    f"| - | {sub.role} | {self._format_outcome(sub)} |\n"
                )
            elif sub.role_type == RoleType.DESIGNER:
                iterations_table += (
                    f"| - | {sub.role} | {self._format_outcome(sub)} |\n"
                )
            elif sub.role_type == RoleType.IMPLEMENTER:
                iterations_table += f"| {sub.iteration} | {sub.role} | Submitted |\n"
            elif sub.role_type == RoleType.GATEKEEPER:
                approved = sub.data.get("approved", False)
                outcome = "✅ Approved" if approved else "❌ Rejected"
                reason = sub.data.get("reason", "")
                if not approved and reason:
                    outcome += f" — {reason[:50]}"
                iterations_table += f"| {sub.iteration} | {sub.role} | {outcome} |\n"

        # Count coder iterations
        coder_iterations = len(
            [s for s in task.submissions if s.role_type == RoleType.IMPLEMENTER]
        )

        summary_md = f"""# Run Summary

## Task
{task.description}

## Result: {"✅ SUCCESS" if result.success else "❌ FAILED"}

"""

        if task.confirmed_requirements:
            summary_md += f"""## Requirements (from BA)
{task.confirmed_requirements}

"""

        if task.current_design:
            summary_md += f"""## Design (from Architect)
{task.current_design}

"""

        summary_md += f"""## Iterations

{iterations_table}

**Coder iterations:** {coder_iterations}

## Files Changed
"""

        for file in result.files_changed:
            summary_md += f"- {file}\n"

        if result.git_branch:
            summary_md += f"""
## Git
- **Branch:** `{result.git_branch}`
- **Merge:** `git checkout main && git merge {result.git_branch}`
"""

        summary_md += f"""
## Timeline
- **Started:** {task.created_at.strftime("%Y-%m-%d %H:%M:%S")}
- **Completed:** {task.completed_at.strftime("%Y-%m-%d %H:%M:%S") if task.completed_at else "N/A"}
"""

        (run_dir / "summary.md").write_text(summary_md)

    def _format_outcome(self, submission: Submission) -> str:
        """Format outcome for display."""
        if submission.outcome == "confirmed":
            return "✅ Requirements confirmed"
        elif submission.outcome == "submitted":
            return "✅ Design submitted"
        elif submission.outcome == "paused":
            return "⏸ Paused for user input"
        elif submission.outcome == "approved":
            return "✅ Approved"
        elif submission.outcome == "rejected":
            return "❌ Rejected"
        else:
            return submission.outcome or "N/A"
