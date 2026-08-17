"""Model pricing — USD per million tokens for cost estimation.

The default pricing table below is checked into the repo so that
`estimate_cost` works out-of-the-box. Users can override any entry
(or add new models) by writing a JSON file at:

    ~/.config/okti/pricing.json

Format:
    {
      "model_substring": {"prompt": 3.0, "completion": 15.0, "cache_read": 0.30},
      ...
    }

Matching is substring-based against the lower-cased model name; the
first matching rule wins in insertion order. `":free"` and `"free"` in
the model name short-circuit to zero cost.

The overlay file is read lazily and cached; call `reload_pricing()` in
tests or after editing the file.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)

_DEFAULT_PRICING_PATH = Path.home() / ".config" / "okti" / "pricing.json"


class PricingEntry(TypedDict):
    prompt: float
    completion: float
    cache_read: float


# Default USD per 1M tokens. Insertion order matters — most specific first.
DEFAULT_PRICING: dict[str, PricingEntry] = {
    "claude-3-7":        {"prompt": 3.0,  "completion": 15.0, "cache_read": 0.30},
    "claude-3.7":        {"prompt": 3.0,  "completion": 15.0, "cache_read": 0.30},
    "claude-3-5":        {"prompt": 3.0,  "completion": 15.0, "cache_read": 0.30},
    "claude-3.5":        {"prompt": 3.0,  "completion": 15.0, "cache_read": 0.30},
    "haiku":             {"prompt": 0.80, "completion": 4.0,  "cache_read": 0.08},
    "gpt-4o-mini":       {"prompt": 0.15, "completion": 0.60, "cache_read": 0.075},
    "o3-mini":           {"prompt": 0.15, "completion": 0.60, "cache_read": 0.075},
    "gpt-4o":            {"prompt": 2.50, "completion": 10.0, "cache_read": 1.25},
    "deepseek":          {"prompt": 0.14, "completion": 0.28, "cache_read": 0.014},
    "gemini-2":          {"prompt": 0.10, "completion": 0.40, "cache_read": 0.025},
    "gemini-1.5-flash":  {"prompt": 0.10, "completion": 0.40, "cache_read": 0.025},
}

# Rate used when nothing matches.
FALLBACK_PRICING: PricingEntry = {"prompt": 0.50, "completion": 1.50, "cache_read": 0.10}

_cached_pricing: dict[str, PricingEntry] | None = None


def _load_overlay(path: Path) -> dict[str, PricingEntry]:
    """Read the user-supplied pricing.json. Missing or invalid → empty dict."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        logger.warning("Failed to load pricing overlay %s: %s", path, e)
        return {}

    if not isinstance(raw, dict):
        logger.warning("Pricing overlay %s is not a dict; ignoring", path)
        return {}

    overlay: dict[str, PricingEntry] = {}
    for key, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        try:
            overlay[str(key).lower()] = {
                "prompt": float(entry["prompt"]),
                "completion": float(entry["completion"]),
                "cache_read": float(entry.get("cache_read", 0.0)),
            }
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("Skipping malformed pricing entry %r: %s", key, e)
    return overlay


def _build_table(overlay_path: Path | None = None) -> dict[str, PricingEntry]:
    path = overlay_path or _DEFAULT_PRICING_PATH
    table: dict[str, PricingEntry] = {}
    # User overlay takes precedence and is checked first for matching.
    table.update(_load_overlay(path))
    for k, v in DEFAULT_PRICING.items():
        table.setdefault(k.lower(), v)
    return table


def reload_pricing(overlay_path: Path | None = None) -> None:
    """Force a re-read of the overlay file. Useful in tests or after edits."""
    global _cached_pricing
    _cached_pricing = _build_table(overlay_path)


def _get_pricing_table() -> dict[str, PricingEntry]:
    global _cached_pricing
    if _cached_pricing is None:
        _cached_pricing = _build_table()
    return _cached_pricing


def match_pricing(model_name: str) -> PricingEntry:
    """Return the pricing entry for the first matching substring rule."""
    m = (model_name or "").lower()
    for key, entry in _get_pricing_table().items():
        if key in m:
            return entry
    return FALLBACK_PRICING


def estimate_cost(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    cache_read: int = 0,
) -> float:
    """Estimate USD cost for a completion.

    Returns 0.0 when the model name contains ``:free`` or ``free``.
    """
    m = (model_name or "").lower()
    if ":free" in m or "free" in m:
        return 0.0

    rates = match_pricing(m)
    uncached_prompt = max(0, prompt_tokens - cache_read)
    cost = (
        uncached_prompt * rates["prompt"]
        + cache_read * rates["cache_read"]
        + completion_tokens * rates["completion"]
    ) / 1_000_000.0
    return round(cost, 6)
