"""MCP server for Team MCP."""

import asyncio
import json
from typing import Any

from mcp.server import Server
from mcp.types import Tool, TextContent

from .config import load_config
from .state import StateMachine
from .git import GitIntegration
from .output import OutputManager
from .types import (
    RoleAssignment,
    TaskPaused,
    TaskComplete,
    TaskReboundOffer,
    TaskEscalate,
    TaskStatus,
    RoleType,
)


# Create server instance
app = Server("team-mcp")

# Global state
config = None
state_machine = None
git_integration = None
output_manager = None


def serialize_response(obj: Any) -> dict:
    """Serialize response objects to JSON-compatible dicts."""
    if isinstance(obj, RoleAssignment):
        return {
            "type": "RoleAssignment",
            "role": obj.role,
            "role_type": obj.role_type,
            "iteration": obj.iteration,
            "instructions": obj.instructions,
            "rules": obj.rules,
            "context": obj.context,
            "task": obj.task,
            "requirements": obj.requirements,
            "failure_context": obj.failure_context,
            "design": obj.design,
            "feedback": obj.feedback,
            "reviewing": obj.reviewing,
            "expected_output": obj.expected_output,
        }
    elif isinstance(obj, TaskPaused):
        return {
            "type": "TaskPaused",
            "role": obj.role,
            "questions": obj.questions,
            "context": obj.context,
            "partial_spec": obj.partial_spec,
        }
    elif isinstance(obj, TaskComplete):
        return {
            "type": "TaskComplete",
            "success": obj.success,
            "summary": obj.summary,
            "iterations": obj.iterations,
            "files_changed": obj.files_changed,
            "requirements": obj.requirements,
            "design": obj.design,
            "git_branch": obj.git_branch,
            "run_path": obj.run_path,
        }
    elif isinstance(obj, TaskReboundOffer):
        return {
            "type": "TaskReboundOffer",
            "failures": obj.failures,
            "last_rejection": obj.last_rejection,
            "pattern": obj.pattern,
            "suggestion": obj.suggestion,
        }
    elif isinstance(obj, TaskEscalate):
        return {
            "type": "TaskEscalate",
            "reason": obj.reason,
            "iterations": obj.iterations,
            "last_feedback": obj.last_feedback,
            "suggestion": obj.suggestion,
        }
    elif isinstance(obj, TaskStatus):
        return {
            "type": "TaskStatus",
            "task": obj.task,
            "state": obj.state.value,
            "current_role": obj.current_role,
            "iteration": obj.iteration,
            "history": obj.history,
            "confirmed_requirements": obj.confirmed_requirements,
            "current_design": obj.current_design,
        }
    else:
        return {"type": "Unknown", "data": str(obj)}


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools."""
    return [
        Tool(
            name="start_task",
            description="Start a new team task",
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Description of what to accomplish",
                    }
                },
                "required": ["task"],
            },
        ),
        Tool(
            name="submit",
            description="Submit work for current role",
            inputSchema={
                "type": "object",
                "properties": {
                    "submission": {
                        "type": "object",
                        "description": "The submission data (format depends on role type)",
                    }
                },
                "required": ["submission"],
            },
        ),
        Tool(
            name="resume",
            description="Resume a paused task with user input",
            inputSchema={
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "User's answers/decision",
                    }
                },
                "required": ["input"],
            },
        ),
        Tool(
            name="get_status",
            description="Get current task status",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_history",
            description="Get detailed submission history",
            inputSchema={
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "description": "Filter by role (optional)",
                    },
                    "iteration": {
                        "type": "integer",
                        "description": "Filter by iteration (optional)",
                    },
                },
            },
        ),
        Tool(
            name="abort",
            description="Abort current task",
            inputSchema={
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Reason for aborting (optional)",
                    }
                },
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool calls."""
    global state_machine, git_integration, output_manager

    try:
        if name == "start_task":
            task_description = arguments["task"]
            result = state_machine.start_task(task_description)

            # Initialize git and output
            git_integration.start_run(state_machine.task.id)
            output_manager.create_run(state_machine.task)

            response = serialize_response(result)
            return [TextContent(type="text", text=json.dumps(response, indent=2))]

        elif name == "submit":
            submission = arguments["submission"]
            result = state_machine.submit(submission)

            # Handle side effects based on result type
            if isinstance(result, RoleAssignment):
                # Write artifacts based on what was just submitted
                if state_machine.task.confirmed_requirements:
                    output_manager.write_requirements(state_machine.task)

                if state_machine.task.current_design:
                    output_manager.write_design(state_machine.task)

                # Write iteration artifact for the last submission
                if state_machine.task.submissions:
                    last_submission = state_machine.task.submissions[-1]
                    output_manager.write_iteration(state_machine.task, last_submission)

                # Commit to git if in branch mode
                if result.role_type == RoleType.IMPLEMENTER.value:
                    files = submission.get("files_changed", [])
                    git_integration.commit(
                        "coder", submission.get("summary", ""), files
                    )

            elif isinstance(result, TaskComplete):
                # Final commit and summary
                git_integration.complete_run()

                # Set git branch in result if available
                if git_integration.get_branch_name():
                    result.git_branch = git_integration.get_branch_name()

                # Write final summary
                output_manager.write_summary(state_machine.task, result)

            response = serialize_response(result)
            return [TextContent(type="text", text=json.dumps(response, indent=2))]

        elif name == "resume":
            user_input = arguments["input"]
            result = state_machine.resume(user_input)

            response = serialize_response(result)
            return [TextContent(type="text", text=json.dumps(response, indent=2))]

        elif name == "get_status":
            result = state_machine.get_status()
            response = serialize_response(result)
            return [TextContent(type="text", text=json.dumps(response, indent=2))]

        elif name == "get_history":
            role_filter = arguments.get("role")
            iteration_filter = arguments.get("iteration")

            history = []
            if state_machine.task:
                for sub in state_machine.task.submissions:
                    if role_filter and sub.role != role_filter:
                        continue
                    if iteration_filter and sub.iteration != iteration_filter:
                        continue

                    history.append(
                        {
                            "role": sub.role,
                            "role_type": sub.role_type.value,
                            "iteration": sub.iteration,
                            "timestamp": sub.timestamp.isoformat(),
                            "outcome": sub.outcome,
                            "data": sub.data,
                        }
                    )

            return [TextContent(type="text", text=json.dumps(history, indent=2))]

        elif name == "abort":
            reason = arguments.get("reason")
            state_machine.abort(reason)
            return [
                TextContent(
                    type="text", text=json.dumps({"status": "aborted"}, indent=2)
                )
            ]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def main():
    """Main entry point for the MCP server."""
    global config, state_machine, git_integration, output_manager

    # Load configuration
    config = load_config()

    # Initialize components
    state_machine = StateMachine(config)
    git_integration = GitIntegration(config.git)
    output_manager = OutputManager(config.output)

    # Run the server
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def run():
    """CLI entry point."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
