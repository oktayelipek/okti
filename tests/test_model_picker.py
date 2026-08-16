"""Tests for ModelPickerModal dialog and free-tier categorizer."""

from oktigent.tui.model_picker import ModelPickerModal, ModelItem


def test_model_item_classification():
    m1 = ModelItem(id="meta-llama/llama-3.3-70b-instruct:free", is_free=True, category="general")
    assert m1.is_free
    assert ":free" in m1.id

    m2 = ModelItem(id="anthropic/claude-3.7-sonnet", is_free=False, category="claude")
    assert not m2.is_free
    assert m2.category == "claude"


def test_model_picker_modal_initialization():
    models = [
        "anthropic/claude-3.7-sonnet",
        "openai/gpt-4o",
        "meta-llama/llama-3.3-70b-instruct:free",
        "deepseek/deepseek-chat",
        "deepseek/deepseek-r1:free",
    ]
    modal = ModelPickerModal(
        provider_name="openrouter",
        current_model="anthropic/claude-3.7-sonnet",
        models=models,
    )
    assert len(modal._parsed_models) == 5
    free_items = [m for m in modal._parsed_models if m.is_free]
    assert len(free_items) == 2
    assert all(":free" in m.id for m in free_items)
