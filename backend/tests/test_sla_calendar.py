from datetime import UTC, datetime, timedelta

import pytest

from apps.tickets.sla_calendar import calculate_business_deadline

WEEKDAY_HOURS = [
    {"weekday": weekday, "start": "09:00", "end": "17:00"}
    for weekday in range(5)
]


def test_deadline_rolls_over_weekend_and_holiday():
    deadline = calculate_business_deadline(
        started_at=datetime(2026, 8, 28, 10, 30, tzinfo=UTC),
        duration=timedelta(hours=2),
        society_timezone="Asia/Kolkata",
        working_intervals=WEEKDAY_HOURS,
        holidays=["2026-08-31"],
        is_emergency_24x7=False,
    )

    assert deadline == datetime(2026, 9, 1, 4, 30, tzinfo=UTC)


def test_spring_dst_gap_counts_only_elapsed_working_time():
    deadline = calculate_business_deadline(
        started_at=datetime(2026, 3, 8, 5, 0, tzinfo=UTC),
        duration=timedelta(hours=3),
        society_timezone="America/New_York",
        working_intervals=[{"weekday": 6, "start": "00:00", "end": "04:00"}],
        holidays=[],
        is_emergency_24x7=False,
    )

    assert deadline == datetime(2026, 3, 8, 8, 0, tzinfo=UTC)


def test_fall_dst_overlap_counts_the_repeated_hour():
    deadline = calculate_business_deadline(
        started_at=datetime(2026, 11, 1, 4, 0, tzinfo=UTC),
        duration=timedelta(hours=5),
        society_timezone="America/New_York",
        working_intervals=[{"weekday": 6, "start": "00:00", "end": "04:00"}],
        holidays=[],
        is_emergency_24x7=False,
    )

    assert deadline == datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


def test_emergency_calendar_uses_continuous_elapsed_time():
    started_at = datetime(2026, 8, 28, 10, 30, tzinfo=UTC)

    deadline = calculate_business_deadline(
        started_at=started_at,
        duration=timedelta(hours=8),
        society_timezone="Asia/Kolkata",
        working_intervals=[],
        holidays=[],
        is_emergency_24x7=True,
    )

    assert deadline == started_at + timedelta(hours=8)


@pytest.mark.parametrize(
    "working_intervals",
    [
        [{"weekday": 0, "start": "17:00", "end": "09:00"}],
        [
            {"weekday": 0, "start": "09:00", "end": "13:00"},
            {"weekday": 0, "start": "12:00", "end": "17:00"},
        ],
    ],
)
def test_invalid_working_intervals_fail_instead_of_scanning_forever(working_intervals):
    with pytest.raises(ValueError):
        calculate_business_deadline(
            started_at=datetime(2026, 8, 24, 4, 0, tzinfo=UTC),
            duration=timedelta(hours=1),
            society_timezone="Asia/Kolkata",
            working_intervals=working_intervals,
            holidays=[],
            is_emergency_24x7=False,
        )