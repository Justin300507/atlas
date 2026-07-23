from __future__ import annotations

import time
from typing import Callable


class StageTimer:
    """Wraps an on_stage callback to record how long each stage took.

    Forwards every call to the wrapped callback unchanged, so it can be
    dropped into an existing on_stage hook with no behavior change beyond
    the timing side channel.
    """

    def __init__(self, on_stage: Callable[[str], None] | None = None) -> None:
        self._on_stage = on_stage
        self._start = time.monotonic()
        self._last_stage_start = self._start
        self._last_stage_name: str | None = None
        self.durations: dict[str, float] = {}

    def __call__(self, stage: str) -> None:
        now = time.monotonic()
        if self._last_stage_name is not None:
            self.durations[self._last_stage_name] = now - self._last_stage_start
        self._last_stage_name = stage
        self._last_stage_start = now
        if self._on_stage is not None:
            self._on_stage(stage)

    def finish(self) -> dict[str, float]:
        now = time.monotonic()
        if self._last_stage_name is not None:
            self.durations[self._last_stage_name] = now - self._last_stage_start
        self.durations["total"] = now - self._start
        return self.durations
