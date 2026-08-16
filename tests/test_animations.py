"""Tests for TUI animations, speedometer, mascots, and themes."""

import time
from oktigent.tui.animations import (
    DEV_QUOTES,
    MASCOTS,
    THEMES,
    Speedometer,
    get_random_mascot,
    get_random_quote,
)


def test_mascots_all_states():
    for state in ["idle", "thinking", "tool", "success", "error"]:
        val = get_random_mascot(state, tool_name="bash")
        assert isinstance(val, str)
        assert len(val) > 0
        if state == "tool" and "{tool}" in MASCOTS["tool"][0]:
            # Should format tool name
            assert "bash" in val or "Tinkering" in val or "Executing" in val or "Applying" in val


def test_get_random_quote():
    q = get_random_quote()
    assert q in DEV_QUOTES
    assert len(q) > 10


def test_speedometer():
    speedo = Speedometer()
    assert speedo.speed() == 0.0
    assert speedo.elapsed() == 0.0

    speedo.start()
    time.sleep(0.12)
    speedo.add_tokens(60)

    spd = speedo.speed()
    el = speedo.elapsed()

    assert el >= 0.1
    assert spd > 0.0


def test_themes_defined():
    assert "default" in THEMES
    assert "synthwave" in THEMES
    assert "matrix" in THEMES
    assert "cyberpunk" in THEMES
    assert "nord" in THEMES
    for name, css in THEMES.items():
        assert len(css.strip()) > 0
