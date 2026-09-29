from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def calculate_business_deadline(
    *,
    started_at: datetime,
    duration: timedelta,
    society_timezone: str,
    working_intervals: list[dict],
    holidays: list[str],
    is_emergency_24x7: bool,
) -> datetime:
    if started_at.utcoffset() is None:
        raise ValueError("started_at must be timezone-aware.")
    if duration <= timedelta(0):
        raise ValueError("duration must be positive.")
    if is_emergency_24x7:
        return started_at + duration

    if not isinstance(working_intervals, list):
        raise ValueError("working_intervals must be a list.")
    intervals_by_weekday = defaultdict(list)
    for interval in working_intervals:
        if not isinstance(interval, dict):
            raise ValueError("Each working interval must be an object.")
        weekday = interval["weekday"]
        if isinstance(weekday, bool) or not isinstance(weekday, int) or not 0 <= weekday <= 6:
            raise ValueError("Working interval weekday must be an integer from 0 to 6.")
        interval_start = time.fromisoformat(interval["start"])
        interval_end = time.fromisoformat(interval["end"])
        if interval_start >= interval_end:
            raise ValueError("Working interval end must be later than its start.")
        intervals_by_weekday[weekday].append((interval_start, interval_end))
    if not intervals_by_weekday:
        raise ValueError("At least one working interval is required.")
    for intervals in intervals_by_weekday.values():
        intervals.sort()
        if any(
            current_start < previous_end
            for (_, previous_end), (current_start, _) in zip(
                intervals,
                intervals[1:],
                strict=False,
            )
        ):
            raise ValueError("Working intervals cannot overlap.")

    holiday_dates = {date.fromisoformat(value) for value in holidays}
    local_timezone = ZoneInfo(society_timezone)
    cursor = started_at.astimezone(UTC)
    remaining = duration
    local_date = cursor.astimezone(local_timezone).date()

    while True:
        if local_date not in holiday_dates:
            for interval_start, interval_end in intervals_by_weekday[local_date.weekday()]:
                start_utc = datetime.combine(
                    local_date,
                    interval_start,
                    tzinfo=local_timezone,
                ).astimezone(UTC)
                end_utc = datetime.combine(
                    local_date,
                    interval_end,
                    tzinfo=local_timezone,
                ).astimezone(UTC)
                segment_start = max(cursor, start_utc)
                if segment_start >= end_utc:
                    continue
                available = end_utc - segment_start
                if remaining <= available:
                    return segment_start + remaining
                remaining -= available
                cursor = end_utc
        local_date += timedelta(days=1)
