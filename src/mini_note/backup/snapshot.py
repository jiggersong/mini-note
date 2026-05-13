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
    """解压快照到恢复目录。

    逐个校验 tar member 的规范化路径必须在 restore_dir 内，
    防止恶意 tar 包通过 ../ 或绝对路径穿越写入。
    """
    import os

    restore_dir.mkdir(parents=True, exist_ok=True)
    resolved_restore = restore_dir.resolve()

    mode = "r:gz" if snapshot_path.suffix == ".gz" else "r"
    with tarfile.open(snapshot_path, mode) as tar:
        for member in tar.getmembers():
            target = (restore_dir / member.name).resolve()
            try:
                target.relative_to(resolved_restore)
            except ValueError:
                raise ValueError(
                    f"tar 路径穿越拒绝: {member.name} → {target}"
                )
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                fh = tar.extractfile(member)
                if fh is None:
                    continue
                # 安全写入：临时文件 + fsync + 原子 replace
                data = fh.read()
                tmp = target.with_suffix(target.suffix + ".tmp")
                with open(tmp, "wb") as wf:
                    wf.write(data)
                    wf.flush()
                    os.fsync(wf.fileno())
                os.replace(tmp, target)
            elif member.issym() or member.islnk():
                raise ValueError(f"tar 快照不允许符号链接或硬链接: {member.name}")

    # 确保必要目录存在
    for sub in [".state/staging", ".state/health", ".state/operations",
                ".state/review_tasks"]:
        (restore_dir / sub).mkdir(parents=True, exist_ok=True)
