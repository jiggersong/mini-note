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
        """backup create 命令创建快照。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        result = main(["backup", "create", "--workspace", str(tmp_workspace), "--reason", "test", "--json"])
        assert result["ok"] is True
        assert result["mode"] == "local"
        assert "snapshot_id" in result
        assert "sha256" in result
        assert "local_path" in result

    def test_backup_create_local_mode_fields(self, tmp_workspace):
        """无 OSS 时 backup create 返回 mode=local, oss_ok=false。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        result = main(["backup", "create", "--workspace", str(tmp_workspace), "--reason", "test", "--json"])
        assert result["mode"] == "local"
        assert result["oss_ok"] is False
        assert "oss_key" not in result
        assert "local_path" in result

    def test_backup_create_prunes_old_local_snapshots(self, tmp_workspace):
        """本地模式只保留最近 5 个快照。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        staging = tmp_workspace / ".state" / "staging"
        # 先创建 7 个快照
        for i in range(7):
            main(["backup", "create", "--workspace", str(tmp_workspace), "--reason", f"test-{i}", "--json"])

        remaining = list(staging.glob("*.tar.gz"))
        assert len(remaining) <= 5

    def test_backup_create_keep_local_writes_to_backups_dir(self, tmp_workspace):
        """--keep-local 写入 .state/backups/ 而非 staging。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        result = main([
            "backup", "create",
            "--workspace", str(tmp_workspace),
            "--reason", "keep-test",
            "--keep-local",
            "--json",
        ])
        assert result["ok"] is True
        local_path = Path(result["local_path"])
        assert ".state/backups" in str(local_path)
        assert local_path.exists()

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
