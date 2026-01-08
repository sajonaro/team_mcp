"""State machine for Team MCP workflow."""

from datetime import datetime
from typing import Optional, Union
import re

from .types import (
    Task,
    TaskState,
    RoleType,
    Submission,
    RoleAssignment,
    TaskPaused,
    TaskComplete,
    TaskReboundOffer,
    TaskEscalate,
    TaskStatus,
    Config,
    Agent,
)
from .agents import load_all_agents
from .config import get_context_files, expand_glob_patterns


class StateMachine:
    """Manages task state and workflow transitions."""

    def __init__(self, config: Config):
        self.config = config
        self.task: Optional[Task] = None
        self.agents: dict[str, Agent] = {}

    def _generate_task_id(self, description: str) -> str:
        """Generate a task ID from timestamp and description."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        # Create slug from description
        slug = re.sub(r"[^a-z0-9]+", "-", description.lower())
        slug = slug[:50].strip("-")
        return f"{timestamp}_{slug}"

    def _record_submission(
        self, role: str, role_type: RoleType, data: dict, outcome: Optional[str] = None
    ) -> None:
        """Record a submission in task history."""
        if not self.task:
            return

        submission = Submission(
            role=role,
            role_type=role_type,
            iteration=self.task.iteration,
            timestamp=datetime.now(),
            data=data,
            outcome=outcome,
        )
        self.task.submissions.append(submission)

    def _make_role_assignment(
        self,
        role: str,
        role_type: RoleType,
        reviewing: Optional[dict] = None,
        feedback: Optional[str] = None,
    ) -> RoleAssignment:
        """Create a RoleAssignment for the given role."""
        if not self.task:
            raise ValueError("No active task")

        agent = self.agents[role]

        # Get context files for this role
        context_patterns = get_context_files(role, self.config)
        context_files = expand_glob_patterns(context_patterns)

        # Build role assignment based on type
        assignment = RoleAssignment(
            role=role,
            role_type=role_type.value,
            iteration=self.task.iteration,
            instructions=agent.prompt,
            rules=self.config.rules,
            context=context_files,
        )

        # Add type-specific context
        if role_type == RoleType.ANALYST:
            assignment.task = self.task.description

        elif role_type == RoleType.DESIGNER:
            assignment.task = self.task.description
            assignment.requirements = self.task.confirmed_requirements
            # If rebounding, provide failure context
            if self.task.last_rejection:
                assignment.failure_context = self._build_failure_context()

        elif role_type == RoleType.IMPLEMENTER:
            assignment.task = self.task.description
            assignment.requirements = self.task.confirmed_requirements
            assignment.design = self.task.current_design
            assignment.feedback = feedback

        elif role_type == RoleType.GATEKEEPER:
            assignment.reviewing = reviewing
            assignment.requirements = self.task.confirmed_requirements
            assignment.design = self.task.current_design

        return assignment

    def _build_failure_context(self) -> str:
        """Build context about repeated failures for architect rebound."""
        if not self.task:
            return ""

        failures = []
        for sub in self.task.submissions:
            if sub.role_type == RoleType.GATEKEEPER and not sub.data.get("approved"):
                failures.append(
                    f"Iteration {sub.iteration}: {sub.data.get('reason', 'No reason given')}"
                )

        return "\n".join(failures)

    def _detect_failure_pattern(self) -> Optional[str]:
        """Detect patterns in repeated failures."""
        if not self.task:
            return None

        # Simple pattern detection - look for repeated keywords
        rejection_reasons = []
        for sub in self.task.submissions:
            if sub.role_type == RoleType.GATEKEEPER and not sub.data.get("approved"):
                rejection_reasons.append(sub.data.get("reason", ""))

        # Check for common words
        if len(rejection_reasons) >= 2:
            words = {}
            for reason in rejection_reasons:
                for word in reason.lower().split():
                    if len(word) > 5:  # Only significant words
                        words[word] = words.get(word, 0) + 1

            # Find most common word
            if words:
                max_word = max(words.items(), key=lambda x: x[1])
                if max_word[1] >= 2:
                    return f"Repeated issue with: {max_word[0]}"

        return None

    def start_task(self, description: str) -> Union[RoleAssignment, TaskPaused]:
        """Start a new team task."""
        task_id = self._generate_task_id(description)

        self.task = Task(
            id=task_id,
            description=description,
            state=TaskState.IN_PROGRESS,
        )

        # Load agents for workflow
        self.agents = load_all_agents(self.config.workflow.sequence)

        # Start with first role
        first_role = self.config.workflow.sequence[0]
        self.task.current_role = first_role.role
        self.task.current_role_index = 0

        return self._make_role_assignment(first_role.role, first_role.type)

    def submit(
        self, submission: dict
    ) -> Union[
        RoleAssignment, TaskPaused, TaskComplete, TaskReboundOffer, TaskEscalate
    ]:
        """Submit work for current role."""
        if not self.task:
            raise ValueError("No active task")

        current_workflow_role = self.config.workflow.sequence[
            self.task.current_role_index
        ]
        current_role = current_workflow_role.role
        current_type = current_workflow_role.type

        # Handle submission based on role type
        if current_type == RoleType.ANALYST:
            return self._handle_analyst_submission(submission)
        elif current_type == RoleType.DESIGNER:
            return self._handle_designer_submission(submission)
        elif current_type == RoleType.IMPLEMENTER:
            return self._handle_implementer_submission(submission)
        elif current_type == RoleType.GATEKEEPER:
            return self._handle_gatekeeper_submission(submission)
        else:
            raise ValueError(f"Unknown role type: {current_type}")

    def _handle_analyst_submission(
        self, submission: dict
    ) -> Union[RoleAssignment, TaskPaused]:
        """Handle submission from analyst."""
        if "questions" in submission:
            # Analyst has questions - pause for user input
            self.task.state = TaskState.PAUSED
            self._record_submission(
                self.task.current_role, RoleType.ANALYST, submission, outcome="paused"
            )
            return TaskPaused(
                role=self.task.current_role,
                questions=submission["questions"],
                context=submission.get("context", ""),
                partial_spec=submission.get("partial_spec"),
            )
        else:
            # Requirements confirmed
            self.task.confirmed_requirements = submission["confirmed_requirements"]
            self._record_submission(
                self.task.current_role,
                RoleType.ANALYST,
                submission,
                outcome="confirmed",
            )
            return self._advance_to_next_role()

    def _handle_designer_submission(self, submission: dict) -> RoleAssignment:
        """Handle submission from designer."""
        self.task.current_design = submission["design"]
        self._record_submission(
            self.task.current_role, RoleType.DESIGNER, submission, outcome="submitted"
        )
        return self._advance_to_next_role()

    def _handle_implementer_submission(self, submission: dict) -> RoleAssignment:
        """Handle submission from implementer."""
        self._record_submission(
            self.task.current_role,
            RoleType.IMPLEMENTER,
            submission,
            outcome="submitted",
        )
        return self._advance_to_next_role(reviewing=submission)

    def _handle_gatekeeper_submission(
        self, submission: dict
    ) -> Union[RoleAssignment, TaskComplete, TaskReboundOffer, TaskEscalate]:
        """Handle submission from gatekeeper."""
        approved = submission.get("approved", False)

        self._record_submission(
            self.task.current_role,
            RoleType.GATEKEEPER,
            submission,
            outcome="approved" if approved else "rejected",
        )

        if approved:
            # Move to next role or complete
            return self._advance_to_next_role()
        else:
            # Rejected - back to implementer
            return self._handle_rejection(submission)

    def _advance_to_next_role(
        self, reviewing: Optional[dict] = None
    ) -> Union[RoleAssignment, TaskComplete]:
        """Advance to the next role in the workflow."""
        if not self.task:
            raise ValueError("No active task")

        # Check if we're at the end
        if self.task.current_role_index >= len(self.config.workflow.sequence) - 1:
            # Task complete!
            return self._complete_task()

        # Move to next role
        self.task.current_role_index += 1
        next_workflow_role = self.config.workflow.sequence[self.task.current_role_index]
        self.task.current_role = next_workflow_role.role

        return self._make_role_assignment(
            next_workflow_role.role, next_workflow_role.type, reviewing=reviewing
        )

    def _handle_rejection(
        self, rejection: dict
    ) -> Union[RoleAssignment, TaskReboundOffer, TaskEscalate]:
        """Handle rejection from a gatekeeper."""
        self.task.iteration += 1
        self.task.coder_failures += 1
        self.task.last_rejection = rejection

        # Check if we should offer rebound
        if self.task.coder_failures == self.config.workflow.rebound_after_failures:
            self.task.state = TaskState.REBOUND_OFFERED
            return TaskReboundOffer(
                failures=self.task.coder_failures,
                last_rejection=rejection.get("reason", "No reason provided"),
                pattern=self._detect_failure_pattern(),
                suggestion="Consider consulting architect to revisit approach",
            )

        # Check max iterations
        if self.task.iteration > self.config.workflow.max_iterations:
            return self._escalate_task(rejection)

        # Find the implementer role to go back to
        implementer_index = None
        for i, role in enumerate(self.config.workflow.sequence):
            if role.type == RoleType.IMPLEMENTER:
                implementer_index = i
                break

        if implementer_index is None:
            raise ValueError("No implementer in workflow")

        self.task.current_role_index = implementer_index
        self.task.current_role = self.config.workflow.sequence[implementer_index].role

        feedback = f"{rejection.get('reason', '')}\n\nIssues:\n" + "\n".join(
            f"- {issue}" for issue in rejection.get("issues", [])
        )

        return self._make_role_assignment(
            self.task.current_role, RoleType.IMPLEMENTER, feedback=feedback
        )

    def _complete_task(self) -> TaskComplete:
        """Mark task as complete."""
        self.task.state = TaskState.COMPLETE
        self.task.completed_at = datetime.now()

        return TaskComplete(
            success=True,
            summary=f"Completed: {self.task.description}",
            iterations=self.task.iteration,
            files_changed=self.task.get_files_changed(),
            requirements=self.task.confirmed_requirements,
            design=self.task.current_design,
            run_path=f".team/runs/{self.task.id}",
        )

    def _escalate_task(self, rejection: dict) -> TaskEscalate:
        """Escalate task after max iterations."""
        self.task.state = TaskState.ESCALATED

        return TaskEscalate(
            reason="Maximum iterations reached without resolution",
            iterations=self.task.iteration,
            last_feedback=rejection.get("reason", ""),
            suggestion="Consider simplifying the task or manually reviewing the implementation",
        )

    def resume(self, user_input: str) -> RoleAssignment:
        """Resume a paused task with user input."""
        if not self.task:
            raise ValueError("No active task")

        if self.task.state == TaskState.PAUSED:
            # User answered analyst questions
            self.task.user_answers = user_input
            self.task.state = TaskState.IN_PROGRESS

            # Record the answers
            self._record_submission(
                self.task.current_role,
                RoleType.ANALYST,
                {"user_answers": user_input},
                outcome="resumed",
            )

            # Move to next role
            return self._advance_to_next_role()

        elif self.task.state == TaskState.REBOUND_OFFERED:
            if user_input.lower() in ("yes", "y"):
                # Go back to architect
                self.task.coder_failures = 0  # Reset counter
                self.task.state = TaskState.IN_PROGRESS

                # Find architect in workflow
                architect_index = None
                for i, role in enumerate(self.config.workflow.sequence):
                    if role.type == RoleType.DESIGNER:
                        architect_index = i
                        break

                if architect_index is None:
                    raise ValueError("No designer in workflow")

                self.task.current_role_index = architect_index
                self.task.current_role = self.config.workflow.sequence[
                    architect_index
                ].role

                return self._make_role_assignment(
                    self.task.current_role, RoleType.DESIGNER
                )
            else:
                # Continue with coder
                self.task.state = TaskState.IN_PROGRESS

                # Find implementer
                implementer_index = None
                for i, role in enumerate(self.config.workflow.sequence):
                    if role.type == RoleType.IMPLEMENTER:
                        implementer_index = i
                        break

                if implementer_index is None:
                    raise ValueError("No implementer in workflow")

                self.task.current_role_index = implementer_index
                self.task.current_role = self.config.workflow.sequence[
                    implementer_index
                ].role

                feedback = (
                    self.task.last_rejection.get("reason", "")
                    if self.task.last_rejection
                    else ""
                )
                return self._make_role_assignment(
                    self.task.current_role, RoleType.IMPLEMENTER, feedback=feedback
                )
        else:
            raise ValueError(f"Cannot resume task in state: {self.task.state}")

    def get_status(self) -> TaskStatus:
        """Get current task status."""
        if not self.task:
            return TaskStatus(
                task="",
                state=TaskState.NOT_STARTED,
            )

        # Build history
        history = []
        for sub in self.task.submissions:
            history.append(
                {
                    "role": sub.role,
                    "type": sub.role_type.value,
                    "iteration": sub.iteration,
                    "outcome": sub.outcome,
                    "timestamp": sub.timestamp.isoformat(),
                    "data": sub.data,
                }
            )

        return TaskStatus(
            task=self.task.description,
            state=self.task.state,
            current_role=self.task.current_role,
            iteration=self.task.iteration,
            history=history,
            confirmed_requirements=self.task.confirmed_requirements,
            current_design=self.task.current_design,
        )

    def abort(self, reason: Optional[str] = None) -> None:
        """Abort current task."""
        if self.task:
            self.task.state = TaskState.ABORTED
            self._record_submission(
                self.task.current_role or "system",
                RoleType.IMPLEMENTER,  # Dummy type
                {"reason": reason or "Aborted by user"},
                outcome="aborted",
            )
