"""Agent swarm — spawn several subagents in parallel and aggregate.

The frontier agentic tools (Devin, Aider architect mode, Manus, omp.sh)
all share one trick: they fan work out to focused sub-agents, then
reduce. `AgentSwarm` does the same on top of the existing `SubagentRunner`
with three guarantees:

  * bounded concurrency (`max_parallel`) so we don't spike token spend
  * per-task timeout so one hung subagent can't block the whole batch
  * ordered results so aggregators can rely on positional identity

The swarm is deliberately simple — no shared memory between subagents
(that path leads to lock hell). If agents need to coordinate they
should do so through the parent's message history after the swarm
returns.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from okti.agent.loop import AgentLoop
from okti.agent.subagent import SubagentConfig, SubagentResult, SubagentRunner

logger = logging.getLogger(__name__)


@dataclass
class SwarmTask:
    """One unit of work in the swarm."""

    name: str          # human-readable label used in the aggregated report
    prompt: str        # user-role prompt sent to the subagent
    config: SubagentConfig
    timeout_s: float = 120.0


@dataclass
class SwarmResult:
    """Aggregated result of a swarm run."""

    tasks: dict[str, SubagentResult] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    total_turns: int = 0

    def render_markdown(self) -> str:
        """Concatenate per-task outputs into a single markdown report."""
        parts = ["# Swarm Report", ""]
        for name, res in self.tasks.items():
            status = "✓" if res.success else "✗"
            parts.append(f"## {status} {name} ({res.turn_count} turns)")
            if res.error:
                parts.append(f"**Error:** `{res.error}`")
            parts.append("")
            parts.append(res.output.strip() or "_(no output)_")
            parts.append("")
        if self.failures:
            parts.append("### Failures")
            for name in self.failures:
                parts.append(f"- {name}")
        return "\n".join(parts)


class AgentSwarm:
    """Run several `SubagentRunner`s concurrently with bounded parallelism."""

    def __init__(self, parent_loop: AgentLoop, max_parallel: int = 3):
        self.parent_loop = parent_loop
        self.max_parallel = max(1, max_parallel)

    async def run(self, tasks: list[SwarmTask]) -> SwarmResult:
        if not tasks:
            return SwarmResult()

        semaphore = asyncio.Semaphore(self.max_parallel)
        runner = SubagentRunner(self.parent_loop)

        async def _one(task: SwarmTask) -> tuple[str, SubagentResult]:
            async with semaphore:
                logger.info("Swarm dispatch: %s", task.name)
                try:
                    result = await asyncio.wait_for(
                        runner.run(task.prompt, task.config),
                        timeout=task.timeout_s,
                    )
                except TimeoutError:
                    logger.warning("Swarm task %s timed out after %.1fs", task.name, task.timeout_s)
                    result = SubagentResult(
                        output="",
                        success=False,
                        error=f"timeout after {task.timeout_s:.1f}s",
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # subagent-level crash — surface as failure
                    logger.exception("Swarm task %s crashed", task.name)
                    result = SubagentResult(output="", success=False, error=str(e))
                return task.name, result

        pairs = await asyncio.gather(*[_one(t) for t in tasks])

        agg = SwarmResult()
        for name, res in pairs:
            agg.tasks[name] = res
            agg.total_turns += res.turn_count
            if not res.success:
                agg.failures.append(name)
        return agg


# ---------------------------------------------------------------------------
# Ready-to-use presets
# ---------------------------------------------------------------------------

_REVIEW_PROMPTS = {
    "security": (
        "You are a security-focused code reviewer. Read the specified files "
        "and report any injection, deserialization, secrets, auth, or "
        "sandbox-escape issues. Rank findings P0-P3. Be concise."
    ),
    "correctness": (
        "You are a correctness-focused reviewer. Read the specified files "
        "and report logic bugs, off-by-one errors, unhandled edge cases, "
        "and incorrect error handling. Rank findings P0-P3. Be concise."
    ),
    "style": (
        "You are a style/readability reviewer. Read the specified files "
        "and report naming, structure, complexity, and dead-code issues. "
        "Rank findings P0-P3. Be concise."
    ),
}


def build_review_swarm(target: str, model: str | None = None) -> list[SwarmTask]:
    """Three parallel reviewers over the same target file(s) or scope."""
    return [
        SwarmTask(
            name=name,
            prompt=f"Review target: {target}\n\nProduce your ranked findings only.",
            config=SubagentConfig(
                system_prompt=prompt,
                allowed_tools=["read_file", "search_files", "glob_files", "list_dir"],
                max_turns=8,
                model=model,
            ),
            timeout_s=90.0,
        )
        for name, prompt in _REVIEW_PROMPTS.items()
    ]
