"""大文件摄入独立队列 — 目录式队列 + 单 worker 锁。

队列目录结构：
  .state/large_ingest_queue/
    pending/    — 待处理
    running/    — 处理中（同时最多 1 个）
    done/       — 已完成
    failed/     — 失败

大文件 worker 使用独立锁 .state/large_ingest.lock，不与普通 ingest 互斥。
"""

import os
import secrets
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

CST = timezone(timedelta(hours=8))


def _queue_dir(workspace: Path) -> Path:
    return workspace / ".state" / "large_ingest_queue"


def _ensure_dirs(workspace: Path) -> None:
    qd = _queue_dir(workspace)
    for sub in ("pending", "running", "done", "failed"):
        (qd / sub).mkdir(parents=True, exist_ok=True)


def enqueue(
    workspace: Path,
    file_path: Path,
    owner_id: str,
    scope: str,
    limit_type: str,
    actual_value: str,
) -> str:
    """将大文件写入 pending 队列并复制到 staging，返回 operation_id。

    文件被复制到 .state/large_ingest_queue/staging/{op_id}/ 以确保
    worker 处理时源文件不会被用户移动/删除。
    """
    _ensure_dirs(workspace)
    now = datetime.now(CST)
    op_id = f"large-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}-{secrets.token_hex(2)}"

    # 复制文件到队列 staging 目录
    staging_dir = _queue_dir(workspace) / "staging" / op_id
    staging_dir.mkdir(parents=True, exist_ok=True)
    stabilized_path = staging_dir / file_path.name
    shutil.copy2(file_path, stabilized_path)

    entry = {
        "operation_id": op_id,
        "file_path": str(file_path),
        "stabilized_path": str(stabilized_path),
        "owner_id": owner_id,
        "scope": scope,
        "limit_type": limit_type,
        "actual_value": actual_value,
        "created_at": now.isoformat(),
    }
    entry_file = _queue_dir(workspace) / "pending" / f"{op_id}.yaml"
    entry_file.write_text(yaml.dump(entry, allow_unicode=True), encoding="utf-8")
    return op_id


def dequeue(workspace: Path) -> dict | None:
    """从 pending 取一个任务移入 running，返回条目数据；队列空则返回 None。

    调用方应先获取 large_ingest.lock 再调此函数。
    """
    _ensure_dirs(workspace)
    pending_dir = _queue_dir(workspace) / "pending"
    entries = sorted(pending_dir.glob("*.yaml"))
    if not entries:
        return None

    entry_file = entries[0]
    data = yaml.safe_load(entry_file.read_text(encoding="utf-8"))
    running_dir = _queue_dir(workspace) / "running"
    entry_file.rename(running_dir / entry_file.name)
    return data


def mark_done(workspace: Path, operation_id: str) -> None:
    """将任务从 running 移入 done。"""
    _move_between(workspace, operation_id, "running", "done")


def mark_failed(workspace: Path, operation_id: str, error: str) -> None:
    """将任务从 running 移入 failed，追加错误信息。"""
    running_file = _queue_dir(workspace) / "running" / f"{operation_id}.yaml"
    if running_file.exists():
        data = yaml.safe_load(running_file.read_text(encoding="utf-8"))
        data["error"] = error
        data["failed_at"] = datetime.now(CST).isoformat()
        running_file.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    _move_between(workspace, operation_id, "running", "failed")


def _move_between(workspace: Path, operation_id: str, src: str, dst: str) -> None:
    _ensure_dirs(workspace)
    src_file = _queue_dir(workspace) / src / f"{operation_id}.yaml"
    dst_file = _queue_dir(workspace) / dst / f"{operation_id}.yaml"
    if src_file.exists():
        src_file.rename(dst_file)


