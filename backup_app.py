"""Incremental folder backup utility with persistent settings.

Run with: python backup_app.py
"""

from __future__ import annotations

import filecmp
import json
import os
import shutil
import threading
import tkinter as tk
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk


SETTINGS_FILE = Path(__file__).resolve().parent / "config.json"


@dataclass
class Settings:
    source: str = ""
    destination: str = ""
    schedule_enabled: bool = False
    schedule_mode: str = "daily"
    schedule_time: str = "02:00"
    schedule_interval_hours: str = "1"


def load_settings() -> Settings:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return Settings(
            source=str(data.get("source", "")),
            destination=str(data.get("destination", "")),
            schedule_enabled=bool(data.get("schedule_enabled", False)),
            schedule_mode=str(data.get("schedule_mode", "daily")),
            schedule_time=str(data.get("schedule_time", "02:00")),
            schedule_interval_hours=str(data.get("schedule_interval_hours", "1")),
        )
    except (OSError, json.JSONDecodeError, TypeError):
        return Settings()


def save_settings(settings: Settings) -> None:
    SETTINGS_FILE.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")


class BackupApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("增量文件夹备份")
        self.resizable(True, True)
        self.minsize(650, 460)
        settings = load_settings()
        self.source_var = tk.StringVar(value=settings.source)
        self.destination_var = tk.StringVar(value=settings.destination)
        self.schedule_enabled_var = tk.BooleanVar(value=settings.schedule_enabled)
        self.schedule_mode_var = tk.StringVar(value=settings.schedule_mode)
        self.schedule_time_var = tk.StringVar(value=settings.schedule_time)
        self.schedule_interval_hours_var = tk.StringVar(value=settings.schedule_interval_hours)
        self.schedule_summary_var = tk.StringVar()
        self.backup_status_var = tk.StringVar(value="请选择源文件夹和备份文件夹。")
        self.schedule_status_var = tk.StringVar(value="定时备份未启用。")
        self.progress_var = tk.DoubleVar(value=0)
        self.backup_running = False
        self.schedule_after_id: str | None = None
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._update_schedule_summary()
        self._schedule_next_backup()

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=16)
        frame.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(8, weight=1)

        ttk.Label(frame, text="源文件夹 A：").grid(row=0, column=0, sticky="w", pady=(0, 10))
        ttk.Entry(frame, textvariable=self.source_var).grid(row=0, column=1, sticky="ew", padx=(8, 8), pady=(0, 10))
        ttk.Button(frame, text="选择…", command=lambda: self._choose_folder(self.source_var)).grid(row=0, column=2, pady=(0, 10))

        ttk.Label(frame, text="备份文件夹 B：").grid(row=1, column=0, sticky="w", pady=(0, 10))
        ttk.Entry(frame, textvariable=self.destination_var).grid(row=1, column=1, sticky="ew", padx=(8, 8), pady=(0, 10))
        ttk.Button(frame, text="选择…", command=lambda: self._choose_folder(self.destination_var)).grid(row=1, column=2, pady=(0, 10))

        self.backup_button = ttk.Button(frame, text="开始增量备份", command=self._start_backup)
        self.backup_button.grid(row=2, column=1, sticky="e", pady=(8, 14))
        ttk.Button(frame, text="设置", command=self._open_settings).grid(row=2, column=2, pady=(8, 14))
        ttk.Checkbutton(
            frame,
            text="启用定时备份",
            variable=self.schedule_enabled_var,
            command=self._on_schedule_enabled_changed,
        ).grid(row=3, column=0, sticky="w", pady=(0, 8))
        self.schedule_summary = ttk.Label(frame, textvariable=self.schedule_summary_var)
        self.schedule_summary.grid(row=3, column=1, columnspan=2, sticky="w", padx=(8, 8), pady=(0, 8))
        self.progress_bar = ttk.Progressbar(
            frame,
            variable=self.progress_var,
            maximum=100,
            mode="determinate",
        )
        ttk.Label(frame, textvariable=self.schedule_status_var, wraplength=600).grid(row=4, column=0, columnspan=3, sticky="w", pady=(0, 6))
        self.progress_bar.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        ttk.Label(frame, textvariable=self.backup_status_var, wraplength=600).grid(row=6, column=0, columnspan=3, sticky="w")
        ttk.Label(frame, text="执行日志：").grid(row=7, column=0, columnspan=3, sticky="w", pady=(12, 4))
        self.log_text = scrolledtext.ScrolledText(frame, height=8, wrap="word", state="disabled")
        self.log_text.grid(row=8, column=0, columnspan=3, sticky="nsew")

        ttk.Label(
            frame,
            text="仅复制新增或已修改的文件；不会删除 B 中已有的其他文件。",
            foreground="#555555",
        ).grid(row=9, column=0, columnspan=3, sticky="w", pady=(12, 0))

    def _choose_folder(self, variable: tk.StringVar) -> None:
        selected = filedialog.askdirectory(initialdir=variable.get() or None)
        if selected:
            variable.set(selected)
            self._save_current_settings()

    def _save_current_settings(self) -> None:
        try:
            save_settings(
                Settings(
                    source=self.source_var.get().strip(),
                    destination=self.destination_var.get().strip(),
                    schedule_enabled=self.schedule_enabled_var.get(),
                    schedule_mode=self.schedule_mode_var.get(),
                    schedule_time=self.schedule_time_var.get().strip(),
                    schedule_interval_hours=self.schedule_interval_hours_var.get().strip(),
                )
            )
        except OSError as error:
            self.backup_status_var.set(f"无法保存设置：{error}")

    def _start_backup(self, show_errors: bool = True) -> bool:
        if self.backup_running:
            return False
        source_text = self.source_var.get().strip()
        destination_text = self.destination_var.get().strip()
        source = Path(source_text).expanduser()
        destination = Path(destination_text).expanduser()
        if not source.is_dir():
            self._show_start_error("请选择一个存在的源文件夹 A。", show_errors)
            return False
        if not destination_text:
            self._show_start_error("请选择备份文件夹 B。", show_errors)
            return False
        try:
            source.resolve().relative_to(destination.resolve())
            self._show_start_error("备份文件夹 B 不能是源文件夹 A 的上级目录或其自身。", show_errors)
            return False
        except ValueError:
            pass
        try:
            destination.resolve().relative_to(source.resolve())
            self._show_start_error("备份文件夹 B 不能位于源文件夹 A 内。", show_errors)
            return False
        except ValueError:
            pass

        self._save_current_settings()
        self.backup_running = True
        self.backup_button.state(["disabled"])
        self.backup_status_var.set("正在备份…")
        self.progress_var.set(0)
        self._append_log(f"开始备份：{source} → {destination}")
        threading.Thread(target=self._backup_worker, args=(source, destination), daemon=True).start()
        return True

    def _show_start_error(self, text: str, show_dialog: bool) -> None:
        if show_dialog:
            messagebox.showerror("无法开始", text)
        else:
            self.backup_status_var.set(f"定时备份未执行：{text}")

    def _backup_worker(self, source: Path, destination: Path) -> None:
        copied = skipped = errors = 0
        try:
            files_to_process = []
            for directory, _, files in os.walk(source):
                current_dir = Path(directory)
                for filename in files:
                    files_to_process.append((current_dir / filename, current_dir.relative_to(source) / filename))

            total = len(files_to_process)
            self.after(0, self._begin_progress, total)
            destination.mkdir(parents=True, exist_ok=True)
            for index, (source_file, relative_path) in enumerate(files_to_process, start=1):
                target_file = destination / relative_path
                try:
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    # A shallow comparison is sufficient for normal incremental backups:
                    # size or modification time changes cause a fresh copy.
                    if target_file.exists() and filecmp.cmp(source_file, target_file, shallow=True):
                        skipped += 1
                    else:
                        shutil.copy2(source_file, target_file)
                        copied += 1
                        self._queue_log(f"已备份：{relative_path}")
                except OSError:
                    errors += 1
                    self._queue_log(f"备份失败：{relative_path}")
                self.after(0, self._update_progress, index, total)
            text = f"备份完成：复制 {copied} 个文件，跳过 {skipped} 个未变化文件"
            if errors:
                text += f"，{errors} 个文件失败。"
            else:
                text += "。"
        except OSError as error:
            text = f"备份失败：{error}"
        self.after(0, self._finish_backup, text)

    def _begin_progress(self, total: int) -> None:
        if total == 0:
            self.progress_var.set(100)
        self.backup_status_var.set(f"正在备份… 共 {total} 个文件")

    def _update_progress(self, done: int, total: int) -> None:
        self.progress_var.set(done * 100 / total if total else 100)
        self.backup_status_var.set(f"正在备份… {done}/{total} 个文件")

    def _finish_backup(self, text: str) -> None:
        self.backup_status_var.set(text)
        self._append_log(text)
        self.backup_running = False
        self.backup_button.state(["!disabled"])

    def _queue_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.after(0, self._append_log, message, timestamp)

    def _append_log(self, message: str, timestamp: str | None = None) -> None:
        timestamp = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _open_settings(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("设置")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=16)
        frame.grid(sticky="nsew")
        mode_var = tk.StringVar(value=self.schedule_mode_var.get())
        time_var = tk.StringVar(value=self.schedule_time_var.get())
        interval_var = tk.StringVar(value=self.schedule_interval_hours_var.get())
        ttk.Label(frame, text="定时方式：").grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Radiobutton(frame, text="每天固定时间", variable=mode_var, value="daily").grid(row=0, column=1, sticky="w", pady=(0, 8))
        ttk.Radiobutton(frame, text="每隔指定小时", variable=mode_var, value="interval").grid(row=0, column=2, sticky="w", pady=(0, 8))

        ttk.Label(frame, text="每日执行时间：").grid(row=1, column=0, sticky="w")
        time_entry = ttk.Entry(frame, textvariable=time_var, width=10)
        time_entry.grid(row=1, column=1, sticky="w", padx=(8, 0))
        ttk.Label(frame, text="格式：HH:MM，例如 23:30").grid(row=1, column=2, sticky="w", padx=(8, 0))

        ttk.Label(frame, text="间隔小时数：").grid(row=2, column=0, sticky="w", pady=(10, 0))
        interval_entry = ttk.Entry(frame, textvariable=interval_var, width=10)
        interval_entry.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(10, 0))
        ttk.Label(frame, text="例如 2 表示每 2 小时执行一次").grid(row=2, column=2, sticky="w", padx=(8, 0), pady=(10, 0))

        def update_mode_controls(*_args: object) -> None:
            daily = mode_var.get() == "daily"
            time_entry.state(["!disabled"] if daily else ["disabled"])
            interval_entry.state(["disabled"] if daily else ["!disabled"])

        mode_var.trace_add("write", update_mode_controls)
        update_mode_controls()

        def save_schedule() -> None:
            mode = mode_var.get()
            schedule_time = time_var.get().strip()
            interval_hours = interval_var.get().strip()
            if mode == "daily" and not self._is_valid_schedule_time(schedule_time):
                messagebox.showerror("时间格式错误", "请输入 00:00 到 23:59 之间的时间。", parent=dialog)
                return
            if mode == "interval" and not self._is_valid_interval_hours(interval_hours):
                messagebox.showerror("间隔时间错误", "请输入 1 到 500 之间的整数小时数。", parent=dialog)
                return
            self.schedule_mode_var.set(mode)
            self.schedule_time_var.set(schedule_time)
            self.schedule_interval_hours_var.set(interval_hours)
            self._update_schedule_summary()
            self._save_current_settings()
            self._schedule_next_backup()
            dialog.destroy()

        ttk.Button(frame, text="保存", command=save_schedule).grid(row=3, column=2, sticky="e", pady=(18, 0))

    @staticmethod
    def _is_valid_schedule_time(value: str) -> bool:
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError:
            return False
        return True

    @staticmethod
    def _is_valid_interval_hours(value: str) -> bool:
        try:
            hours = int(value)
        except ValueError:
            return False
        return 1 <= hours <= 500

    def _update_schedule_summary(self) -> None:
        if self.schedule_mode_var.get() == "interval":
            self.schedule_summary_var.set(f"每隔 {self.schedule_interval_hours_var.get()} 小时执行")
        else:
            self.schedule_summary_var.set(f"每天 {self.schedule_time_var.get()} 执行")

    def _on_schedule_enabled_changed(self) -> None:
        mode = self.schedule_mode_var.get()
        invalid_daily = mode == "daily" and not self._is_valid_schedule_time(self.schedule_time_var.get().strip())
        invalid_interval = mode == "interval" and not self._is_valid_interval_hours(self.schedule_interval_hours_var.get().strip())
        if self.schedule_enabled_var.get() and (invalid_daily or invalid_interval):
            self.schedule_enabled_var.set(False)
            messagebox.showerror("定时设置错误", "请先在设置中填写正确的定时规则。")
        self._save_current_settings()
        self._schedule_next_backup()
        if not self.schedule_enabled_var.get():
            self.schedule_status_var.set("定时备份已关闭。")

    def _schedule_next_backup(self) -> None:
        if self.schedule_after_id is not None:
            self.after_cancel(self.schedule_after_id)
            self.schedule_after_id = None
        if not self.schedule_enabled_var.get():
            return

        mode = self.schedule_mode_var.get()
        if mode not in {"daily", "interval"}:
            mode = "daily"
            self.schedule_mode_var.set(mode)

        if mode == "daily" and not self._is_valid_schedule_time(self.schedule_time_var.get().strip()):
            self.schedule_enabled_var.set(False)
            self._save_current_settings()
            self.schedule_status_var.set("定时备份未启用：时间格式无效。")
            return
        now = datetime.now()
        if mode == "daily":
            hour, minute = map(int, self.schedule_time_var.get().strip().split(":"))
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            schedule_description = f"每天 {self.schedule_time_var.get().strip()}"
        else:
            interval_hours = self.schedule_interval_hours_var.get().strip()
            if not self._is_valid_interval_hours(interval_hours):
                self.schedule_enabled_var.set(False)
                self._save_current_settings()
                self.schedule_status_var.set("定时备份未启用：间隔小时数无效。")
                return
            next_run = now + timedelta(hours=int(interval_hours))
            schedule_description = f"每隔 {interval_hours} 小时"

        delay_ms = int((next_run - now).total_seconds() * 1000)
        self.schedule_after_id = self.after(delay_ms, self._run_scheduled_backup)
        self._update_schedule_summary()
        self.schedule_status_var.set(f"定时备份已启用：{schedule_description}，下次在 {next_run:%Y-%m-%d %H:%M} 执行。")

    def _run_scheduled_backup(self) -> None:
        self.schedule_after_id = None
        self._schedule_next_backup()
        if self.backup_running:
            self.schedule_status_var.set("定时备份跳过：已有备份任务正在执行。")
            return
        self._start_backup(show_errors=False)

    def _on_close(self) -> None:
        if self.schedule_after_id is not None:
            self.after_cancel(self.schedule_after_id)
        self._save_current_settings()
        self.destroy()


if __name__ == "__main__":
    BackupApp().mainloop()
