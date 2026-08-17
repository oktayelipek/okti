"""Session-scoped USD budget tracker with tiered enforcement.

Three thresholds, each configurable in ``config.budget``:

  * ``warn_at``          — first cross emits BudgetEvent(kind="warn")
  * ``disable_yolo_at``  — cross forces ``config.permissions.yolo = False``
                           and emits BudgetEvent(kind="disable_yolo")
  * ``hard_stop_at``     — cross emits BudgetEvent(kind="stop"); the
                           agent loop checks ``is_stopped()`` before every
                           tool call and refuses if True

Each event fires **once** per session. Reset with ``BudgetGuard.reset()``
(or by starting a new session). The guard mutates the passed-in
config in place when it disables YOLO — that mirrors what the /yolo
slash command does.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from okti.config import OktiConfig

logger = logging.getLogger(__name__)


EventKind = Literal["warn", "disable_yolo", "stop"]


@dataclass
class BudgetEvent:
    kind: EventKind
    cap_usd: float
    spent_usd: float
    threshold_fraction: float


class BudgetGuard:
    """Tracks cumulative spend and emits threshold-crossing events."""

    def __init__(self, config: OktiConfig) -> None:
        self.config = config
        self._fired: set[EventKind] = set()
        self._stopped = False

    # -- state --------------------------------------------------------------

    def reset(self) -> None:
        self._fired.clear()
        self._stopped = False

    def is_stopped(self) -> bool:
        return self._stopped

    def cap(self) -> float | None:
        return self.config.budget.session_usd_cap

    def fraction_used(self, spent_usd: float) -> float:
        cap = self.cap()
        if not cap or cap <= 0:
            return 0.0
        return spent_usd / cap

    # -- inspection ---------------------------------------------------------

    def observe(self, spent_usd: float) -> list[BudgetEvent]:
        """Feed the latest cumulative spend; return newly-fired events."""
        cap = self.cap()
        if not cap or cap <= 0:
            return []

        cfg = self.config.budget
        thresholds: list[tuple[EventKind, float]] = [
            ("warn", cfg.warn_at),
            ("disable_yolo", cfg.disable_yolo_at),
            ("stop", cfg.hard_stop_at),
        ]
        fired: list[BudgetEvent] = []
        for kind, frac in thresholds:
            if kind in self._fired:
                continue
            if spent_usd >= cap * frac:
                event = BudgetEvent(
                    kind=kind, cap_usd=cap,
                    spent_usd=spent_usd, threshold_fraction=frac,
                )
                self._fired.add(kind)
                fired.append(event)
                self._apply(event)
        return fired

    # -- effects ------------------------------------------------------------

    def _apply(self, event: BudgetEvent) -> None:
        if event.kind == "disable_yolo" and self.config.permissions.yolo:
            self.config.permissions.yolo = False
            logger.warning(
                "Budget guard: disabling YOLO at %.0f%% of $%.2f cap "
                "(spent: $%.4f)",
                event.threshold_fraction * 100, event.cap_usd, event.spent_usd,
            )
        elif event.kind == "stop":
            self._stopped = True
            logger.error(
                "Budget guard: hard stop at $%.4f / $%.2f cap "
                "(no further tool calls will be dispatched)",
                event.spent_usd, event.cap_usd,
            )

    # -- reporting ----------------------------------------------------------

    def summary(self, spent_usd: float) -> str:
        """One-line human-readable status."""
        cap = self.cap()
        if not cap:
            return f"Budget: uncapped · spent ${spent_usd:.4f}"
        pct = self.fraction_used(spent_usd) * 100
        state = "STOPPED" if self._stopped else "OK"
        return (
            f"Budget: ${spent_usd:.4f} / ${cap:.2f} ({pct:.1f}% · {state})"
        )
