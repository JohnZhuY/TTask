from __future__ import annotations

import copy
import secrets
import shlex
import socket
import sys
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

# Load Shiboken before Qt modules. This is required by some frozen Windows
# builds so its ABI DLL is initialized before PySide6.QtCore.
import shiboken6
from PySide6.QtCore import QByteArray, QDate, QEvent, QObject, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCalendarWidget,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QSplitter,
    QStyle,
    QSystemTrayIcon,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .database import Database
from . import __version__
from .engine import SchedulerEngine
from .holidays_cn import (
    day_info, day_source, downloaded_years, is_workday, manual_info,
    set_manual_day, update_years,
)
from .models import ActionType, ScheduleType, Task
from .scheduling import count_occurrences_on_date, next_occurrence, upcoming_occurrences


SCHEDULE_LABELS = {
    ScheduleType.FIXED: "定点执行",
    ScheduleType.RANDOM_WINDOW: "时间段内随机执行",
    ScheduleType.ONCE: "指定日期执行一次",
    ScheduleType.INTERVAL: "固定间隔执行",
}
ACTION_LABELS = {
    ActionType.COMMAND: "执行命令/脚本",
    ActionType.NOTIFICATION: "桌面通知",
    ActionType.OPEN: "打开程序/文件",
    ActionType.HTTP: "HTTP 请求",
    ActionType.COPY: "复制文件",
    ActionType.MOVE: "移动文件",
}
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
APP_VERSION = __version__.removesuffix(".0")
APP_AUTHOR = "JohnZhu"
IPC_REQUEST = b"TTASK_ACTIVATE_V1\n"
IPC_RESPONSE = b"TTASK_OK_V1\n"


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative


def format_datetime(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value.replace("T", " ", 1)


def autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --tray'
    return f'"{sys.executable}" -m ttask --tray'


def upgrade_existing_autostart() -> None:
    """Migrate an existing startup entry to background/tray mode."""
    if sys.platform != "win32":
        return
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE
        ) as key:
            winreg.QueryValueEx(key, "TTask")
            winreg.SetValueEx(key, "TTask", 0, winreg.REG_SZ, autostart_command())
    except FileNotFoundError:
        pass


STYLE = """
QWidget { font-family: "Microsoft YaHei UI"; font-size: 11px; color: #172033; }
QMainWindow, QDialog { background: #f4f7fb; }
QToolBar { background: #ffffff; border: none; border-bottom: 1px solid #dfe6f0; spacing: 4px; padding: 4px 8px; }
QToolButton, QPushButton { background: #ffffff; border: 1px solid #d7dfeb; border-radius: 6px; padding: 4px 9px; }
QToolButton:hover, QPushButton:hover { background: #edf4ff; border-color: #7caef8; }
QToolButton#primaryTool { color: white; background: #3478f6; border-color: #3478f6; font-weight: 600; }
QToolButton#dangerTool { color: #dc2626; }
QPushButton#primary { color: white; background: #3478f6; border-color: #3478f6; font-weight: 600; }
QLineEdit, QComboBox, QSpinBox { background: white; border: 1px solid #d5ddea; border-radius: 6px; padding: 4px; min-height: 17px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #3478f6; }
QTabWidget::pane { background: white; border: 1px solid #dfe6f0; border-radius: 8px; }
QTabBar::tab { padding: 6px 14px; background: #edf1f7; margin-right: 2px; }
QTabBar::tab:selected { color: #2563d9; background: white; border-top: 2px solid #3478f6; }
QTabBar::tab { min-width: 112px; }
QTableWidget { background: white; alternate-background-color: #f7f9fc; border: 1px solid #dfe6f0; border-radius: 8px; gridline-color: #e8edf4; selection-background-color: #d9e9ff; selection-color: #172033; }
QTableWidget::item:hover { background: #edf5ff; }
QHeaderView::section { background: #eef3f9; color: #344159; border: none; border-right: 1px solid #dde5ef; border-bottom: 1px solid #d5deea; padding: 5px; font-weight: 600; }
QCalendarWidget QWidget { alternate-background-color: #f4f7fb; }
QStatusBar { background: #273449; color: white; }
QLabel#sectionTitle { font-size: 12px; font-weight: 700; color: #26364d; }
QFrame#card { background: white; border: 1px solid #dfe6f0; border-radius: 10px; }
QFrame#metricCard { background: white; border: 1px solid #dfe6f0; border-radius: 8px; }
QLabel#metricValue { color: #2563eb; font-size: 17px; font-weight: 700; }
QLabel#metricLabel { color: #64748b; font-size: 10px; }
QFrame#dateStateCard, QFrame#legendCard { background: #f8fafc; border: 1px solid #dbe3ee; border-radius: 8px; }
QMessageBox { background: #f7f9fc; }
QMessageBox QLabel { color: #26364d; font-size: 12px; min-width: 260px; padding: 5px 2px; }
QMessageBox QPushButton { min-width: 78px; min-height: 25px; padding: 3px 14px; }
QDialog#previewDialog QFrame#previewHero { background: #edf4ff; border: 1px solid #cfe0fb; border-radius: 10px; }
QDialog#previewDialog QLabel#previewTitle { color: #1f4fa3; font-size: 16px; font-weight: 700; }
QDialog#previewDialog QLabel#previewHint { color: #64748b; font-size: 10px; }
QDialog#previewDialog QListWidget { background: white; border: 1px solid #dbe4f0; border-radius: 8px; padding: 5px; outline: none; }
QDialog#previewDialog QListWidget::item { min-height: 30px; border-bottom: 1px solid #edf1f6; padding: 2px 10px; }
QDialog#previewDialog QListWidget::item:hover { background: #edf5ff; }
"""


class ToggleSwitch(QCheckBox):
    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("点击启用或停用任务")

    def sizeHint(self):
        return QSize(42, 22)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        track = QRectF(2, 2, 38, 18)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#3478f6" if self.isChecked() else "#b8c2d1"))
        painter.drawRoundedRect(track, 9, 9)
        knob_x = 23 if self.isChecked() else 4
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(knob_x, 3.5, 15, 15))


class HolidayCalendar(QCalendarWidget):
    """Calendar that adds official holiday/workday names below the date number."""

    def paintCell(self, painter, rect, qdate):
        super().paintCell(painter, rect, qdate)
        info = day_info(qdate.toPython())
        is_today = qdate == QDate.currentDate()
        if not info.name and not is_today:
            return
        painter.save()
        font = QFont(painter.font())
        font.setPointSize(max(7, font.pointSize() - 2))
        painter.setFont(font)
        if is_today:
            painter.setPen(QColor("#2563eb"))
            painter.drawText(rect.adjusted(2, 2, -2, -2), Qt.AlignHCenter | Qt.AlignTop, "今日")
        if info.name:
            painter.setPen(QColor("#c2410c" if info.is_holiday else "#2563eb"))
            label = info.name if info.is_holiday else "调休上班"
            painter.drawText(rect.adjusted(2, 2, -2, -2), Qt.AlignHCenter | Qt.AlignBottom, label)
        painter.restore()


