# 增量文件夹备份工具

运行 `python backup_app.py`，分别选择源文件夹 A 和备份文件夹 B，然后点击“开始增量备份”。

工具会复制 A 中新增或修改的文件，保留原有目录结构；不会删除 B 内的文件。所选路径会保存到当前 Windows 用户目录下的 `.incremental_backup_settings.json`，下次启动时自动恢复。
