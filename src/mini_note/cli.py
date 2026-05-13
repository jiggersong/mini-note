"""CLI 入口 — argparse 命令解析、--json 输出、错误格式。

所有命令支持 --json 标志输出结构化结果。
错误输出包含 ok/error_code/message/operation_id/retryable 标准字段。
"""

import argparse
import json
import sys
from pathlib import Path


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

    # ingest
    ingest_p = subparsers.add_parser("ingest", help="摄入文件")
    ingest_p.add_argument("--workspace", type=Path, default=Path.cwd())
    ingest_p.add_argument("--file", type=Path)
    ingest_p.add_argument("--owner", type=str, default="user-default")
    ingest_p.add_argument("--scope", type=str, default="shared")
    ingest_p.add_argument("--scan-inbox", action="store_true", default=False)
    ingest_p.add_argument("--json", action="store_true", default=False)

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
    backup_create.add_argument("--keep-local", action="store_true", default=False)
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
    except Exception as e:
        return _error_result(
            error_code="INTERNAL_ERROR",
            message=str(e),
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
    engine = LintEngine(args.workspace)
    return {
        "ok": True,
        "broken_wikilinks": engine.check_broken_wikilinks(),
        "orphan_pages": engine.check_orphan_pages(),
        "claim_grounding": engine.check_claim_grounding(),
        "contradictions": engine.check_contradictions(),
        "partial_misuse": engine.check_partial_misuse(),
    }


def _cmd_ingest(args: argparse.Namespace) -> dict:
    from mini_note.ingest.pipeline import IngestPipeline

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
    }
    if not result.ok:
        out["error_code"] = result.error_code
        out["message"] = result.message
        out["retryable"] = result.retryable
    return out


def _cmd_ingest_scan(args: argparse.Namespace) -> dict:
    """扫描 inbox 目录批量摄入。"""
    from mini_note.ingest.pipeline import IngestPipeline

    ws: Path = args.workspace
    inbox_dir = ws / "raw" / "inbox"
    if not inbox_dir.exists():
        return {"ok": True, "results": [], "message": "inbox 目录不存在"}

    results = []
    pipeline = IngestPipeline(ws)
    for f in sorted(inbox_dir.rglob("*")):
        if not f.is_file():
            continue
        if f.name.startswith(".") or f.name.endswith(".gitkeep"):
            continue
        r = pipeline.run(
            file_path=f,
            owner_id=args.owner,
            scope=args.scope,
        )
        item = {
            "file": str(f.relative_to(ws)),
            "ok": r.ok,
            "source_id": r.source_id,
            "ingestion_status": r.ingestion_status,
        }
        if not r.ok:
            item["error_code"] = r.error_code
            item["message"] = r.message
            item["retryable"] = r.retryable
        results.append(item)

    return {"ok": True, "results": results}


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
        from mini_note.ingest.pipeline import _prune_staging_snapshots
        import secrets

        ws: Path = args.workspace
        now = datetime.now(timezone(timedelta(hours=8)))
        snapshot_id = f"snap-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}-{secrets.token_hex(4)}"
        snapshot_path = ws / ".state" / "staging" / f"{snapshot_id}.tar.gz"
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)

        sha = create_snapshot(ws, snapshot_path, compression="gzip")

        # OSS 上传（如已配置）
        oss_result = None
        oss_configured = False
        try:
            from mini_note.backup.oss import OSSBackup
            oss = OSSBackup()
            if oss.enabled:
                oss_configured = True
                oss_result = oss.upload(snapshot_path, snapshot_id)
        except Exception:
            oss_result = {"ok": False, "error": "OSS 上传异常"}

        oss_ok = oss_result.get("ok", False) if oss_result else True
        oss_key = oss_result.get("oss_key", "") if oss_result else ""

        # 快照生命周期：OSS 成功则删本地包，本地模式/失败则保留最近 N 个
        keep_local = getattr(args, "keep_local", False)
        if oss_configured and oss_ok and not keep_local:
            # OSS 上传成功，本地临时包已完成使命，删除
            snapshot_path.unlink(missing_ok=True)
        elif oss_configured and not oss_ok:
            # OSS 上传失败，保留本地包作为 fallback，只保留最近 3 个
            _prune_staging_snapshots(ws, keep=3)
        elif not oss_configured and not keep_local:
            # 无 OSS，本地包即唯一备份，保留最近 5 个
            _prune_staging_snapshots(ws, keep=5)

        log = BackupLog(ws / ".state" / "backup_log.jsonl")
        log.record(
            oss_object=oss_key or snapshot_id,
            sha256=sha,
            status="success" if oss_ok else "created",
            operation_id=snapshot_id,
            error=None if oss_ok else oss_result.get("error"),
        )

        return {
            "ok": oss_ok,
            "snapshot_id": snapshot_id,
            "sha256": sha,
            "oss_key": oss_key,
            "oss_ok": oss_ok,
            "reason": args.reason,
        }
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
        from mini_note.ingest.pipeline import _prune_staging_snapshots

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

        # 统计剩余快照
        remaining = sorted(staging.glob("*.tar.gz"))
        return {
            "ok": True,
            "staging_snapshots": len(remaining),
            "removed_dirs": removed_dirs,
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
