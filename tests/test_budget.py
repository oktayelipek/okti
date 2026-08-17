"""Tests for the session-scoped BudgetGuard."""

from __future__ import annotations

import pytest

from okti.agent.budget import BudgetGuard
from okti.config import OktiConfig


def _cfg(cap: float | None, yolo: bool = False, **budget_kw) -> OktiConfig:
    cfg = OktiConfig()
    cfg.permissions.yolo = yolo
    cfg.budget.session_usd_cap = cap
    for k, v in budget_kw.items():
        setattr(cfg.budget, k, v)
    return cfg


# ---------------------------------------------------------------------------
# Uncapped
# ---------------------------------------------------------------------------

def test_no_cap_never_fires():
    guard = BudgetGuard(_cfg(cap=None))
    assert guard.observe(1_000.0) == []
    assert not guard.is_stopped()


def test_zero_or_negative_cap_treated_as_uncapped():
    guard = BudgetGuard(_cfg(cap=0.0))
    assert guard.observe(1_000.0) == []


# ---------------------------------------------------------------------------
# Threshold crossings
# ---------------------------------------------------------------------------

def test_warn_fires_at_80_percent_only_once():
    guard = BudgetGuard(_cfg(cap=1.00))
    events = guard.observe(0.80)
    kinds = [e.kind for e in events]
    assert "warn" in kinds
    # Second observation at the same level → no re-fire
    assert guard.observe(0.85) == []


def test_disable_yolo_flips_config_and_only_once():
    cfg = _cfg(cap=1.00, yolo=True)
    guard = BudgetGuard(cfg)
    events = guard.observe(0.91)
    kinds = [e.kind for e in events]
    assert "disable_yolo" in kinds
    assert cfg.permissions.yolo is False
    # No re-fire even though we cross again after a reset of yolo
    cfg.permissions.yolo = True
    assert guard.observe(0.95) == []


def test_hard_stop_marks_stopped_flag():
    guard = BudgetGuard(_cfg(cap=1.00))
    events = guard.observe(1.00)
    kinds = [e.kind for e in events]
    assert "stop" in kinds
    assert guard.is_stopped()


def test_single_observation_crosses_all_three_thresholds():
    """A very expensive single turn should fire warn, disable_yolo, stop
    in the same call — in threshold order."""
    cfg = _cfg(cap=1.00, yolo=True)
    guard = BudgetGuard(cfg)
    events = guard.observe(2.00)
    assert [e.kind for e in events] == ["warn", "disable_yolo", "stop"]
    assert cfg.permissions.yolo is False
    assert guard.is_stopped()


# ---------------------------------------------------------------------------
# Custom thresholds
# ---------------------------------------------------------------------------

def test_custom_warn_threshold():
    guard = BudgetGuard(_cfg(cap=1.00, warn_at=0.5))
    events = guard.observe(0.50)
    assert any(e.kind == "warn" for e in events)


def test_disabled_hard_stop():
    """hard_stop_at > 1 should mean the stop event never fires."""
    guard = BudgetGuard(_cfg(cap=1.00, hard_stop_at=2.0))
    events = guard.observe(1.00)
    assert not any(e.kind == "stop" for e in events)
    assert not guard.is_stopped()


# ---------------------------------------------------------------------------
# Reset & reporting
# ---------------------------------------------------------------------------

def test_reset_reallows_all_events():
    guard = BudgetGuard(_cfg(cap=1.00))
    guard.observe(1.00)
    assert guard.is_stopped()
    guard.reset()
    assert not guard.is_stopped()
    events = guard.observe(0.80)
    assert any(e.kind == "warn" for e in events)


def test_summary_uncapped():
    guard = BudgetGuard(_cfg(cap=None))
    assert "uncapped" in guard.summary(0.42)


def test_summary_capped_shows_pct_and_state():
    guard = BudgetGuard(_cfg(cap=1.00))
    guard.observe(0.85)
    text = guard.summary(0.85)
    assert "$0.85" in text
    assert "$1.00" in text
    assert "85.0%" in text
    assert "OK" in text


def test_summary_shows_stopped_after_hard_stop():
    guard = BudgetGuard(_cfg(cap=1.00))
    guard.observe(1.00)
    text = guard.summary(1.00)
    assert "STOPPED" in text


# ---------------------------------------------------------------------------
# Fraction helper
# ---------------------------------------------------------------------------

def test_fraction_used():
    guard = BudgetGuard(_cfg(cap=2.00))
    assert guard.fraction_used(0.50) == pytest.approx(0.25)
    assert guard.fraction_used(2.00) == pytest.approx(1.00)


def test_fraction_used_no_cap_is_zero():
    guard = BudgetGuard(_cfg(cap=None))
    assert guard.fraction_used(1000.0) == 0.0
