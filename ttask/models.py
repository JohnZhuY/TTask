from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any


class ScheduleType(StrEnum):
    FIXED = "fixed"
    RANDOM_WINDOW = "random_window"
    ONCE = "once"
    INTERVAL = "interval"


class ActionType(StrEnum):
    COMMAND = "command"
    NOTIFICATION = "notification"
    OPEN = "open"
    HTTP = "http"
    COPY = "copy"
    MOVE = "move"


@dataclass(slots=True)
class Task:
    name: str
    schedule_type: ScheduleType
    action_type: ActionType
    time_start: str
    time_end: str | None = None
    time_windows: list[list[str]] = field(default_factory=list)
    run_date: str | None = None
    interval_seconds: int | None = None
    anchor_at: str | None = None
    weekdays: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    workdays_only: bool = False
    weekend_overrides: list[str] = field(default_factory=list)
    excluded_dates: list[str] = field(default_factory=list)
    action_config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    id: int | None = None

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("任务名称不能为空")
        _parse_clock(self.time_start)
        for window in self.time_windows:
            if not window:
                raise ValueError("时间规则不能为空")
            _parse_clock(window[0])
            if self.schedule_type == ScheduleType.RANDOM_WINDOW:
                if len(window) < 2:
                    raise ValueError("随机时间段必须包含开始和结束时间")
                if _parse_clock(window[1]) <= _parse_clock(window[0]):
                    raise ValueError(f"随机时间段无效：{window[0]}–{window[1]}")
        if self.schedule_type == ScheduleType.ONCE:
            if not self.run_date:
                raise ValueError("一次性任务必须设置执行日期")
            date.fromisoformat(self.run_date)
        if self.schedule_type == ScheduleType.INTERVAL:
            if not self.interval_seconds or self.interval_seconds < 1:
                raise ValueError("固定间隔必须至少为 1 秒")
            if not self.anchor_at:
                raise ValueError("固定间隔任务必须设置开始时间")
            from datetime import datetime

            datetime.fromisoformat(self.anchor_at)
        if self.schedule_type == ScheduleType.RANDOM_WINDOW:
            if not self.time_end:
                raise ValueError("随机任务必须设置结束时间")
            if _parse_clock(self.time_end) <= _parse_clock(self.time_start):
                raise ValueError("结束时间必须晚于开始时间")
        if self.schedule_type not in (ScheduleType.ONCE,) and not self.weekdays and not self.workdays_only:
            raise ValueError("至少选择一个星期")
        if any(day not in range(7) for day in self.weekdays):
            raise ValueError("星期值必须在 0 到 6 之间")
        for value in self.weekend_overrides:
            date.fromisoformat(value)
        for value in self.excluded_dates:
            date.fromisoformat(value)
        if set(self.weekend_overrides) & set(self.excluded_dates):
            raise ValueError("同一日期不能同时设为执行例外和排除日期")

    def to_record(self) -> dict[str, Any]:
        data = asdict(self)
        data["schedule_type"] = self.schedule_type.value
        data["action_type"] = self.action_type.value
        return data


def _parse_clock(value: str) -> tuple[int, int, int]:
    pieces = value.split(":")
    if len(pieces) not in (2, 3):
        raise ValueError(f"无效时间：{value}")
    hour, minute = int(pieces[0]), int(pieces[1])
    second = int(pieces[2]) if len(pieces) == 3 else 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise ValueError(f"无效时间：{value}")
    return hour, minute, second
