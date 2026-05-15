"""
CLI 入口单元测试 — argparse 命令解析、--json 输出、错误格式。

测试目标（v2.4 §15）:
- 所有命令支持 --json
- 错误输出包含 ok/error_code/message/operation_id/retryable
- 所有子命令可解析
"""

import json
from pathlib import Path

import pytest


class TestCLICommands:
    """测试 CLI 命令解析。"""

    def test_init_command(self, tmp_workspace):
        """init 命令初始化 workspace。"""
        from mini_note.cli import main

        result = main(["init", "--workspace", str(tmp_workspace)])
        assert result["ok"] is True

    def test_init_creates_required_dirs(self, tmp_workspace):
        """init 创建全部必要目录。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        for d in ["meta", "raw/archive", "wiki", ".state"]:
            assert (tmp_workspace / d).is_dir(), f"{d} 未创建"

    def test_health_command(self, tmp_workspace):
        """health 命令返回 JSON 报告。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        result = main(["health", "--workspace", str(tmp_workspace), "--json"])
        assert result["ok"] is True
        assert "checks" in result

    def test_lint_command(self, tmp_workspace):
        """lint 命令不崩溃。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        result = main(["lint", "--workspace", str(tmp_workspace), "--changed-only", "--json"])
        assert "broken_wikilinks" in result or "ok" in result

    def test_lint_full_command(self, tmp_workspace):
        """lint --full 命令不崩溃。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        result = main(["lint", "--workspace", str(tmp_workspace), "--full", "--json"])
        assert isinstance(result, dict)

    def test_index_rebuild_command(self, tmp_workspace):
        """index rebuild 命令不崩溃。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        result = main(["index", "rebuild", "--workspace", str(tmp_workspace), "--json"])
        assert result["ok"] is True

    def test_ingest_command(self, tmp_workspace, sample_md_file):
        """ingest 命令摄入文件。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        result = main([
            "ingest", "--workspace", str(tmp_workspace),
            "--file", str(sample_md_file),
            "--owner", "user-default",
            "--json",
        ])
        assert result["ok"] is True

    def test_query_command(self, tmp_workspace):
        """query 命令返回 JSON 素材。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        result = main([
            "query", "--workspace", str(tmp_workspace),
            "--question", "ECS 性能",
            "--json",
        ])
        assert "pages" in result
        assert "claims" in result

    def test_review_list_command(self, tmp_workspace):
        """review list 命令不崩溃。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        result = main(["review", "list", "--workspace", str(tmp_workspace), "--json"])
        assert isinstance(result, list)

    def test_unknown_command_errors(self, tmp_workspace):
        """未知命令返回错误。"""
        from mini_note.cli import main

        result = main(["unknown_cmd", "--workspace", str(tmp_workspace)])
        assert result["ok"] is False

    def test_backup_create_command(self, tmp_workspace):
        """backup create 无 OSS 时跳过。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        result = main(["backup", "create", "--workspace", str(tmp_workspace), "--reason", "test", "--json"])
        assert result["ok"] is True
        assert result["mode"] == "local"
        assert result.get("skipped") is True
        assert "message" in result
        assert "snapshot_id" not in result
        assert "local_path" not in result

    def test_backup_create_local_mode_fields(self, tmp_workspace):
        """无 OSS 时 backup create 返回 skipped=true，不含 oss_key。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        result = main(["backup", "create", "--workspace", str(tmp_workspace), "--reason", "test", "--json"])
        assert result["mode"] == "local"
        assert result.get("skipped") is True
        assert "oss_key" not in result
        assert "local_path" not in result

    def test_prune_staging_snapshots(self, tmp_workspace):
        """_prune_staging_snapshots 保留最多指定数量的快照。"""
        from mini_note.cli import _prune_staging_snapshots

        staging = tmp_workspace / ".state" / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        for i in range(7):
            (staging / f"snap-20260101-{i:06d}-abcd.tar.gz").write_bytes(b"fake")

        _prune_staging_snapshots(tmp_workspace, keep=5)
        remaining = list(staging.glob("*.tar.gz"))
        assert len(remaining) <= 5

    def test_backup_create_oss_upload_failure(self, tmp_workspace, monkeypatch):
        """OSS 已配置但上传失败时返回 ok=false, OSS_UPLOAD_FAILED。"""
        from mini_note.cli import main

        # 设置 OSS 环境变量使 enabled=True
        monkeypatch.setenv("OSS_ENDPOINT", "https://oss-cn-hangzhou.aliyuncs.com")
        monkeypatch.setenv("OSS_BUCKET", "test-bucket")
        monkeypatch.setenv("OSS_ACCESS_KEY_ID", "test-key")
        monkeypatch.setenv("OSS_ACCESS_KEY_SECRET", "test-secret")

        main(["init", "--workspace", str(tmp_workspace)])

        # Mock OSSBackup.upload 返回失败
        import mini_note.backup.oss as oss_module
        original_upload = oss_module.OSSBackup.upload

        def fake_upload(self, snapshot_path, snapshot_id):
            return {"ok": False, "error": "mock upload failure"}

        monkeypatch.setattr(oss_module.OSSBackup, "upload", fake_upload)

        result = main([
            "backup", "create",
            "--workspace", str(tmp_workspace),
            "--reason", "failure-test",
            "--json",
        ])
        assert result["ok"] is False
        assert result["error_code"] == "OSS_UPLOAD_FAILED"
        assert result["retryable"] is True
        assert result["oss_ok"] is False
        assert result["mode"] == "oss"
        assert "local_path" in result
        assert "sha256" in result
        # 本地 fallback 文件应存在
        from pathlib import Path
        assert Path(result["local_path"]).exists()

    def test_review_answer_command(self, tmp_workspace):
        """review answer 命令执行审核动作。"""
        from mini_note.cli import main
        from mini_note.review.engine import ReviewEngine

        main(["init", "--workspace", str(tmp_workspace)])
        engine = ReviewEngine(tmp_workspace)
        task_id = engine.create_task(
            severity="high",
            reason="测试",
            question_for_user="确认？",
            recommended_action="keep_both_as_conflict",
            allowed_actions=["keep_both_as_conflict", "mark_old_claim_deprecated"],
            related_claims=[],
        )

        result = main([
            "review", "answer",
            "--workspace", str(tmp_workspace),
            "--id", task_id,
            "--action", "keep_both_as_conflict",
            "--comment", "已确认",
            "--json",
        ])
        assert result["ok"] is True
        assert result["review_id"] == task_id

    def test_ingest_scan_inbox_command(self, tmp_workspace, sample_md_file):
        """ingest --scan-inbox 扫描 inbox 目录。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        result = main([
            "ingest", "--workspace", str(tmp_workspace),
            "--scan-inbox",
            "--owner", "user-default",
            "--json",
        ])
        assert result["ok"] is True
        assert "results" in result


class TestCLIErrorFormat:
    """测试 CLI 错误输出格式。"""

    def test_error_format(self):
        """错误输出包含标准字段。"""
        from mini_note.cli import _error_result

        err = _error_result(
            error_code="BACKUP_PENDING",
            message="OSS backup failed",
            operation_id="op-test",
            retryable=True,
        )
        assert err["ok"] is False
        assert err["error_code"] == "BACKUP_PENDING"
        assert err["retryable"] is True
        assert "operation_id" in err

    def test_json_output_enabled(self, tmp_workspace):
        """--json 标志启用 JSON 输出。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        result = main([
            "health", "--workspace", str(tmp_workspace), "--json",
        ])
        assert isinstance(result, dict)


