"""Tests for the pricing overlay & cost estimator."""

from __future__ import annotations

import json

import pytest

from okti.models import pricing


@pytest.fixture(autouse=True)
def _reset_cache(tmp_path):
    """Force each test to rebuild the pricing table from a fresh (empty) overlay."""
    pricing.reload_pricing(tmp_path / "no-overlay.json")
    yield
    pricing.reload_pricing(tmp_path / "no-overlay.json")


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def test_estimate_cost_free_model():
    assert pricing.estimate_cost("openrouter/some-model:free", 1000, 1000) == 0.0
    assert pricing.estimate_cost("free-tier", 500, 500) == 0.0


def test_estimate_cost_claude():
    # 1M prompt @ $3.0 + 1M completion @ $15.0 = $18.0
    cost = pricing.estimate_cost("claude-3-7-sonnet-20250219", 1_000_000, 1_000_000)
    assert cost == pytest.approx(18.0, rel=1e-4)


def test_estimate_cost_gpt4o_mini():
    # 1M prompt @ $0.15 + 1M completion @ $0.60 = $0.75
    cost = pricing.estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
    assert cost == pytest.approx(0.75, rel=1e-4)


def test_estimate_cost_fallback_unknown():
    # unknown model uses FALLBACK: $0.50 prompt + $1.50 completion
    cost = pricing.estimate_cost("some-random-model", 1_000_000, 1_000_000)
    assert cost == pytest.approx(2.0, rel=1e-4)


def test_estimate_cost_cache_read_discount():
    # 1M prompt of which 500k came from cache. Claude:
    # uncached: 500k * 3.0 = $1.5, cached: 500k * 0.30 = $0.15, no completion.
    cost = pricing.estimate_cost("claude-3-5-sonnet", 1_000_000, 0, cache_read=500_000)
    assert cost == pytest.approx(1.65, rel=1e-4)


# ---------------------------------------------------------------------------
# Overlay
# ---------------------------------------------------------------------------

def test_overlay_adds_new_model(tmp_path):
    overlay = tmp_path / "pricing.json"
    overlay.write_text(json.dumps({
        "my-custom-model": {"prompt": 1.0, "completion": 2.0, "cache_read": 0.1},
    }))
    pricing.reload_pricing(overlay)
    cost = pricing.estimate_cost("my-custom-model-v1", 1_000_000, 1_000_000)
    # 1.0 + 2.0 = 3.0
    assert cost == pytest.approx(3.0, rel=1e-4)


def test_overlay_overrides_default(tmp_path):
    overlay = tmp_path / "pricing.json"
    overlay.write_text(json.dumps({
        "gpt-4o-mini": {"prompt": 0.05, "completion": 0.10, "cache_read": 0.01},
    }))
    pricing.reload_pricing(overlay)
    cost = pricing.estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
    # override: 0.05 + 0.10 = 0.15
    assert cost == pytest.approx(0.15, rel=1e-4)


def test_overlay_malformed_ignored(tmp_path):
    overlay = tmp_path / "pricing.json"
    overlay.write_text("{ not valid json")
    pricing.reload_pricing(overlay)
    # Falls back to defaults
    cost = pricing.estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
    assert cost == pytest.approx(0.75, rel=1e-4)


def test_overlay_malformed_entry_skipped(tmp_path):
    overlay = tmp_path / "pricing.json"
    overlay.write_text(json.dumps({
        "good-model": {"prompt": 1.0, "completion": 2.0},
        "bad-model": {"prompt": "not-a-number"},
        "another-bad": "not-a-dict",
    }))
    pricing.reload_pricing(overlay)
    # Good entry survives
    assert pricing.estimate_cost("good-model", 1_000_000, 0) == pytest.approx(1.0)
    # Bad entries fall back to defaults
    assert pricing.estimate_cost("bad-model", 1_000_000, 1_000_000) == pytest.approx(2.0)


def test_overlay_missing_file_uses_defaults(tmp_path):
    pricing.reload_pricing(tmp_path / "does-not-exist.json")
    # "haiku" alone matches only the haiku rule (0.80 + 4.0 = 4.80)
    cost = pricing.estimate_cost("haiku", 1_000_000, 1_000_000)
    assert cost == pytest.approx(4.80, rel=1e-4)


# ---------------------------------------------------------------------------
# Backward compat
# ---------------------------------------------------------------------------

def test_openai_compat_reexport():
    from okti.models.openai_compat import estimate_cost as legacy
    assert legacy is pricing.estimate_cost
