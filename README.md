# Team MCP

> A state machine MCP server that guides Claude through focused roles with quality gates — using your existing Claude subscription.

## Overview

Team MCP solves a fundamental problem with LLM-based coding: **the LLM has no adversary**. It marks its own homework, leading to incomplete implementations, broken tests, and hours of manual fixes.

Team MCP enforces **forced perspectives** through a workflow of specialized agents:

- **BA (Business Analyst)**: Clarifies requirements before coding starts
- **Architect**: Designs the approach and identifies patterns
- **Coder**: Implements the solution with proof it works
- **QA**: Verifies execution with real evidence
- **Reviewer**: Ensures code quality and consistency

Each agent acts as an adversarial reviewer, not just a worker. Code doesn't progress until it passes quality gates.

## Key Features

- ✅ **State Machine Workflow**: Claude adopts different roles as directed by Team MCP
- ✅ **Quality Gates**: Code must pass QA and Reviewer before completion
- ✅ **Architect Rebound**: After repeated failures, consult architect for a new approach
- ✅ **Git Integration**: Automatic branching and commits (optional)
- ✅ **Run Artifacts**: Markdown files documenting every step
- ✅ **Customizable**: Add your own agents and workflows

## Installation

### Option 1: Install from GitHub (Recommended for Users)

```bash
# Install directly from GitHub
pip install git+https://github.com/sajonaro/team-mcp.git

# Or install a specific version/tag
pip install git+https://github.com/sajonaro/team-mcp.git@v0.1.0
```

### Option 2: Install from PyPI (When Published)

```bash
pip install team-mcp
```

### Option 3: Install from Source (For Development)

```bash
# Clone the repository
git clone https://github.com/sajonaro/team-mcp.git
cd team-mcp

# Install in development mode
pip install -e .

# Or build and install
pip install .
```

## Quick Start

### 1. Configure MCP Server

Add Team MCP to your MCP settings (e.g., `(~/.vscode-server/data/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json)`):

```json
{
  "mcpServers": {
    "team-mcp": {
      "command": "python",
      "args": ["-m", "team_mcp.server"]
    }
  }
}
```

### 2. Start Using Team MCP

In your Claude conversation:

```
Start team task: add password reset functionality
```

Team MCP will:
1. BA asks clarifying questions
2. You provide answers
3. Architect designs the approach
4. Coder implements
5. QA verifies it works
6. Reviewer checks code quality
7. Done! ✅

## How It Works

### State Machine

Team MCP doesn't call Claude. Instead, **Claude uses Team MCP to manage workflow state**. Team MCP:

