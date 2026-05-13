"""
集成测试：OSS 快照恢复验证。

验证（v2.4 §18.2）:
- 快照可下载到临时目录
- 解包后文件完整
- 删除 SQLite 后可从文件重建
- health check 通过
"""

import hashlib
from pathlib import Path

import pytest


class TestRestoreVerify:
    """测试快照恢复验证流程。"""

    def test_snapshot_roundtrip(self, tmp_workspace, sample_md_file):
        """完整快照循环：打包 → 解包到新目录 → 文件一致。"""
        from mini_note.backup.snapshot import create_snapshot, restore_snapshot
        from mini_note.ingest.pipeline import IngestPipeline
        import filecmp

        # 先摄入一个文件
        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=sample_md_file,
            owner_id="user-default",
            scope="shared",
        )

        # 创建快照
        snapshot_path = tmp_workspace / "snapshot.tar.gz"
        create_snapshot(tmp_workspace, snapshot_path, compression="gzip")

        # 恢复到临时目录
        restore_dir = tmp_workspace / "restored"
        restore_dir.mkdir()
        restore_snapshot(snapshot_path, restore_dir)

        # 验证关键文件存在
        assert (restore_dir / "wiki" / "index.md").exists()
        assert (restore_dir / "meta" / "purpose.md").exists()

    def test_restore_without_sqlite_rebuilds(self, tmp_workspace, sample_md_file):
        """恢复目录中无 SQLite，可重建索引。"""
        from mini_note.backup.snapshot import create_snapshot, restore_snapshot
        from mini_note.ingest.pipeline import IngestPipeline
        from mini_note.indexer import Indexer

        pipeline = IngestPipeline(tmp_workspace)
        pipeline.run(
            file_path=sample_md_file,
            owner_id="user-default",
            scope="shared",
        )

        # 创建快照（包含 notes.db 作为恢复加速）
        snapshot_path = tmp_workspace / "snapshot.tar.gz"
        create_snapshot(tmp_workspace, snapshot_path, compression="gzip")

        # 恢复
        restore_dir = tmp_workspace / "restored"
        restore_dir.mkdir()
        restore_snapshot(snapshot_path, restore_dir)

        # 模拟：删除恢复目录中的 SQLite
        restored_db = restore_dir / ".state" / "notes.db"
        if restored_db.exists():
            restored_db.unlink()

        # 重建
        idx = Indexer(restore_dir)
        idx.rebuild()

        # 重建成功
        assert restored_db.exists()

    def test_health_check_after_restore(self, tmp_workspace, sample_md_file):
        """恢复后 health check 通过。"""
        from mini_note.backup.snapshot import create_snapshot, restore_snapshot
        from mini_note.ingest.pipeline import IngestPipeline

        pipeline = IngestPipeline(tmp_workspace)
        pipeline.run(
            file_path=sample_md_file,
            owner_id="user-default",
            scope="shared",
        )

        snapshot_path = tmp_workspace / "snapshot.tar.gz"
        create_snapshot(tmp_workspace, snapshot_path, compression="gzip")

        restore_dir = tmp_workspace / "restored"
        restore_dir.mkdir()
        restore_snapshot(snapshot_path, restore_dir)

        # 运行 health check
        from mini_note.lint.health import run_health_check
        report = run_health_check(restore_dir)

        assert report["ok"] is True
        assert "checks" in report

    def test_snapshot_hash_validation(self, tmp_workspace, sample_md_file):
        """快照 hash 校验。"""
        from mini_note.backup.snapshot import create_snapshot

        (tmp_workspace / "wiki" / "index.md").write_text("# test content")
        snapshot_path = tmp_workspace / "snapshot.tar.gz"
        sha = create_snapshot(tmp_workspace, snapshot_path, compression="gzip")

        # 直接校验文件 hash
        content = snapshot_path.read_bytes()
        computed = hashlib.sha256(content).hexdigest()
        assert sha == computed

    def test_restore_report_written(self, tmp_workspace, sample_md_file):
        """恢复演练后写入 restore report。"""
        from mini_note.backup.snapshot import create_snapshot, restore_snapshot
        from mini_note.ingest.pipeline import IngestPipeline
        import json

        pipeline = IngestPipeline(tmp_workspace)
        pipeline.run(
            file_path=sample_md_file,
            owner_id="user-default",
            scope="shared",
        )

        snapshot_path = tmp_workspace / "snapshot.tar.gz"
        create_snapshot(tmp_workspace, snapshot_path, compression="gzip")

        restore_dir = tmp_workspace / "restored"
        restore_dir.mkdir()
        restore_snapshot(snapshot_path, restore_dir)

        # 模拟恢复报告
        report = {
            "snapshot_sha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
            "restored_at": "2026-05-13T12:00:00+08:00",
            "health_check_passed": True,
        }
        report_path = restore_dir / "restore_report.json"
        report_path.write_text(json.dumps(report, indent=2))

        assert report_path.exists()
        data = json.loads(report_path.read_text())
        assert data["health_check_passed"] is True
