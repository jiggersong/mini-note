"""OSS 备份集成测试 — 需要真实 OSS 凭证且有写入权限，否则自动跳过。

使用 @requires_oss 标记，无环境变量时 pytest skip。
运行方式: PYTHONPATH=src python -m pytest tests/integration/test_oss_backup.py -v
"""

import pytest

from tests.conftest import requires_oss


def _oss_writable() -> bool:
    """检查 OSS bucket 是否可写入。

    无凭证、无写入权限、网络不通等情况均返回 False。
    """
    import tempfile
    from pathlib import Path
    from mini_note.backup.oss import OSSBackup, OSSConfig

    cfg = OSSConfig.from_env()
    if cfg is None:
        return False

    tmp = Path(tempfile.mkdtemp(prefix="oss-probe-"))
    try:
        p = tmp / "probe.tar.gz"
        p.write_bytes(b"mini-note oss probe")
        oss = OSSBackup(config=cfg)
        result = oss.upload(p, "probe-writable-check")
        return result.get("ok", False)
    except Exception:
        return False
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# 仅在有可写 OSS 时运行的上传依赖测试
requires_oss_writable = pytest.mark.skipif(
    not _oss_writable(),
    reason="OSS 不可写（检查 bucket ACL 或访问密钥权限）",
)


@requires_oss_writable
class TestOSSUpload:
    """上传快照到 OSS。"""

    def test_upload_small_snapshot(self, tmp_workspace):
        """小快照上传成功且返回 sha256。"""
        from mini_note.backup.snapshot import create_snapshot
        from mini_note.backup.oss import OSSBackup

        ws = tmp_workspace
        snapshot_path = ws / ".state" / "staging" / "test-upload.tar.gz"
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        sha = create_snapshot(ws, snapshot_path)

        oss = OSSBackup()
        result = oss.upload(snapshot_path, "test-upload-001")
        assert result["ok"] is True
        assert result["mode"] == "oss"
        assert result["sha256"] == sha
        assert "oss_key" in result

    def test_upload_hash_consistency(self, tmp_workspace):
        """上传前后本地与返回的 sha256 一致。"""
        from mini_note.backup.snapshot import create_snapshot
        from mini_note.backup.oss import OSSBackup

        ws = tmp_workspace
        snapshot_path = ws / ".state" / "staging" / "test-hash.tar.gz"
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        sha = create_snapshot(ws, snapshot_path)

        oss = OSSBackup()
        result = oss.upload(snapshot_path, "test-hash-001")
        assert result["sha256"] == sha


@requires_oss_writable
class TestOSSDownload:
    """从 OSS 下载快照。"""

    def test_download_after_upload(self, tmp_workspace, tmp_path):
        """上传后下载，内容一致。"""
        import hashlib
        from mini_note.backup.snapshot import create_snapshot
        from mini_note.backup.oss import OSSBackup

        ws = tmp_workspace
        snapshot_path = ws / ".state" / "staging" / "test-dl.tar.gz"
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)

        create_snapshot(ws, snapshot_path)
        original_sha = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()

        oss = OSSBackup()
        key = "test-download-001"
        up = oss.upload(snapshot_path, key)
        assert up["ok"] is True

        target = tmp_path / "downloaded.tar.gz"
        down = oss.download(up["oss_key"], target)
        assert down["ok"] is True
        assert down["sha256"] == original_sha
        assert target.exists()

    def test_download_nonexistent_key_fails(self, tmp_path):
        """不存在的 key 下载失败。"""
        from mini_note.backup.oss import OSSBackup

        oss = OSSBackup()
        target = tmp_path / "no-file.tar.gz"
        result = oss.download("snapshots/nonexistent-key-99999.tar.gz", target)
        if result["ok"]:
            pytest.skip("OSS key 意外存在")
        assert result["ok"] is False


@requires_oss
class TestOSSList:
    """列出 OSS 中的快照（仅需读取权限）。"""

    def test_list_returns_list(self):
        """list_snapshots 返回列表。"""
        from mini_note.backup.oss import OSSBackup

        oss = OSSBackup()
        result = oss.list_snapshots(max_keys=10)
        assert isinstance(result, list)
        for item in result:
            assert "oss_key" in item
            assert "size" in item

    def test_list_max_keys_respected(self):
        """max_keys 参数限制返回数量。"""
        from mini_note.backup.oss import OSSBackup

        oss = OSSBackup()
        result = oss.list_snapshots(max_keys=3)
        assert len(result) <= 3


