"""Plan mode — scope analysis → task generation → user approval → execution.

When a user provides a scope (e.g., "add user authentication"), the planner:
1. Analyzes the scope against the codebase
2. Generates a structured task list (JSON)
3. Presents it to the user for approval
4. Executes approved tasks sequentially via the agent loop
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Task:
    """A single task in a plan."""

    id: str
    title: str
    description: str
    files_involved: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)  # task IDs
    status: TaskStatus = TaskStatus.PENDING
    result: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "files_involved": self.files_involved,
            "dependencies": self.dependencies,
            "status": self.status.value,
            "result": self.result,
        }

    def estimated_tokens(self) -> int:
        """Rough token estimate for executing this task.

        Heuristic: fixed overhead for the task prompt (system + boilerplate),
        plus a per-file allowance (read + edit), plus 4× description chars
        (loose token/char ratio, biased toward code output).
        """
        base_prompt = 800
        per_file = 1500
        description_tokens = max(0, len(self.description)) * 4 // 3
        return base_prompt + per_file * max(1, len(self.files_involved)) + description_tokens


@dataclass
class Plan:
    """A structured plan with tasks."""

    scope: str
    tasks: list[Task] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "scope": self.scope,
            "summary": self.summary,
            "tasks": [t.to_dict() for t in self.tasks],
        }

    def pending_tasks(self) -> list[Task]:
        return [t for t in self.tasks if t.status == TaskStatus.PENDING]

    def completed_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)

    def total_estimated_tokens(self, only_pending: bool = True) -> int:
        """Sum of per-task token estimates. Split roughly 30/70 prompt/completion."""
        pool = self.pending_tasks() if only_pending else self.tasks
        return sum(t.estimated_tokens() for t in pool)

    def estimated_cost_usd(self, model_name: str, only_pending: bool = True) -> float:
        """Estimate USD cost to execute (remaining) tasks with the given model."""
        from okti.models.pricing import estimate_cost

        total = self.total_estimated_tokens(only_pending=only_pending)
        # Rough split: 30% prompt, 70% completion. Tune once we have telemetry.
        prompt_tokens = int(total * 0.30)
        completion_tokens = total - prompt_tokens
        return estimate_cost(model_name, prompt_tokens, completion_tokens)

    def cost_summary(self, model_name: str) -> str:
        """Human-readable cost preview for /approve confirmation."""
        pending = len(self.pending_tasks())
        tokens = self.total_estimated_tokens()
        cost = self.estimated_cost_usd(model_name)
        cost_str = f"${cost:.4f}" if cost < 0.01 else f"${cost:.2f}"
        return (
            f"{pending} pending task(s) · ~{tokens:,} tokens · "
            f"~{cost_str} on {model_name}"
        )


def build_plan_prompt(scope: str, codebase_context: str = "") -> str:
    """Build the system prompt for plan generation."""
    return f"""You are a software development planner. Given a scope/task, create a structured plan.

SCOPE: {scope}

CODEBASE CONTEXT:
{codebase_context or "No codebase context provided."}

Generate a JSON plan with these fields:
- summary: Brief overview of the approach
- tasks: Array of tasks, each with:
  - id: Unique string (e.g. "task-1", "task-2")
  - title: Short title
  - description: Detailed description of what to do
  - files_involved: List of file paths that will be modified/created
  - dependencies: List of task IDs that must complete first (empty if none)

Rules:
- Break the work into 3-10 focused tasks
- Order tasks by dependency (no circular dependencies)
- Each task should be completable in a single focused pass
- Be specific about file paths and code changes
- Consider testing as a final task

Respond with ONLY valid JSON in this format:
{{
  "summary": "...",
  "tasks": [
    {{"id": "task-1", "title": "...", "description": "...", "files_involved": [...], "dependencies": []}},
    ...
  ]
}}"""


def parse_plan_response(response: str) -> Plan | None:
    """Parse a plan JSON response from the model."""
    try:
        # Extract JSON from possible markdown code block
        text = response.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1])  # strip ``` markers

        data = json.loads(text)
        tasks = []
        for t in data.get("tasks", []):
            tasks.append(Task(
                id=t["id"],
                title=t["title"],
                description=t.get("description", ""),
                files_involved=t.get("files_involved", []),
                dependencies=t.get("dependencies", []),
            ))
        return Plan(
            scope="",
            tasks=tasks,
            summary=data.get("summary", ""),
        )
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Failed to parse plan JSON: %s", e)
        return None


def build_task_prompt(task: Task, plan_summary: str) -> str:
    """Build the prompt for executing a single task."""
    deps = ""
    if task.dependencies:
        deps = f"\nDependencies already completed: {', '.join(task.dependencies)}"

    return f"""Execute the following task as part of a larger plan.

PLAN SUMMARY: {plan_summary}

TASK: {task.title}
DESCRIPTION: {task.description}
FILES INVOLVED: {', '.join(task.files_involved) or 'none specified'}
{deps}

Instructions:
- Read the relevant files first
- Make the necessary changes using edit_file (diff-based, not full rewrites)
- Verify your changes compile/work if possible
- Report what you did concisely"""
