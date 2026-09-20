import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch
from pathlib import Path

from ttask.database import Database
from ttask.engine import SchedulerEngine
from ttask.models import ActionType, ScheduleType, Task


class EngineTests(unittest.TestCase):
    def test_missed_fixed_schedule_is_caught_up_once(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Database(Path(folder) / "misfire.db")
            task = database.save_task(Task(
                name="补执行", schedule_type=ScheduleType.FIXED,
                action_type=ActionType.NOTIFICATION, time_start="08:00:00",
                weekdays=list(range(7)), action_config={"misfire_policy": "run_once"},
            ))
            engine = SchedulerEngine(database)
            engine.pool.submit = MagicMock()
            engine._dispatch_due(
                task, datetime(2026, 9, 20, 7, 55), datetime(2026, 9, 20, 8, 0, 10)
            )
            engine.pool.submit.assert_called_once()
            self.assertEqual(database.list_logs()[0]["scheduled_at"], "2026-09-20T08:00:00")
            engine.stop()

    def test_missed_schedule_can_be_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Database(Path(folder) / "skip.db")
            task = database.save_task(Task(
                name="跳过", schedule_type=ScheduleType.FIXED,
                action_type=ActionType.NOTIFICATION, time_start="08:00:00",
                weekdays=list(range(7)), action_config={"misfire_policy": "skip"},
            ))
            engine = SchedulerEngine(database)
            engine.pool.submit = MagicMock()
            engine._dispatch_due(
                task, datetime(2026, 9, 20, 7, 55), datetime(2026, 9, 20, 8, 0, 10)
            )
            engine.pool.submit.assert_not_called()
            engine.stop()

    def test_missed_schedule_defaults_to_skip(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Database(Path(folder) / "default-skip.db")
            task = database.save_task(Task(
                name="默认跳过", schedule_type=ScheduleType.FIXED,
                action_type=ActionType.NOTIFICATION, time_start="08:00:00",
                weekdays=list(range(7)), action_config={},
            ))
            engine = SchedulerEngine(database)
            engine.pool.submit = MagicMock()
            engine._dispatch_due(
                task, datetime(2026, 9, 20, 7, 55), datetime(2026, 9, 20, 8, 0, 10)
            )
            engine.pool.submit.assert_not_called()
            engine.stop()

    def test_notification_action_writes_success_log(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Database(Path(folder) / "engine.db")
            task = database.save_task(
                Task(
                    name="通知测试",
                    schedule_type=ScheduleType.FIXED,
                    action_type=ActionType.NOTIFICATION,
                    time_start="08:00:00",
                    action_config={"message": "立即执行成功"},
                )
            )
            notifications = []
            engine = SchedulerEngine(database, lambda title, message: notifications.append((title, message)))
            log_id = database.claim_occurrence(task.id, "manual:test")
            engine._execute(task, log_id)
            self.assertEqual(notifications, [("通知测试", "立即执行成功")])
            self.assertEqual(database.list_logs()[0]["status"], "success")
            engine.stop()

    def test_failed_action_retries_then_succeeds(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Database(Path(folder) / "retry.db")
            task = database.save_task(
                Task(
                    name="重试测试",
                    schedule_type=ScheduleType.FIXED,
                    action_type=ActionType.NOTIFICATION,
                    time_start="08:00:00",
                    action_config={"retries": 2, "retry_delay": 0},
                )
            )
            engine = SchedulerEngine(database)
            attempts = []

            def flaky(_task):
                attempts.append(1)
                if len(attempts) < 3:
                    raise RuntimeError("暂时失败")
                return "恢复成功"

            engine._execute_once = flaky
            log_id = database.claim_occurrence(task.id, "manual:retry")
            engine._execute(task, log_id)
            self.assertEqual(len(attempts), 3)
            self.assertEqual(database.list_logs()[0]["status"], "success")
            engine.stop()

    def test_template_variables_are_rendered(self):
        task = Task(
            name="模板任务",
            schedule_type=ScheduleType.FIXED,
            action_type=ActionType.NOTIFICATION,
            time_start="08:00:00",
            action_config={"message": "{task_name}_{date}"},
        )
        rendered = SchedulerEngine._render_config(task)
        self.assertTrue(rendered["message"].startswith("模板任务_"))
        self.assertNotIn("{date}", rendered["message"])

    def test_gui_command_with_no_output_is_successful(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = SchedulerEngine(Database(Path(folder) / "gui-command.db"))
            value = Task(
                name="gui-command",
                schedule_type=ScheduleType.FIXED,
                action_type=ActionType.COMMAND,
                time_start="08:00:00",
                action_config={"command": ["gui-app.exe"]},
            )
            process = MagicMock()
            process.communicate.return_value = (None, None)
            process.returncode = 0
            with patch("ttask.engine.subprocess.Popen", return_value=process):
                self.assertEqual(engine._execute_once(value), "")
            engine.stop()

    def test_consecutive_failures_disable_task(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Database(Path(folder) / "disable.db")
            task = database.save_task(
                Task(
                    name="失败保护",
                    schedule_type=ScheduleType.FIXED,
                    action_type=ActionType.COMMAND,
                    time_start="08:00:00",
                    action_config={"command": [], "disable_after_failures": 2},
                )
            )
            engine = SchedulerEngine(database)
            for number in range(2):
                log_id = database.claim_occurrence(task.id, f"manual:fail-{number}")
                engine._execute(task, log_id)
            self.assertFalse(database.get_task(task.id).enabled)
            engine.stop()


if __name__ == "__main__":
    unittest.main()
