"""Core types and data models for Team MCP."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Any


class TaskState(Enum):
    """States a task can be in."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"  # Waiting for user input (analyst questions)
    REBOUND_OFFERED = "rebound_offered"  # Offering architect consult after failures
    COMPLETE = "complete"
    ESCALATED = "escalated"
    ABORTED = "aborted"


class RoleType(Enum):
    """Types of roles in the workflow."""

    ANALYST = "analyst"  # Clarify requirements
    DESIGNER = "designer"  # Technical approach
    IMPLEMENTER = "implementer"  # Write code
    GATEKEEPER = "gatekeeper"  # Review and approve/reject


@dataclass
class RoleAssignment:
    """Returned when Claude should adopt a new role."""

    role: str  # "ba", "architect", "coder", "qa", "reviewer", or custom
    role_type: str  # "analyst" | "designer" | "implementer" | "gatekeeper"
    iteration: int  # Current iteration number

    instructions: str  # System prompt for this role
    rules: list[str]  # Global rules that apply
    context: list[str]  # Relevant files/docs loaded

    # For analyst:
    task: Optional[str] = None  # Original task to analyze

    # For designer:
    requirements: Optional[str] = None  # Confirmed requirements from analyst
    failure_context: Optional[str] = None  # If rebounding, what went wrong

    # For implementer:
    design: Optional[str] = None  # From designer
    feedback: Optional[str] = None  # Feedback from previous rejection

    # For gatekeeper:
    reviewing: Optional[dict] = None  # The submission to review

    expected_output: dict = field(default_factory=dict)  # Schema of expected submission


@dataclass
class TaskPaused:
    """Returned when analyst needs user input."""

    role: str  # Which analyst paused
    questions: list[str]  # Questions needing answers
    context: str  # What analyst understood so far
    partial_spec: Optional[str] = None  # Any requirements already clear


@dataclass
class TaskReboundOffer:
    """Returned when repeated failures suggest design issue."""

    failures: int  # How many times coder failed
    last_rejection: str  # Most recent rejection reason
    pattern: Optional[str] = None  # Detected pattern in failures
    suggestion: str = "Consider consulting architect to revisit approach"


@dataclass
class TaskComplete:
    """Returned when all gates pass."""

    success: bool
    summary: str
    iterations: int
    files_changed: list[str]

    requirements: Optional[str] = None  # What was built (from BA)
    design: Optional[str] = None  # How it was built (from Architect)

    git_branch: Optional[str] = None  # If git mode is branch
    run_path: str = ""  # Path to .team/runs/...


@dataclass
class TaskEscalate:
    """Returned when max iterations reached without resolution."""

    reason: str
    iterations: int
    last_feedback: str  # Why it kept failing
    suggestion: str  # What user might do


@dataclass
class TaskStatus:
    """Current status of a task."""

    task: str  # Original task description
    state: TaskState
    current_role: Optional[str] = None
    iteration: int = 0
    history: list[dict] = field(default_factory=list)
    confirmed_requirements: Optional[str] = None  # If BA completed
    current_design: Optional[str] = None  # If architect completed


@dataclass
class Submission:
    """A submission from a role."""

    role: str
    role_type: RoleType
    iteration: int
    timestamp: datetime
    data: dict
    outcome: Optional[str] = None  # "confirmed", "approved", "rejected", etc.


@dataclass
class WorkflowRole:
    """A role in the workflow sequence."""

    role: str  # Role name (e.g., "ba", "architect")
    type: RoleType  # Role type


@dataclass
class WorkflowConfig:
    """Workflow configuration."""

    sequence: list[WorkflowRole]
    max_iterations: int = 5
    rebound_after_failures: int = 3
    on_max_iterations: str = "escalate"  # "escalate" | "fail"


@dataclass
class GitConfig:
    """Git integration configuration."""

    mode: str = "branch"  # "branch" | "current" | "none"
    branch_prefix: str = "team/"
    commit_message_format: str = "team({role}): {summary}"


@dataclass
class OutputConfig:
    """Output configuration."""

    runs_dir: str = ".team/runs"
    verbose: bool = True


@dataclass
class AgentConfig:
    """Configuration for a custom agent."""

    type: RoleType
    stance: Optional[str] = None
    context: list[str] = field(default_factory=list)


@dataclass
class Config:
    """Main configuration object."""

    version: int
    workflow: WorkflowConfig
    rules: list[str] = field(default_factory=list)
    context: dict[str, list[str]] = field(default_factory=dict)
    git: GitConfig = field(default_factory=GitConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    agents: dict[str, AgentConfig] = field(default_factory=dict)


@dataclass
class Agent:
    """An agent with its prompt and configuration."""

    name: str
    type: RoleType
    prompt: str
    config: Optional[AgentConfig] = None


@dataclass
class Task:
    """A task being executed."""

    id: str
    description: str
    state: TaskState
    current_role: Optional[str] = None
    current_role_index: int = 0
    iteration: int = 1

    confirmed_requirements: Optional[str] = None
    current_design: Optional[str] = None
    user_answers: Optional[str] = None

    submissions: list[Submission] = field(default_factory=list)
    coder_failures: int = 0
    last_rejection: Optional[dict] = None

    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    def get_files_changed(self) -> list[str]:
        """Extract list of files changed from coder submissions."""
        files = []
        for sub in self.submissions:
            if sub.role_type == RoleType.IMPLEMENTER and "files_changed" in sub.data:
                files.extend(sub.data["files_changed"])
        return list(set(files))  # Deduplicate