class TimeRuleDialog(QDialog):
    def __init__(self, parent, random_window: bool, start: str, end: str):
        super().__init__(parent)
        self.setWindowTitle("添加随机时间段" if random_window else "添加定点时间")
        self.random_window = random_window
        self.start_edit = QLineEdit(start)
        self.end_edit = QLineEdit(end)
        form = QFormLayout(self)
        form.setContentsMargins(18, 18, 18, 14)
        form.addRow("开始时间" if random_window else "执行时间", self.start_edit)
        if random_window:
            form.addRow("结束时间", self.end_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _accept(self):
        try:
            start = datetime.strptime(self.start_edit.text().strip(), "%H:%M:%S")
            if self.random_window:
                end = datetime.strptime(self.end_edit.text().strip(), "%H:%M:%S")
                if end <= start:
                    raise ValueError("结束时间必须晚于开始时间")
        except ValueError as exc:
            QMessageBox.warning(self, "时间格式有误", str(exc))
            return
        self.accept()

    def value(self) -> list[str]:
        result = [self.start_edit.text().strip()]
        if self.random_window:
            result.append(self.end_edit.text().strip())
        return result


class TaskDialog(QDialog):
    def __init__(self, parent=None, task: Task | None = None):
        super().__init__(parent)
        self.task = task
        self.result_task: Task | None = None
        self.windows = copy.deepcopy(task.time_windows) if task and task.time_windows else []
        self.overrides = set(task.weekend_overrides if task else [])
        self.excluded = set(task.excluded_dates if task else [])
        self.setWindowTitle("编辑任务" if task else "新建任务")
        self.resize(680, 540)
        self.setWindowIcon(parent.windowIcon() if parent else QIcon())

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 14)
        tabs = QTabWidget()
        root.addWidget(tabs)
        tabs.addTab(self._task_tab(), "任务设置")
        tabs.addTab(self._plan_tab(), "计划设置")
        tabs.addTab(self._date_tab(), "日期设置")
        tabs.addTab(self._execution_tab(), "执行设置")
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Save).setObjectName("primary")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _task_tab(self):
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(10)
        self.name = QLineEdit(self.task.name if self.task else "")
        self.action = QComboBox()
        self.action.addItems(ACTION_LABELS.values())
        if self.task:
            self.action.setCurrentText(ACTION_LABELS[self.task.action_type])
        self.payload = QLineEdit(self._payload(self.task))
        form.addRow("任务名称", self.name)
        form.addRow("动作类型", self.action)
        form.addRow("动作参数", self.payload)
        hint = QLabel("命令：程序路径和参数；HTTP：方法|URL|请求体；复制/移动：源路径|目标路径")
        hint.setStyleSheet("color:#718096")
        hint.setWordWrap(True)
        form.addRow("", hint)
        return page

    def _plan_tab(self):
        page = QWidget()
        layout = QGridLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(12)
        self.schedule = QComboBox()
        self.schedule.addItems(SCHEDULE_LABELS.values())
        if self.task:
            self.schedule.setCurrentText(SCHEDULE_LABELS[self.task.schedule_type])
        self.start = QLineEdit(self.task.time_start if self.task else "08:00:00")
        self.end = QLineEdit((self.task.time_end if self.task else None) or "08:25:00")
        self.run_date = QLineEdit(
            (self.task.run_date or (self.task.anchor_at or "")[:10])
            if self.task else date.today().isoformat()
        )
        self.interval = QSpinBox()
        self.interval.setRange(1, 31536000)
        self.interval.setValue((self.task.interval_seconds if self.task else None) or 3600)
        for row, (label, widget) in enumerate((
            ("调度方式", self.schedule), ("执行/开始时间", self.start),
            ("结束时间", self.end), ("执行/开始日期", self.run_date),
            ("固定间隔（秒）", self.interval),
        )):
            layout.addWidget(QLabel(label), row, 0)
            layout.addWidget(widget, row, 1, 1, 2)
        self.date_rule = QComboBox()
        self.date_rule.addItems(["每周指定日期", "工作日（含法定调休）"])
        if self.task and self.task.workdays_only:
            self.date_rule.setCurrentIndex(1)
        layout.addWidget(QLabel("日期规则"), 5, 0)
        layout.addWidget(self.date_rule, 5, 1, 1, 2)
        self.rules = QListWidget()
        self.rules.setAlternatingRowColors(True)
        self._refresh_rules()
        add = QPushButton("＋ 添加时间规则")
        remove = QPushButton("－ 删除选中规则")
        add.clicked.connect(self._add_rule)
        remove.clicked.connect(self._remove_rule)
        layout.addWidget(QLabel("多个时间点/时段"), 6, 0)
        layout.addWidget(self.rules, 6, 1)
        rule_buttons = QVBoxLayout()
        rule_buttons.addWidget(add)
        rule_buttons.addWidget(remove)
        rule_buttons.addStretch()
        layout.addLayout(rule_buttons, 6, 2)
        days = QHBoxLayout()
        self.day_checks = []
        for index, label in enumerate(WEEKDAYS):
            check = QCheckBox(label)
            check.setChecked(index in self.task.weekdays if self.task else index < 5)
            self.day_checks.append(check)
            days.addWidget(check)
        days.addStretch()
        layout.addWidget(QLabel("每周执行日"), 7, 0)
        layout.addLayout(days, 7, 1, 1, 2)
        self.date_rule.currentIndexChanged.connect(self._date_rule_changed)
        self._date_rule_changed()
        layout.setColumnStretch(1, 1)
        layout.setRowStretch(6, 1)
        return page

    def _date_tab(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)
        self.calendar = HolidayCalendar()
        self.calendar.setGridVisible(True)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.calendar.setSelectedDate(QDate.fromString(self.run_date.text(), "yyyy-MM-dd"))
        self.calendar.selectionChanged.connect(self._paint_calendar)
        self.calendar.currentPageChanged.connect(lambda _year, _month: self._paint_calendar())
        self.schedule.currentTextChanged.connect(lambda _text: self._paint_calendar())
        for check in self.day_checks:
            check.toggled.connect(lambda _checked: self._paint_calendar())
        layout.addWidget(self.calendar, 3)
        side = QVBoxLayout()
        side.setSpacing(9)
        title = QLabel("日期执行设置")
        title.setObjectName("sectionTitle")
        side.addWidget(title)
        hint = QLabel("单击日期进行选择，再使用下方按钮设置当天是否执行。日期双击不会改变状态。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b;")
        side.addWidget(hint)

        selected_card = QFrame()
        selected_card.setObjectName("dateStateCard")
        selected_layout = QVBoxLayout(selected_card)
        selected_layout.setContentsMargins(12, 10, 12, 10)
        self.selected_date_label = QLabel()
        self.selected_date_label.setStyleSheet("font-weight:700; font-size:13px;")
        self.selected_state_label = QLabel()
        self.selected_state_label.setWordWrap(True)
        self.selected_holiday_label = QLabel()
        self.selected_holiday_label.setWordWrap(True)
        self.selected_holiday_label.setStyleSheet("color:#475569;")
        selected_layout.addWidget(self.selected_date_label)
        selected_layout.addWidget(self.selected_holiday_label)
        selected_layout.addWidget(self.selected_state_label)
        side.addWidget(selected_card)

        action_row = QHBoxLayout()
        self.execute_date_button = QPushButton("设为执行")
        self.execute_date_button.setObjectName("primary")
        self.skip_date_button = QPushButton("设为不执行")
        self.restore_date_button = QPushButton("恢复规则")
        self.execute_date_button.clicked.connect(lambda: self._set_selected_date_mode("execute"))
        self.skip_date_button.clicked.connect(lambda: self._set_selected_date_mode("skip"))
        self.restore_date_button.clicked.connect(lambda: self._set_selected_date_mode("default"))
        action_row.addWidget(self.execute_date_button)
        action_row.addWidget(self.skip_date_button)
        action_row.addWidget(self.restore_date_button)
        side.addLayout(action_row)

        legend = QFrame()
        legend.setObjectName("legendCard")
        legend_layout = QGridLayout(legend)
        legend_layout.setContentsMargins(10, 9, 10, 9)
        legend_layout.setHorizontalSpacing(10)
        legend_layout.setVerticalSpacing(7)
        for index, (text, color) in enumerate((
            ("按周期规则执行", "#dcfce7"), ("手动指定执行", "#dbeafe"),
            ("手动排除", "#fee2e2"), ("默认不执行", "#f1f5f9"),
        )):
            swatch = QLabel()
            swatch.setFixedSize(18, 18)
            swatch.setStyleSheet(f"background:{color}; border:1px solid #cbd5e1; border-radius:4px;")
            legend_layout.addWidget(swatch, index, 0)
            legend_layout.addWidget(QLabel(text), index, 1)
        side.addWidget(legend)

        self.date_info = QLabel()
        self.date_info.setWordWrap(True)
        self.date_info.setStyleSheet("color:#475569;")
        side.addWidget(self.date_info)
        side.addStretch()
        layout.addLayout(side, 2)
        self._paint_calendar()
        return page

    def _execution_tab(self):
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(20, 20, 20, 20)
        config = self.task.action_config if self.task else {}
        self.retries = QSpinBox()
        self.retries.setRange(0, 10)
        self.retries.setValue(int(config.get("retries", 0)))
        self.retry_delay = QSpinBox()
        self.retry_delay.setRange(0, 3600)
        self.retry_delay.setValue(int(config.get("retry_delay", 5)))
        self.disable_after = QSpinBox()
        self.disable_after.setRange(0, 100)
        self.disable_after.setValue(int(config.get("disable_after_failures", 0)))
        self.misfire_policy = QComboBox()
        self.misfire_policy.addItem("直接跳过错过计划（默认）", "skip")
        self.misfire_policy.addItem("补执行一次", "run_once")
        self.misfire_policy.addItem("补执行错过计划（最多 1000 次）", "run_all")
        selected_policy = self.misfire_policy.findData(config.get("misfire_policy", "skip"))
        self.misfire_policy.setCurrentIndex(max(0, selected_policy))
        form.addRow("失败重试次数", self.retries)
        form.addRow("重试间隔（秒）", self.retry_delay)
        form.addRow("连续失败自动停用", self.disable_after)
        form.addRow("错过计划时", self.misfire_policy)
        return page

    def _schedule_type(self):
        return next(key for key, label in SCHEDULE_LABELS.items() if label == self.schedule.currentText())

    def _action_type(self):
        return next(key for key, label in ACTION_LABELS.items() if label == self.action.currentText())

    def _date_rule_changed(self):
        workdays = self.date_rule.currentIndex() == 1
        for check in self.day_checks:
            check.setEnabled(not workdays)
        if hasattr(self, "calendar"):
            self._paint_calendar()

    def _add_rule(self):
        dialog = TimeRuleDialog(
            self, self._schedule_type() == ScheduleType.RANDOM_WINDOW,
            self.start.text(), self.end.text(),
        )
        if dialog.exec() == QDialog.Accepted:
            value = dialog.value()
            if value not in self.windows:
                self.windows.append(value)
                self.windows.sort(key=lambda item: item[0])
                self._refresh_rules()
            else:
                QMessageBox.information(self, "提示", "相同的时间规则已经存在。")

    def _remove_rule(self):
        row = self.rules.currentRow()
        if row >= 0:
            self.windows.pop(row)
            self._refresh_rules()

    def _refresh_rules(self):
        self.rules.clear()
        for value in self.windows:
            self.rules.addItem(value[0] if len(value) == 1 else f"{value[0]}  —  {value[1]}")

    def _base_allowed(self, value: date) -> bool:
        if self._schedule_type() == ScheduleType.ONCE:
            return value.isoformat() == self.run_date.text()
        if self.date_rule.currentIndex() == 1:
            return is_workday(value)
        return self.day_checks[value.weekday()].isChecked()

    def _set_selected_date_mode(self, mode: str):
        qdate = self.calendar.selectedDate()
        iso = qdate.toString("yyyy-MM-dd")
        if self._schedule_type() == ScheduleType.ONCE:
            if mode == "execute":
                self.run_date.setText(iso)
        elif mode == "execute":
            self.excluded.discard(iso)
            if not self._base_allowed(qdate.toPython()):
                self.overrides.add(iso)
            else:
                self.overrides.discard(iso)
        elif mode == "skip":
            self.overrides.discard(iso)
            self.excluded.add(iso)
        else:
            self.overrides.discard(iso)
            self.excluded.discard(iso)
        self._paint_calendar()

    def _selected_date_state(self):
        qdate = self.calendar.selectedDate()
        pydate = qdate.toPython()
        iso = pydate.isoformat()
        if self._schedule_type() == ScheduleType.ONCE:
            if iso == self.run_date.text():
                return "执行一次", "该日期是一次性任务的执行日期", "#2563eb"
            return "不执行", "点击“设为执行”可将一次性任务改到这一天", "#64748b"
        if iso in self.excluded:
            return "不执行", "已手动排除，不受星期规则影响", "#dc2626"
        if iso in self.overrides:
            return "执行", "已手动指定执行，不受星期规则影响", "#2563eb"
        if self._base_allowed(pydate):
            if self.date_rule.currentIndex() == 1:
                info = day_info(pydate)
                source = "法定调休工作日" if info.is_adjusted_workday else "中国大陆工作日"
                return "执行", f"按工作日规则执行（{source}）", "#15803d"
            return "执行", f"按{WEEKDAYS[pydate.weekday()]}周期规则执行", "#15803d"
        if self.date_rule.currentIndex() == 1:
            info = day_info(pydate)
            reason = info.name if info.is_holiday else "周末"
            return "不执行", f"工作日规则：{reason}", "#64748b"
        return "不执行", f"{WEEKDAYS[pydate.weekday()]}未启用", "#64748b"

    def _paint_calendar(self):
        if not hasattr(self, "calendar"):
            return
        first = self.calendar.selectedDate().addMonths(-2)
        for offset in range(150):
            qdate = first.addDays(offset)
            pydate = qdate.toPython()
            iso = pydate.isoformat()
            fmt = QTextCharFormat()
            if iso in self.excluded:
                fmt.setBackground(QColor("#fee2e2"))
            elif iso in self.overrides:
                fmt.setBackground(QColor("#dbeafe"))
            elif self._base_allowed(pydate):
                fmt.setBackground(QColor("#dcfce7"))
            else:
                fmt.setBackground(QColor("#f1f5f9"))
            self.calendar.setDateTextFormat(qdate, fmt)
        state, source, color = self._selected_date_state()
        selected_pydate = self.calendar.selectedDate().toPython()
        selected_info = day_info(selected_pydate)
        self.selected_date_label.setText(self.calendar.selectedDate().toString("yyyy年M月d日 dddd"))
        if selected_info.is_holiday:
            holiday_text = f"法定节假日 · {selected_info.name}"
        elif selected_info.is_adjusted_workday:
            holiday_text = "调休工作日 · 正常上班"
        elif not selected_info.data_available:
            holiday_text = "该年份暂无官方节假日数据，工作日暂按周一至周五判断"
        else:
            holiday_text = "普通工作日" if selected_pydate.weekday() < 5 else "普通周末"
        self.selected_holiday_label.setText(holiday_text)
        self.selected_state_label.setText(
            f"<span style='color:{color}; font-weight:700'>{state}</span>　{source}"
        )
        once = self._schedule_type() == ScheduleType.ONCE
        self.skip_date_button.setEnabled(not once)
        self.restore_date_button.setEnabled(not once)
        self.date_info.setText(
            f"手动执行日期：{len(self.overrides)} 天\n"
            f"手动排除日期：{len(self.excluded)} 天"
        )

    @staticmethod
    def _payload(task: Task | None) -> str:
        if not task:
            return ""
        config = task.action_config
        if task.action_type == ActionType.COMMAND:
            return subprocess_list2cmdline(config.get("command", []))
        if task.action_type == ActionType.NOTIFICATION:
            return str(config.get("message", ""))
        if task.action_type == ActionType.OPEN:
            return str(config.get("target", ""))
        if task.action_type == ActionType.HTTP:
            return "|".join(str(value) for value in (
                config.get("method", "GET"), config.get("url", ""), config.get("body", "")
            )).rstrip("|")
        return f"{config.get('source', '')}|{config.get('destination', '')}"

    def _action_config(self):
        action = self._action_type()
        payload = self.payload.text().strip()
        if action == ActionType.COMMAND:
            config = {"command": shlex.split(payload, posix=False), "timeout": 300}
        elif action == ActionType.NOTIFICATION:
            config = {"message": payload}
        elif action == ActionType.OPEN:
            config = {"target": payload}
        elif action == ActionType.HTTP:
            parts = payload.split("|", 2)
            if len(parts) < 2:
                raise ValueError("HTTP 格式应为：方法|URL|请求体")
            config = {"method": parts[0], "url": parts[1], "timeout": 30}
            if len(parts) == 3:
                config["body"] = parts[2]
        else:
            parts = payload.split("|", 1)
            if len(parts) != 2:
                raise ValueError("文件操作格式应为：源路径|目标路径")
            config = {"source": parts[0], "destination": parts[1]}
        config.update(
            retries=self.retries.value(), retry_delay=self.retry_delay.value(),
            disable_after_failures=self.disable_after.value(),
            misfire_policy=self.misfire_policy.currentData(),
            random_seed=(
                self.task.action_config.get("random_seed")
                if self.task and self.task.action_config.get("random_seed")
                else secrets.token_hex(16)
            ),
        )
        return config

    def _save(self):
        try:
            schedule = self._schedule_type()
            windows = copy.deepcopy(self.windows) or [[self.start.text().strip()] + (
                [self.end.text().strip()] if schedule == ScheduleType.RANDOM_WINDOW else []
            )]
            task = Task(
                id=self.task.id if self.task else None,
                name=self.name.text().strip(), schedule_type=schedule,
                action_type=self._action_type(), time_start=self.start.text().strip(),
                time_end=self.end.text().strip() if schedule == ScheduleType.RANDOM_WINDOW else None,
                time_windows=windows,
                run_date=self.run_date.text().strip() if schedule == ScheduleType.ONCE else None,
                interval_seconds=self.interval.value() if schedule == ScheduleType.INTERVAL else None,
                anchor_at=(
                    f"{self.run_date.text().strip()}T{self.start.text().strip()}"
                    if schedule == ScheduleType.INTERVAL else None
                ),
                weekdays=[i for i, check in enumerate(self.day_checks) if check.isChecked()],
                workdays_only=self.date_rule.currentIndex() == 1,
                weekend_overrides=sorted(self.overrides), excluded_dates=sorted(self.excluded),
                action_config=self._action_config(),
                enabled=self.task.enabled if self.task else True,
            )
            task.validate()
        except Exception as exc:
            QMessageBox.warning(self, "配置无效", str(exc))
            return
        self.result_task = task
        self.accept()


