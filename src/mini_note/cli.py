"""CLI 入口 — argparse 命令解析、--json 输出、错误格式。

所有命令支持 --json 标志输出结构化结果。
错误输出包含 ok/error_code/message/operation_id/retryable 标准字段。
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

logger = logging.getLogger("mini_note")


def _error_result(
    error_code: str,
    message: str,
    operation_id: str | None = None,
    retryable: bool = False,
) -> dict:
    """构造标准错误结果。"""
    return {
        "ok": False,
        "error_code": error_code,
        "message": message,
        "operation_id": operation_id,
        "retryable": retryable,
    }


def main(argv: list[str] | None = None) -> dict | list:
    """CLI 主入口。"""
    # 强制 UTF-8 输出（解决 LANG=C 等非 UTF-8 环境下的中文乱码）
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="mini-note",
        description="给 OpenClaw 用的笔记管理软件，参考 Karpathy LLM Wiki 理念实现",
        exit_on_error=False,
    )
    subparsers = parser.add_subparsers(dest="command")

    # init
    init_p = subparsers.add_parser("init", help="初始化 workspace")
    init_p.add_argument("--workspace", type=Path, default=Path.cwd())

    # health
    health_p = subparsers.add_parser("health", help="健康检查")
    health_p.add_argument("--workspace", type=Path, default=Path.cwd())
    health_p.add_argument("--json", action="store_true", default=False)

    # lint
    lint_p = subparsers.add_parser("lint", help="Lint 检查")
    lint_p.add_argument("--workspace", type=Path, default=Path.cwd())
    lint_p.add_argument("--json", action="store_true", default=False)
    lint_p.add_argument("--changed-only", action="store_true", default=False)
    lint_p.add_argument("--full", action="store_true", default=False)
    lint_p.add_argument("--min-severity", type=str, default="warning",
                        choices=["error", "warning", "info"])

    # ingest
    ingest_p = subparsers.add_parser("ingest", help="摄入文件")
    ingest_p.add_argument("--workspace", type=Path, default=Path.cwd())
    ingest_p.add_argument("--file", type=Path)
    ingest_p.add_argument("--owner", type=str, default="user-default")
    ingest_p.add_argument("--scope", type=str, default="shared")
    ingest_p.add_argument("--scan-inbox", action="store_true", default=False)
    ingest_p.add_argument("--force", action="store_true", default=False)
    ingest_p.add_argument("--cleanup", type=str, default=None, choices=["processed"])
    ingest_p.add_argument("--json", action="store_true", default=False)
    ingest_sp = ingest_p.add_subparsers(dest="ingest_command")
    precheck_p = ingest_sp.add_parser("precheck-disk", help="评估导入文件的磁盘空间需求")
    precheck_p.add_argument("--workspace", type=Path, default=Path.cwd())
    precheck_p.add_argument("--dir", type=Path, default=None)
    precheck_p.add_argument("--files", type=Path, nargs="*", default=None)
    precheck_p.add_argument("--json", action="store_true", default=False)

    # ingest-large
    il_p = subparsers.add_parser("ingest-large", help="大文件队列管理")
    il_sp = il_p.add_subparsers(dest="ingest_large_command")
    il_enqueue = il_sp.add_parser("enqueue", help="手动将文件加入大文件队列")
    il_enqueue.add_argument("--workspace", type=Path, default=Path.cwd())
    il_enqueue.add_argument("--file", type=Path, required=True)
    il_enqueue.add_argument("--owner", type=str, default="user-default")
    il_enqueue.add_argument("--scope", type=str, default="shared")
    il_enqueue.add_argument("--json", action="store_true", default=False)
    il_worker = il_sp.add_parser("worker", help="启动大文件 worker（单次处理一个任务）")
    il_worker.add_argument("--workspace", type=Path, default=Path.cwd())
    il_worker.add_argument("--once", action="store_true", default=True)
    il_worker.add_argument("--json", action="store_true", default=False)
    il_status = il_sp.add_parser("status", help="查看大文件队列状态")
    il_status.add_argument("--workspace", type=Path, default=Path.cwd())
    il_status.add_argument("--json", action="store_true", default=False)

    # query
    query_p = subparsers.add_parser("query", help="查询知识库")
    query_p.add_argument("--workspace", type=Path, default=Path.cwd())
    query_p.add_argument("--question", type=str, default="")
    query_p.add_argument("--scope", type=str, default="shared")
    query_p.add_argument("--json", action="store_true", default=False)

    # index
    index_p = subparsers.add_parser("index", help="索引管理")
    index_sp = index_p.add_subparsers(dest="index_command")
    index_rebuild = index_sp.add_parser("rebuild", help="重建索引")
    index_rebuild.add_argument("--workspace", type=Path, default=Path.cwd())
    index_rebuild.add_argument("--json", action="store_true", default=False)

    # backup
    backup_p = subparsers.add_parser("backup", help="备份管理")
    backup_sp = backup_p.add_subparsers(dest="backup_command")
    backup_create = backup_sp.add_parser("create", help="创建备份")
    backup_create.add_argument("--workspace", type=Path, default=Path.cwd())
    backup_create.add_argument("--reason", type=str, default="manual")
    backup_create.add_argument("--json", action="store_true", default=False)

    # restore
    restore_p = subparsers.add_parser("restore", help="恢复管理")
    restore_sp = restore_p.add_subparsers(dest="restore_command")
    restore_verify = restore_sp.add_parser("verify", help="验证恢复")
    restore_verify.add_argument("--workspace", type=Path, default=Path.cwd())
    restore_verify.add_argument("--snapshot", type=str, default="")
    restore_verify.add_argument("--json", action="store_true", default=False)

    # maintenance
    maint_p = subparsers.add_parser("maintenance", help="维护管理")
    maint_sp = maint_p.add_subparsers(dest="maintenance_command")
    maint_cleanup = maint_sp.add_parser("cleanup", help="清理临时文件")
    maint_cleanup.add_argument("--workspace", type=Path, default=Path.cwd())
    maint_cleanup.add_argument("--keep-snapshots", type=int, default=5)
    maint_cleanup.add_argument("--json", action="store_true", default=False)

    # review
    review_p = subparsers.add_parser("review", help="审核管理")
    review_sp = review_p.add_subparsers(dest="review_command")
    review_list = review_sp.add_parser("list", help="列出审核任务")
    review_list.add_argument("--workspace", type=Path, default=Path.cwd())
    review_list.add_argument("--json", action="store_true", default=False)
    review_answer = review_sp.add_parser("answer", help="回答审核任务")
    review_answer.add_argument("--workspace", type=Path, default=Path.cwd())
    review_answer.add_argument("--id", type=str, required=True, dest="review_id")
    review_answer.add_argument("--action", type=str, required=True)
    review_answer.add_argument("--comment", type=str, default="")
    review_answer.add_argument("--json", action="store_true", default=False)

    try:
        args = parser.parse_args(argv)
    except (argparse.ArgumentError, SystemExit) as e:
        return _error_result(
            error_code="UNKNOWN_COMMAND",
            message=f"无效命令参数: {e}",
            retryable=False,
        )

    if not args.command:
        return _error_result(
            error_code="UNKNOWN_COMMAND",
            message="未知命令",
            retryable=False,
        )

    try:
        return _dispatch(args)
    except argparse.ArgumentError as e:
        return _error_result(
            error_code="UNKNOWN_COMMAND",
            message=str(e),
            retryable=False,
        )
    except SystemExit as e:
        if e.code == 0:
            return {"ok": True}
        return _error_result(
            error_code="INTERNAL_ERROR",
            message=f"CLI 参数错误 (exit={e.code})",
            retryable=False,
        )
    except (ValueError, FileNotFoundError, OSError) as e:
        # 已知的输入/IO 错误，不可重试
        return _error_result(
            error_code="INVALID_INPUT",
            message=str(e),
            retryable=False,
        )
    except Exception as e:
        # 未知编程错误，记录完整栈以便排查，不向调用方暴露内部细节
        logger.error("未预期错误", exc_info=True)
        return _error_result(
            error_code="INTERNAL_ERROR",
            message=f"内部错误: {type(e).__name__}",
            retryable=True,
        )


def _dispatch(args: argparse.Namespace) -> dict | list:
    cmd = args.command

    if cmd == "init":
        return _cmd_init(args)
    elif cmd == "health":
        return _cmd_health(args)
    elif cmd == "lint":
        return _cmd_lint(args)
    elif cmd == "ingest":
        return _cmd_ingest(args)
    elif cmd == "ingest-large":
        return _cmd_ingest_large(args)
    elif cmd == "query":
        return _cmd_query(args)
    elif cmd == "index":
        return _cmd_index(args)
    elif cmd == "backup":
        return _cmd_backup(args)
    elif cmd == "restore":
        return _cmd_restore(args)
    elif cmd == "review":
        return _cmd_review(args)
    elif cmd == "maintenance":
        return _cmd_maintenance(args)
    else:
        return _error_result(
            error_code="UNKNOWN_COMMAND",
            message=f"未知命令: {cmd}",
            retryable=False,
        )


# ================================================================
# 内部辅助函数
# ================================================================

def _prune_staging_snapshots(workspace: Path, keep: int) -> None:
    """清理 .state/staging/ 中的旧快照，只保留最近 keep 个 .tar.gz。"""
    staging = workspace / ".state" / "staging"
    if not staging.exists():
        return
    tars = sorted(
        staging.glob("*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in tars[keep:]:
        old.unlink(missing_ok=True)


# ================================================================
# 命令实现
# ================================================================

def _cmd_init(args: argparse.Namespace) -> dict:
    ws: Path = args.workspace
    ws.mkdir(parents=True, exist_ok=True)

    dirs = [
        "meta",
        "raw/inbox/users", "raw/inbox/teams",
        "raw/archive", "raw/extracted",
        "wiki/entities", "wiki/concepts", "wiki/sources",
        "wiki/synthesis", "wiki/queries",
        ".state/operations", ".state/review_tasks",
        ".state/health", ".state/staging",
    ]
    for d in dirs:
        (ws / d).mkdir(parents=True, exist_ok=True)

    defaults = {
        "meta/purpose.md": "# 知识库目标\n\n请编辑此文件描述你的知识库目标。\n",
        "wiki/index.md": "# Index\n",
        "wiki/overview.md": "# Overview\n",
        "wiki/log.md": "# Log\n",
    }
    for rel, content in defaults.items():
        p = ws / rel
        if not p.exists():
            p.write_text(content, encoding="utf-8")

    return {"ok": True}


def _cmd_health(args: argparse.Namespace) -> dict:
    from mini_note.lint.health import run_health_check
    return run_health_check(args.workspace)


def _cmd_lint(args: argparse.Namespace) -> dict:
    from mini_note.lint.engine import LintEngine

    SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}
    min_severity = getattr(args, "min_severity", "warning")
    min_rank = SEVERITY_RANK.get(min_severity, 1)

    total_before = 0
    total_after = 0

    def _filter(items: list[dict]) -> list[dict]:
        nonlocal total_before, total_after
        total_before += len(items)
        if not items:
            return items
        filtered = [it for it in items
                    if SEVERITY_RANK.get(it.get("severity", "info"), 2) <= min_rank]
        total_after += len(filtered)
        return filtered

    engine = LintEngine(args.workspace)
    return {
        "ok": True,
        "broken_wikilinks": _filter(engine.check_broken_wikilinks()),
        "orphan_pages": _filter(engine.check_orphan_pages()),
        "claim_grounding": _filter(engine.check_claim_grounding()),
        "contradictions": _filter(engine.check_contradictions()),
        "partial_misuse": _filter(engine.check_partial_misuse()),
        "lint_summary": {
            "min_severity": min_severity,
            "total_before_filter": total_before,
            "total_after_filter": total_after,
            "suppressed_count": total_before - total_after,
        },
    }


def _cmd_ingest(args: argparse.Namespace) -> dict:
    from mini_note.ingest.pipeline import IngestPipeline

    if args.ingest_command == "precheck-disk":
        return _cmd_precheck_disk(args)

    if args.scan_inbox:
        return _cmd_ingest_scan(args)

    if not args.file:
        return _error_result(
            error_code="MISSING_FILE",
            message="请指定 --file 或使用 --scan-inbox",
            retryable=False,
        )

    pipeline = IngestPipeline(args.workspace)
    result = pipeline.run(
        file_path=args.file,
        owner_id=args.owner,
        scope=args.scope,
    )
    out = {
        "ok": result.ok,
        "operation_id": result.operation_id,
        "source_id": result.source_id,
        "ingestion_status": result.ingestion_status,
        "backup_status": result.backup_status,
        "source_page_path": result.source_page_path,
        "dedup_status": result.dedup_status,
    }
    if not result.ok:
        out["error_code"] = result.error_code
        out["message"] = result.message
        out["retryable"] = result.retryable
    return out


def _cmd_precheck_disk(args: argparse.Namespace) -> dict:
    """评估导入文件的磁盘空间需求。"""
    from mini_note.ingest.pipeline import check_import_disk_space

    ws: Path = args.workspace

    # 收集文件路径
    file_paths: list[Path] = []
    if args.dir:
        src_dir = args.dir
        if not src_dir.is_dir():
            return _error_result(
                error_code="INVALID_INPUT",
                message=f"目录不存在: {src_dir}",
                retryable=False,
            )
        for f in src_dir.rglob("*"):
            if f.is_file() and not f.name.startswith(".") and not f.name.endswith(".gitkeep"):
                file_paths.append(f)
    elif args.files:
        for f in args.files:
            if f.is_file():
                file_paths.append(f)
            else:
                return _error_result(
                    error_code="INVALID_INPUT",
                    message=f"文件不存在: {f}",
                    retryable=False,
                )
    else:
        return _error_result(
            error_code="MISSING_INPUT",
            message="请指定 --dir 或 --files",
            retryable=False,
        )

    if not file_paths:
        import shutil
        usage = shutil.disk_usage(ws)
        return {
            "ok": True,
            "file_count": 0,
            "total_size_bytes": 0,
            "available_bytes": usage.free,
            "estimated_need_bytes": 0,
            "safe_margin_bytes": 100 * 1024 * 1024,
            "would_fit": True,
            "message": "没有可评估的文件",
            "time_estimation": {
                "total_estimated_seconds": 0,
                "estimated_human": "约 0 秒",
                "by_category": {},
            },
        }

    from mini_note.ingest.progress import estimate_batch_time, format_duration

    disk_result = check_import_disk_space(ws, file_paths)
    time_est = estimate_batch_time(file_paths)
    disk_result["time_estimation"] = {
        "total_estimated_seconds": time_est["total_estimated_seconds"],
        "estimated_human": format_duration(time_est["total_estimated_seconds"]),
        "by_category": time_est["by_category"],
    }
    return disk_result


def _cmd_ingest_scan(args: argparse.Namespace) -> dict:
    """扫描 inbox 目录批量摄入（含磁盘空间预检、时间预估、进度追踪）。"""
    import shutil
    from mini_note.ingest.pipeline import (
        IngestPipeline, check_import_disk_space,
        _acquire_lock, _release_lock,
    )
    from mini_note.ingest.progress import (
        BatchProgressTracker, estimate_batch_time, format_duration,
    )

    ws: Path = args.workspace
    inbox_dir = ws / "raw" / "inbox"
    if not inbox_dir.exists():
        return {"ok": True, "results": [], "message": "inbox 目录不存在"}

    # 收集待处理文件（排除 processed/ 已处理目录）
    pending_files = []
    for f in sorted(inbox_dir.rglob("*")):
        if not f.is_file():
            continue
        if f.name.startswith(".") or f.name.endswith(".gitkeep"):
            continue
        # 排除 raw/inbox/processed/ 根下的历史文件
        rel_parts = f.relative_to(inbox_dir).parts
        if rel_parts and rel_parts[0] == "processed":
            continue
        pending_files.append(f)

    if not pending_files:
        return {"ok": True, "results": [], "message": "inbox 中没有待处理文件"}

    # 磁盘空间预检
    if not args.force:
        disk_check = check_import_disk_space(ws, pending_files)
        if not disk_check["would_fit"]:
            return _error_result(
                error_code="DISK_SPACE_LOW",
                message=(
                    f"磁盘空间不足：{disk_check['file_count']} 个文件 "
                    f"（共 {disk_check['total_size_bytes'] / 1024 / 1024:.1f} MB），"
                    f"预估需求 {disk_check['estimated_need_bytes'] / 1024 / 1024:.1f} MB，"
                    f"当前可用 {disk_check['available_bytes'] / 1024 / 1024:.1f} MB。"
                    f"使用 --force 可强制导入。"
                ),
                retryable=False,
            )

    # 初始化进度追踪器
    tracker = BatchProgressTracker(pending_files)
    init_est = tracker.initial_estimate

    # 向 stderr 输出初始预估（OpenClaw 可解析反馈用户）
    from datetime import datetime, timezone, timedelta
    CST = timezone(timedelta(hours=8))
    print(json.dumps({
        "type": "estimation",
        "ts": datetime.now(CST).isoformat(),
        "total_files": len(pending_files),
        "estimated_seconds": init_est["total_estimated_seconds"],
        "estimated_human": format_duration(init_est["total_estimated_seconds"]),
        "by_category": init_est["by_category"],
    }, ensure_ascii=False), file=sys.stderr)
    sys.stderr.flush()

    results = []
    dedup_stats = {"new": 0, "existing": 0, "queued_large_file": 0, "failed": 0}
    pipeline = IngestPipeline(ws)
    for f in pending_files:
        start = time.monotonic()
        r = pipeline.run(
            file_path=f,
            owner_id=args.owner,
            scope=args.scope,
            rebuild_index=False,       # 批次末尾统一重建
            run_health_check=False,    # 批次末尾统一检查
        )
        elapsed = time.monotonic() - start

        item = {
            "file": str(f.relative_to(ws)),
            "ok": r.ok,
            "source_id": r.source_id,
            "ingestion_status": r.ingestion_status,
            "dedup_status": r.dedup_status,
        }
        if not r.ok:
            item["error_code"] = r.error_code
            item["message"] = r.message
            item["retryable"] = r.retryable
        results.append(item)
        if r.ok:
            dedup_stats[r.dedup_status] = dedup_stats.get(r.dedup_status, 0) + 1
        else:
            dedup_stats["failed"] += 1

        snapshot = tracker.file_complete(ok=r.ok, elapsed_seconds=elapsed)
        if snapshot is not None:
            print(json.dumps(snapshot, ensure_ascii=False), file=sys.stderr)
            sys.stderr.flush()

    # 批次末尾：统一重建索引 + 健康检查（持有批次锁防止并发写）
    _acquire_lock(ws)
    try:
        indexed = False
        sqlite_counts = {}
        index_error = None
        try:
            from mini_note.indexer import Indexer
            Indexer(ws).rebuild()
            indexed = True
            db_path = ws / ".state" / "notes.db"
            if db_path.exists():
                import sqlite3
                conn = sqlite3.connect(str(db_path))
                try:
                    for table in ("sources", "pages", "claims"):
                        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                        sqlite_counts[table] = row[0] if row else 0
                finally:
                    conn.close()
        except Exception as e:
            logger.error(f"索引重建失败: {e}", exc_info=True)
            index_error = str(e)

        if index_error is not None:
            return {
                "ok": False,
                "error_code": "INDEX_REBUILD_FAILED",
                "message": f"索引重建失败: {index_error}",
                "retryable": True,
                "results": results,
                "indexed": False,
                "cleaned_count": 0,
                "sqlite_counts": sqlite_counts,
                "dedup_summary": dedup_stats,
                "progress_summary": tracker.final_summary(),
            }

        from mini_note.lint.health import run_health_check
        health = run_health_check(ws)
        health_ok = health.get("ok", False)
        if not health_ok:
            return {
                "ok": False,
                "error_code": "HEALTH_CHECK_FAILED",
                "message": "批量摄入后健康检查失败",
                "retryable": True,
                "results": results,
                "indexed": indexed,
                "cleaned_count": 0,
                "health": health,
                "sqlite_counts": sqlite_counts,
                "dedup_summary": dedup_stats,
                "progress_summary": tracker.final_summary(),
            }

        # 清理已处理的 inbox 文件（仅移动成功摄入的文件）
        cleaned_count = 0
        if getattr(args, "cleanup", None) == "processed":
            success_paths = set()
            for r, f in zip(results, pending_files):
                if r["ok"] and r.get("dedup_status") != "queued_large_file":
                    success_paths.add(f)
            today = datetime.now(CST).strftime("%Y%m%d")
            processed_dir = inbox_dir / "processed" / today
            processed_dir.mkdir(parents=True, exist_ok=True)
            for f in pending_files:
                if f not in success_paths or not f.exists():
                    continue
                dest = processed_dir / f.name
                if dest.exists():
                    ts = datetime.now(CST).strftime("%H%M%S")
                    dest = processed_dir / f"{f.stem}-{ts}{f.suffix}"
                shutil.move(str(f), str(dest))
                cleaned_count += 1

        return {
            "ok": True,
            "results": results,
            "indexed": indexed,
            "health_ok": health_ok,
            "sqlite_counts": sqlite_counts,
            "dedup_summary": dedup_stats,
            "cleaned_count": cleaned_count,
            "progress_summary": tracker.final_summary(),
        }
    finally:
        _release_lock(ws)


def _cmd_ingest_large(args: argparse.Namespace) -> dict:
    ws: Path = args.workspace
    cmd = args.ingest_large_command

    if cmd == "enqueue":
        from mini_note.ingest.large_file_queue import enqueue
        op_id = enqueue(ws, args.file, args.owner, args.scope, "manual", "手动入队")
        return {"ok": True, "operation_id": op_id, "message": "已加入大文件队列"}

    elif cmd == "worker":
        from mini_note.ingest.large_file_queue import run_large_worker
        return run_large_worker(ws, once=True)

    elif cmd == "status":
        from mini_note.ingest.large_file_queue import status
        return {"ok": True, **status(ws)}

    return _error_result(
        error_code="UNKNOWN_COMMAND",
        message=f"未知 ingest-large 子命令: {cmd}",
        retryable=False,
    )


def _cmd_query(args: argparse.Namespace) -> dict:
    from mini_note.query.engine import QueryEngine
    engine = QueryEngine(args.workspace)
    return engine.search(args.question, scope=args.scope)


def _cmd_index(args: argparse.Namespace) -> dict:
    if args.index_command == "rebuild":
        from mini_note.indexer import Indexer
        idx = Indexer(args.workspace)
        idx.rebuild()
        return {"ok": True}
    return _error_result(
        error_code="UNKNOWN_COMMAND",
        message=f"未知 index 子命令: {args.index_command}",
        retryable=False,
    )


def _cmd_backup(args: argparse.Namespace) -> dict:
    if args.backup_command == "create":
        from datetime import datetime, timezone, timedelta
        from mini_note.backup.snapshot import create_snapshot
        from mini_note.backup.status import BackupLog
        import secrets

        ws: Path = args.workspace

        # 检测 OSS 配置，无 OSS 则跳过备份
        oss_configured = False
        try:
            from mini_note.backup.oss import OSSBackup
            oss = OSSBackup()
            oss_configured = oss.enabled
        except Exception:
            pass

        if not oss_configured:
            return {
                "ok": True,
                "mode": "local",
                "skipped": True,
                "message": "OSS 未配置，本次没有创建远程备份。请不要把当前状态视为已容灾。",
            }

        # 有 OSS，创建快照并上传
        now = datetime.now(timezone(timedelta(hours=8)))
        snapshot_id = f"snap-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}-{secrets.token_hex(4)}"

        snapshot_dir = ws / ".state" / "staging"
        snapshot_path = snapshot_dir / f"{snapshot_id}.tar.gz"
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)

        sha = create_snapshot(ws, snapshot_path, compression="gzip")

        # OSS 上传
        oss_result = None
        try:
            oss_result = oss.upload(snapshot_path, snapshot_id)
        except Exception:
            oss_result = {"ok": False, "error": "OSS 上传异常"}

        oss_ok = oss_result.get("ok", False) if oss_result else False
        oss_key = oss_result.get("oss_key", "") if oss_result else ""

        # 保留最近 7 个本地快照作为 fallback
        _prune_staging_snapshots(ws, keep=7)

        log_status = "success" if oss_ok else "failed"
        log = BackupLog(ws / ".state" / "backup_log.jsonl")
        log.record(
            oss_object=oss_key or snapshot_id,
            sha256=sha,
            status=log_status,
            operation_id=snapshot_id,
            error=None if oss_ok else (oss_result.get("error") if oss_result else None),
        )

        result: dict = {
            "ok": oss_ok,
            "mode": "oss",
            "snapshot_id": snapshot_id,
            "sha256": sha,
            "oss_ok": oss_ok,
            "local_path": str(snapshot_path),
            "reason": args.reason,
        }
        if oss_key:
            result["oss_key"] = oss_key
        if not oss_ok:
            result["error_code"] = "OSS_UPLOAD_FAILED"
            result["message"] = oss_result.get("error", "OSS 上传失败") if oss_result else "OSS 上传失败"
            result["retryable"] = True
        return result

    return _error_result(
        error_code="UNKNOWN_COMMAND",
        message=f"未知 backup 子命令: {args.backup_command}",
        retryable=False,
    )


def _cmd_restore(args: argparse.Namespace) -> dict:
    if args.restore_command == "verify":
        ws: Path = args.workspace
        snapshot_ref = args.snapshot

        import tempfile
        from mini_note.backup.snapshot import restore_snapshot
        from mini_note.lint.health import run_health_check
        from mini_note.indexer import Indexer

        restore_dir = Path(tempfile.mkdtemp(prefix="mini-note-restore-"))

        if snapshot_ref:
            local_path = Path(snapshot_ref)
            if local_path.exists():
                snapshot_path = local_path
            elif snapshot_ref.startswith(("/", "~", ".")):
                # 看起来像本地路径，不尝试 OSS
                return _error_result(
                    error_code="SNAPSHOT_NOT_FOUND",
                    message=f"快照文件不存在: {snapshot_ref}",
                    retryable=False,
                )
            else:
                # 不像本地路径，尝试从 OSS 下载
                snapshot_path = None
                try:
                    from mini_note.backup.oss import OSSBackup
                    oss = OSSBackup()
                    if oss.enabled:
                        target = restore_dir / "snapshot.tar.gz"
                        dl = oss.download(snapshot_ref, target)
                        if dl["ok"]:
                            snapshot_path = target
                        else:
                            return _error_result(
                                error_code="OSS_DOWNLOAD_FAILED",
                                message=dl.get("error", "下载失败"),
                                retryable=True,
                            )
                except ImportError:
                    pass

                if snapshot_path is None:
                    return _error_result(
                        error_code="SNAPSHOT_NOT_FOUND",
                        message=f"快照不存在（OSS 未找到）: {snapshot_ref}",
                        retryable=False,
                    )
        else:
            return _error_result(
                error_code="MISSING_SNAPSHOT",
                message="请指定 --snapshot（本地路径或 OSS key）",
                retryable=False,
            )

        try:
            restore_snapshot(snapshot_path, restore_dir)

            idx = Indexer(restore_dir)
            idx.rebuild()

            health = run_health_check(restore_dir)
        finally:
            import shutil
            shutil.rmtree(restore_dir, ignore_errors=True)

        return {
            "ok": health.get("ok", False),
            "health": health,
            "snapshot": str(snapshot_path),
        }
    return _error_result(
        error_code="UNKNOWN_COMMAND",
        message=f"未知 restore 子命令: {args.restore_command}",
        retryable=False,
    )


def _cmd_review(args: argparse.Namespace) -> dict | list:
    from mini_note.review.engine import ReviewEngine
    engine = ReviewEngine(args.workspace)
    if args.review_command == "list":
        return engine.list_tasks()
    elif args.review_command == "answer":
        return engine.answer(
            task_id=args.review_id,
            action=args.action,
            comment=args.comment,
        )
    return _error_result(
        error_code="UNKNOWN_COMMAND",
        message=f"未知 review 子命令: {args.review_command}",
        retryable=False,
    )


def _cmd_maintenance(args: argparse.Namespace) -> dict:
    if args.maintenance_command == "cleanup":
        from shutil import rmtree

        ws: Path = args.workspace
        staging = ws / ".state" / "staging"

        # 清理旧快照
        _prune_staging_snapshots(ws, keep=args.keep_snapshots)

        # 清理 tmp 后缀（原子写入残留）
        for tmp in staging.rglob("*.tmp"):
            tmp.unlink(missing_ok=True)

        # 清理空目录
        removed_dirs = []
        for d in sorted(staging.rglob("*"), reverse=True):
            if d.is_dir() and d != staging and not any(d.iterdir()):
                d.rmdir()
                rel = str(d.relative_to(ws))
                removed_dirs.append(rel)

        # 清理过期锁文件
        from mini_note.ingest.pipeline import _cleanup_stale_locks
        cleaned_locks = _cleanup_stale_locks(ws)

        # 统计剩余快照
        remaining = sorted(staging.glob("*.tar.gz"))
        return {
            "ok": True,
            "staging_snapshots": len(remaining),
            "removed_dirs": removed_dirs,
            "cleaned_locks": cleaned_locks,
        }
    return _error_result(
        error_code="UNKNOWN_COMMAND",
        message=f"未知 maintenance 子命令: {args.maintenance_command}",
        retryable=False,
    )


if __name__ == "__main__":
    result = main()
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    if isinstance(result, dict) and result.get("ok") is False:
        sys.exit(1)
    sys.exit(0)
