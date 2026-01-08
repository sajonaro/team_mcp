# Team MCP: Design Document v3

> A state machine MCP server that guides Claude through focused roles with quality gates — using your existing Claude subscription.

## Problem Statement

Working with LLMs for coding tasks suffers from a fundamental issue:

```
Current experience:
  Claude: "I've implemented the feature! ✅"
  
  Reality:
    - 5% implemented
    - 3 files broken
    - No tests
    - Hardcoded values
    - "TODO" comments everywhere
    - You spend 2 hours fixing
```

The LLM has no adversary. It marks its own homework. There's no forcing function to ensure quality before declaring "done."

## Core Insight

The solution isn't different knowledge — Claude already knows SQL, Python, security, patterns. The solution is **forced perspectives** and **quality gates**.

```
Desired experience:
  BA: "Before we start — email or SMS reset? Token expiry?"
  User: "Email, 24 hours"
  Architect: "We'll reuse TokenService, store in Redis, follow existing patterns"
  Coder: "I've implemented the feature!"
  QA: "Did you run it? Show me output."
  Coder: "..."
  QA: "It throws ImportError on line 12."
  Coder: *fixes*
  Reviewer: "You've duplicated logic from utils.py"
  Coder: *refactors*
  QA + Reviewer: "Approved."
  → Returns to user, actually working
```

**Agents are adversarial reviewers, not just workers.**

## Architecture

### Key Constraint

Claude Code CLI is interactive — there's no batch mode like `claude -p "prompt"`. We can't spawn separate Claude processes per agent.

### Solution: State Machine

Team MCP doesn't *call* Claude. Instead, **Claude uses Team MCP to manage workflow state**. Team MCP:

