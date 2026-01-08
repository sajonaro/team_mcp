"""Agent discovery and loading."""

from pathlib import Path
from typing import Optional
import yaml

from ..types import Agent, AgentConfig, RoleType
from ..config import (
    get_package_defaults_dir,
    get_user_config_dir,
    get_project_config_dir,
)


def load_agent_prompt(agent_name: str, search_dirs: list[Path]) -> Optional[str]:
    """Load agent prompt from prompt.md, searching in order."""
    for base_dir in search_dirs:
        prompt_path = base_dir / "agents" / agent_name / "prompt.md"
        if prompt_path.exists():
            with open(prompt_path, "r") as f:
                return f.read()
    return None


def load_agent_config(
    agent_name: str, search_dirs: list[Path]
) -> Optional[AgentConfig]:
    """Load agent config from agent.yaml, searching in order."""
    for base_dir in search_dirs:
        config_path = base_dir / "agents" / agent_name / "agent.yaml"
        if config_path.exists():
            with open(config_path, "r") as f:
                data = yaml.safe_load(f)
                if data:
                    agent_type = RoleType(data.get("type", "implementer"))
                    return AgentConfig(
                        type=agent_type,
                        stance=data.get("stance"),
                        context=data.get("context", []),
                    )
    return None


def discover_agent_names() -> set[str]:
    """Discover all available agent names from all config directories."""
    agent_names = set()

    search_dirs = [
        get_package_defaults_dir(),
        get_user_config_dir(),
        get_project_config_dir(),
    ]

    for base_dir in search_dirs:
        agents_dir = base_dir / "agents"
        if agents_dir.exists() and agents_dir.is_dir():
            for agent_dir in agents_dir.iterdir():
                if agent_dir.is_dir():
                    # Check if it has a prompt.md
                    if (agent_dir / "prompt.md").exists():
                        agent_names.add(agent_dir.name)

    return agent_names


def load_agent(agent_name: str, role_type: RoleType) -> Agent:
    """
    Load an agent with its prompt and config.

    Searches in order: project → user → defaults.
    Later layers override earlier ones for prompts.
    """
    search_dirs = [
        get_project_config_dir(),
        get_user_config_dir(),
        get_package_defaults_dir(),
    ]

    # Load prompt (project overrides user overrides defaults)
    prompt = load_agent_prompt(agent_name, search_dirs)
    if not prompt:
        raise ValueError(f"Agent '{agent_name}' not found - no prompt.md exists")

    # Load config (if exists)
    config = load_agent_config(agent_name, search_dirs)

    # Use role_type from config if available, otherwise use passed-in type
    if config and config.type:
        actual_type = config.type
    else:
        actual_type = role_type

    return Agent(name=agent_name, type=actual_type, prompt=prompt, config=config)


def load_all_agents(workflow_roles: list) -> dict[str, Agent]:
    """Load all agents needed for the workflow."""
    agents = {}

    for workflow_role in workflow_roles:
        agent = load_agent(workflow_role.role, workflow_role.type)
        agents[workflow_role.role] = agent

    return agents