class TestScanInboxCleanup:
    """inbox 扫描排除 processed/ 与 cleanup 只移动成功文件。"""

    def test_scan_excludes_processed_dir(self, tmp_workspace):
        """raw/inbox/processed/ 下的文件不被扫描。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        inbox = tmp_workspace / "raw" / "inbox" / "users"
        inbox.mkdir(parents=True, exist_ok=True)
        processed = tmp_workspace / "raw" / "inbox" / "processed" / "20260514"
        processed.mkdir(parents=True, exist_ok=True)

        # 在 processed/ 写入文件
        old_file = processed / "old.md"
        old_file.write_text("# old")
        # 在 users/ 写入待处理文件
        new_file = inbox / "new.md"
        new_file.write_text("# new")

        result = main([
            "ingest", "--workspace", str(tmp_workspace),
            "--scan-inbox", "--json",
        ])
        assert result["ok"] is True
        # processed/ 下文件不应被扫描
        files = [r["file"] for r in result.get("results", [])]
        assert "raw/inbox/processed/20260514/old.md" not in files
        assert any("new.md" in f for f in files)

    def test_cleanup_keeps_failed_file_in_inbox(self, tmp_workspace):
        """失败文件不被 cleanup 移走。symlink 会被拒绝。"""
        from mini_note.cli import main
        import os

        main(["init", "--workspace", str(tmp_workspace)])
        inbox = tmp_workspace / "raw" / "inbox" / "users"
        inbox.mkdir(parents=True, exist_ok=True)

        # 正常文件
        good = inbox / "good.md"
        good.write_text("# good file")
        # 符号链接会被拒绝
        bad_link = inbox / "bad_link.md"
        target = tmp_workspace / "target.md"
        target.write_text("target")
        os.symlink(str(target), str(bad_link))

        result = main([
            "ingest", "--workspace", str(tmp_workspace),
            "--scan-inbox", "--cleanup", "processed", "--json",
        ])
        # good.md 应被移走，symlink 应留在 inbox
        assert not good.exists(), "成功文件应被 cleanup 移走"
        assert bad_link.exists(), "失败文件(symlink)应留在 inbox"

    def test_empty_inbox_returns_early(self, tmp_workspace):
        """空 inbox 目录直接返回。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        result = main([
            "ingest", "--workspace", str(tmp_workspace),
            "--scan-inbox", "--json",
        ])
        assert result["ok"] is True
        assert result.get("message") == "inbox 中没有待处理文件"


