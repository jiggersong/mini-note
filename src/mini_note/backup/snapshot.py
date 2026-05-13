"""快照打包与恢复 — tar 压缩、hash 校验。"""

import hashlib
import tarfile
from pathlib import Path


def _reset_tarinfo(ti: tarfile.TarInfo) -> tarfile.TarInfo:
    """重置 tarinfo 中导致非确定性的字段，确保相同内容产相同 hash。"""
    ti.mtime = 0
    ti.uid = 0
    ti.gid = 0
    ti.uname = ""
    ti.gname = ""
    return ti


def create_snapshot(
    workspace: Path,
    output: Path,
    compression: str = "gzip",
) -> str:
    """创建 workspace 快照的 tar 压缩包，返回 SHA256 hash。

    快照包含 meta/、raw/、wiki/、.state/operations/、.state/review_tasks/、
    .state/backup_log.jsonl、（可选）.state/notes.db。
    """
    mode = "w:gz" if compression == "gzip" else "w"

    with tarfile.open(output, mode, format=tarfile.PAX_FORMAT) as tar:
        for inc in ["meta", "raw", "wiki"]:
            target = workspace / inc
            if not target.exists():
                continue
            for f in sorted(target.rglob("*"), key=lambda p: str(p)):
                arcname = str(f.relative_to(workspace))
                ti = _reset_tarinfo(tar.gettarinfo(f, arcname=arcname))
                if ti.isreg():
                    with open(f, "rb") as fh:
                        tar.addfile(ti, fh)
                elif ti.isdir():
                    tar.addfile(ti)

        for sub in ["operations", "review_tasks"]:
            target = workspace / ".state" / sub
            if not target.exists():
                continue
            for f in sorted(target.rglob("*"), key=lambda p: str(p)):
                arcname = str(f.relative_to(workspace))
                ti = _reset_tarinfo(tar.gettarinfo(f, arcname=arcname))
                if ti.isreg():
                    with open(f, "rb") as fh:
                        tar.addfile(ti, fh)
                elif ti.isdir():
                    tar.addfile(ti)

        for rel in ["backup_log.jsonl", "notes.db"]:
            p = workspace / ".state" / rel
            if p.exists():
                arcname = f".state/{rel}"
                ti = _reset_tarinfo(tar.gettarinfo(p, arcname=arcname))
                with open(p, "rb") as fh:
                    tar.addfile(ti, fh)

    # 计算 hash
    data = output.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    return sha


def restore_snapshot(snapshot_path: Path, restore_dir: Path) -> None:
    """解压快照到恢复目录。"""
    restore_dir.mkdir(parents=True, exist_ok=True)

    mode = "r:gz" if snapshot_path.suffix == ".gz" else "r"
    with tarfile.open(snapshot_path, mode) as tar:
        tar.extractall(path=restore_dir)

    # 确保必要目录存在
    for sub in [".state/staging", ".state/health", ".state/operations",
                ".state/review_tasks"]:
        (restore_dir / sub).mkdir(parents=True, exist_ok=True)