def subprocess_list2cmdline(command):
    import subprocess
    return subprocess.list2cmdline(command)


class HolidayManagerDialog(QDialog):
    update_finished = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("节假日管理")
        self.setWindowIcon(parent.windowIcon() if parent else QIcon())
        self.resize(760, 500)
        root = QHBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)

        self.calendar = HolidayCalendar()
        self.calendar.setGridVisible(True)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.calendar.selectionChanged.connect(self._refresh_selected)
        self.calendar.currentPageChanged.connect(lambda _y, _m: self._paint_calendar())
        root.addWidget(self.calendar, 3)

        side = QVBoxLayout()
        title = QLabel("节假日数据")
        title.setObjectName("sectionTitle")
        side.addWidget(title)
        self.years_label = QLabel()
        self.years_label.setWordWrap(True)
        self.years_label.setStyleSheet("color:#64748b;")
        side.addWidget(self.years_label)
        self.update_button = QPushButton()
        self.update_button.setObjectName("primary")
        self.update_button.clicked.connect(self._start_update)
        side.addWidget(self.update_button)

        selected_card = QFrame()
        selected_card.setObjectName("dateStateCard")
        card_layout = QVBoxLayout(selected_card)
        card_layout.setContentsMargins(12, 11, 12, 11)
        self.date_label = QLabel()
        self.date_label.setStyleSheet("font-size:13px; font-weight:700;")
        self.kind_label = QLabel()
        self.kind_label.setWordWrap(True)
        self.source_label = QLabel()
        self.source_label.setStyleSheet("color:#64748b;")
        card_layout.addWidget(self.date_label)
        card_layout.addWidget(self.kind_label)
        card_layout.addWidget(self.source_label)
        side.addWidget(selected_card)

        side.addWidget(QLabel("手工修改（优先于在线和内置数据）"))
        holiday = QPushButton("设为节假日")
        workday = QPushButton("设为调休工作日")
        restore = QPushButton("恢复自动数据")
        holiday.clicked.connect(self._set_holiday)
        workday.clicked.connect(lambda: self._set_manual("workday", "调休上班"))
        restore.clicked.connect(lambda: self._set_manual(None, ""))
        side.addWidget(holiday)
        side.addWidget(workday)
        side.addWidget(restore)

        legend = QLabel("● 节假日　　● 调休工作日　　◆ 手工修改")
        legend.setStyleSheet("color:#475569; padding-top:8px;")
        side.addWidget(legend)
        side.addStretch()
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        side.addWidget(close)
        root.addLayout(side, 2)

        self.update_finished.connect(self._update_done)
        self._refresh_update_text()
        self._paint_calendar()

    def _refresh_update_text(self):
        current = date.today().year
        years = downloaded_years()
        self.years_label.setText(
            "一键获取中国大陆法定节假日和调休安排。\n"
            f"本次更新：{current}、{current + 1}\n"
            f"已在线更新：{', '.join(map(str, years)) if years else '暂无'}"
        )
        self.update_button.setText(f"更新 {current}–{current + 1} 年")

    def _start_update(self):
        current = date.today().year
        self.update_button.setEnabled(False)
        self.update_button.setText("正在更新…")

        def worker():
            try:
                years = update_years([current, current + 1])
                self.update_finished.emit(True, f"已更新：{', '.join(map(str, years))} 年")
            except Exception as exc:
                self.update_finished.emit(False, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _update_done(self, success: bool, message: str):
        self.update_button.setEnabled(True)
        self._refresh_update_text()
        self._paint_calendar()
        if success:
            QMessageBox.information(self, "更新完成", message)
        else:
            QMessageBox.warning(self, "更新失败", message + "\n\n现有内置和本地数据未受影响。")

    def _set_holiday(self):
        value = self.calendar.selectedDate().toPython()
        current = day_info(value).name if day_info(value).is_holiday else "自定义节假日"
        name, accepted = QInputDialog.getText(self, "节假日名称", "名称", text=current)
        if accepted:
            self._set_manual("holiday", name)

    def _set_manual(self, kind: str | None, name: str):
        try:
            set_manual_day(self.calendar.selectedDate().toPython(), kind, name)
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self._paint_calendar()

    def _refresh_selected(self):
        value = self.calendar.selectedDate().toPython()
        info = day_info(value)
        self.date_label.setText(self.calendar.selectedDate().toString("yyyy年M月d日 dddd"))
        if info.is_holiday:
            description = f"<b style='color:#c2410c'>节假日</b>　{info.name}"
        elif info.is_adjusted_workday:
            related = f"{info.name}调休" if info.name and info.name != "调休上班" else "正常上班"
            description = f"<b style='color:#2563eb'>调休工作日</b>　{related}"
        else:
            description = "普通工作日" if value.weekday() < 5 else "普通周末"
        self.kind_label.setText(description)
        source = day_source(value)
        if manual_info(value):
            source += "（优先）"
        self.source_label.setText(f"数据来源：{source}")

    def _paint_calendar(self):
        shown = QDate(self.calendar.yearShown(), self.calendar.monthShown(), 1).addDays(-7)
        for offset in range(50):
            qdate = shown.addDays(offset)
            value = qdate.toPython()
            info = day_info(value)
            fmt = QTextCharFormat()
            if info.is_holiday:
                fmt.setBackground(QColor("#ffedd5"))
            elif info.is_adjusted_workday:
                fmt.setBackground(QColor("#dbeafe"))
            elif value.weekday() >= 5:
                fmt.setBackground(QColor("#f1f5f9"))
            if manual_info(value):
                fmt.setFontWeight(QFont.Bold)
                fmt.setForeground(QColor("#7c3aed"))
            self.calendar.setDateTextFormat(qdate, fmt)
        self._refresh_selected()


class OptionsDialog(QDialog):
    def __init__(self, parent, database: Database):
        super().__init__(parent)
        self.database = database
        self.setWindowTitle("选项")
        self.setWindowIcon(parent.windowIcon())
        self.setFixedSize(470, 300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        general = QWidget()
        general_layout = QVBoxLayout(general)
        general_layout.setContentsMargins(24, 22, 24, 22)
        self.autostart = QCheckBox("开机时自动运行 TTask")
        self.autostart.setChecked(self._autostart_enabled())
        general_layout.addWidget(self.autostart)
        general_layout.addSpacing(12)
        general_layout.addWidget(QLabel("点击主窗口关闭按钮时："))
        self.to_tray = QRadioButton("隐藏到系统托盘，任务继续运行")
        self.exit_app = QRadioButton("直接退出程序")
        mode = database.get_setting("close_mode", "tray")
        self.to_tray.setChecked(mode == "tray")
        self.exit_app.setChecked(mode == "exit")
        general_layout.addWidget(self.to_tray)
        general_layout.addWidget(self.exit_app)
        general_layout.addStretch()
        notice = QWidget()
        notice_layout = QVBoxLayout(notice)
        notice_layout.setContentsMargins(24, 22, 24, 22)
        self.notifications = QCheckBox("显示任务失败及自动停用通知")
        self.notifications.setChecked(database.get_setting("notifications", "1") == "1")
        notice_layout.addWidget(self.notifications)
        notice_layout.addWidget(QLabel("关闭后执行结果仍会完整写入最近执行记录。"))
        notice_layout.addStretch()
        tabs.addTab(general, "常规")
        tabs.addTab(notice, "通知")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _autostart_enabled():
        if sys.platform != "win32":
            return False
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                winreg.QueryValueEx(key, "TTask")
            return True
        except FileNotFoundError:
            return False

    @staticmethod
    def _set_autostart(enabled):
        if sys.platform != "win32":
            return
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_ALL_ACCESS,
        ) as key:
            if enabled:
                winreg.SetValueEx(key, "TTask", 0, winreg.REG_SZ, autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, "TTask")
                except FileNotFoundError:
                    pass

    def _save(self):
        try:
            self._set_autostart(self.autostart.isChecked())
            self.database.set_settings({
                "close_mode": "tray" if self.to_tray.isChecked() else "exit",
                "notifications": "1" if self.notifications.isChecked() else "0",
            })
        except Exception as exc:
            QMessageBox.warning(self, "保存选项失败", str(exc))
            return
        self.accept()


class PreviewDialog(QDialog):
    def __init__(self, task: Task, occurrences: list[datetime], parent=None):
        super().__init__(parent)
        self.setObjectName("previewDialog")
        self.setWindowTitle("执行计划预览")
        self.setWindowIcon(QIcon(str(resource_path("assets/clock.ico"))))
        self.resize(500, 430)
        self.setMinimumSize(440, 340)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        hero = QFrame()
        hero.setObjectName("previewHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(16, 12, 16, 12)
        title = QLabel(f"◷  {task.name}")
        title.setObjectName("previewTitle")
        hint = QLabel(f"以下为接下来 {len(occurrences)} 次预计执行时间，仅用于预览")
        hint.setObjectName("previewHint")
        hero_layout.addWidget(title)
        hero_layout.addWidget(hint)
        layout.addWidget(hero)

        schedule, _ = MainWindow._summary(task)
        summary = QLabel(schedule.replace("\n", "  ·  "))
        summary.setWordWrap(True)
        summary.setStyleSheet("color:#52637a; padding:0 4px;")
        layout.addWidget(summary)
        times = QListWidget()
        if occurrences:
            for index, value in enumerate(occurrences, 1):
                day_note = MainWindow._date_group(value.date())
                times.addItem(f"{index:02d}    {value:%Y-%m-%d  %H:%M:%S}    {day_note}")
        else:
            times.addItem("暂无可执行时间，请检查任务启用状态及日期规则")
        layout.addWidget(times, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class Bridge(QObject):
    notification = Signal(str, str)
    activate = Signal()


class MainWindow(QMainWindow):
    def __init__(self, database: Database, start_services: bool = True):
        super().__init__()
        self.database = database
        self.bridge = Bridge()
        self.bridge.notification.connect(self._notify)
        self.bridge.activate.connect(self.show_window)
        self.engine: SchedulerEngine | None = None
        self.tray: QSystemTrayIcon | None = None
        self.quitting = False
        self.syncing_detail_headers = False
        self._detail_source = {"today_logs": [], "logs": [], "today_future": [], "future": []}
        self.layout_save_timer = QTimer(self)
        self.layout_save_timer.setSingleShot(True)
        self.layout_save_timer.setInterval(400)
        self.layout_save_timer.timeout.connect(self._save_layout)
        self.setWindowTitle("TTask 定时任务")
        self.setWindowIcon(QIcon(str(resource_path("assets/clock.ico"))))
        self.resize(960, 600)
        self.setMinimumSize(820, 510)
        self._build_ui()
        if start_services:
            self.engine = SchedulerEngine(database, lambda t, m: self.bridge.notification.emit(t, m))
            self.engine.start()
            self._create_tray()
            self._start_ipc_server()
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.refresh)
            self.timer.start(5000)
        self.refresh()

    def _build_ui(self):
        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        actions = [
            ("＋ 新建", self.create_task, "primaryTool"),
            ("✎ 编辑", self.edit_task, ""),
            ("▣ 复制", self.copy_task, ""),
            ("✕ 删除", self.delete_task, "dangerTool"),
            ("▶ 立即运行", self.run_now, ""),
            ("◷ 预览", self.preview, ""),
        ]
        for text, slot, object_name in actions:
            action = QAction(text, self)
            action.triggered.connect(slot)
            toolbar.addAction(action)
            if object_name:
                toolbar.widgetForAction(action).setObjectName(object_name)
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().Policy.Expanding, spacer.sizePolicy().Policy.Preferred)
        toolbar.addWidget(spacer)
        for text, slot in (("▦ 节假日", self.holidays), ("⚙ 选项", self.options)):
            action = QAction(text, self)
            action.triggered.connect(slot)
            toolbar.addAction(action)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索任务…")
        self.search.setFixedWidth(220)
        self.search.textChanged.connect(self.refresh)
        toolbar.addWidget(self.search)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(9, 7, 9, 6)
        metrics = QHBoxLayout()
        metrics.setSpacing(8)
        self.metric_tasks, task_metric = self._metric("任务总数")
        self.metric_enabled, enabled_metric = self._metric("正在运行")
        self.metric_today, today_metric = self._metric("今日待执行")
        metrics.addWidget(task_metric)
        metrics.addWidget(enabled_metric)
        metrics.addWidget(today_metric)
        metrics.addStretch(2)
        outer.addLayout(metrics)
        self.main_splitter = QSplitter(Qt.Vertical)
        outer.addWidget(self.main_splitter)
        self.tasks = self._table(["任务", "参数", "计划", "下次运行", "启用开关", "状态", "动作"])
        self.tasks.verticalHeader().setDefaultSectionSize(38)
        self._size_task_columns()
        task_card, _ = self._card("任务列表", self.tasks)
        self.main_splitter.addWidget(task_card)

        detail_tools = QHBoxLayout()
        detail_tools.setContentsMargins(2, 0, 2, 2)
        self.detail_task_filter = QComboBox()
        self.detail_task_filter.setMinimumWidth(140)
        self.detail_date_filter = QComboBox()
        self.detail_date_filter.addItems(["全部日期", "今天", "近 7 天", "近 30 天"])
        self.detail_status_filter = QComboBox()
        self.detail_status_filter.addItems(["全部状态", "成功", "失败", "运行中", "异常中断"])
        self.detail_exception_only = QCheckBox("只看异常")
        self.reset_columns_button = QPushButton("恢复默认列宽")
        detail_tools.addWidget(QLabel("任务"))
        detail_tools.addWidget(self.detail_task_filter)
        detail_tools.addWidget(QLabel("日期"))
        detail_tools.addWidget(self.detail_date_filter)
        detail_tools.addWidget(self.detail_status_filter)
        detail_tools.addWidget(self.detail_exception_only)
        detail_tools.addStretch()
        detail_tools.addWidget(self.reset_columns_button)
        outer.addLayout(detail_tools)
        self.detail_tabs = QTabWidget()
        self.today_history = self._table(["序号", "任务", "执行时间", "结果", "信息"])
        self.today_upcoming = self._table(["序号", "任务", "计划", "预计执行时间", "动作"])
        self.history = self._table(["序号", "任务", "执行时间", "结果", "信息"])
        self.upcoming = self._table(["序号", "任务", "计划", "预计执行时间", "动作"])
        self.detail_tables = (
            self.today_history, self.today_upcoming, self.history, self.upcoming,
        )
        for table in self.detail_tables:
            self._size_detail_columns(table)
        for table in (self.today_history, self.history):
            table.cellDoubleClicked.connect(
                lambda row, _column, source=table: self._log_details(source, row)
            )
        for table in (self.today_upcoming, self.upcoming):
            table.verticalHeader().setDefaultSectionSize(34)
        self.detail_tabs.addTab(self.today_history, "今日已执行")
        self.detail_tabs.addTab(self.today_upcoming, "今日待执行")
        self.detail_tabs.addTab(self.history, "全部执行记录")
        self.detail_tabs.addTab(self.upcoming, "未来执行计划")
        self.clear_records_button = QPushButton("清空当前记录")
        self.clear_records_button.clicked.connect(self.clear_logs)
        self.detail_tabs.setCornerWidget(self.clear_records_button, Qt.TopRightCorner)
        self.main_splitter.addWidget(self.detail_tabs)
        self.main_splitter.setSizes([310, 330])
        self.main_splitter.setStretchFactor(0, 4)
        self.main_splitter.setStretchFactor(1, 5)
        self.setCentralWidget(central)
        self.tasks.itemSelectionChanged.connect(self.refresh_details)
        self.tasks.cellDoubleClicked.connect(lambda _r, _c: self.edit_task())
        self.tasks.cellClicked.connect(self._task_clicked)
        self.tasks.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tasks.customContextMenuRequested.connect(self._task_context_menu)
        for table in self.detail_tables:
            table.setContextMenuPolicy(Qt.CustomContextMenu)
            table.customContextMenuRequested.connect(
                lambda pos, source=table: self._detail_context_menu(source, pos)
            )
        for control in (
            self.detail_task_filter, self.detail_date_filter, self.detail_status_filter,
        ):
            control.currentIndexChanged.connect(self._apply_detail_filters)
        self.detail_exception_only.toggled.connect(self._apply_detail_filters)
        self.reset_columns_button.clicked.connect(self._reset_column_widths)
        self.author_label = QLabel(f"TTask v{APP_VERSION} · 作者：{APP_AUTHOR}")
        self.author_label.setStyleSheet("color:#dbe7f5; padding:0 8px;")
        self.statusBar().addPermanentWidget(self.author_label)
        self._restore_layout()
        for table in (self.tasks, *self.detail_tables):
            table.horizontalHeader().sectionResized.connect(self._queue_layout_save)
            table.horizontalHeader().sectionMoved.connect(self._queue_layout_save)
        for table in self.detail_tables:
            table.horizontalHeader().sectionResized.connect(
                lambda logical, _old, size, source=table: self._sync_detail_headers(source, logical, size)
            )
            table.horizontalHeader().sectionMoved.connect(
                lambda _logical, _old, _new, source=table: self._sync_detail_header_order(source)
            )
        self.main_splitter.splitterMoved.connect(self._queue_layout_save)
        self.detail_tabs.currentChanged.connect(self._queue_layout_save)
        self.detail_tabs.currentChanged.connect(self._detail_tab_changed)
        self._detail_tab_changed(self.detail_tabs.currentIndex())
        self.statusBar().showMessage("就绪")

    def _table(self, headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(28)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.horizontalHeader().setSectionsMovable(True)
        table.horizontalHeader().setStretchLastSection(False)
        return table

    @staticmethod
    def _metric(label):
        card = QFrame()
        card.setObjectName("metricCard")
        card.setFixedSize(126, 50)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 5, 12, 5)
        value = QLabel("0")
        value.setObjectName("metricValue")
        caption = QLabel(label)
        caption.setObjectName("metricLabel")
        layout.addWidget(value)
        layout.addWidget(caption)
        layout.addStretch()
        return value, card

    def _size_task_columns(self):
        header = self.tasks.horizontalHeader()
        for column in range(7):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
        for column, width in enumerate((155, 205, 235, 155, 82, 92, 105)):
            self.tasks.setColumnWidth(column, width)

    def _size_detail_columns(self, table):
        header = table.horizontalHeader()
        for column in range(5):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
        for column, width in enumerate((55, 170, 260, 185, 220)):
            table.setColumnWidth(column, width)

    def _sync_detail_headers(self, source, logical, size):
        if self.syncing_detail_headers:
            return
        self.syncing_detail_headers = True
        try:
            for table in self.detail_tables:
                if table is not source:
                    table.horizontalHeader().resizeSection(logical, size)
        finally:
            self.syncing_detail_headers = False

    def _sync_detail_header_order(self, source):
        if self.syncing_detail_headers:
            return
        self.syncing_detail_headers = True
        try:
            state = source.horizontalHeader().saveState()
            for table in self.detail_tables:
                if table is not source:
                    table.horizontalHeader().restoreState(state)
        finally:
            self.syncing_detail_headers = False

    def _detail_tab_changed(self, index):
        self.clear_records_button.setVisible(index in (0, 2))
        self.detail_status_filter.setVisible(index in (0, 2))
        self.detail_exception_only.setVisible(index in (0, 2))

    def _queue_layout_save(self, *_args):
        self.layout_save_timer.start()

    @staticmethod
    def _encode_state(value: QByteArray) -> str:
        return bytes(value.toBase64()).decode("ascii")

    @staticmethod
    def _decode_state(value: str) -> QByteArray:
        return QByteArray.fromBase64(value.encode("ascii"))

    def _save_layout(self):
        self.database.set_settings({
            "ui_header_tasks": self._encode_state(self.tasks.horizontalHeader().saveState()),
            "ui_header_details": self._encode_state(self.history.horizontalHeader().saveState()),
            "ui_splitter_main": self._encode_state(self.main_splitter.saveState()),
            "ui_detail_tab": str(self.detail_tabs.currentIndex()),
        })

    def _restore_layout(self):
        for key, target in (
            ("ui_header_tasks", self.tasks.horizontalHeader()),
            ("ui_splitter_main", self.main_splitter),
        ):
            value = self.database.get_setting(key)
            if value:
                target.restoreState(self._decode_state(value))
        detail_state = self.database.get_setting("ui_header_details")
        if detail_state:
            decoded = self._decode_state(detail_state)
            for table in self.detail_tables:
                table.horizontalHeader().restoreState(decoded)
        try:
            self.detail_tabs.setCurrentIndex(int(self.database.get_setting("ui_detail_tab", "0")))
        except ValueError:
            self.detail_tabs.setCurrentIndex(0)

    def _card(self, title, content):
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(7, 5, 7, 7)
        head = QHBoxLayout()
        label = QLabel(title)
        label.setObjectName("sectionTitle")
        head.addWidget(label)
        head.addStretch()
        layout.addLayout(head)
        layout.addWidget(content)
        return card, head

    def selected_task(self):
        rows = self.tasks.selectionModel().selectedRows()
        return self.database.get_task(int(self.tasks.item(rows[0].row(), 0).data(Qt.UserRole))) if rows else None

    def holidays(self):
        HolidayManagerDialog(self).exec()
        self.refresh()

    @staticmethod
    def _summary(task):
        if task.schedule_type == ScheduleType.ONCE:
            title = "单次执行"
            detail = f"{task.run_date}  {task.time_start}"
        elif task.schedule_type == ScheduleType.INTERVAL:
            title = "固定间隔"
            detail = f"每 {task.interval_seconds} 秒"
        else:
            title = "随机时段" if task.schedule_type == ScheduleType.RANDOM_WINDOW else "定点执行"
            windows = task.time_windows or [[task.time_start] + ([task.time_end] if task.time_end else [])]
            detail = "；".join(v[0] if len(v) == 1 else f"{v[0]}—{v[1]}" for v in windows)
        if task.workdays_only and task.schedule_type != ScheduleType.ONCE:
            title += " · 工作日"
        schedule = f"{title}\n{detail}"
        return schedule, TaskDialog._payload(task)

    def _set_row(self, table, row, values, color, centered=(), cell_colors=None):
        table.insertRow(row)
        cell_colors = cell_colors or {}
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setBackground(QColor(cell_colors.get(column, color)))
            item.setToolTip(str(value))
            item.setTextAlignment(
                Qt.AlignCenter if column in centered else Qt.AlignVCenter | Qt.AlignLeft
            )
            table.setItem(row, column, item)

    @staticmethod
    def _compact_time(value: datetime, today: date | None = None) -> str:
        today = today or datetime.now().date()
        if value.date() == today:
            return value.strftime("今天 %H:%M:%S")
        if value.date() == today + timedelta(days=1):
            return value.strftime("明天 %H:%M")
        return value.strftime("%m-%d %H:%M")

    def refresh(self):
        selected = self.selected_task()
        selected_id = selected.id if selected else None
        self.tasks.blockSignals(True)
        self.tasks.setRowCount(0)
        query = self.search.text().strip().lower()
        all_tasks = self.database.list_tasks()
        selected_filter = self.detail_task_filter.currentData()
        self.detail_task_filter.blockSignals(True)
        self.detail_task_filter.clear()
        self.detail_task_filter.addItem("全部任务", None)
        for filter_task in all_tasks:
            self.detail_task_filter.addItem(filter_task.name, filter_task.id)
        index = self.detail_task_filter.findData(selected_filter)
        self.detail_task_filter.setCurrentIndex(max(0, index))
        self.detail_task_filter.blockSignals(False)
        now = datetime.now()
        today_pending = sum(count_occurrences_on_date(task, now.date(), now) for task in all_tasks)
        self.metric_tasks.setText(str(len(all_tasks)))
        self.metric_enabled.setText(str(sum(task.enabled for task in all_tasks)))
        self.metric_today.setText(str(today_pending))
        latest_by_task = {}
        for latest in self.database.list_logs(200):
            latest_by_task.setdefault(latest["task_id"], latest)
        shown = 0
        for task in all_tasks:
            schedule, payload = self._summary(task)
            nxt = next_occurrence(task, now)
            values = [
                task.name, payload, schedule,
                nxt.strftime("%Y-%m-%d %H:%M:%S") if nxt else "—",
                "● 开" if task.enabled else "○ 关",
                self._task_status(task, nxt, now, latest_by_task.get(task.id)),
                ACTION_LABELS[task.action_type],
            ]
            if query and query not in " ".join(values).lower():
                continue
            color = "#ffffff" if shown % 2 == 0 else "#f8fafc"
            if not task.enabled:
                color = "#f1f5f9" if shown % 2 == 0 else "#f6f7f9"
            status_text = values[5]
            status_color = {
                "执行中": "#ede9fe", "上次失败": "#fee2e2", "异常中断": "#ffedd5",
                "即将执行": "#dbeafe", "等待中": "#dcfce7",
            }.get(status_text, "#e2e8f0")
            if task.enabled and nxt and (nxt - now).total_seconds() <= 1800 and status_text == "等待中":
                status_color = "#dbeafe"
            self._set_row(self.tasks, shown, values, color, centered=(0, 2, 3, 4, 5, 6), cell_colors={5: status_color})
            self.tasks.item(shown, 0).setData(Qt.UserRole, task.id)
            switch_holder = QWidget()
            switch_holder.setStyleSheet(f"background:{color};")
            switch_layout = QHBoxLayout(switch_holder)
            switch_layout.setContentsMargins(0, 0, 0, 0)
            switch_layout.setAlignment(Qt.AlignCenter)
            switch = ToggleSwitch(task.enabled)
            switch.toggled.connect(
                lambda checked, task_id=task.id: self._set_task_enabled(task_id, checked)
            )
            switch_layout.addWidget(switch)
            self.tasks.setCellWidget(shown, 4, switch_holder)
            if task.id == selected_id:
                self.tasks.selectRow(shown)
            shown += 1
        if not self.tasks.selectedItems() and shown:
            self.tasks.selectRow(0)
        self.tasks.blockSignals(False)
        self.refresh_details()
        service_running = bool(self.engine and self.engine.is_alive)
        service_text = "● 调度服务运行中" if service_running else "● 调度服务异常" if self.engine else "○ 界面预览模式"
        if self.engine and self.engine.last_error:
            service_text += f" · {self.engine.last_error}"
        self.statusBar().showMessage(
            f"{len(all_tasks)} 个任务 · {sum(t.enabled for t in all_tasks)} 个启用"
            f"　　　　　　　　　{service_text}"
        )

    def refresh_details(self):
        self.today_history.setRowCount(0)
        self.today_upcoming.setRowCount(0)
        self.history.setRowCount(0)
        self.upcoming.setRowCount(0)
        now = datetime.now()
        all_logs = self.database.list_logs(None)
        logs = all_logs
        today_logs = []
        for log in all_logs:
            try:
                if datetime.fromisoformat(log["started_at"]).date() == now.date():
                    today_logs.append(log)
            except (TypeError, ValueError):
                continue
        all_tasks = self.database.list_tasks()
        tasks = all_tasks
        future = []
        for current in tasks:
            if current and current.enabled:
                schedule, _ = self._summary(current)
                future.extend((value, current, schedule) for value in upcoming_occurrences(current, now, 20))
        future = sorted(future, key=lambda value: value[0])[:200]
        all_future = []
        for current in all_tasks:
            if current.enabled:
                schedule, _ = self._summary(current)
                all_future.extend(
                    (value, current, schedule)
                    for value in upcoming_occurrences(current, now, 20)
                )
        today_future = sorted(
            (item for item in all_future if item[0].date() == now.date()),
            key=lambda value: value[0],
        )[:200]
        today_pending_total = sum(
            count_occurrences_on_date(task, now.date(), now) for task in all_tasks
        )
        self._detail_source = {
            "today_logs": today_logs, "logs": logs,
            "today_future": today_future, "future": future,
            "today_pending_total": today_pending_total,
        }
        self._apply_detail_filters()

    def _apply_detail_filters(self, *_args):
        task_id = self.detail_task_filter.currentData()
        task_name = self.detail_task_filter.currentText() if task_id is not None else None
        date_mode = self.detail_date_filter.currentText()
        status_text = self.detail_status_filter.currentText()
        status_map = {"成功": "success", "失败": "failed", "运行中": "running", "异常中断": "interrupted"}
        now = datetime.now()

        def in_range(value):
            try:
                day = value if isinstance(value, date) else datetime.fromisoformat(value).date()
            except (TypeError, ValueError):
                return False
            if date_mode == "今天":
                return day == now.date()
            days = 7 if date_mode == "近 7 天" else 30 if date_mode == "近 30 天" else None
            return days is None or abs((day - now.date()).days) < days

        def filter_logs(values):
            result = [v for v in values if (task_id is None or v["task_id"] == task_id) and in_range(v["started_at"])]
            if self.detail_exception_only.isChecked():
                result = [v for v in result if v["status"] in ("failed", "interrupted")]
            elif status_text in status_map:
                result = [v for v in result if v["status"] == status_map[status_text]]
            return result

        def filter_future(values):
            return [v for v in values if (task_id is None or v[1].id == task_id) and in_range(v[0].date())]

        today_logs = filter_logs(self._detail_source["today_logs"])
        logs = filter_logs(self._detail_source["logs"])
        today_future = filter_future(self._detail_source["today_future"])
        future = filter_future(self._detail_source["future"])
        for table in self.detail_tables:
            table.setRowCount(0)
        self._fill_log_table(self.today_history, today_logs)
        self._fill_log_table(self.history, logs)
        self._fill_upcoming_table(self.today_upcoming, today_future)
        self._fill_upcoming_table(self.upcoming, future)
        if date_mode in ("全部日期", "今天"):
            if task_id is None:
                pending_count = self._detail_source.get("today_pending_total", len(today_future))
            else:
                selected_task = self.database.get_task(int(task_id))
                pending_count = count_occurrences_on_date(selected_task, now.date(), now) if selected_task else 0
        else:
            pending_count = len(today_future)
        labels = (
            ("今日已执行", len(today_logs)), ("今日待执行", pending_count),
            ("全部执行记录", len(logs)), ("未来执行计划", len(future)),
        )
        for index, (label, count) in enumerate(labels):
            self.detail_tabs.setTabText(index, f"{label}   {count}")

    def _fill_log_table(self, table, logs):
        if not logs:
            self._show_empty(table, "暂无执行记录", "任务运行后，执行结果会显示在这里")
            return
        for row, log in enumerate(logs[:200]):
            color = "#fff1f2" if log["status"] in ("failed", "interrupted") else ("#ffffff" if row % 2 == 0 else "#f8fafc")
            labels = {"success": "成功", "failed": "失败", "running": "运行中", "interrupted": "异常中断"}
            result_color = {
                "success": "#dcfce7", "failed": "#fee2e2",
                "running": "#dbeafe", "interrupted": "#ffedd5",
            }.get(log["status"], color)
            try:
                display_time = self._compact_time(datetime.fromisoformat(log["started_at"]))
            except (TypeError, ValueError):
                display_time = format_datetime(log["started_at"])
            message = (log["message"] or "").replace("\n", " ")
            self._set_row(table, row, [
                row + 1, log["task_name"], display_time,
                labels.get(log["status"], log["status"]), message[:90] + ("…" if len(message) > 90 else ""),
            ], color, centered=(0, 1, 2, 3), cell_colors={3: result_color})
            for column in range(table.columnCount()):
                table.item(row, column).setData(Qt.UserRole, dict(log))
            table.item(row, 2).setToolTip(format_datetime(log["started_at"]))
            table.item(row, 4).setToolTip(message or "无输出")

    def _fill_upcoming_table(self, table, future):
        if not future:
            self._show_empty(table, "暂无待执行计划", "请检查任务启用状态、日期规则和筛选条件")
            return
        last_group = None
        display_row = 0
        sequence = 0
        for value, current, schedule in future[:200]:
            group = self._date_group(value.date())
            if group != last_group:
                table.insertRow(display_row)
                group_item = QTableWidgetItem(group)
                group_item.setBackground(QColor("#e8eef8"))
                group_item.setForeground(QColor("#40516c"))
                group_item.setFont(QFont(group_item.font().family(), group_item.font().pointSize(), QFont.DemiBold))
                group_item.setData(Qt.UserRole + 1, "group")
                table.setItem(display_row, 0, group_item)
                table.setSpan(display_row, 0, 1, 5)
                table.setRowHeight(display_row, 27)
                display_row += 1
                last_group = group
            row = display_row
            sequence += 1
            color = "#ffffff" if row % 2 == 0 else "#f8fafc"
            seconds = (value - datetime.now()).total_seconds()
            time_color = "#ffedd5" if seconds <= 0 else "#dbeafe" if seconds <= 1800 else "#eef4ff"
            self._set_row(table, row, [
                sequence, current.name, schedule, self._compact_time(value),
                ACTION_LABELS[current.action_type],
            ], color, centered=(0, 1, 2, 3, 4), cell_colors={3: time_color})
            for column in range(table.columnCount()):
                table.item(row, column).setData(Qt.UserRole, current.id)
            table.item(row, 3).setToolTip(value.strftime("%Y-%m-%d %H:%M:%S"))
            display_row += 1

    @staticmethod
    def _date_group(day):
        today = datetime.now().date()
        if day == today:
            return "今天"
        if day == today + timedelta(days=1):
            return "明天"
        if day == today + timedelta(days=2):
            return "后天"
        return day.strftime("%Y年%m月%d日  %A")

    @staticmethod
    def _task_status(task, nxt, now, latest=None):
        if not task.enabled:
            return "已停用"
        if latest and latest["status"] == "running":
            return "执行中"
        if latest and latest["status"] == "failed":
            return "上次失败"
        if latest and latest["status"] == "interrupted":
            return "异常中断"
        if nxt is None:
            return "无计划"
        return "即将执行" if 0 <= (nxt - now).total_seconds() <= 1800 else "等待中"

    @staticmethod
    def _show_empty(table, title, hint):
        table.insertRow(0)
        item = QTableWidgetItem(f"{title}\n{hint}")
        item.setTextAlignment(Qt.AlignCenter)
        item.setForeground(QColor("#7b8ba3"))
        item.setBackground(QColor("#fbfcfe"))
        item.setData(Qt.UserRole + 1, "empty")
        table.setItem(0, 0, item)
        table.setSpan(0, 0, 1, table.columnCount())
        table.setRowHeight(0, 66)

    def _reset_column_widths(self):
        self.syncing_detail_headers = True
        try:
            self._size_task_columns()
            for table in self.detail_tables:
                self._size_detail_columns(table)
        finally:
            self.syncing_detail_headers = False
        self._save_layout()
        self.statusBar().showMessage("已恢复默认列宽")

    def _task_context_menu(self, pos):
        row = self.tasks.rowAt(pos.y())
        if row < 0:
            return
        self.tasks.selectRow(row)
        menu = QMenu(self)
        run_action = menu.addAction("▶ 立即执行")
        edit_action = menu.addAction("✎ 编辑任务")
        menu.addSeparator()
        copy_action = menu.addAction("▣ 复制任务")
        delete_action = menu.addAction("✕ 删除任务")
        chosen = menu.exec(self.tasks.viewport().mapToGlobal(pos))
        if chosen == run_action:
            self.run_now()
        elif chosen == edit_action:
            self.edit_task()
        elif chosen == copy_action:
            self.copy_task()
        elif chosen == delete_action:
            self.delete_task()

    def _detail_context_menu(self, table, pos):
        row = table.rowAt(pos.y())
        if row < 0 or not table.item(row, 0) or table.item(row, 0).data(Qt.UserRole + 1):
            return
        table.selectRow(row)
        menu = QMenu(self)
        if table in (self.today_history, self.history):
            details_action = menu.addAction("查看完整详情")
            copy_action = menu.addAction("复制错误/信息")
            chosen = menu.exec(table.viewport().mapToGlobal(pos))
            if chosen == details_action:
                self._log_details(table, row)
            elif chosen == copy_action:
                data = table.item(row, 0).data(Qt.UserRole) or {}
                QApplication.clipboard().setText(data.get("message", ""))
                self.statusBar().showMessage("信息已复制")
            return
        task_id = table.item(row, 0).data(Qt.UserRole)
        task = self.database.get_task(int(task_id)) if task_id else None
        run_action = menu.addAction("▶ 立即执行")
        edit_action = menu.addAction("✎ 编辑任务")
        locate_action = menu.addAction("定位到任务")
        chosen = menu.exec(table.viewport().mapToGlobal(pos))
        if not task:
            return
        self._select_task_by_id(task.id)
        if chosen == run_action:
            self.run_now()
        elif chosen == edit_action:
            self.edit_task()
        elif chosen == locate_action:
            self.tasks.setFocus()

    def _select_task_by_id(self, task_id):
        for row in range(self.tasks.rowCount()):
            item = self.tasks.item(row, 0)
            if item and item.data(Qt.UserRole) == task_id:
                self.tasks.selectRow(row)
                self.tasks.scrollToItem(item, QAbstractItemView.PositionAtCenter)
                break

    def _dialog(self, task=None):
        dialog = TaskDialog(self, task)
        return dialog.result_task if dialog.exec() == QDialog.Accepted else None

    def create_task(self):
        task = self._dialog()
        if task:
            self.database.save_task(task)
            self.refresh()

    def edit_task(self):
        task = self.selected_task()
        if task:
            result = self._dialog(task)
            if result:
                self.database.save_task(result)
                self.refresh()

    def copy_task(self):
        task = self.selected_task()
        if task:
            task = copy.deepcopy(task)
            task.id = None
            task.name += " - 副本"
            result = self._dialog(task)
            if result:
                result.id = None
                self.database.save_task(result)
                self.refresh()

    def delete_task(self):
        task = self.selected_task()
        if task and QMessageBox.question(self, "删除任务", f"确定删除“{task.name}”吗？") == QMessageBox.Yes:
            self.database.delete_task(task.id)
            self.refresh()

    def _task_clicked(self, row, column):
        return

    def _set_task_enabled(self, task_id, enabled):
        self.database.set_enabled(task_id, enabled)
        self.refresh()
        self.statusBar().showMessage("任务已启用" if enabled else "任务已停用")

    def run_now(self):
        task = self.selected_task()
        if not task:
            QMessageBox.information(self, "立即运行", "请先选择任务。")
        elif self.engine and self.engine.run_now(task):
            self.statusBar().showMessage(f"任务“{task.name}”已提交执行")
            QTimer.singleShot(800, self.refresh_details)

    def preview(self):
        task = self.selected_task()
        if task:
            PreviewDialog(
                task, upcoming_occurrences(task, datetime.now(), 10), self
            ).exec()
        else:
            QMessageBox.information(self, "预览执行计划", "请先在任务列表中选择一个任务。")

    def clear_logs(self):
        if QMessageBox.question(
            self, "清空执行记录", "确定清空全部任务的执行记录吗？此操作无法撤销。"
        ) == QMessageBox.Yes:
            self.database.clear_logs()
            self.refresh()

    def _log_details(self, table, row):
        source = table.item(row, 0).data(Qt.UserRole) if table.item(row, 0) else None
        if source:
            QMessageBox.information(
                self,
                "执行记录详情",
                f"任务：{source.get('task_name', '')}\n"
                f"执行时间：{format_datetime(source.get('started_at'))}\n"
                f"结束时间：{format_datetime(source.get('finished_at'))}\n"
                f"结果：{source.get('status', '')}\n\n"
                f"信息：\n{source.get('message') or '无输出'}",
            )
            return
        values = [table.item(row, col).text() for col in range(table.columnCount())]
        QMessageBox.information(
            self,
            "执行记录详情",
            f"序号：{values[0]}\n任务：{values[1]}\n执行时间：{values[2]}\n"
            f"结果：{values[3]}\n\n信息：\n{values[4] or '无输出'}",
        )

    def options(self):
        OptionsDialog(self, self.database).exec()

    def _create_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = self.tray.contextMenu() or __import__("PySide6.QtWidgets", fromlist=["QMenu"]).QMenu()
        show_action = menu.addAction("打开主界面")
        show_action.triggered.connect(self.show_window)
        menu.addSeparator()
        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.show_window()
            if reason == QSystemTrayIcon.DoubleClick else None
        )
        self.tray.show()

    def _notify(self, title, message):
        if self.tray and self.database.get_setting("notifications", "1") == "1":
            self.tray.showMessage(title, message, self.windowIcon())

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _start_ipc_server(self):
        def serve():
            server = socket.socket()
            try:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind(("127.0.0.1", 47653))
                server.listen()
                while True:
                    connection, _ = server.accept()
                    with connection:
                        connection.settimeout(1)
                        if connection.recv(64) == IPC_REQUEST:
                            connection.sendall(IPC_RESPONSE)
                            self.bridge.activate.emit()
            except OSError:
                pass
        threading.Thread(target=serve, daemon=True).start()

    def closeEvent(self, event):
        self._save_layout()
        if self.quitting:
            event.accept()
        elif self.database.get_setting("close_mode", "tray") == "exit":
            event.accept() if self.quit_app() else event.ignore()
        elif self.tray:
            self.hide()
            event.ignore()
            self.tray.showMessage("TTask", "程序仍在后台运行，双击时钟图标可恢复。")
        else:
            event.accept()

    def quit_app(self):
        wait_for_tasks = False
        force = False
        if self.engine and self.engine.active_count:
            box = QMessageBox(self)
            box.setWindowTitle("任务仍在执行")
            box.setText(f"当前有 {self.engine.active_count} 个任务正在执行。")
            box.setInformativeText("可以等待任务完成后退出，或强制终止正在运行的命令。")
            wait_button = box.addButton("等待完成并退出", QMessageBox.AcceptRole)
            force_button = box.addButton("强制退出", QMessageBox.DestructiveRole)
            cancel_button = box.addButton("取消", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() == cancel_button:
                return False
            wait_for_tasks = box.clickedButton() == wait_button
            force = box.clickedButton() == force_button
        self._save_layout()
        self.quitting = True
        if self.engine:
            self.engine.stop(wait=wait_for_tasks, force=force)
        if self.tray:
            self.tray.hide()
        QApplication.quit()
        return True


def run(database_path: Path) -> int:
    try:
        probe = socket.create_connection(("127.0.0.1", 47653), timeout=0.3)
        with probe:
            probe.settimeout(0.5)
            probe.sendall(IPC_REQUEST)
            if probe.recv(64) == IPC_RESPONSE:
                return 0
    except OSError:
        pass
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    icon = QIcon(str(resource_path("assets/clock.ico")))
    app.setWindowIcon(icon)
    try:
        upgrade_existing_autostart()
    except OSError:
        pass
    window = MainWindow(Database(database_path))
    start_in_tray = "--tray" in sys.argv or "--background" in sys.argv
    if not start_in_tray:
        window.show()
    code = app.exec()
    if window.engine and not window.quitting:
        window.engine.stop()
    return code