def status(workspace: Path) -> dict:
    """返回队列各目录条目数。"""
    _ensure_dirs(workspace)
    qd = _queue_dir(workspace)
    return {
        "pending": len(sorted((qd / "pending").glob("*.yaml"))),
        "running": len(sorted((qd / "running").glob("*.yaml"))),
        "done": len(sorted((qd / "done").glob("*.yaml"))),
        "failed": len(sorted((qd / "failed").glob("*.yaml"))),
    }


def acquire_large_worker_lock(workspace: Path) -> bool:
    """尝试获取大文件 worker 锁（O_EXCL 原子操作）。

    返回 True 表示获取成功，False 表示已有 worker 在运行。
    """
    lock_file = workspace / ".state" / "large_ingest.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, b"large_worker")
        os.close(fd)
        return True
    except FileExistsError:
        return False


def release_large_worker_lock(workspace: Path) -> None:
    """释放大文件 worker 锁。"""
    lock_file = workspace / ".state" / "large_ingest.lock"
    if lock_file.exists():
        lock_file.unlink()


def run_large_worker(workspace: Path, once: bool = True) -> dict:
    """大文件单 worker：两阶段提交，消除与普通 ingest 的共享状态竞态。

    large_ingest.lock 覆盖整个任务生命周期（提取 + 提交），保证任意时刻最多一个
    大文件任务处于 running。阶段二短暂持有 ingest.lock 写共享状态，普通 ingest
    仅在共享状态提交阶段被串行化，不会被大文件提取的耗时 IO 阻塞。

    once=True（默认）：处理一个任务后退出。
    once=False：持续处理直到队列为空（预留，当前仅支持 once）。
    """
    if not acquire_large_worker_lock(workspace):
        return {
            "ok": False,
            "error_code": "WORKER_BUSY",
            "message": "已有大文件 worker 在运行",
            "retryable": True,
        }

    entry = None
    try:
        entry = dequeue(workspace)
        if entry is None:
            return {"ok": True, "message": "队列为空，无待处理任务"}

        # 优先使用入队时复制的稳定副本
        file_path = Path(entry.get("stabilized_path", entry["file_path"]))
        if not file_path.exists():
            mark_failed(workspace, entry["operation_id"], f"文件不存在: {file_path}")
            return {
                "ok": False,
                "error_code": "FILE_NOT_FOUND",
                "message": f"队列任务文件不存在: {file_path}",
                "operation_id": entry["operation_id"],
                "retryable": False,
            }

        # === 阶段一：重提取（large_ingest.lock 下，不触及共享状态）===
        from mini_note.config import get_limits
        from mini_note.ingest.extraction import extract_by_type
        limits = get_limits(workspace)
        ext_result = extract_by_type(file_path, limits=limits)

        # === 阶段二：提交（短暂持 ingest.lock 写共享状态，large_ingest.lock 仍持有）===
        from mini_note.ingest.pipeline import IngestPipeline
        pipeline = IngestPipeline(workspace)
        result = pipeline.run(
            file_path=file_path,
            owner_id=entry["owner_id"],
            scope=entry.get("scope", "shared"),
            skip_precheck=True,
            use_lock=True,
            pre_extracted=ext_result,
        )

        if result.ok:
            mark_done(workspace, entry["operation_id"])
        else:
            mark_failed(workspace, entry["operation_id"], result.message or "未知错误")

        return {
            "ok": result.ok,
            "operation_id": entry["operation_id"],
            "source_id": result.source_id,
            "ingestion_status": result.ingestion_status,
            "message": result.message,
        }
    except Exception as e:
        if entry:
            mark_failed(workspace, entry["operation_id"], str(e))
        return {
            "ok": False,
            "error_code": "WORKER_EXCEPTION",
            "message": str(e),
            "operation_id": entry["operation_id"] if entry else None,
            "retryable": True,
        }
    finally:
        release_large_worker_lock(workspace)
        # 清理 staging 目录（含 FILE_NOT_FOUND 提前返回的情况）
        if entry:
            staging_dir = _queue_dir(workspace) / "staging" / entry["operation_id"]
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
