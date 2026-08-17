"""Tests for AgentSwarm — parallel subagent orchestration."""

from __future__ import annotations

import asyncio

import pytest

from okti.agent.subagent import SubagentConfig, SubagentResult
from okti.agent.swarm import AgentSwarm, SwarmTask, build_review_swarm


class _FakeRunner:
    """Drop-in replacement for SubagentRunner that records dispatch order."""

    def __init__(self, *, delay: float = 0.05, fail: set[str] | None = None) -> None:
        self.delay = delay
        self.fail = fail or set()
        self.dispatched: list[str] = []
        self._max_in_flight = 0
        self._in_flight = 0
        self._lock = asyncio.Lock()

    async def run(self, prompt: str, config: SubagentConfig) -> SubagentResult:
        # Extract the task name from the prompt (build_review_swarm uses labels)
        name = prompt.split("\n", 1)[0]
        async with self._lock:
            self.dispatched.append(name)
            self._in_flight += 1
            self._max_in_flight = max(self._max_in_flight, self._in_flight)

        try:
            await asyncio.sleep(self.delay)
            if any(f in name for f in self.fail):
                raise RuntimeError(f"forced failure: {name}")
            return SubagentResult(output=f"{name} done", turn_count=1, success=True)
        finally:
            async with self._lock:
                self._in_flight -= 1


def _swarm_with_runner(runner: _FakeRunner) -> AgentSwarm:
    swarm = AgentSwarm(parent_loop=object(), max_parallel=2)
    # Bypass the real runner by monkey-patching at the class level for this call
    return swarm, runner


@pytest.mark.asyncio
async def test_swarm_runs_tasks_in_parallel(monkeypatch):
    runner = _FakeRunner(delay=0.1)
    swarm, _ = _swarm_with_runner(runner)

    monkeypatch.setattr(
        "okti.agent.swarm.SubagentRunner",
        lambda parent_loop: runner,
    )

    tasks = [
        SwarmTask(name=f"t{i}", prompt=f"target-{i}",
                  config=SubagentConfig(system_prompt="s"))
        for i in range(4)
    ]

    start = asyncio.get_event_loop().time()
    result = await swarm.run(tasks)
    elapsed = asyncio.get_event_loop().time() - start

    # 4 tasks, 2 in parallel, 0.1s each → ~0.2s, well under 0.4s serial time
    assert elapsed < 0.35, f"expected concurrency, but ran in {elapsed:.3f}s"
    assert len(result.tasks) == 4
    assert all(r.success for r in result.tasks.values())
    assert result.failures == []


@pytest.mark.asyncio
async def test_swarm_respects_max_parallel(monkeypatch):
    runner = _FakeRunner(delay=0.05)
    swarm, _ = _swarm_with_runner(runner)

    monkeypatch.setattr(
        "okti.agent.swarm.SubagentRunner",
        lambda parent_loop: runner,
    )

    tasks = [
        SwarmTask(name=f"t{i}", prompt=f"p{i}",
                  config=SubagentConfig(system_prompt="s"))
        for i in range(5)
    ]
    await swarm.run(tasks)
    assert runner._max_in_flight <= 2


@pytest.mark.asyncio
async def test_swarm_timeout_marks_failure(monkeypatch):
    runner = _FakeRunner(delay=1.0)  # slow
    swarm, _ = _swarm_with_runner(runner)

    monkeypatch.setattr(
        "okti.agent.swarm.SubagentRunner",
        lambda parent_loop: runner,
    )

    tasks = [SwarmTask(
        name="slow", prompt="p",
        config=SubagentConfig(system_prompt="s"),
        timeout_s=0.1,
    )]
    result = await swarm.run(tasks)
    assert result.failures == ["slow"]
    assert "timeout" in result.tasks["slow"].error


@pytest.mark.asyncio
async def test_swarm_isolates_failures(monkeypatch):
    runner = _FakeRunner(delay=0.05, fail={"t2"})
    swarm, _ = _swarm_with_runner(runner)

    monkeypatch.setattr(
        "okti.agent.swarm.SubagentRunner",
        lambda parent_loop: runner,
    )

    tasks = [
        SwarmTask(name=n, prompt=n, config=SubagentConfig(system_prompt="s"))
        for n in ("t1", "t2", "t3")
    ]
    result = await swarm.run(tasks)
    assert result.failures == ["t2"]
    assert result.tasks["t1"].success is True
    assert result.tasks["t3"].success is True
    assert result.tasks["t2"].success is False


@pytest.mark.asyncio
async def test_render_markdown_includes_all_tasks(monkeypatch):
    runner = _FakeRunner(delay=0.01)
    swarm, _ = _swarm_with_runner(runner)

    monkeypatch.setattr(
        "okti.agent.swarm.SubagentRunner",
        lambda parent_loop: runner,
    )

    tasks = [
        SwarmTask(name="alpha", prompt="p1", config=SubagentConfig(system_prompt="s")),
        SwarmTask(name="beta",  prompt="p2", config=SubagentConfig(system_prompt="s")),
    ]
    result = await swarm.run(tasks)
    md = result.render_markdown()
    assert "# Swarm Report" in md
    assert "alpha" in md
    assert "beta" in md


def test_build_review_swarm_creates_three_perspectives():
    tasks = build_review_swarm("okti/foo.py")
    names = [t.name for t in tasks]
    assert set(names) == {"security", "correctness", "style"}
    for t in tasks:
        assert "okti/foo.py" in t.prompt


@pytest.mark.asyncio
async def test_empty_swarm_returns_empty_result():
    swarm = AgentSwarm(parent_loop=object())
    result = await swarm.run([])
    assert result.tasks == {}
    assert result.failures == []
