"""Tests for Plan.budget_warning() — projected cost vs session cap."""

from __future__ import annotations

from okti.agent.plan import Plan, Task


def _plan_with_pending(n: int, files: int = 2) -> Plan:
    """Build a plan with n pending tasks; adjust file count to grow the estimate."""
    tasks = [
        Task(
            id=f"t{i}",
            title=f"Task {i}",
            description="do a thing",
            files_involved=[f"f{j}.py" for j in range(files)],
        )
        for i in range(n)
    ]
    return Plan(scope="s", tasks=tasks, summary="")


def test_no_warning_when_cap_unset():
    plan = _plan_with_pending(2)
    assert plan.budget_warning("gpt-4o", cap_usd=None) is None


def test_no_warning_when_cap_zero_or_negative():
    plan = _plan_with_pending(2)
    assert plan.budget_warning("gpt-4o", cap_usd=0.0) is None
    assert plan.budget_warning("gpt-4o", cap_usd=-1.0) is None


def test_no_warning_when_projected_fits_under_cap():
    plan = _plan_with_pending(1, files=1)
    # Give it plenty of headroom
    assert plan.budget_warning("gpt-4o", cap_usd=10_000.0, already_spent_usd=0.0) is None


def test_warning_when_projected_exceeds_cap():
    plan = _plan_with_pending(5, files=5)
    projected = plan.estimated_cost_usd("gpt-4o")
    # Cap that's clearly below the projection
    cap = projected / 2.0
    warn = plan.budget_warning("gpt-4o", cap_usd=cap, already_spent_usd=0.0)
    assert warn is not None
    assert "Budget breach" in warn
    assert f"${cap:.2f}" in warn


def test_warning_accounts_for_already_spent():
    plan = _plan_with_pending(1)
    projected_remaining = plan.estimated_cost_usd("gpt-4o")
    # Set a cap that fits the remaining plan alone, but not with prior spend added
    cap = projected_remaining * 1.5
    already_spent = projected_remaining
    warn = plan.budget_warning("gpt-4o", cap_usd=cap, already_spent_usd=already_spent)
    assert warn is not None
    # Overshoot should be roughly half the remaining projection
    assert "would exceed" in warn


def test_warning_mentions_overshoot_amount():
    plan = _plan_with_pending(3, files=4)
    projected = plan.estimated_cost_usd("gpt-4o")
    cap = projected * 0.1
    warn = plan.budget_warning("gpt-4o", cap_usd=cap)
    assert warn is not None
    # The overshoot number should appear formatted to 4 decimals
    overshoot = projected - cap
    assert f"${overshoot:.4f}" in warn


def test_boundary_behaviour_headroom():
    plan = _plan_with_pending(1, files=1)
    assert plan.budget_warning("gpt-4o", cap_usd=1000.0, already_spent_usd=0.0) is None


def test_boundary_behaviour_near_cap():
    plan = _plan_with_pending(1, files=1)
    remaining = plan.estimated_cost_usd("gpt-4o")
    # Already spent enough that any additional cost breaches the cap
    cap = 1.0
    warn = plan.budget_warning("gpt-4o", cap_usd=cap, already_spent_usd=cap - remaining / 2)
    assert warn is not None
