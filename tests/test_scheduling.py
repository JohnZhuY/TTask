import unittest
from datetime import date, datetime
from unittest.mock import patch

import ttask.holidays_cn as holidays
from ttask.models import ActionType, ScheduleType, Task
from ttask.scheduling import (
    count_occurrences_on_date,
    date_is_allowed,
    next_occurrence,
    occurrence_for_date,
    upcoming_occurrences,
)


def task(schedule=ScheduleType.FIXED) -> Task:
    return Task(
        id=7,
        name="测试任务",
        schedule_type=schedule,
        action_type=ActionType.NOTIFICATION,
        time_start="08:00:00",
        time_end="08:25:00" if schedule == ScheduleType.RANDOM_WINDOW else None,
        action_config={"message": "hello"},
    )


class SchedulingTests(unittest.TestCase):
    def test_interval_daily_count_is_exact(self):
        value = task(ScheduleType.INTERVAL)
        value.anchor_at = "2026-09-20T00:00:00"
        value.interval_seconds = 60
        value.weekdays = list(range(7))
        self.assertEqual(
            count_occurrences_on_date(
                value, date(2026, 9, 20), datetime(2026, 9, 20, 12, 0, 0)
            ),
            719,
        )

    def test_weekday_is_automatic(self):
        value = task()
        self.assertTrue(date_is_allowed(value, date(2026, 7, 27)))  # Monday

    def test_weekend_is_skipped_by_default(self):
        value = task()
        self.assertFalse(date_is_allowed(value, date(2026, 8, 1)))  # Saturday

    def test_workday_rule_skips_official_holiday(self):
        value = task()
        value.workdays_only = True
        with patch.dict(holidays._manual, {}, clear=True):
            self.assertFalse(date_is_allowed(value, date(2026, 10, 1)))

    def test_workday_rule_includes_adjusted_weekend(self):
        value = task()
        value.workdays_only = True
        self.assertTrue(date_is_allowed(value, date(2026, 10, 10)))

    def test_manual_date_rules_override_workday_calendar(self):
        value = task()
        value.workdays_only = True
        value.weekend_overrides = ["2026-10-01"]
        self.assertTrue(date_is_allowed(value, date(2026, 10, 1)))
        value.excluded_dates = ["2026-10-10"]
        self.assertFalse(date_is_allowed(value, date(2026, 10, 10)))

    def test_weekend_can_be_enabled_as_a_recurring_day(self):
        value = task()
        value.weekdays.extend([5, 6])
        self.assertTrue(date_is_allowed(value, date(2026, 8, 1)))
        self.assertTrue(date_is_allowed(value, date(2026, 8, 2)))

    def test_selected_weekend_date_runs_once(self):
        value = task()
        value.weekend_overrides = ["2026-08-01"]
        self.assertTrue(date_is_allowed(value, date(2026, 8, 1)))
        self.assertFalse(date_is_allowed(value, date(2026, 8, 2)))

    def test_fixed_occurrence(self):
        value = task()
        self.assertEqual(
            occurrence_for_date(value, date(2026, 7, 27)),
            datetime(2026, 7, 27, 8, 0),
        )

    def test_random_occurrence_is_stable_and_inside_window(self):
        value = task(ScheduleType.RANDOM_WINDOW)
        value.action_config["random_seed"] = "test-seed"
        first = occurrence_for_date(value, date(2026, 7, 27))
        second = occurrence_for_date(value, date(2026, 7, 27))
        next_day = occurrence_for_date(value, date(2026, 7, 28))
        self.assertEqual(first, second)
        self.assertNotEqual(first.time(), next_day.time())
        self.assertGreaterEqual(first, datetime(2026, 7, 27, 8, 0))
        self.assertLessEqual(first, datetime(2026, 7, 27, 8, 25))

    def test_next_occurrence_skips_weekend(self):
        value = task()
        result = next_occurrence(value, datetime(2026, 7, 31, 9, 0))
        self.assertEqual(result, datetime(2026, 8, 3, 8, 0))

    def test_weekday_can_be_added_as_date_override(self):
        value = task()
        value.weekdays = [1, 2, 3, 4]
        value.weekend_overrides = ["2026-07-27"]
        value.validate()
        self.assertTrue(date_is_allowed(value, date(2026, 7, 27)))

    def test_excluded_weekday_is_skipped(self):
        value = task()
        value.excluded_dates = ["2026-07-27"]
        self.assertFalse(date_is_allowed(value, date(2026, 7, 27)))

    def test_upcoming_occurrences_returns_requested_count(self):
        value = task()
        results = upcoming_occurrences(value, datetime(2026, 7, 27, 9, 0), 3)
        self.assertEqual(
            results,
            [
                datetime(2026, 7, 28, 8, 0),
                datetime(2026, 7, 29, 8, 0),
                datetime(2026, 7, 30, 8, 0),
            ],
        )

    def test_one_time_schedule(self):
        value = task(ScheduleType.ONCE)
        value.run_date = "2026-08-10"
        self.assertEqual(
            next_occurrence(value, datetime(2026, 8, 9, 12, 0)),
            datetime(2026, 8, 10, 8, 0),
        )
        self.assertIsNone(next_occurrence(value, datetime(2026, 8, 10, 9, 0)))

    def test_interval_schedule(self):
        value = task(ScheduleType.INTERVAL)
        value.anchor_at = "2026-07-27T08:00:00"
        value.interval_seconds = 600
        self.assertEqual(
            next_occurrence(value, datetime(2026, 7, 27, 8, 1)),
            datetime(2026, 7, 27, 8, 10),
        )

    def test_multiple_fixed_times_choose_next_on_same_day(self):
        value = task()
        value.time_windows = [["08:00:00"], ["12:30:00"], ["17:45:00"]]
        self.assertEqual(
            next_occurrence(value, datetime(2026, 7, 27, 9, 0)),
            datetime(2026, 7, 27, 12, 30),
        )

    def test_multiple_random_windows_are_stable(self):
        value = task(ScheduleType.RANDOM_WINDOW)
        value.time_windows = [
            ["08:00:00", "08:25:00"],
            ["13:00:00", "13:30:00"],
        ]
        from ttask.scheduling import occurrences_for_date

        first = occurrences_for_date(value, date(2026, 7, 27))
        second = occurrences_for_date(value, date(2026, 7, 27))
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        self.assertLessEqual(first[0], datetime(2026, 7, 27, 8, 25))
        self.assertGreaterEqual(first[1], datetime(2026, 7, 27, 13, 0))


if __name__ == "__main__":
    unittest.main()
