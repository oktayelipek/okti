"""Tests for the streamed tool-argument JSON repair used by AgentLoop."""

from okti.agent.loop import _parse_streamed_tool_args


def test_empty_returns_empty_dict():
    parsed, err = _parse_streamed_tool_args("")
    assert parsed == {}
    assert err is None


def test_valid_json_parses_strict():
    parsed, err = _parse_streamed_tool_args('{"path": "a.py", "n": 1}')
    assert parsed == {"path": "a.py", "n": 1}
    assert err is None


def test_trailing_comma_is_repaired():
    parsed, err = _parse_streamed_tool_args('{"path": "a.py",}')
    assert parsed == {"path": "a.py"}
    assert err is None


def test_missing_closing_brace_is_repaired():
    parsed, err = _parse_streamed_tool_args('{"path": "a.py", "n": 1')
    assert parsed == {"path": "a.py", "n": 1}
    assert err is None


def test_nested_missing_braces_are_repaired():
    parsed, err = _parse_streamed_tool_args('{"a": {"b": [1, 2')
    assert parsed == {"a": {"b": [1, 2]}}
    assert err is None


def test_unterminated_string_is_repaired():
    parsed, err = _parse_streamed_tool_args('{"path": "a.py')
    assert parsed == {"path": "a.py"}
    assert err is None


def test_dangling_key_before_close_is_dropped():
    parsed, err = _parse_streamed_tool_args('{"path": "a.py", "n":')
    assert parsed == {"path": "a.py"}
    assert err is None


def test_escaped_quotes_inside_string_are_respected():
    parsed, err = _parse_streamed_tool_args(r'{"msg": "he said \"hi\""}')
    assert parsed == {"msg": 'he said "hi"'}
    assert err is None


def test_non_object_top_level_reports_error():
    parsed, err = _parse_streamed_tool_args("[1, 2, 3]")
    assert parsed is None
    assert err is not None


def test_unrecoverable_garbage_returns_error():
    parsed, err = _parse_streamed_tool_args("not json at all !!!")
    assert parsed is None
    assert err is not None