@requires_oss_writable
class TestOSSVerify:
    """OSS 快照完整性验证。"""

    def test_verify_after_upload_succeeds(self, tmp_workspace):
        """上传后 verify 通过。"""
        from mini_note.backup.snapshot import create_snapshot
        from mini_note.backup.oss import OSSBackup
        import hashlib

        ws = tmp_workspace
        snapshot_path = ws / ".state" / "staging" / "test-verify.tar.gz"
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)

        create_snapshot(ws, snapshot_path)
        sha = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()

        oss = OSSBackup()
        up = oss.upload(snapshot_path, "test-verify-001")
        assert up["ok"] is True

        result = oss.verify(up["oss_key"], sha)
        assert result["ok"] is True
        assert result["sha256_match"] is True

    def test_verify_wrong_hash_fails(self, tmp_workspace):
        """错误 hash 时 verify 返回 sha256_match=False。"""
        from mini_note.backup.snapshot import create_snapshot
        from mini_note.backup.oss import OSSBackup

        ws = tmp_workspace
        snapshot_path = ws / ".state" / "staging" / "test-verify2.tar.gz"
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)

        create_snapshot(ws, snapshot_path)

        oss = OSSBackup()
        up = oss.upload(snapshot_path, "test-verify-002")
        assert up["ok"] is True

        result = oss.verify(up["oss_key"], "0000000000000000000000000000000000000000000000000000000000000000")
        assert result["sha256_match"] is False


@requires_oss_writable
class TestOSSCLI:
    """CLI 备份/恢复命令与 OSS 集成。"""

    def test_backup_create_with_oss(self, tmp_workspace):
        """backup create 在有 OSS 配置时返回 oss_ok=True。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        result = main([
            "backup", "create",
            "--workspace", str(tmp_workspace),
            "--reason", "integration-test",
            "--json",
        ])
        assert result["ok"] is True
        assert result["oss_ok"] is True
        assert "snapshot_id" in result
        assert "sha256" in result
        assert result["oss_key"] != ""

    def test_restore_verify_with_oss_key(self, tmp_workspace):
        """restore verify 用 OSS key 下载并验证。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])

        backup_result = main([
            "backup", "create",
            "--workspace", str(tmp_workspace),
            "--reason", "restore-test",
            "--json",
        ])
        assert backup_result["ok"] is True

        result = main([
            "restore", "verify",
            "--workspace", str(tmp_workspace),
            "--snapshot", backup_result["oss_key"],
            "--json",
        ])
        assert "health" in result


class TestOSSCLILocal:
    """无 OSS 配置或 OSS 不可写时 CLI 的备份恢复行为。"""

    def test_backup_create_local_mode(self, tmp_workspace):
        """backup create 至少创建本地快照。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        result = main([
            "backup", "create",
            "--workspace", str(tmp_workspace),
            "--reason", "local-test",
            "--json",
        ])
        assert result["snapshot_id"] != ""
        assert result["sha256"] != ""

    def test_restore_verify_local_snapshot(self, tmp_workspace):
        """restore verify 用本地文件路径做恢复演练。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])

        backup_result = main([
            "backup", "create",
            "--workspace", str(tmp_workspace),
            "--reason", "local-restore-test",
            "--json",
        ])
        snapshot_id = backup_result["snapshot_id"]
        snapshot_path = tmp_workspace / ".state" / "staging" / f"{snapshot_id}.tar.gz"

        result = main([
            "restore", "verify",
            "--workspace", str(tmp_workspace),
            "--snapshot", str(snapshot_path),
            "--json",
        ])
        assert "health" in result

    def test_restore_verify_nonexistent_snapshot(self, tmp_workspace):
        """不存在的本地快照返回 SNAPSHOT_NOT_FOUND。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        result = main([
            "restore", "verify",
            "--workspace", str(tmp_workspace),
            "--snapshot", "/nonexistent/snapshot.tar.gz",
            "--json",
        ])
        assert result["ok"] is False
        assert result["error_code"] == "SNAPSHOT_NOT_FOUND"

    def test_restore_verify_missing_snapshot_arg(self, tmp_workspace):
        """未指定 --snapshot 返回 MISSING_SNAPSHOT。"""
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        result = main([
            "restore", "verify",
            "--workspace", str(tmp_workspace),
            "--snapshot", "",
            "--json",
        ])
        assert result["ok"] is False
        assert result["error_code"] == "MISSING_SNAPSHOT"
