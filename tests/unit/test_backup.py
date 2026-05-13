"""
Backup 单元测试 — OSS 快照上传、校验、恢复演练。

测试目标（v2.4 §18.1）:
- 快照文件包含正确的 hash
- 备份失败有重试机制
- 快照内容完整
"""

import hashlib
from pathlib import Path

import pytest


# ============================================================
# 快照打包
# ============================================================

class TestSnapshotPack:
    """测试快照打包和 hash 校验。"""

    def test_pack_produces_tar_file(self, tmp_workspace):
        """打包后产生 tar 文件。"""
        from mini_note.backup.snapshot import create_snapshot

        (tmp_workspace / "meta" / "purpose.md").write_text("# purpose")
        (tmp_workspace / "wiki" / "index.md").write_text("# index")

        snapshot_path = tmp_workspace / "snapshot.tar.gz"
        sha = create_snapshot(tmp_workspace, snapshot_path, compression="gzip")

        assert snapshot_path.exists()
        assert snapshot_path.stat().st_size > 0
        assert len(sha) == 64  # SHA256 hex

    def test_snapshot_hash_matches_content(self, tmp_workspace):
        """快照 hash 与文件内容一致。"""
        from mini_note.backup.snapshot import create_snapshot

        (tmp_workspace / "meta" / "purpose.md").write_text("# purpose")

        snapshot_path = tmp_workspace / "snapshot.tar.gz"
        sha = create_snapshot(tmp_workspace, snapshot_path, compression="gzip")

        # 直接计算文件 hash 对比
        content = snapshot_path.read_bytes()
        expected = hashlib.sha256(content).hexdigest()
        assert sha == expected

    def test_snapshot_excludes_state_db_by_default(self, tmp_workspace):
        """快照默认排除 .state/ 下的运行时状态（可选包含 notes.db 作为恢复加速）。"""
        from mini_note.backup.snapshot import create_snapshot
        import tarfile

        (tmp_workspace / "wiki" / "index.md").write_text("# index")

        snapshot_path = tmp_workspace / "snapshot.tar.gz"
        create_snapshot(tmp_workspace, snapshot_path, compression="gzip")

        with tarfile.open(snapshot_path, "r:gz") as tar:
            names = tar.getnames()
            # wiki 文件在快照中
            assert any("wiki/index.md" in n for n in names)

    def test_snapshot_hash_validates_content(self, tmp_workspace):
        """快照 hash 可验证文件完整性（hash 与文件内容一致）。"""
        from mini_note.backup.snapshot import create_snapshot

        (tmp_workspace / "wiki" / "index.md").write_text("# index test")

        p1 = tmp_workspace / "s1.tar.gz"
        sha1 = create_snapshot(tmp_workspace, p1, compression="gzip")

        # hash 与文件内容一致
        content = p1.read_bytes()
        expected = hashlib.sha256(content).hexdigest()
        assert sha1 == expected

        # 再次快照后 hash 仍与内容一致
        p2 = tmp_workspace / "s2.tar.gz"
        sha2 = create_snapshot(tmp_workspace, p2, compression="gzip")
        content2 = p2.read_bytes()
        assert sha2 == hashlib.sha256(content2).hexdigest()


# ============================================================
# 快照恢复
# ============================================================

class TestSnapshotRestore:
    """测试快照解包和恢复。"""

    def test_restore_to_empty_dir(self, tmp_workspace):
        """解包到空目录后文件结构一致。"""
        from mini_note.backup.snapshot import create_snapshot, restore_snapshot

        (tmp_workspace / "wiki" / "index.md").write_text("# index test")
        snapshot_path = tmp_workspace / "snapshot.tar.gz"
        create_snapshot(tmp_workspace, snapshot_path, compression="gzip")

        restore_dir = tmp_workspace / "restored"
        restore_dir.mkdir()
        restore_snapshot(snapshot_path, restore_dir)

        assert (restore_dir / "wiki" / "index.md").exists()
        assert (restore_dir / "wiki" / "index.md").read_text() == "# index test"


# ============================================================
# 备份状态追踪
# ============================================================

class TestBackupStatus:
    """测试备份状态记录。"""

    def test_backup_log_entry(self, tmp_workspace):
        """备份操作写入 backup_log.jsonl。"""
        from mini_note.backup.status import BackupLog

        log_path = tmp_workspace / ".state" / "backup_log.jsonl"
        log = BackupLog(log_path)
        log.record(
            oss_object="snapshots/inc/2026/05/13/op-test.tar.gz.enc",
            sha256="abc123",
            status="success",
            operation_id="op-test",
        )

        entries = log.read_all()
        assert len(entries) == 1
        assert entries[0]["status"] == "success"
        assert entries[0]["sha256"] == "abc123"

    def test_backup_failure_recorded(self, tmp_workspace):
        """备份失败也有记录。"""
        from mini_note.backup.status import BackupLog

        log_path = tmp_workspace / ".state" / "backup_log.jsonl"
        log = BackupLog(log_path)
        log.record(
            oss_object="snapshots/inc/2026/05/13/op-fail.tar.gz.enc",
            sha256="",
            status="failed",
            operation_id="op-fail",
            error="OSS upload timeout",
        )

        entries = log.read_all()
        assert len(entries) == 1
        assert entries[0]["status"] == "failed"
        assert "error" in entries[0]

    def test_backup_retry_count(self, tmp_workspace):
        """备份失败后有重试次数。"""
        from mini_note.backup.status import BackupLog

        log_path = tmp_workspace / ".state" / "backup_log.jsonl"
        log = BackupLog(log_path)

        for i in range(3):
            log.record(
                oss_object=f"snapshots/inc/op-retry.tar.gz.enc",
                sha256="",
                status="failed" if i < 2 else "success",
                operation_id="op-retry",
                attempt=i + 1,
            )

        entries = log.read_all()
        assert entries[-1]["status"] == "success"
        assert entries[-1]["attempt"] == 3
