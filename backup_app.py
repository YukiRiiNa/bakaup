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
from dataclasses import dataclass, asdict
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


SETTINGS_FILE = Path.home() / ".incremental_backup_settings.json"


@dataclass
class Settings:
    source: str = ""
    destination: str = ""


def load_settings() -> Settings:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return Settings(**{key: data.get(key, "") for key in ("source", "destination")})
    except (OSError, json.JSONDecodeError, TypeError):
        return Settings()


def save_settings(settings: Settings) -> None:
    SETTINGS_FILE.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")


class BackupApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("增量文件夹备份")
        self.resizable(True, False)
        self.minsize(650, 240)
        settings = load_settings()
        self.source_var = tk.StringVar(value=settings.source)
        self.destination_var = tk.StringVar(value=settings.destination)
        self.status_var = tk.StringVar(value="请选择源文件夹和备份文件夹。")
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=16)
        frame.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="源文件夹 A：").grid(row=0, column=0, sticky="w", pady=(0, 10))
        ttk.Entry(frame, textvariable=self.source_var).grid(row=0, column=1, sticky="ew", padx=(8, 8), pady=(0, 10))
        ttk.Button(frame, text="选择…", command=lambda: self._choose_folder(self.source_var)).grid(row=0, column=2, pady=(0, 10))

        ttk.Label(frame, text="备份文件夹 B：").grid(row=1, column=0, sticky="w", pady=(0, 10))
        ttk.Entry(frame, textvariable=self.destination_var).grid(row=1, column=1, sticky="ew", padx=(8, 8), pady=(0, 10))
        ttk.Button(frame, text="选择…", command=lambda: self._choose_folder(self.destination_var)).grid(row=1, column=2, pady=(0, 10))

        self.backup_button = ttk.Button(frame, text="开始增量备份", command=self._start_backup)
        self.backup_button.grid(row=2, column=1, sticky="e", pady=(8, 14))
        ttk.Label(frame, textvariable=self.status_var, wraplength=600).grid(row=3, column=0, columnspan=3, sticky="w")

        ttk.Label(
            frame,
            text="仅复制新增或已修改的文件；不会删除 B 中已有的其他文件。",
            foreground="#555555",
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(12, 0))

    def _choose_folder(self, variable: tk.StringVar) -> None:
        selected = filedialog.askdirectory(initialdir=variable.get() or None)
        if selected:
            variable.set(selected)
            self._save_current_settings()

    def _save_current_settings(self) -> None:
        try:
            save_settings(Settings(self.source_var.get().strip(), self.destination_var.get().strip()))
        except OSError as error:
            self.status_var.set(f"无法保存设置：{error}")

    def _start_backup(self) -> None:
        source_text = self.source_var.get().strip()
        destination_text = self.destination_var.get().strip()
        source = Path(source_text).expanduser()
        destination = Path(destination_text).expanduser()
        if not source.is_dir():
            messagebox.showerror("无法开始", "请选择一个存在的源文件夹 A。")
            return
        if not destination_text:
            messagebox.showerror("无法开始", "请选择备份文件夹 B。")
            return
        try:
            source.resolve().relative_to(destination.resolve())
            messagebox.showerror("无法开始", "备份文件夹 B 不能是源文件夹 A 的上级目录或其自身。")
            return
        except ValueError:
            pass
        try:
            destination.resolve().relative_to(source.resolve())
            messagebox.showerror("无法开始", "备份文件夹 B 不能位于源文件夹 A 内。")
            return
        except ValueError:
            pass

        self._save_current_settings()
        self.backup_button.state(["disabled"])
        self.status_var.set("正在备份…")
        threading.Thread(target=self._backup_worker, args=(source, destination), daemon=True).start()

    def _backup_worker(self, source: Path, destination: Path) -> None:
        copied = skipped = errors = 0
        try:
            destination.mkdir(parents=True, exist_ok=True)
            for directory, _, files in os.walk(source):
                current_dir = Path(directory)
                relative_dir = current_dir.relative_to(source)
                target_dir = destination / relative_dir
                target_dir.mkdir(parents=True, exist_ok=True)
                for filename in files:
                    source_file = current_dir / filename
                    target_file = target_dir / filename
                    try:
                        # A shallow comparison is sufficient for normal incremental backups:
                        # size or modification time changes cause a fresh copy.
                        if target_file.exists() and filecmp.cmp(source_file, target_file, shallow=True):
                            skipped += 1
                        else:
                            shutil.copy2(source_file, target_file)
                            copied += 1
                    except OSError:
                        errors += 1
            text = f"备份完成：复制 {copied} 个文件，跳过 {skipped} 个未变化文件"
            if errors:
                text += f"，{errors} 个文件失败。"
            else:
                text += "。"
        except OSError as error:
            text = f"备份失败：{error}"
        self.after(0, self._finish_backup, text)

    def _finish_backup(self, text: str) -> None:
        self.status_var.set(text)
        self.backup_button.state(["!disabled"])

    def _on_close(self) -> None:
        self._save_current_settings()
        self.destroy()


if __name__ == "__main__":
    BackupApp().mainloop()