- Tracks current role and task state
- Enforces transitions (can't skip QA)
- Injects role-specific instructions
- Pauses for user input when needed (BA questions)
- Records all submissions
- Offers architect rebound on repeated failures
- Decides when complete or escalate

Claude stays in your single session and adopts different roles as directed by Team MCP.

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  You: "Start team task: add password reset"                                 │
│                                                                             │
│       ┌─────────────────────────────────────────────────────────────────┐   │
│       │ Team MCP: State → BA                                            │   │
│       └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  Claude (as BA): "Before we build, I need to clarify:                       │
│                   1. Reset via email or SMS?                                │
│                   2. Token expiry time?                                     │
│                   3. Rate limiting needed?"                                 │
│                                                                             │
│       ┌─────────────────────────────────────────────────────────────────┐   │
│       │ Team MCP: State → PAUSED (waiting for user)                     │   │
│       └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  You: "Email, 24h, yes rate limit to 3/hour"                                │
│                                                                             │
│       ┌─────────────────────────────────────────────────────────────────┐   │
│       │ Team MCP: State → ARCHITECT                                     │   │
│       └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  Claude (as Architect): "Here's my design:                                  │
│                          - Reuse TokenService from auth/                    │
│                          - Redis for token storage (auto-expiry)            │
│                          - RateLimiter middleware on endpoint               │
│                          - Follow existing email template pattern"          │
│                                                                             │
│       ┌─────────────────────────────────────────────────────────────────┐   │
│       │ Team MCP: State → CODER                                         │   │
│       └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  Claude (as Coder): [implements based on architect's design]                │
│                     [uses filesystem MCP, terminal MCP]                     │
│                     [submits with proof]                                    │
│                                                                             │
│       ┌─────────────────────────────────────────────────────────────────┐   │
│       │ Team MCP: State → QA                                            │   │
│       └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  Claude (as QA): "REJECTED: No integration test shown"                      │
│                                                                             │
│       ┌─────────────────────────────────────────────────────────────────┐   │
│       │ Team MCP: State → CODER (iteration 2)                           │   │
│       └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  Claude (as Coder): [fixes, adds integration test, resubmits]               │
│                                                                             │
│       ... QA approves → Reviewer approves ...                               │
│                                                                             │
│       ┌─────────────────────────────────────────────────────────────────┐   │
│       │ Team MCP: State → COMPLETE                                      │   │
│       └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  Claude: "Task complete! Branch ready to merge."                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Architect Rebound Flow

When coder fails repeatedly (e.g., 3 times), Team MCP offers to consult architect:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  [Iteration 3: QA rejects again]                                            │
│                                                                             │
│       ┌─────────────────────────────────────────────────────────────────┐   │
│       │ Team MCP: State → REBOUND_OFFERED                               │   │
│       │ "Failed 3 times. Want to consult architect?"                    │   │
│       └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                          ┌────────┴────────┐                                │
│                          ▼                 ▼                                │
│                                                                             │
│  Option A: You say "yes"              Option B: You say "no, keep trying"   │
│       │                                    │                                │
│       ▼                                    ▼                                │
│  ┌─────────────────────┐           ┌─────────────────────┐                  │
│  │ State → ARCHITECT   │           │ State → CODER       │                  │
│  │ (with failure       │           │ (iteration 4)       │                  │
│  │  context)           │           │                     │                  │
│  └─────────────────────┘           └─────────────────────┘                  │
│       │                                                                     │
│       ▼                                                                     │
│  Architect reviews failures,                                                │
│  proposes new approach                                                      │
│       │                                                                     │
│       ▼                                                                     │
│  Flow continues with new design                                             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Role Types

| Type | Purpose | Produces | Blocks Until |
|------|---------|----------|--------------|
| `analyst` | Clarify requirements, surface ambiguity | Questions → confirmed spec | User provides answers |
| `designer` | Technical approach, patterns, structure | Design/plan for implementer | Design submitted |
| `implementer` | Write code, make changes | Files + proof of execution | Work submitted |
| `gatekeeper` | Review and approve/reject | Approval or rejection + feedback | Approved |

## Default Agents

Team MCP ships with 5 agents out of the box:

| Agent | Type | Purpose |
|-------|------|---------|
| `ba` | analyst | Clarify requirements before building |
| `architect` | designer | Design approach, identify patterns, prevent wrong turns |
| `coder` | implementer | Write the actual code |
| `qa` | gatekeeper | Verify it works (execution proof) |
| `reviewer` | gatekeeper | Verify code quality and consistency |

### Default Workflow Sequence

```yaml
workflow:
  sequence:
    - role: ba
      type: analyst
    - role: architect
      type: designer
    - role: coder
      type: implementer
    - role: qa
      type: gatekeeper
    - role: reviewer
      type: gatekeeper
```

You can customize this — skip agents, reorder, add custom ones.

## MCP Server Interface

### Tools

```python
@tool
def start_task(task: str) -> RoleAssignment | TaskPaused:
    """
    Start a new team task.
    
    Returns either:
    - RoleAssignment: First role to adopt (if workflow starts with designer/implementer)
    - TaskPaused: If workflow starts with analyst who has questions
    
    Args:
        task: Description of what to accomplish
    """

@tool
def submit(submission: dict) -> RoleAssignment | TaskPaused | TaskComplete | TaskReboundOffer | TaskEscalate:
    """
    Submit work for current role.
    
    Submission format depends on role type:
    
    For 'analyst':
        submission: {
            "questions": ["question 1", "question 2"],  # If needs clarification
            # OR
            "confirmed_requirements": "clear spec..."    # If requirements clear
        }
    
    For 'designer':
        submission: {
            "design": "technical approach...",
            "patterns": ["pattern 1", "pattern 2"],
            "warnings": ["potential issue 1"]  # Optional
        }
    
    For 'implementer':
        submission: {
            "summary": "what I did",
            "files_changed": ["path/to/file.py", ...],
            "proof": "command output showing it works",
            "concerns": "optional: anything I'm unsure about"
        }
    
    For 'gatekeeper':
        submission: {
            "approved": true/false,
            "reason": "why approved or rejected",
            "issues": ["specific issue 1", ...]  # Required if rejected
        }
    
    Returns one of:
        - RoleAssignment: Next role to adopt
        - TaskPaused: Analyst needs user input
        - TaskComplete: All gates passed
        - TaskReboundOffer: Multiple failures, offering architect consult
        - TaskEscalate: Max iterations reached
    """

@tool
def resume(input: str) -> RoleAssignment:
    """
    Resume a paused task with user input.
    
    Use after TaskPaused (answering analyst questions) or 
    TaskReboundOffer (deciding whether to consult architect).
    
    Args:
        input: User's answers/decision
               For TaskPaused: answers to analyst questions
               For TaskReboundOffer: "yes" to consult architect, "no" to continue
    """

@tool
def get_status() -> TaskStatus:
    """
    Get current task status.
    
    Returns:
        {
            "task": "original task description",
            "state": "in_progress" | "paused" | "rebound_offered" | "complete" | "escalated" | "aborted",
            "current_role": "ba" | "architect" | "coder" | "qa" | "reviewer",
            "iteration": 2,
            "history": [
                {"role": "ba", "type": "analyst", "outcome": "confirmed", ...},
                {"role": "architect", "type": "designer", "design": "...", ...},
                {"role": "coder", "iteration": 1, "summary": "...", ...},
                {"role": "qa", "iteration": 1, "approved": false, "reason": "...", ...},
                ...
            ],
            "confirmed_requirements": "...",  # If BA completed
            "current_design": "..."           # If architect completed
        }
    """

@tool
def get_history(role: str = None, iteration: int = None) -> list[Submission]:
    """Get detailed submission history. Filter by role or iteration."""

@tool  
def abort(reason: str = None) -> None:
    """Abort current task."""
```

### Response Types

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class RoleAssignment:
    """Returned when Claude should adopt a new role."""
    
    role: str                      # "ba", "architect", "coder", "qa", "reviewer", or custom
    role_type: str                 # "analyst" | "designer" | "implementer" | "gatekeeper"
    iteration: int                 # Current iteration number
    
    instructions: str              # System prompt for this role
    rules: list[str]               # Global rules that apply
    context: list[str]             # Relevant files/docs loaded
    
    # For analyst:
    task: str                      # Original task to analyze
    
    # For designer:
    task: str                      # Task description
    requirements: str | None       # Confirmed requirements from analyst
    failure_context: str | None    # If rebounding, what went wrong
    
    # For implementer:
    task: str                      # What to accomplish
    requirements: str | None       # From analyst
    design: str | None             # From designer
    feedback: str | None           # Feedback from previous rejection
    
    # For gatekeeper:
    reviewing: dict | None         # The submission to review
    requirements: str | None       # To verify against
    design: str | None             # To verify against
    
    expected_output: dict          # Schema of expected submission

@dataclass  
class TaskPaused:
    """Returned when analyst needs user input."""
    
    role: str                      # Which analyst paused
    questions: list[str]           # Questions needing answers
    context: str                   # What analyst understood so far
    partial_spec: str | None       # Any requirements already clear
    
    # User calls resume(answers) to continue

@dataclass
class TaskReboundOffer:
    """Returned when repeated failures suggest design issue."""
    
    failures: int                  # How many times coder failed
    last_rejection: str            # Most recent rejection reason
    pattern: str | None            # Detected pattern in failures
    suggestion: str                # "Consider consulting architect to revisit approach"
    
    # User calls resume("yes") to consult architect
    # User calls resume("no") to continue with coder

@dataclass
class TaskComplete:
    """Returned when all gates pass."""
    
    success: bool
    summary: str
    iterations: int
    files_changed: list[str]
    
    requirements: str              # What was built (from BA)
    design: str                    # How it was built (from Architect)
    
    git_branch: str | None         # If git mode is branch
    run_path: str                  # Path to .team/runs/...

@dataclass
class TaskEscalate:
    """Returned when max iterations reached without resolution."""
    
    reason: str
    iterations: int
    last_feedback: str             # Why it kept failing
    suggestion: str                # What user might do
```

## Task States

```python
class TaskState(Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"                    # Waiting for user input (analyst questions)
    REBOUND_OFFERED = "rebound_offered"  # Offering architect consult after failures
    COMPLETE = "complete"
    ESCALATED = "escalated"
    ABORTED = "aborted"
```

## Configuration

### Layered Configuration

```
1. Package defaults     src/team_mcp/defaults/     (shipped with package)
2. User global          ~/.team-mcp/               (user customizations)
3. Project local        ./.team/                   (project-specific)

Later layers override earlier. Deep merge for config, full override for prompts.
```

### Directory Structure

#### Global (User Defaults)

```
~/.team-mcp/
├── config.yaml
├── agents/
│   ├── ba/
│   │   └── prompt.md
│   ├── architect/
│   │   └── prompt.md
│   ├── coder/
│   │   └── prompt.md
│   ├── qa/
│   │   └── prompt.md
│   └── reviewer/
│       └── prompt.md
└── context/
    └── defaults.md
```

#### Project-Level

```
my-project/.team/
├── config.yaml
├── agents/
│   ├── security/              # Custom agent
│   │   ├── prompt.md
│   │   └── agent.yaml
│   └── coder/
│       └── prompt.md          # Override default coder
├── context/
│   ├── architecture.md
│   └── conventions.md
└── runs/                      # Output artifacts
    └── 2025-01-08_153042_add-password-reset/
        ├── task.md
        ├── requirements.md    # BA output
        ├── design.md          # Architect output
        ├── iterations/
        │   ├── 01_coder.md
        │   ├── 01_qa_review.md
        │   └── ...
        └── summary.md
```

### Main Configuration File

```yaml
# .team/config.yaml

version: 1

# Workflow — always explicit, no magic presets
workflow:
  sequence:
    - role: ba
      type: analyst
    - role: architect
      type: designer
    - role: coder
      type: implementer
    - role: qa
      type: gatekeeper
    - role: reviewer
      type: gatekeeper
  
  max_iterations: 5
  
  # When to offer architect rebound
  rebound:
    after_failures: 3           # Offer after this many coder failures
  
  on_max_iterations: escalate   # escalate | fail

# Global rules (injected into ALL roles)
rules:
  - "No TODO/FIXME in final code"
  - "No placeholder implementations"
  - "All existing tests must pass"
  - "Show real output, not hypothetical"
  - "If you break something, fix it before submitting"

# Context to load per role
context:
  always:
    - .team/context/*.md
  ba:
    - README.md
    - docs/requirements/*.md
  architect:
    - src/**/README.md
    - .team/context/architecture.md
  coder:
    - src/**/*.py
  qa:
    - tests/**/*.py
  reviewer:
    - .team/context/conventions.md

# Git integration
git:
  mode: branch                  # branch | current | none
  branch_prefix: "team/"
  commit_message_format: "team({role}): {summary}"

# Output settings  
output:
  runs_dir: .team/runs
  verbose: true
```

## Default Agent Prompts

### BA (Business Analyst)

```markdown
<!-- defaults/agents/ba/prompt.md -->

You are BA — the Business Analyst.

## Your Job

Clarify requirements BEFORE anyone writes code. Surface ambiguity. Confirm understanding.

Your questions now save hours of rework later.

## Process

1. Read the task description
2. Identify what's NOT specified
3. Ask clarifying questions
4. Wait for user answers
5. Produce confirmed requirements

## Questions to Consider

- What's the exact scope? (MVP vs full feature)
- What are the inputs and outputs?
- What are the edge cases?
- What should happen on errors?
- Are there performance requirements?
- What's out of scope?

## If Task is Already Clear

If the task is unambiguous and complete, you may skip questions and confirm requirements directly.

## Submission Format

If you have questions:
```json
{
  "questions": [
    "Should password reset be via email or SMS?",
    "What should the token expiry time be?",
    "Should we rate-limit reset requests?"
  ]
}
```

If requirements are clear:
```json
{
  "confirmed_requirements": "Password reset feature:\n- Reset via email link\n- Token expires in 24h\n- Rate limit: 3 requests per hour per user\n- Must invalidate token after use"
}
```
```

### Architect

```markdown
<!-- defaults/agents/architect/prompt.md -->

You are ARCHITECT — the technical designer.

## Your Job

Design the approach BEFORE coding starts. Identify patterns. Prevent wrong turns.

Good architecture now prevents rewrites later.

## Process

1. Review the confirmed requirements
2. Analyze existing codebase patterns
3. Design the technical approach
4. Identify reusable components
5. Flag potential issues

## Consider

- What existing code can we reuse?
- What patterns does this codebase follow?
- Where should new code live?
- What are the dependencies?
- What could go wrong?

## If Rebounding (After Failures)

If you're being consulted because the coder failed repeatedly:

1. Review what went wrong
2. Identify why the approach failed
3. Propose a different approach
4. Be specific about what to change

## Submission Format

```json
{
  "design": "## Approach\n\n1. Create PasswordResetService in src/auth/\n2. Reuse existing TokenService for token generation\n3. Store tokens in Redis (auto-expiry)\n4. Add POST /auth/reset-password endpoint\n5. Use existing EmailService for sending\n\n## File Structure\n- src/auth/password_reset.py (new)\n- src/routes/auth.py (modify)\n- tests/test_password_reset.py (new)",
  "patterns": [
    "Follow existing service pattern in src/auth/",
    "Use dependency injection like other services",
    "Match existing test structure"
  ],
  "warnings": [
    "Redis connection might need configuration",
    "Email templates need review"
  ]
}
```
```

### Coder

```markdown
<!-- defaults/agents/coder/prompt.md -->

You are CODER — the implementer.

## Your Job

Write code that actually works. Not sketches. Not "this should work." 
Code that demonstrably runs.

## Process

1. Review the requirements (from BA)
2. Follow the design (from Architect)
3. Implement the solution
4. Prove it works
5. Submit with evidence

## After ANY Code Change

You MUST provide:

1. **Files changed** — list every file you created or modified
2. **How to test** — exact command to run
3. **Actual output** — copy/paste real terminal output
4. **Existing tests** — prove you didn't break them

## Rules

- Follow the architect's design
- No TODO comments
- No placeholder functions  
- No "you'll need to implement this"
- If you're unsure, say so — don't fake it

## If You Received Feedback

Address ALL points from the previous rejection before resubmitting.

## Submission Format

```json
{
  "summary": "Implemented password reset with token generation, email sending, and rate limiting",
  "files_changed": [
    "src/auth/password_reset.py",
    "src/routes/auth.py",
    "tests/test_password_reset.py"
  ],
  "proof": "$ pytest tests/test_password_reset.py -v\n...\n4 passed in 0.23s\n\n$ curl -X POST localhost:8000/auth/reset-password -d '{\"email\": \"test@example.com\"}'\n{\"message\": \"Reset email sent\"}\n\n$ pytest tests/ -v\n...\n47 passed in 2.31s",
  "concerns": "Redis configuration is hardcoded to localhost"
}
```
```

### QA

```markdown
<!-- defaults/agents/qa/prompt.md -->

You are QA — the skeptic.

## Your Job

Reject until proven working. Your default answer is NO.

## Process

1. Review the requirements (what should it do?)
2. Review the coder's submission
3. Verify the proof is real and sufficient
4. Approve only with evidence

## You Must Verify

1. **Code executes** — not "should work", actually runs
2. **Output shown** — real terminal output, not hypothetical
3. **Tests pass** — actually ran, not "would pass"
4. **Nothing broken** — existing functionality still works
5. **Requirements met** — does it do what BA specified?

## Reject If

- "I believe this works" — belief is not proof
- "This should work" — should is not does
- No test output shown
- Only unit tests (what about integration?)
- Existing tests not verified
- Requirements not fully addressed

## Approve Only

When you have EVIDENCE. Terminal output. Test results. Proof.

## Submission Format

If rejecting:
```json
{
  "approved": false,
  "reason": "No integration test showing actual HTTP request to endpoint",
  "issues": [
    "Only unit tests shown, no end-to-end verification",
    "Existing test suite not run",
    "Rate limiting not demonstrated"
  ]
}
```

If approving:
```json
{
  "approved": true,
  "reason": "All tests pass, endpoint works, rate limiting verified, existing tests still pass"
}
```
```

### Reviewer

```markdown
<!-- defaults/agents/reviewer/prompt.md -->

You are REVIEWER — the quality guardian.

## Your Job

Enforce consistency, quality, and maintainability.
The code might work, but is it GOOD?

## Process

1. Review the design (what approach was planned?)
2. Review the code changes
3. Check for quality issues
4. Approve only if maintainable

## Check For

1. **Duplication** — does this repeat existing code?
2. **Patterns** — does it match the codebase style?
3. **Design adherence** — did coder follow architect's plan?
4. **Complexity** — is this the simple solution?
5. **Naming** — will future devs understand this?
6. **Structure** — is it in the right place?
7. **Error handling** — are failures handled gracefully?

## Reject If

- Duplicates logic that exists elsewhere
- Inconsistent with established patterns
- Deviates from architect's design without reason
- Over-engineered for the problem
- Poor naming or unclear structure
- Missing error handling

## Submission Format

If rejecting:
```json
{
  "approved": false,
  "reason": "Code duplicates existing token generation logic",
  "issues": [
    "TokenService already has generate_token() - should reuse",
    "Error messages don't match existing format",
    "Missing docstrings on public functions"
  ]
}
```

If approving:
```json
{
  "approved": true,
  "reason": "Follows established patterns, clean implementation, good test coverage"
}
```
```

## Adding Custom Agents

Adding a custom agent is straightforward:

### 1. Create the Agent Folder

```bash
mkdir -p .team/agents/security
```

### 2. Write the Prompt

```markdown
<!-- .team/agents/security/prompt.md -->

You are SECURITY — the paranoid one.

## Your Job

Find security vulnerabilities before they ship.

## Check For

- SQL injection possibilities
- Hardcoded secrets or credentials
- Missing input validation  
- Authentication/authorization gaps
- Sensitive data exposure
- Insecure dependencies

## Reject If

Any security concern, no matter how minor.
We fix it now or we fix it after the breach.

## Submission Format

```json
{
  "approved": false,
  "reason": "SQL injection vulnerability in user input handling",
  "issues": [
    "Line 45: User input passed directly to SQL query",
    "No rate limiting on login endpoint",
    "Password reset token is predictable"
  ]
}
```
```

### 3. (Optional) Add Configuration

```yaml
# .team/agents/security/agent.yaml

type: gatekeeper
stance: paranoid

context:
  - src/auth/**/*.py
  - src/routes/**/*.py
```

### 4. Add to Workflow

```yaml
# .team/config.yaml

workflow:
  sequence:
    - role: ba
      type: analyst
    - role: architect
      type: designer
    - role: coder
      type: implementer
    - role: qa
      type: gatekeeper
    - role: security        # Your custom agent
      type: gatekeeper
    - role: reviewer
      type: gatekeeper
```

That's it. Team MCP auto-discovers agents from the folder structure.

## Shorter Workflows

Don't need all 5 agents? Just specify what you want:

### Quick Tasks (Skip BA and Architect)

```yaml
workflow:
  sequence:
    - role: coder
      type: implementer
    - role: qa
      type: gatekeeper
    - role: reviewer
      type: gatekeeper
```

### Solo Coder with QA

```yaml
workflow:
  sequence:
    - role: coder
      type: implementer
    - role: qa
      type: gatekeeper
```

### Full Team + Security

```yaml
workflow:
  sequence:
    - role: ba
      type: analyst
    - role: architect
      type: designer
    - role: coder
      type: implementer
    - role: qa
      type: gatekeeper
    - role: security
      type: gatekeeper
    - role: reviewer
      type: gatekeeper
```

## Run Artifacts

Each run produces artifacts in `.team/runs/`:

```
.team/runs/2025-01-08_153042_add-password-reset/
├── task.md              # Original task
├── requirements.md      # BA's confirmed requirements
├── design.md            # Architect's design
├── iterations/
│   ├── 01_coder.md
│   ├── 01_qa_review.md
│   ├── 02_coder.md
│   ├── 02_qa_review.md
│   └── 02_reviewer_review.md
└── summary.md
```

### Example Summary

```markdown
# Run Summary

## Task
Add password reset functionality

## Result: ✅ SUCCESS

## Requirements (from BA)
- Reset via email link
- Token expires in 24h
- Rate limit: 3 requests per hour
- Invalidate token after use

## Design (from Architect)
- PasswordResetService in src/auth/
- Reuse TokenService
- Redis for token storage
- POST /auth/reset-password endpoint

## Iterations

| # | Role | Outcome |
|---|------|---------|
| - | ba | ✅ Requirements confirmed |
| - | architect | ✅ Design submitted |
| 1 | coder | Submitted |
| 1 | qa | ❌ Rejected — no integration test |
| 2 | coder | Submitted |  
| 2 | qa | ✅ Approved |
| 2 | reviewer | ✅ Approved |

**Coder iterations:** 2

## Files Changed
- src/auth/password_reset.py (new)
- src/routes/auth.py (modified)
- tests/test_password_reset.py (new)
- tests/integration/test_auth.py (modified)

## Git
- **Branch:** `team/2025-01-08_153042_add-password-reset`
- **Commits:** 4
- **Merge:** `git checkout main && git merge team/2025-01-08_153042_add-password-reset`
```

## Git Integration

### Modes

| Mode | Behavior |
|------|----------|
| `branch` | Creates branch per run, commits each iteration, does NOT auto-merge |
| `current` | Commits to current branch after successful completion only |
| `none` | No git operations |

### Branch Mode Flow

```
Before:
  main ─────●

During run:
  main ─────●
             \
              ● team/2025-01-08_153042_add-password-reset
              │ "team(architect): design submitted"
              │
              ● "team(coder): iteration 1"
              │
              ● "team(coder): iteration 2 - address qa feedback"  
              │
              ● "team(complete): add password reset [qa:✓ reviewer:✓]"

After:
  You review, merge when ready
```

## Implementation

### Project Structure

```
team-mcp/
├── pyproject.toml
├── README.md
├── src/
│   └── team_mcp/
│       ├── __init__.py
│       ├── server.py              # MCP server entry point
│       ├── config.py              # Layered config loading  
│       ├── discovery.py           # Agent auto-discovery
│       ├── state.py               # Task state management
│       ├── workflow.py            # Workflow sequencing, rebound logic
│       ├── git.py                 # Git integration
│       ├── types.py               # RoleAssignment, TaskPaused, etc.
│       ├── agents/
│       │   ├── loader.py          # Load from prompt.md + agent.yaml
│       │   └── registry.py        # Available agents
│       ├── output/
│       │   ├── markdown.py        # Write run artifacts  
│       │   └── formatter.py       # Format responses
│       └── defaults/              # Shipped defaults
│           ├── config.yaml
│           └── agents/
│               ├── ba/
│               │   └── prompt.md
│               ├── architect/
│               │   └── prompt.md
│               ├── coder/
│               │   └── prompt.md
│               ├── qa/
│               │   └── prompt.md
│               └── reviewer/
│                   └── prompt.md
└── examples/
    └── .team/
        ├── config.yaml
        └── context/
            └── example.md
```

### Dependencies

```toml
[project]
dependencies = [
    "mcp",           # MCP server SDK
    "pyyaml",        # Config parsing  
    "rich",          # Terminal formatting (optional)
]
```

### Core State Machine

```python
# state.py

class StateMachine:
    def __init__(self, config: Config):
        self.config = config
        self.task: Optional[Task] = None
        self.coder_failures = 0
        
    def start_task(self, description: str) -> RoleAssignment | TaskPaused:
        self.task = Task(
            id=self._generate_id(description),
            description=description,
            state=TaskState.IN_PROGRESS,
        )
        
        first_role = self.config.workflow.sequence[0]
        self.task.current_role = first_role.role
        self.task.current_role_index = 0
        
        self.git.start_run(self.task.id)
        self.output.create_run(self.task)
        
        return self._make_role_assignment(first_role)
    
    def submit(self, submission: dict) -> RoleAssignment | TaskPaused | TaskComplete | TaskReboundOffer | TaskEscalate:
        current = self.config.workflow.sequence[self.task.current_role_index]
        
        # Record submission
        self._record_submission(current.role, submission)
        
        if current.type == "analyst":
            return self._handle_analyst_submission(submission)
        elif current.type == "designer":
            return self._handle_designer_submission(submission)
        elif current.type == "implementer":
            return self._handle_implementer_submission(submission)
        elif current.type == "gatekeeper":
            return self._handle_gatekeeper_submission(submission)
    
    def _handle_analyst_submission(self, submission) -> RoleAssignment | TaskPaused:
        if "questions" in submission:
            self.task.state = TaskState.PAUSED
            return TaskPaused(
                role=self.task.current_role,
                questions=submission["questions"],
                context=submission.get("context", ""),
                partial_spec=submission.get("partial_spec")
            )
        else:
            # Requirements confirmed, move to next role
            self.task.confirmed_requirements = submission["confirmed_requirements"]
            return self._advance_to_next_role()
    
    def _handle_designer_submission(self, submission) -> RoleAssignment:
        self.task.current_design = submission["design"]
        self.git.commit("architect", "design submitted")
        return self._advance_to_next_role()
    
    def _handle_implementer_submission(self, submission) -> RoleAssignment:
        self.git.commit("coder", f"iteration {self.task.iteration}")
        return self._advance_to_next_role(reviewing=submission)
    
    def _handle_gatekeeper_submission(self, submission) -> RoleAssignment | TaskComplete | TaskReboundOffer | TaskEscalate:
        if submission.get("approved"):
            return self._advance_to_next_role()
        else:
            # Rejected — back to implementer
            return self._handle_rejection(submission)
    
    def _handle_rejection(self, rejection) -> RoleAssignment | TaskReboundOffer | TaskEscalate:
        self.task.iteration += 1
        self.coder_failures += 1
        
        # Check if we should offer rebound
        rebound_after = self.config.workflow.rebound.get("after_failures", 3)
        if self.coder_failures == rebound_after:
            self.task.state = TaskState.REBOUND_OFFERED
            return TaskReboundOffer(
                failures=self.coder_failures,
                last_rejection=rejection.get("reason"),
                pattern=self._detect_failure_pattern(),
                suggestion="Consider consulting architect to revisit approach"
            )
        
        # Check max iterations
        if self.task.iteration > self.config.workflow.max_iterations:
            return self._escalate_task(rejection)
        
        # Back to implementer
        return self._assign_implementer(feedback=rejection)
    
    def resume(self, input: str) -> RoleAssignment:
        if self.task.state == TaskState.PAUSED:
            # User answered analyst questions
            self.task.user_answers = input
            return self._advance_to_next_role()
        
        elif self.task.state == TaskState.REBOUND_OFFERED:
            if input.lower() in ("yes", "y"):
                # Go back to architect
                self.coder_failures = 0  # Reset counter
                return self._assign_architect(rebound=True)
            else:
                # Continue with coder
                self.task.state = TaskState.IN_PROGRESS
                return self._assign_implementer(feedback=self.task.last_rejection)
```

## Example Session

```
┌────────────────────────────────────────────────────────────────────────────┐
│ Claude Code Session                                                        │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│ You: Start team task: add password reset functionality                     │
│                                                                            │
│ Claude: [calls team.start_task("add password reset functionality")]        │
│                                                                            │
│ Response: RoleAssignment(role="ba", type="analyst", ...)                   │
│                                                                            │
│ Claude (as BA): Before we build this, I need to clarify a few things.      │
│                                                                            │
│ [calls team.submit({                                                       │
│   "questions": [                                                           │
│     "Should reset be via email or SMS?",                                   │
│     "What should the token expiry time be?",                               │
│     "Should we rate-limit reset requests?",                                │
│     "Should the token be single-use?"                                      │
│   ]                                                                        │
│ })]                                                                        │
│                                                                            │
│ Response: TaskPaused(questions=[...])                                      │
│                                                                            │
│ Claude: I have some questions before we proceed:                           │
│         1. Should reset be via email or SMS?                               │
│         2. What should the token expiry time be?                           │
│         3. Should we rate-limit reset requests?                            │
│         4. Should the token be single-use?                                 │
│                                                                            │
│ You: Email, 24 hours, yes 3 per hour, yes single use                       │
│                                                                            │
│ Claude: [calls team.resume("Email, 24 hours, yes 3 per hour, single use")] │
│                                                                            │
│ Response: RoleAssignment(role="architect", type="designer", ...)           │
│                                                                            │
│ Claude (as Architect): Based on the requirements, here's my design...      │
│                                                                            │
│ [calls team.submit({                                                       │
│   "design": "## Approach\n1. Create PasswordResetService...",              │
│   "patterns": ["Reuse TokenService", "Follow existing email pattern"],     │
│   "warnings": ["Redis config may need setup"]                              │
│ })]                                                                        │
│                                                                            │
│ Response: RoleAssignment(role="coder", type="implementer", ...)            │
│                                                                            │
│ Claude (as Coder): Following the architect's design...                     │
│         [creates files, runs tests]                                        │
│                                                                            │
│ [calls team.submit({                                                       │
│   "summary": "Implemented password reset...",                              │
│   "files_changed": ["src/auth/password_reset.py", ...],                    │
│   "proof": "$ pytest ... 4 passed"                                         │
│ })]                                                                        │
│                                                                            │
│ Response: RoleAssignment(role="qa", type="gatekeeper", reviewing={...})    │
│                                                                            │
│ Claude (as QA): Reviewing the submission...                                │
│         No integration test shown. Rejecting.                              │
│                                                                            │
│ [calls team.submit({                                                       │
│   "approved": false,                                                       │
│   "reason": "No integration test",                                         │
│   "issues": ["Only unit tests", "No HTTP request shown"]                   │
│ })]                                                                        │
│                                                                            │
│ Response: RoleAssignment(role="coder", iteration=2, feedback={...})        │
│                                                                            │
│ Claude (as Coder): Addressing QA feedback...                               │
│         [adds integration test, reruns everything]                         │
│                                                                            │
│ ... QA approves → Reviewer approves ...                                    │
│                                                                            │
│ Response: TaskComplete(success=true, iterations=2, ...)                    │
│                                                                            │
│ Claude: ✅ Task complete!                                                   │
│         - Requirements: Email reset, 24h expiry, rate limited              │
│         - Files: src/auth/password_reset.py, +3 more                       │
│         - Branch: team/2025-01-08_160532_add-password-reset                │
│         - Run details: .team/runs/2025-01-08_160532_.../summary.md         │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

## MVP Scope

### MVP Includes

- [x] 5 default agents: ba, architect, coder, qa, reviewer
- [x] 4 role types: analyst, designer, implementer, gatekeeper
- [x] Always-explicit workflow configuration
- [x] Layered config (defaults → global → project)
- [x] Custom agents via folder + prompt.md
- [x] TaskPaused state for analyst questions
- [x] TaskReboundOffer after N coder failures (user decides)
- [x] All MCP tools: start_task, submit, resume, get_status, abort
- [x] Markdown artifacts in .team/runs/
- [x] Git integration (branch/current/none)

### MVP Excludes (Future)

- [ ] Parallel gatekeepers
- [ ] Conditional workflows
- [ ] Cost/token tracking
- [ ] Web UI for viewing runs
- [ ] Cross-run learning
- [ ] Multiple implementers

## Open Questions (Post-MVP)

1. **What if analyst keeps asking questions?**
   - Cap at 2 rounds of questions?
   - Or trust the prompting to be reasonable?

2. **Designer rejection?**
   - Can architect reject coder's work directly?
   - Or only gatekeepers can reject?

3. **Parallel gates?**
   - Run QA and Reviewer simultaneously
   - Requires DAG workflow, more complexity
