"""备份状态追踪 — backup_log.jsonl 读写。"""

import json
from pathlib import Path


class BackupLog:
    """管理 .state/backup_log.jsonl。"""

    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        oss_object: str,
        sha256: str,
        status: str,
        operation_id: str,
        error: str | None = None,
        attempt: int = 1,
    ) -> None:
        """追加一条备份记录。"""
        entry = {
            "oss_object": oss_object,
            "sha256": sha256,
            "status": status,
            "operation_id": operation_id,
            "attempt": attempt,
        }
        if error:
            entry["error"] = error
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read_all(self) -> list[dict]:
        """读取全部备份记录。"""
        if not self.log_path.exists():
            return []
        entries = []
        with self.log_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return entries
