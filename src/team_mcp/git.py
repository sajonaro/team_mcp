"""Git integration for Team MCP."""

import subprocess
from pathlib import Path
from typing import Optional

from .types import GitConfig, Task


class GitIntegration:
    """Manages git operations for Team MCP."""

    def __init__(self, config: GitConfig):
        self.config = config
        self.current_branch: Optional[str] = None
        self.original_branch: Optional[str] = None

    def _run_git(self, *args: str) -> tuple[int, str, str]:
        """Run a git command and return (returncode, stdout, stderr)."""
        try:
            result = subprocess.run(
                ["git"] + list(args),
                capture_output=True,
                text=True,
                cwd=Path.cwd(),
            )
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        except Exception as e:
            return 1, "", str(e)

    def is_git_repo(self) -> bool:
        """Check if current directory is a git repository."""
        returncode, _, _ = self._run_git("rev-parse", "--git-dir")
        return returncode == 0

    def get_current_branch(self) -> Optional[str]:
        """Get the current git branch."""
        returncode, stdout, _ = self._run_git("rev-parse", "--abbrev-ref", "HEAD")
        if returncode == 0:
            return stdout
        return None

    def start_run(self, task_id: str) -> bool:
        """Start a new run - create branch if in branch mode."""
        if self.config.mode == "none":
            return True

        if not self.is_git_repo():
            return False

        if self.config.mode == "branch":
            # Save original branch
            self.original_branch = self.get_current_branch()

            # Create new branch
            branch_name = f"{self.config.branch_prefix}{task_id}"
            returncode, _, _ = self._run_git("checkout", "-b", branch_name)
            if returncode == 0:
                self.current_branch = branch_name
                return True
            return False

        elif self.config.mode == "current":
            # Stay on current branch
            self.current_branch = self.get_current_branch()
            return True

        return False

    def commit(
        self, role: str, summary: str, files: Optional[list[str]] = None
    ) -> bool:
        """Commit changes with a formatted message."""
        if self.config.mode == "none":
            return True

        if not self.is_git_repo():
            return False

        # Stage files
        if files:
            for file in files:
                self._run_git("add", file)
        else:
            # Stage all changes
            self._run_git("add", "-A")

        # Check if there are changes to commit
        returncode, stdout, _ = self._run_git("diff", "--cached", "--quiet")
        if returncode == 0:
            # No changes to commit
            return True

        # Format commit message
        message = self.config.commit_message_format.format(role=role, summary=summary)

        # Commit
        returncode, _, _ = self._run_git("commit", "-m", message)
        return returncode == 0

    def complete_run(self) -> bool:
        """Complete a run - commit final state if in current mode."""
        if self.config.mode == "current":
            return self.commit("complete", "task completed")
        return True

    def get_branch_name(self) -> Optional[str]:
        """Get the current working branch name."""
        return self.current_branch