class TestScanInboxFailureBranches:
    """批量摄入失败分支：health/index 失败不 cleanup，dedup 失败计数。"""

    def test_health_failure_returns_error_and_keeps_files(self, tmp_workspace, monkeypatch):
        """health check 失败时返回 HEALTH_CHECK_FAILED，不执行 cleanup。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        inbox = tmp_workspace / "raw" / "inbox" / "users"
        inbox.mkdir(parents=True, exist_ok=True)
        test_file = inbox / "note.md"
        test_file.write_text("# test health failure")

        import mini_note.lint.health as health_module
        monkeypatch.setattr(
            health_module, "run_health_check",
            lambda ws: {"ok": False, "checks": [{"name": "db", "passed": False}]},
        )

        result = main([
            "ingest", "--workspace", str(tmp_workspace),
            "--scan-inbox", "--cleanup", "processed", "--json",
        ])
        assert result["ok"] is False
        assert result["error_code"] == "HEALTH_CHECK_FAILED"
        assert result["cleaned_count"] == 0
        assert test_file.exists(), "health 失败时文件应保留在 inbox"

    def test_only_excludes_root_processed_dir(self, tmp_workspace):
        """仅排除 raw/inbox/processed/，用户子目录中名为 processed 的仍扫描。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        # 根 processed/ 文件
        root_processed = tmp_workspace / "raw" / "inbox" / "processed" / "20260515"
        root_processed.mkdir(parents=True, exist_ok=True)
        (root_processed / "skip.md").write_text("# skip")
        # 用户子目录中名为 processed/ 的文件
        user_processed = tmp_workspace / "raw" / "inbox" / "users" / "project" / "processed"
        user_processed.mkdir(parents=True, exist_ok=True)
        (user_processed / "note.md").write_text("# include")

        result = main([
            "ingest", "--workspace", str(tmp_workspace),
            "--scan-inbox", "--json",
        ])
        files = [r["file"] for r in result.get("results", [])]
        assert not any("raw/inbox/processed/" in f for f in files), \
            "根 processed/ 不应被扫描"
        assert any("users/project/processed/note.md" in f for f in files), \
            "用户子目录 processed/ 应被扫描"

    def test_failed_file_in_dedup_summary_failed(self, tmp_workspace):
        """symlink 失败文件计入 dedup_summary.failed，不计入 new。"""
        from mini_note.cli import main
        import os

        main(["init", "--workspace", str(tmp_workspace)])
        inbox = tmp_workspace / "raw" / "inbox" / "users"
        inbox.mkdir(parents=True, exist_ok=True)
        # 正常文件
        (inbox / "good.md").write_text("# good")
        # symlink 失败
        target = tmp_workspace / "target.md"
        target.write_text("target")
        os.symlink(str(target), str(inbox / "bad.md"))

        result = main([
            "ingest", "--workspace", str(tmp_workspace),
            "--scan-inbox", "--json",
        ])
        ds = result.get("dedup_summary", {})
        assert ds.get("failed", 0) >= 1, f"symlink 失败应计入 failed，实际: {ds}"

    def test_index_rebuild_failure_returns_error_and_keeps_files(self, tmp_workspace, monkeypatch):
        """索引重建失败时返回 INDEX_REBUILD_FAILED，不执行 cleanup。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        inbox = tmp_workspace / "raw" / "inbox" / "users"
        inbox.mkdir(parents=True, exist_ok=True)
        test_file = inbox / "note.md"
        test_file.write_text("# test index failure")

        class FakeIndexer:
            def __init__(self, *args, **kwargs):
                pass
            def rebuild(self):
                raise RuntimeError("simulated index crash")

        import mini_note.indexer as idx_mod
        monkeypatch.setattr(idx_mod, "Indexer", FakeIndexer)

        result = main([
            "ingest", "--workspace", str(tmp_workspace),
            "--scan-inbox", "--cleanup", "processed", "--json",
        ])
        assert result["ok"] is False
        assert result["error_code"] == "INDEX_REBUILD_FAILED"
        assert result.get("cleaned_count") == 0
        assert test_file.exists(), "索引失败时文件应保留在 inbox"
