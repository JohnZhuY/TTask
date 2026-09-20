from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta

from .models import ScheduleType, Task, _parse_clock
from .holidays_cn import is_workday


def date_is_allowed(task: Task, target: date) -> bool:
    """Weekdays follow the recurring rule; weekends require a date override."""
    iso = target.isoformat()
    if iso in task.excluded_dates:
        return False
    if task.schedule_type == ScheduleType.ONCE:
        return iso == task.run_date
    if iso in task.weekend_overrides:
        return True
    if task.workdays_only:
        return is_workday(target)
    return target.weekday() in task.weekdays


def occurrence_for_date(task: Task, target: date) -> datetime | None:
    values = occurrences_for_date(task, target)
    return values[0] if values else None


def occurrences_for_date(task: Task, target: date) -> list[datetime]:
    if not task.enabled or not date_is_allowed(task, target):
        return []
    if task.schedule_type == ScheduleType.INTERVAL:
        return []
    windows = task.time_windows or [
        [task.time_start] + ([task.time_end] if task.time_end else [])
    ]
    results: list[datetime] = []
    for index, window in enumerate(windows):
        start = datetime.combine(target, time(*_parse_clock(window[0])))
        if task.schedule_type in (ScheduleType.FIXED, ScheduleType.ONCE):
            results.append(start)
            continue
        end_value = window[1] if len(window) > 1 else task.time_end or ""
        end = datetime.combine(target, time(*_parse_clock(end_value)))
        span_seconds = int((end - start).total_seconds())
        if span_seconds <= 0:
            raise ValueError("随机时间段必须在同一天且结束时间晚于开始时间")
        seed = task.action_config.get("random_seed") or f"{task.id or task.name}"
        key = f"{seed}:{target.isoformat()}:{index}".encode("utf-8")
        offset = int.from_bytes(hashlib.sha256(key).digest()[:8], "big") % (span_seconds + 1)
        results.append(start + timedelta(seconds=offset))
    return sorted(results)


def next_occurrence(task: Task, after: datetime, days: int = 370) -> datetime | None:
    if not task.enabled:
        return None
    if task.schedule_type == ScheduleType.INTERVAL:
        anchor = datetime.fromisoformat(task.anchor_at or "")
        interval = int(task.interval_seconds or 0)
        if after < anchor:
            candidate = anchor
        else:
            elapsed = (after - anchor).total_seconds()
            candidate = anchor + timedelta(seconds=(int(elapsed // interval) + 1) * interval)
        horizon = after + timedelta(days=days)
        while candidate <= horizon:
            if date_is_allowed(task, candidate.date()):
                return candidate
            next_day = datetime.combine(candidate.date() + timedelta(days=1), time.min)
            seconds_to_next_day = max(1, (next_day - candidate).total_seconds())
            steps = max(1, int((seconds_to_next_day + interval - 1) // interval))
            candidate += timedelta(seconds=steps * interval)
        return None
    for offset in range(days + 1):
        candidates = occurrences_for_date(task, after.date() + timedelta(days=offset))
        for candidate in candidates:
            if candidate > after:
                return candidate
    return None


def upcoming_occurrences(task: Task, after: datetime, count: int = 10) -> list[datetime]:
    results: list[datetime] = []
    cursor = after
    while len(results) < count:
        candidate = next_occurrence(task, cursor)
        if candidate is None:
            break
        results.append(candidate)
        cursor = candidate
    return results


def count_occurrences_on_date(task: Task, target: date, after: datetime | None = None) -> int:
    """Count occurrences on one date without materializing every interval tick."""
    if not task.enabled or not date_is_allowed(task, target):
        return 0
    lower = after if after and after.date() == target else datetime.combine(target, time.min)
    finish = datetime.combine(target + timedelta(days=1), time.min)
    if task.schedule_type != ScheduleType.INTERVAL:
        return sum(value > lower for value in occurrences_for_date(task, target))
    anchor = datetime.fromisoformat(task.anchor_at or "")
    interval = int(task.interval_seconds or 0)
    if interval < 1 or finish <= anchor:
        return 0
    effective = max(lower, anchor - timedelta(microseconds=1))
    first = next_occurrence(task, effective, days=2)
    if first is None or first.date() != target:
        return 0
    return 1 + int((finish - timedelta(microseconds=1) - first).total_seconds() // interval)
