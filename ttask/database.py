from __future__ import annotations

import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .models import ActionType, ScheduleType, Task


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    schedule_type TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    time_start TEXT NOT NULL,
                    time_end TEXT,
                    time_windows TEXT NOT NULL DEFAULT '[]',
                    run_date TEXT,
                    interval_seconds INTEGER,
                    anchor_at TEXT,
                    weekdays TEXT NOT NULL,
                    workdays_only INTEGER NOT NULL DEFAULT 0,
                    weekend_overrides TEXT NOT NULL DEFAULT '[]',
                    excluded_dates TEXT NOT NULL DEFAULT '[]',
                    action_config TEXT NOT NULL DEFAULT '{}',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS execution_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER,
                    scheduled_at TEXT,
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS ux_log_occurrence
                ON execution_logs(task_id, scheduled_at)
                WHERE scheduled_at IS NOT NULL AND status IN ('running', 'success', 'failed');
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            columns = {row["name"] for row in db.execute("PRAGMA table_info(tasks)")}
            if "excluded_dates" not in columns:
                db.execute("ALTER TABLE tasks ADD COLUMN excluded_dates TEXT NOT NULL DEFAULT '[]'")
            if "workdays_only" not in columns:
                db.execute("ALTER TABLE tasks ADD COLUMN workdays_only INTEGER NOT NULL DEFAULT 0")
            for name, definition in (
                ("run_date", "TEXT"),
                ("interval_seconds", "INTEGER"),
                ("anchor_at", "TEXT"),
                ("time_windows", "TEXT NOT NULL DEFAULT '[]'"),
            ):
                if name not in columns:
                    db.execute(f"ALTER TABLE tasks ADD COLUMN {name} {definition}")
                    columns.add(name)
            db.execute(
                """UPDATE execution_logs SET status='interrupted',
                message=CASE WHEN message='' THEN '软件异常退出，任务执行被中断' ELSE message END,
                finished_at=? WHERE status='running'""",
                (datetime.now().isoformat(timespec="seconds"),),
            )

    def save_task(self, task: Task) -> Task:
        task.validate()
        values = (
            task.name,
            task.schedule_type.value,
            task.action_type.value,
            task.time_start,
            task.time_end,
            json.dumps(task.time_windows, ensure_ascii=False),
            task.run_date,
            task.interval_seconds,
            task.anchor_at,
            json.dumps(task.weekdays),
            int(task.workdays_only),
            json.dumps(task.weekend_overrides, ensure_ascii=False),
            json.dumps(task.excluded_dates, ensure_ascii=False),
            json.dumps(task.action_config, ensure_ascii=False),
            int(task.enabled),
        )
        with self.connect() as db:
            if task.id is None:
                cursor = db.execute(
                    """INSERT INTO tasks
                    (name,schedule_type,action_type,time_start,time_end,time_windows,run_date,
                     interval_seconds,anchor_at,weekdays,workdays_only,
                     weekend_overrides,excluded_dates,action_config,enabled)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    values,
                )
                task.id = cursor.lastrowid
            else:
                db.execute(
                    """UPDATE tasks SET name=?,schedule_type=?,action_type=?,
                    time_start=?,time_end=?,time_windows=?,run_date=?,interval_seconds=?,anchor_at=?,
                    weekdays=?,workdays_only=?,weekend_overrides=?,excluded_dates=?,
                    action_config=?,enabled=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    values + (task.id,),
                )
        return task

    def list_tasks(self) -> list[Task]:
        with self.connect() as db:
            return [self._task(row) for row in db.execute("SELECT * FROM tasks ORDER BY id")]

    def get_task(self, task_id: int) -> Task | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return self._task(row) if row else None

    def delete_task(self, task_id: int) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM tasks WHERE id=?", (task_id,))

    def set_enabled(self, task_id: int, enabled: bool) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE tasks SET enabled=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (int(enabled), task_id),
            )

    def claim_occurrence(self, task_id: int, scheduled_at: str) -> int | None:
        try:
            with self.connect() as db:
                cursor = db.execute(
                    """INSERT INTO execution_logs(task_id,scheduled_at,started_at,status)
                    VALUES (?,?,?,'running')""",
                    (task_id, scheduled_at, datetime.now().isoformat(timespec="seconds")),
                )
                return cursor.lastrowid
        except sqlite3.IntegrityError:
            return None

    def finish_log(self, log_id: int, status: str, message: str = "") -> None:
        with self.connect() as db:
            db.execute(
                """UPDATE execution_logs SET status=?,message=?,
                finished_at=? WHERE id=?""",
                (status, message[-10000:], datetime.now().isoformat(timespec="seconds"), log_id),
            )

    def list_logs(self, limit: int | None = 200, task_id: int | None = None) -> list[sqlite3.Row]:
        with self.connect() as db:
            where = "WHERE l.task_id=?" if task_id is not None else ""
            parameters: tuple = (task_id,) if task_id is not None else ()
            limit_sql = " LIMIT ?" if limit is not None else ""
            if limit is not None:
                parameters += (limit,)
            return list(
                db.execute(
                    """SELECT l.*, COALESCE(t.name, '已删除任务') AS task_name
                    FROM execution_logs l
                    LEFT JOIN tasks t ON t.id=l.task_id
                    """
                    + where
                    + " ORDER BY l.id DESC"
                    + limit_sql,
                    parameters,
                )
            )

    def count_logs(self, task_id: int | None = None) -> int:
        with self.connect() as db:
            if task_id is None:
                row = db.execute("SELECT COUNT(*) AS count FROM execution_logs").fetchone()
            else:
                row = db.execute(
                    "SELECT COUNT(*) AS count FROM execution_logs WHERE task_id=?", (task_id,)
                ).fetchone()
        return int(row["count"])

    def consecutive_failures(self, task_id: int, limit: int) -> int:
        with self.connect() as db:
            rows = db.execute(
                """SELECT status FROM execution_logs WHERE task_id=?
                ORDER BY id DESC LIMIT ?""",
                (task_id, limit),
            ).fetchall()
        count = 0
        for row in rows:
            if row["status"] != "failed":
                break
            count += 1
        return count

    def clear_logs(self, task_id: int | None = None) -> None:
        with self.connect() as db:
            if task_id is None:
                db.execute("DELETE FROM execution_logs")
            else:
                db.execute("DELETE FROM execution_logs WHERE task_id=?", (task_id,))

    def get_setting(self, key: str, default: str = "") -> str:
        with self.connect() as db:
            row = db.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_settings(self, values: dict[str, str]) -> None:
        with self.connect() as db:
            db.executemany(
                """INSERT INTO app_settings(key,value) VALUES (?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                values.items(),
            )

    def delete_settings(self, keys: list[str]) -> None:
        if not keys:
            return
        with self.connect() as db:
            db.executemany("DELETE FROM app_settings WHERE key=?", ((key,) for key in keys))

    def backup_to(self, destination: str | Path) -> None:
        """Create a transactionally consistent SQLite backup."""
        destination = str(destination)
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as source:
            with closing(sqlite3.connect(destination)) as target:
                source.backup(target)

    def restore_from(self, source: str | Path) -> None:
        """Validate and restore a database backup over the current database."""
        source = Path(source)
        with closing(sqlite3.connect(source)) as candidate:
            result = candidate.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {row[0] for row in candidate.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if result != "ok" or not {"tasks", "execution_logs", "app_settings"}.issubset(tables):
            raise ValueError("备份文件不是有效的 TTask 数据库")
        # SQLite's backup API safely replaces the live database while the
        # scheduler may still open short-lived read connections.
        with closing(sqlite3.connect(source, timeout=10)) as candidate:
            with closing(sqlite3.connect(self.path, timeout=10)) as target:
                candidate.backup(target)
        self._initialize()

    def cleanup_logs(self, retention_days: int) -> int:
        if retention_days <= 0:
            return 0
        cutoff = datetime.now().timestamp() - retention_days * 86400
        cutoff_text = datetime.fromtimestamp(cutoff).isoformat(timespec="seconds")
        with self.connect() as db:
            cursor = db.execute("DELETE FROM execution_logs WHERE started_at < ?", (cutoff_text,))
            return cursor.rowcount

    def health_check(self) -> str:
        with self.connect() as db:
            return str(db.execute("PRAGMA integrity_check").fetchone()[0])

    @staticmethod
    def _task(row: sqlite3.Row) -> Task:
        return Task(
            id=row["id"],
            name=row["name"],
            schedule_type=ScheduleType(row["schedule_type"]),
            action_type=ActionType(row["action_type"]),
            time_start=row["time_start"],
            time_end=row["time_end"],
            time_windows=json.loads(row["time_windows"]),
            run_date=row["run_date"],
            interval_seconds=row["interval_seconds"],
            anchor_at=row["anchor_at"],
            weekdays=json.loads(row["weekdays"]),
            workdays_only=bool(row["workdays_only"]),
            weekend_overrides=json.loads(row["weekend_overrides"]),
            excluded_dates=json.loads(row["excluded_dates"]),
            action_config=json.loads(row["action_config"]),
            enabled=bool(row["enabled"]),
        )
