import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication, QCalendarWidget

from ttask.database import Database
import ttask.holidays_cn as holidays
from ttask.models import ActionType, ScheduleType, Task
from ttask.qt_gui import (
    MainWindow,
    HolidayManagerDialog,
    TaskDialog,
    ToggleSwitch,
    autostart_command,
    format_datetime,
)


class QtGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_has_icon_and_three_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                Database(Path(directory) / "qt-main.db"),
                start_services=False,
            )
            self.assertFalse(window.windowIcon().isNull())
            self.assertEqual(window.tasks.columnCount(), 7)
            self.assertEqual(window.history.columnCount(), 5)
            self.assertEqual(window.upcoming.columnCount(), 5)
            self.assertEqual(window.detail_tabs.count(), 4)
            self.assertTrue(window.detail_tabs.tabText(0).startswith("今日已执行   "))
            self.assertTrue(window.detail_tabs.tabText(1).startswith("今日待执行   "))
            expected_widths = [55, 170, 260, 185, 220]
            for table in window.detail_tables:
                self.assertEqual(
                    [table.columnWidth(index) for index in range(5)], expected_widths
                )
            self.assertEqual(window.tasks.verticalHeader().defaultSectionSize(), 38)
            self.assertEqual(window.metric_tasks.text(), "0")
            self.assertEqual(window.author_label.text(), "TTask v9.16 · 作者：JohnZhu")
            window.close()

    def test_detail_tables_share_layout_and_clear_button_visibility(self):
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                Database(Path(directory) / "shared-detail-layout.db"),
                start_services=False,
            )
            window.today_history.horizontalHeader().resizeSection(2, 333)
            self.assertTrue(all(table.columnWidth(2) == 333 for table in window.detail_tables))
            window.detail_tabs.setCurrentIndex(1)
            self.assertTrue(window.clear_records_button.isHidden())
            window.detail_tabs.setCurrentIndex(2)
            self.assertFalse(window.clear_records_button.isHidden())
            window.close()

    def test_task_rows_have_different_backgrounds(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "row-colors.db")
            for index in range(2):
                database.save_task(
                    Task(
                        name=f"task-{index}",
                        schedule_type=ScheduleType.FIXED,
                        action_type=ActionType.NOTIFICATION,
                        time_start="23:59:00",
                    )
                )
            window = MainWindow(database, start_services=False)
            first = window.tasks.item(0, 0).background().color().name()
            second = window.tasks.item(1, 0).background().color().name()
            self.assertNotEqual(first, second)
            self.assertEqual(
                window.tasks.item(0, 0).textAlignment(),
                int(Qt.AlignCenter),
            )
            switch = window.tasks.cellWidget(0, 4).findChild(ToggleSwitch)
            self.assertIsNotNone(switch)
            self.assertTrue(switch.isChecked())
            window.close()

    def test_selection_does_not_filter_global_upcoming_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "selection.db")
            saved = []
            for name, clock in (("morning", "08:00:00"), ("evening", "18:00:00")):
                saved.append(database.save_task(Task(
                    name=name, schedule_type=ScheduleType.FIXED,
                    action_type=ActionType.NOTIFICATION, time_start=clock,
                )))
            window = MainWindow(database, start_services=False)
            window.tasks.selectRow(1)
            window.refresh_details()
            rows = [row for row in range(window.upcoming.rowCount()) if window.upcoming.item(row, 1)]
            self.assertEqual(window.upcoming.item(rows[0], 0).text(), "1")
            names = {window.upcoming.item(row, 1).text() for row in rows}
            self.assertEqual(names, {"morning", "evening"})
            window.close()

    def test_today_pending_is_global_even_when_task_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "today-global.db")
            for name in ("first", "second"):
                database.save_task(Task(
                    name=name, schedule_type=ScheduleType.FIXED,
                    action_type=ActionType.NOTIFICATION, time_start="23:59:59",
                    weekdays=list(range(7)),
                ))
            window = MainWindow(database, start_services=False)
            window.tasks.selectRow(0)
            window.refresh_details()
            self.assertEqual(window.metric_today.text(), "2")
            self.assertEqual(window.today_upcoming.rowCount(), 3)  # date group + two plans
            self.assertEqual(window.detail_tabs.tabText(1), "今日待执行   2")
            names = {
                window.upcoming.item(row, 1).text()
                for row in range(window.upcoming.rowCount())
                if window.upcoming.item(row, 1)
            }
            self.assertEqual(names, {"first", "second"})
            window.close()

    def test_log_filter_uses_task_id_for_duplicate_names(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "duplicate-names.db")
            tasks = [database.save_task(Task(
                name="同名任务", schedule_type=ScheduleType.FIXED,
                action_type=ActionType.NOTIFICATION, time_start="23:59:59",
            )) for _ in range(2)]
            for saved in tasks:
                log_id = database.claim_occurrence(saved.id, f"manual:{saved.id}")
                database.finish_log(log_id, "success", str(saved.id))
            window = MainWindow(database, start_services=False)
            window.detail_task_filter.setCurrentIndex(
                window.detail_task_filter.findData(tasks[1].id)
            )
            window._apply_detail_filters()
            self.assertEqual(window.history.rowCount(), 1)
            self.assertEqual(window.history.item(0, 0).data(Qt.UserRole)["task_id"], tasks[1].id)
            window.close()

    def test_table_layout_is_draggable_and_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "layout.db")
            first = MainWindow(database, start_services=False)
            header = first.tasks.horizontalHeader()
            self.assertTrue(header.sectionsMovable())
            header.resizeSection(0, 211)
            header.moveSection(0, 2)
            first._save_layout()
            first.close()

            second = MainWindow(database, start_services=False)
            restored = second.tasks.horizontalHeader()
            self.assertEqual(restored.sectionSize(0), 211)
            self.assertEqual(restored.visualIndex(0), 2)
            second.close()

    def test_iso_time_format(self):
        self.assertEqual(
            format_datetime("2026-07-27T15:43:35"),
            "2026-07-27 15:43:35",
        )

    def test_new_task_checks_weekdays_but_not_weekends(self):
        dialog = TaskDialog()
        self.assertEqual(len(dialog.day_checks), 7)
        self.assertTrue(all(check.isChecked() for check in dialog.day_checks[:5]))
        self.assertFalse(dialog.day_checks[5].isChecked())
        self.assertFalse(dialog.day_checks[6].isChecked())
        self.assertEqual(dialog.misfire_policy.currentData(), "skip")
        dialog.close()

    def test_workday_rule_disables_weekday_checks_and_shows_holiday(self):
        with patch.dict(holidays._manual, {}, clear=True):
            dialog = TaskDialog()
            dialog.date_rule.setCurrentIndex(1)
            self.assertTrue(all(not check.isEnabled() for check in dialog.day_checks))
            dialog.calendar.setSelectedDate(QDate(2026, 10, 1))
            dialog._paint_calendar()
            self.assertIn("国庆节", dialog.selected_holiday_label.text())
            self.assertIn("不执行", dialog.selected_state_label.text())
            dialog.close()

    def test_holiday_manager_opens_as_calendar(self):
        dialog = HolidayManagerDialog()
        self.assertIsNotNone(dialog.calendar)
        self.assertIn(str(datetime.now().year), dialog.update_button.text())
        self.assertIn(str(datetime.now().year + 1), dialog.update_button.text())
        dialog.calendar.setSelectedDate(QDate(2026, 9, 20))
        dialog._refresh_selected()
        self.assertIn("调休工作日", dialog.kind_label.text())
        self.assertIn("国庆节调休", dialog.kind_label.text())
        dialog.close()

    def test_date_tab_exposes_clear_date_actions(self):
        dialog = TaskDialog()
        self.assertEqual(dialog.execute_date_button.text(), "设为执行")
        self.assertEqual(dialog.skip_date_button.text(), "设为不执行")
        self.assertEqual(dialog.restore_date_button.text(), "恢复规则")
        self.assertEqual(
            dialog.calendar.verticalHeaderFormat(),
            QCalendarWidget.NoVerticalHeader,
        )
        dialog.close()

    def test_calendar_click_does_not_change_date_rules(self):
        dialog = TaskDialog()
        target = QDate(2026, 9, 20)
        dialog.calendar.setSelectedDate(target)
        before = (set(dialog.overrides), set(dialog.excluded))
        dialog.calendar.clicked.emit(target)
        self.assertEqual((set(dialog.overrides), set(dialog.excluded)), before)
        dialog.close()

    def test_autostart_command_starts_in_tray(self):
        self.assertIn("--tray", autostart_command())


if __name__ == "__main__":
    unittest.main()
