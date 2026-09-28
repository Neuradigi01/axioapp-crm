"""Date-triggered custom events — minute-of-hour fire time (migration 0239).

Pure schema coverage (no DB): ``ScheduleConfig.minute_local`` defaults
to ``:00`` for callers that predate the field, and only accepts the
5-minute slots the every-5-minute sweep can actually hit.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.app.core.custom_events.schemas import ScheduleConfig

_BASE = {
    "source": "system",
    "field_ref": "expected_close_date",
    "offset_days": 0,
    "recurring": "none",
    "hour_local": 17,
}


def test_minute_defaults_to_top_of_hour() -> None:
    assert ScheduleConfig(**_BASE).minute_local == 0


@pytest.mark.parametrize("minute", [0, 5, 30, 55])
def test_minute_accepts_five_minute_slots(minute: int) -> None:
    assert ScheduleConfig(**_BASE, minute_local=minute).minute_local == minute


@pytest.mark.parametrize("minute", [-5, 3, 59, 60])
def test_minute_rejects_off_grid_or_out_of_range(minute: int) -> None:
    with pytest.raises(ValidationError):
        ScheduleConfig(**_BASE, minute_local=minute)
