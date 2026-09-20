import tempfile
import unittest
from pathlib import Path

from ttask.database import Database
from ttask.models import ActionType, ScheduleType, Task


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.db")

    def tearDown(self):
        self.temp.cleanup()

    def test_task_round_trip(self):
        saved = self.database.save_task(
            Task(
                name="备份",
                schedule_type=ScheduleType.RANDOM_WINDOW,
                action_type=ActionType.COMMAND,
                time_start="08:00:00",
                time_end="08:25:00",
                workdays_only=True,
                weekend_overrides=["2026-08-01"],
                time_windows=[
                    ["08:00:00", "08:25:00"],
                    ["13:00:00", "13:30:00"],
                ],
                action_config={"command": ["python", "job.py"]},
            )
        )
        loaded = self.database.get_task(saved.id)
        self.assertEqual(loaded.name, "备份")
        self.assertEqual(loaded.weekend_overrides, ["2026-08-01"])
        self.assertTrue(loaded.workdays_only)
        self.assertEqual(loaded.action_config["command"], ["python", "job.py"])
        self.assertEqual(len(loaded.time_windows), 2)

    def test_occurrence_can_only_be_claimed_once(self):
        saved = self.database.save_task(
            Task(
                name="通知",
                schedule_type=ScheduleType.FIXED,
                action_type=ActionType.NOTIFICATION,
                time_start="08:00:00",
            )
        )
        stamp = "2026-07-27T08:00:00"
        self.assertIsNotNone(self.database.claim_occurrence(saved.id, stamp))
        self.assertIsNone(self.database.claim_occurrence(saved.id, stamp))

    def test_execution_log_can_be_listed(self):
        saved = self.database.save_task(
            Task(
                name="立即运行测试",
                schedule_type=ScheduleType.FIXED,
                action_type=ActionType.NOTIFICATION,
                time_start="08:00:00",
            )
        )
        log_id = self.database.claim_occurrence(saved.id, "manual:test")
        self.database.finish_log(log_id, "success", "完成")
        logs = self.database.list_logs()
        self.assertEqual(logs[0]["task_name"], "立即运行测试")
        self.assertEqual(logs[0]["status"], "success")
        self.assertEqual(logs[0]["message"], "完成")

    def test_running_log_is_recovered_as_interrupted(self):
        saved = self.database.save_task(
            Task(
                name="恢复测试",
                schedule_type=ScheduleType.FIXED,
                action_type=ActionType.NOTIFICATION,
                time_start="08:00:00",
            )
        )
        self.database.claim_occurrence(saved.id, "manual:interrupted")
        reopened = Database(self.database.path)
        self.assertEqual(reopened.list_logs()[0]["status"], "interrupted")

    def test_application_settings_round_trip(self):
        self.database.set_settings({"close_mode": "exit", "notifications": "0"})
        self.assertEqual(self.database.get_setting("close_mode"), "exit")
        self.assertEqual(self.database.get_setting("notifications"), "0")
        self.assertEqual(self.database.get_setting("missing", "default"), "default")

    def test_logs_can_be_filtered_and_cleared_per_task(self):
        tasks = []
        for name in ("task-a", "task-b"):
            tasks.append(
                self.database.save_task(
                    Task(
                        name=name,
                        schedule_type=ScheduleType.FIXED,
                        action_type=ActionType.NOTIFICATION,
                        time_start="08:00:00",
                    )
                )
            )
        for saved in tasks:
            log_id = self.database.claim_occurrence(saved.id, f"manual:{saved.id}")
            self.database.finish_log(log_id, "success", "done")
        self.assertEqual(len(self.database.list_logs(task_id=tasks[0].id)), 1)
        self.database.clear_logs(tasks[0].id)
        self.assertEqual(self.database.list_logs(task_id=tasks[0].id), [])
        self.assertEqual(len(self.database.list_logs(task_id=tasks[1].id)), 1)

    def test_all_logs_and_count_are_available(self):
        task = self.database.save_task(Task(
            name="many", schedule_type=ScheduleType.FIXED,
            action_type=ActionType.NOTIFICATION, time_start="08:00:00",
        ))
        for number in range(3):
            log_id = self.database.claim_occurrence(task.id, f"manual:{number}")
            self.database.finish_log(log_id, "success", "done")
        self.assertEqual(self.database.count_logs(), 3)
        self.assertEqual(len(self.database.list_logs(None)), 3)


if __name__ == "__main__":
    unittest.main()