- Tracks current role and task state
- Enforces transitions (can't skip QA)
- Injects role-specific instructions
- Pauses for user input when needed (BA questions)
- Records all submissions
- Offers architect rebound on repeated failures
- Decides when complete or escalate

### Workflow Example

```
┌─────────────────────────────────────────┐
│  You: "Start team task: add password    │
│        reset functionality"             │
└─────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│  BA: "Before we build, I need to        │
│       clarify:                          │
│       1. Reset via email or SMS?        │
│       2. Token expiry time?             │
│       3. Rate limiting needed?"         │
└─────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│  You: "Email, 24h, yes 3/hour"          │
└─────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│  Architect: "Here's my design:          │
│             - Reuse TokenService        │
│             - Redis for storage         │
│             - Follow email pattern"     │
└─────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│  Coder: [implements, runs tests]        │
└─────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│  QA: "REJECTED: No integration test"    │
└─────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│  Coder: [fixes, adds test, reruns]      │
└─────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│  QA: ✅ Approved                        │
│  Reviewer: ✅ Approved                  │
│  Task Complete!                         │
└─────────────────────────────────────────┘
```

## Configuration

### Layered Configuration

Configuration is loaded in order (later overrides earlier):

1. **Package defaults** - `src/team_mcp/defaults/`
2. **User global** - `~/.team-mcp/`
3. **Project local** - `./.team/`

### Example Project Configuration

Create `.team/config.yaml`:

```yaml
version: 1

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
  
  rebound:
    after_failures: 3
  
  on_max_iterations: escalate

rules:
  - "No TODO/FIXME in final code"
  - "No placeholder implementations"
  - "All existing tests must pass"

git:
  mode: branch  # branch | current | none
  branch_prefix: "team/"
  commit_message_format: "team({role}): {summary}"

output:
  runs_dir: .team/runs
  verbose: true
```

## Custom Agents

### Add a Security Agent

1. Create the agent folder:

```bash
mkdir -p .team/agents/security
```

2. Write the prompt (`.team/agents/security/prompt.md`):

```markdown
You are SECURITY — the paranoid one.

## Your Job

Find security vulnerabilities before they ship.

## Check For

- SQL injection possibilities
- Hardcoded secrets
- Missing input validation
- Auth/authz gaps
- Sensitive data exposure

## Submission Format

\```json
{
  "approved": false,
  "reason": "SQL injection vulnerability",
  "issues": [
    "Line 45: User input passed directly to SQL query"
  ]
}
\```
```

3. Add to workflow:

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
    - role: security  # Your custom agent
      type: gatekeeper
    - role: reviewer
      type: gatekeeper
```

## Run Artifacts

Each run creates detailed artifacts in `.team/runs/`:

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
└── summary.md           # Final summary
```

## Available MCP Tools

- `start_task` - Start a new team task
- `submit` - Submit work for current role
- `resume` - Resume a paused task with user input
- `get_status` - Get current task status
- `get_history` - Get detailed submission history
- `abort` - Abort current task

## Shorter Workflows

Don't need all 5 agents? Customize:

### Quick Tasks (Skip BA and Architect)

```yaml
workflow:
  sequence:
    - role: coder
      type: implementer
    - role: qa
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

## Git Integration

### Branch Mode (Default)

Creates a new branch per task:

```
main ─────●
           \
            ● team/2025-01-08_153042_add-password-reset
            │ "team(architect): design submitted"
            │
            ● "team(coder): iteration 1"
            │
            ● "team(complete): add password reset [qa:✓ reviewer:✓]"
```

You review and merge when ready.

### Current Mode

Commits to current branch after successful completion only.

### None Mode

No git operations.

## Architecture

```
team-mcp/
├── src/team_mcp/
│   ├── server.py              # MCP server entry point
│   ├── config.py              # Layered config loading
│   ├── state.py               # Task state management
│   ├── git.py                 # Git integration
│   ├── output.py              # Markdown artifacts
│   ├── types.py               # Data models
│   ├── agents/
│   │   └── loader.py          # Agent discovery
│   └── defaults/              # Shipped defaults
│       ├── config.yaml
│       └── agents/
│           ├── ba/
│           ├── architect/
│           ├── coder/
│           ├── qa/
│           └── reviewer/
└── pyproject.toml
```

## Design Philosophy

### The Problem

LLMs have no adversary. They mark their own homework:

```
Current experience:
  Claude: "I've implemented the feature! ✅"
  
  Reality:
    - 5% implemented
    - 3 files broken
    - No tests
    - Hardcoded values
    - You spend 2 hours fixing
```

### The Solution

**Forced perspectives** and **quality gates**:

```
Desired experience:
  BA: Clarifies requirements
  Architect: Designs approach
  Coder: Implements
  QA: "Did you run it? Show me output."
  Coder: "..."
  QA: "It throws ImportError on line 12."
  Coder: *fixes*
  Reviewer: "You've duplicated logic from utils.py"
  Coder: *refactors*
  QA + Reviewer: "Approved."
  → Returns to user, actually working
```

## Contributing

Contributions are welcome! This is an MVP implementation with room for enhancements:

- Parallel gatekeepers
- Conditional workflows
- Cost/token tracking
- Web UI for viewing runs
- Cross-run learning

## License

MIT

## Credits

Created based on the Team MCP design document v3.