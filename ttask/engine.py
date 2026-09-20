from __future__ import annotations

import subprocess
import threading
import os
import shutil
import urllib.request
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Callable

from .database import Database
from .models import ActionType, ScheduleType, Task
from .scheduling import next_occurrence


class SchedulerEngine:
    def __init__(self, database: Database, notify: Callable[[str, str], None] | None = None):
        self.database = database
        self.notify = notify or (lambda _title, _message: None)
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ttask")
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_error = ""
        self._active = 0
        self._active_lock = threading.Lock()
        self._processes: set[subprocess.Popen] = set()
        self._process_lock = threading.Lock()
        self.last_check = self._load_last_check()
        self._last_persisted = self.last_check

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    @property
    def active_count(self) -> int:
        with self._active_lock:
            return self._active

    @property
    def is_alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def stop(self, wait: bool = False, force: bool = False) -> None:
        self.stop_event.set()
        if force:
            with self._process_lock:
                for process in list(self._processes):
                    try:
                        process.terminate()
                    except OSError:
                        pass
        if self.thread:
            self.thread.join(timeout=2)
        self._save_last_check(datetime.now())
        self.pool.shutdown(wait=wait, cancel_futures=True)

    def _load_last_check(self) -> datetime:
        value = self.database.get_setting("scheduler_last_check")
        try:
            return datetime.fromisoformat(value) if value else datetime.now() - timedelta(seconds=2)
        except ValueError:
            return datetime.now() - timedelta(seconds=2)

    def _save_last_check(self, value: datetime) -> None:
        try:
            self.database.set_settings({"scheduler_last_check": value.isoformat(timespec="seconds")})
        except Exception as exc:
            self.last_error = f"保存调度进度失败：{exc}"

    def _loop(self) -> None:
        while not self.stop_event.wait(1):
            now = datetime.now()
            window_start = min(self.last_check, now)
            try:
                tasks = self.database.list_tasks()
            except Exception as exc:
                self.last_error = f"读取任务失败：{exc}"
                continue
            for task in tasks:
                try:
                    self._dispatch_due(task, window_start, now)
                except Exception as exc:
                    self.last_error = f"任务“{task.name}”调度失败：{exc}"
            self.last_check = now
            if (now - self._last_persisted).total_seconds() >= 15:
                self._save_last_check(now)
                self._last_persisted = now

    def _dispatch_due(self, task: Task, start: datetime, now: datetime) -> None:
        if not task.enabled or task.id is None:
            return
        policy = str(task.action_config.get("misfire_policy", "skip"))
        if policy == "run_once" and task.schedule_type == ScheduleType.INTERVAL:
            interval = max(1, int(task.interval_seconds or 1))
            due = next_occurrence(task, now - timedelta(seconds=interval))
            due_values = [due] if due and start < due <= now else []
        else:
            due_values = []
            cursor = start
            for _ in range(1000):
                due = next_occurrence(task, cursor)
                if due is None or due > now:
                    break
                due_values.append(due)
                cursor = due
        if not due_values:
            return
        if policy == "skip":
            due_values = [value for value in due_values if (now - value).total_seconds() <= 2]
        elif policy != "run_all":
            due_values = due_values[-1:]
        for due in due_values:
            stamp = due.isoformat(timespec="seconds")
            log_id = self.database.claim_occurrence(task.id, stamp)
            if log_id is not None:
                self.pool.submit(self._execute, task, log_id)

    def run_now(self, task: Task) -> bool:
        if task.id is None:
            return False
        stamp = f"manual:{datetime.now().isoformat(timespec='microseconds')}"
        log_id = self.database.claim_occurrence(task.id, stamp)
        if log_id is not None:
            self.pool.submit(self._execute, task, log_id)
            return True
        return False

    def _execute(self, task: Task, log_id: int) -> None:
        with self._active_lock:
            self._active += 1
        retries = max(0, int(task.action_config.get("retries", 0)))
        retry_delay = max(0, int(task.action_config.get("retry_delay", 5)))
        last_error: Exception | None = None
        try:
            for attempt in range(retries + 1):
                try:
                    output = self._execute_once(task)
                    self.database.finish_log(log_id, "success", output)
                    return
                except Exception as exc:
                    last_error = exc
                    if attempt < retries and self.stop_event.wait(retry_delay):
                        break
            self.database.finish_log(log_id, "failed", str(last_error))
            self.notify(f"{task.name} 执行失败", str(last_error))
            threshold = int(task.action_config.get("disable_after_failures", 0))
            if task.id and threshold > 0 and self.database.consecutive_failures(task.id, threshold) >= threshold:
                self.database.set_enabled(task.id, False)
                self.notify(f"{task.name} 已自动停用", f"连续失败达到 {threshold} 次")
        finally:
            with self._active_lock:
                self._active -= 1

    def _execute_once(self, task: Task) -> str:
        config = self._render_config(task)
        if task.action_type == ActionType.NOTIFICATION:
            message = str(config.get("message", task.name))
            self.notify(task.name, message)
            return message
        if task.action_type == ActionType.OPEN:
            target = str(config.get("target", ""))
            if not target:
                raise ValueError("未配置要打开的文件或程序")
            os.startfile(target)
            return f"已打开：{target}"
        if task.action_type == ActionType.HTTP:
            url = str(config.get("url", ""))
            if not url:
                raise ValueError("未配置 URL")
            method = str(config.get("method", "GET")).upper()
            body = config.get("body")
            data = str(body).encode("utf-8") if body else None
            request = urllib.request.Request(url, data=data, method=method)
            with urllib.request.urlopen(
                request, timeout=int(config.get("timeout", 30))
            ) as response:
                content = response.read(10000).decode("utf-8", errors="replace")
                return f"HTTP {response.status}\n{content}"
        if task.action_type in (ActionType.COPY, ActionType.MOVE):
            source = str(config.get("source", ""))
            destination = str(config.get("destination", ""))
            if not source or not destination:
                raise ValueError("源路径和目标路径不能为空")
            operation = shutil.copy2 if task.action_type == ActionType.COPY else shutil.move
            result = operation(source, destination)
            return f"完成：{result}"
        if task.action_type == ActionType.COMMAND:
            command = config.get("command", [])
            if isinstance(command, str):
                raise ValueError("命令必须以参数列表形式保存")
            if not command:
                raise ValueError("未配置执行命令")
            process = subprocess.Popen(
                [str(item) for item in command],
                cwd=config.get("cwd") or None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            with self._process_lock:
                self._processes.add(process)
            try:
                stdout, stderr = process.communicate(timeout=int(config.get("timeout", 300)))
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise TimeoutError("命令执行超时")
            finally:
                with self._process_lock:
                    self._processes.discard(process)
            # A Windows GUI executable may not provide either stream even when
            # capture_output is requested. Treat missing streams as empty text.
            output = ((stdout or "") + "\n" + (stderr or "")).strip()
            if process.returncode:
                raise RuntimeError(f"退出码 {process.returncode}\n{output}")
            return output
        raise ValueError(f"不支持的动作类型：{task.action_type}")

    @staticmethod
    def _render_config(task: Task) -> dict:
        now = datetime.now()
        variables = {
            "{date}": now.strftime("%Y-%m-%d"),
            "{time}": now.strftime("%H-%M-%S"),
            "{datetime}": now.strftime("%Y-%m-%d_%H-%M-%S"),
            "{weekday}": str(now.weekday() + 1),
            "{task_name}": task.name,
        }

        def render(value):
            if isinstance(value, str):
                for token, replacement in variables.items():
                    value = value.replace(token, replacement)
                return value
            if isinstance(value, list):
                return [render(item) for item in value]
            if isinstance(value, dict):
                return {key: render(item) for key, item in value.items()}
            return value

        return render(copy.deepcopy(task.action_config))
