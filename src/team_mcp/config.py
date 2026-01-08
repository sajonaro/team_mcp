"""Configuration loading and management for Team MCP."""

import os
from pathlib import Path
from typing import Optional
import yaml

from .types import (
    Config,
    WorkflowConfig,
    WorkflowRole,
    RoleType,
    GitConfig,
    OutputConfig,
    AgentConfig,
)


def get_package_defaults_dir() -> Path:
    """Get the package defaults directory."""
    return Path(__file__).parent / "defaults"


def get_user_config_dir() -> Path:
    """Get the user's global config directory."""
    return Path.home() / ".team-mcp"


def get_project_config_dir() -> Path:
    """Get the project's local config directory."""
    return Path.cwd() / ".team"


def deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dictionaries, with override taking precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_yaml_config(path: Path) -> dict:
    """Load a YAML configuration file."""
    if not path.exists():
        return {}

    with open(path, "r") as f:
        data = yaml.safe_load(f)
        return data if data is not None else {}


def parse_workflow_config(data: dict) -> WorkflowConfig:
    """Parse workflow configuration from dict."""
    sequence_data = data.get("sequence", [])
    sequence = []

    for role_data in sequence_data:
        role_type_str = role_data.get("type", "implementer")
        role_type = RoleType(role_type_str)
        sequence.append(WorkflowRole(role=role_data["role"], type=role_type))

    rebound_config = data.get("rebound", {})

    return WorkflowConfig(
        sequence=sequence,
        max_iterations=data.get("max_iterations", 5),
        rebound_after_failures=rebound_config.get("after_failures", 3),
        on_max_iterations=data.get("on_max_iterations", "escalate"),
    )


def parse_git_config(data: dict) -> GitConfig:
    """Parse git configuration from dict."""
    return GitConfig(
        mode=data.get("mode", "branch"),
        branch_prefix=data.get("branch_prefix", "team/"),
        commit_message_format=data.get(
            "commit_message_format", "team({role}): {summary}"
        ),
    )


def parse_output_config(data: dict) -> OutputConfig:
    """Parse output configuration from dict."""
    return OutputConfig(
        runs_dir=data.get("runs_dir", ".team/runs"), verbose=data.get("verbose", True)
    )


def parse_agents_config(data: dict) -> dict[str, AgentConfig]:
    """Parse agents configuration from dict."""
    agents = {}
    for agent_name, agent_data in data.items():
        if isinstance(agent_data, dict):
            agent_type_str = agent_data.get("type", "implementer")
            agent_type = RoleType(agent_type_str)
            agents[agent_name] = AgentConfig(
                type=agent_type,
                stance=agent_data.get("stance"),
                context=agent_data.get("context", []),
            )
    return agents


def load_config() -> Config:
    """Load layered configuration (defaults → user → project)."""

    # Layer 1: Package defaults
    defaults_config_path = get_package_defaults_dir() / "config.yaml"
    config_data = load_yaml_config(defaults_config_path)

    # Layer 2: User global config
    user_config_path = get_user_config_dir() / "config.yaml"
    user_config_data = load_yaml_config(user_config_path)
    config_data = deep_merge(config_data, user_config_data)

    # Layer 3: Project local config
    project_config_path = get_project_config_dir() / "config.yaml"
    project_config_data = load_yaml_config(project_config_path)
    config_data = deep_merge(config_data, project_config_data)

    # Parse into Config object
    workflow_data = config_data.get("workflow", {})
    git_data = config_data.get("git", {})
    output_data = config_data.get("output", {})
    agents_data = config_data.get("agents", {})

    return Config(
        version=config_data.get("version", 1),
        workflow=parse_workflow_config(workflow_data),
        rules=config_data.get("rules", []),
        context=config_data.get("context", {}),
        git=parse_git_config(git_data),
        output=parse_output_config(output_data),
        agents=parse_agents_config(agents_data),
    )


def get_context_files(role: str, config: Config) -> list[str]:
    """Get context files for a specific role."""
    context_files = []

    # Always-included context
    if "always" in config.context:
        context_files.extend(config.context["always"])

    # Role-specific context
    if role in config.context:
        context_files.extend(config.context[role])

    return context_files


def expand_glob_patterns(
    patterns: list[str], base_dir: Optional[Path] = None
) -> list[str]:
    """Expand glob patterns to actual file paths."""
    if base_dir is None:
        base_dir = Path.cwd()

    expanded = []
    for pattern in patterns:
        pattern_path = base_dir / pattern
        parent = pattern_path.parent

        if "*" in str(pattern):
            # Glob pattern
            if "**" in str(pattern):
                # Recursive glob
                for match in base_dir.glob(pattern):
                    if match.is_file():
                        expanded.append(str(match.relative_to(base_dir)))
            else:
                # Non-recursive glob
                for match in parent.glob(pattern_path.name):
                    if match.is_file():
                        expanded.append(str(match.relative_to(base_dir)))
        else:
            # Literal path
            if pattern_path.is_file():
                expanded.append(pattern)

    return expanded
