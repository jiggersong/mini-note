"""PID 锁过期检测 + 磁盘空间预检 单元测试。"""

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest


# ============================================================
# _is_pid_alive
# ============================================================

class TestIsPidAlive:
    """PID 存活检测。"""

    def test_current_pid_alive(self):
        from mini_note.ingest.pipeline import _is_pid_alive
        assert _is_pid_alive(os.getpid()) is True

    def test_dead_pid(self):
        from mini_note.ingest.pipeline import _is_pid_alive
        # 99999 几乎不可能被使用
        assert _is_pid_alive(99999) is False

    def test_permission_error_bubbles_up(self):
        """PermissionError 应向上抛出（不被吞掉），以便调用方回退到 mtime。"""
        from mini_note.ingest.pipeline import _is_pid_alive

        def mock_kill_eperm(pid, sig):
            raise PermissionError("EPERM")

        with mock.patch("os.kill", side_effect=mock_kill_eperm):
            with pytest.raises(PermissionError):
                _is_pid_alive(12345)

    def test_process_lookup_error_returns_false(self):
        """ProcessLookupError 表示进程不存在，返回 False。"""
        from mini_note.ingest.pipeline import _is_pid_alive

        def mock_kill_esrch(pid, sig):
            raise ProcessLookupError("ESRCH")

        with mock.patch("os.kill", side_effect=mock_kill_esrch):
            assert _is_pid_alive(12345) is False


# ============================================================
# _is_lock_stale
# ============================================================

class TestIsLockStale:
    """锁过期检测。"""

    @pytest.fixture
    def lock_dir(self):
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    def test_alive_pid_not_stale(self, lock_dir):
        """持有进程存活 → 锁未过期。"""
        from mini_note.ingest.pipeline import _is_lock_stale
        lock = lock_dir / "test.lock"
        lock.write_text(json.dumps({"pid": os.getpid(), "timestamp": "2026-01-01T00:00:00"}))
        assert _is_lock_stale(lock, 300) is False

    def test_dead_pid_is_stale(self, lock_dir):
        """持有进程已死 → 锁过期。"""
        from mini_note.ingest.pipeline import _is_lock_stale
        lock = lock_dir / "test.lock"
        lock.write_text(json.dumps({"pid": 99999, "timestamp": "2026-01-01T00:00:00"}))
        assert _is_lock_stale(lock, 300) is True

    def test_permission_error_falls_back_to_mtime(self, lock_dir):
        """跨用户 PermissionError → 回退到 mtime 判断。"""
        from mini_note.ingest.pipeline import _is_lock_stale
        lock = lock_dir / "test.lock"
        lock.write_text(json.dumps({"pid": 1, "timestamp": "2026-01-01T00:00:00"}))

        def mock_kill_eperm(pid, sig):
            raise PermissionError("EPERM")

        with mock.patch("os.kill", side_effect=mock_kill_eperm):
            # 文件刚创建，mtime 很新 → 短超时判过期
            assert _is_lock_stale(lock, 1) is False
            # 长超时不判过期
            assert _is_lock_stale(lock, 999999) is False

    def test_non_int_pid_falls_back_to_mtime(self, lock_dir):
        """pid 字段不是整数 → 回退到 mtime，不抛 TypeError。"""
        from mini_note.ingest.pipeline import _is_lock_stale
        lock = lock_dir / "test.lock"
        lock.write_text(json.dumps({"pid": "not-an-int", "timestamp": "2026-01-01T00:00:00"}))
        # 不应抛出异常
        result = _is_lock_stale(lock, 300)
        assert isinstance(result, bool)

    def test_old_format_plain_text_falls_back_to_mtime(self, lock_dir):
        """旧格式纯文本锁 → 回退到 mtime。"""
        from mini_note.ingest.pipeline import _is_lock_stale
        lock = lock_dir / "test.lock"
        lock.write_text("locked")
        result = _is_lock_stale(lock, 300)
        assert isinstance(result, bool)

    def test_corrupt_json_falls_back_to_mtime(self, lock_dir):
        """损坏 JSON → 回退到 mtime，不抛异常。"""
        from mini_note.ingest.pipeline import _is_lock_stale
        lock = lock_dir / "test.lock"
        lock.write_text("not json {{{")
        result = _is_lock_stale(lock, 300)
        assert isinstance(result, bool)

    def test_file_deleted_before_read_returns_stale(self, lock_dir):
        """锁文件在读取前被并发删除 → 视为过期，不抛异常。"""
        from mini_note.ingest.pipeline import _is_lock_stale
        lock = lock_dir / "test.lock"
        lock.write_text(json.dumps({"pid": 99999, "timestamp": "2026-01-01T00:00:00"}))
        lock.unlink()  # 模拟并发删除
        result = _is_lock_stale(lock, 300)
        assert result is True  # 文件已不存在，视为过期


# ============================================================
# _acquire_lock / _release_lock
# ============================================================

class TestAcquireReleaseLock:
    """PID 锁的获取与释放。"""

    def test_acquire_and_release(self, tmp_workspace):
        from mini_note.ingest.pipeline import _acquire_lock, _release_lock
        ws = tmp_workspace
        _acquire_lock(ws)
        lock_file = ws / ".state" / "ingest.lock"
        assert lock_file.exists()
        data = json.loads(lock_file.read_text())
        assert data["pid"] == os.getpid()
        assert "timestamp" in data
        _release_lock(ws)
        assert not lock_file.exists()

    def test_second_acquire_raises(self, tmp_workspace):
        from mini_note.ingest.pipeline import _acquire_lock, _release_lock
        ws = tmp_workspace
        _acquire_lock(ws)
        try:
            with pytest.raises(RuntimeError, match="已有 ingest 操作正在执行"):
                _acquire_lock(ws)
        finally:
            _release_lock(ws)

    def test_error_message_includes_pid(self, tmp_workspace):
        from mini_note.ingest.pipeline import _acquire_lock, _release_lock
        ws = tmp_workspace
        _acquire_lock(ws)
        try:
            with pytest.raises(RuntimeError) as exc_info:
                _acquire_lock(ws)
            assert "PID=" in str(exc_info.value)
        finally:
            _release_lock(ws)

    def test_stale_lock_reacquired(self, tmp_workspace):
        """过期锁（死 PID）应被自动清理并重建。"""
        from mini_note.ingest.pipeline import _acquire_lock, _release_lock
        ws = tmp_workspace
        lock_file = ws / ".state" / "ingest.lock"
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        # 创建过期锁（不存在的 PID）
        lock_file.write_text(json.dumps({"pid": 99999, "timestamp": "2026-01-01T00:00:00"}))

        _acquire_lock(ws)
        data = json.loads(lock_file.read_text())
        assert data["pid"] == os.getpid()  # 锁已更新为当前 PID
        _release_lock(ws)


# ============================================================
# _cleanup_stale_locks
# ============================================================

class TestCleanupStaleLocks:
    """过期锁清理。"""

    def test_cleans_stale_lock(self, tmp_workspace):
        from mini_note.ingest.pipeline import _cleanup_stale_locks
        ws = tmp_workspace
        lock_file = ws / ".state" / "ingest.lock"
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock_file.write_text(json.dumps({"pid": 99999, "timestamp": "2026-01-01T00:00:00"}))

        cleaned = _cleanup_stale_locks(ws)
        assert ".state/ingest.lock" in cleaned
        assert not lock_file.exists()

    def test_keeps_valid_lock(self, tmp_workspace):
        from mini_note.ingest.pipeline import _cleanup_stale_locks, _acquire_lock, _release_lock
        ws = tmp_workspace
        _acquire_lock(ws)
        try:
            cleaned = _cleanup_stale_locks(ws)
            assert ".state/ingest.lock" not in cleaned
        finally:
            _release_lock(ws)

    def test_missing_ok_on_concurrent_removal(self, tmp_workspace):
        """锁文件在判定过期后被并发清理 → missing_ok 不抛异常。"""
        from mini_note.ingest.pipeline import _cleanup_stale_locks, _is_lock_stale
        ws = tmp_workspace
        lock_file = ws / ".state" / "ingest.lock"
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock_file.write_text(json.dumps({"pid": 99999, "timestamp": "2026-01-01T00:00:00"}))

        real_is_stale = _is_lock_stale

        def remove_before_cleanup(lf, to):
            result = real_is_stale(lf, to)
            if result and lf.exists():
                lf.unlink()  # 模拟并发清理
            return result

        with mock.patch(
            "mini_note.ingest.pipeline._is_lock_stale",
            side_effect=remove_before_cleanup,
        ):
            cleaned = _cleanup_stale_locks(ws)
            # 不应崩溃，锁文件被双方任一方清理
            assert not lock_file.exists()


# ============================================================
# check_import_disk_space
# ============================================================

class TestCheckImportDiskSpace:
    """磁盘空间预检。"""

    def test_normal_files_fit(self, tmp_workspace):
        from mini_note.ingest.pipeline import check_import_disk_space
        ws = tmp_workspace
        f1 = ws / "a.txt"; f1.write_text("hello")
        f2 = ws / "b.txt"; f2.write_text("world")
        result = check_import_disk_space(ws, [f1, f2])
        assert result["ok"] is True
        assert result["file_count"] == 2
        assert result["total_size_bytes"] == 10
        assert result["estimated_need_bytes"] == 20
        assert result["would_fit"] is True  # 10 bytes, 肯定够
        assert "safe_margin_bytes" in result
        assert "available_bytes" in result

    def test_file_count_excludes_nonexistent(self, tmp_workspace):
        from mini_note.ingest.pipeline import check_import_disk_space
        ws = tmp_workspace
        f1 = ws / "a.txt"; f1.write_text("hello")
        ghost = ws / "ghost.txt"  # 不存在
        result = check_import_disk_space(ws, [f1, ghost])
        assert result["file_count"] == 1
        assert result["total_size_bytes"] == 5

    def test_empty_file_list(self, tmp_workspace):
        from mini_note.ingest.pipeline import check_import_disk_space
        result = check_import_disk_space(tmp_workspace, [])
        assert result["file_count"] == 0
        assert result["total_size_bytes"] == 0
        assert result["estimated_need_bytes"] == 0
        assert result["would_fit"] is True

    def test_disk_full_detected(self, tmp_workspace):
        """模拟磁盘空间不足。"""
        from mini_note.ingest.pipeline import check_import_disk_space
        ws = tmp_workspace
        f1 = ws / "big.bin"
        f1.write_bytes(b"\x00" * 1024 * 1024)  # 1MB

        # Mock disk_usage 返回极小的可用空间
        fake_usage = mock.MagicMock()
        fake_usage.free = 1024 * 1024  # 仅 1MB 可用
        with mock.patch("shutil.disk_usage", return_value=fake_usage):
            result = check_import_disk_space(ws, [f1])
            # 预估需求 = 1MB * 2 = 2MB; 可用仅 1MB; 不够
            assert result["would_fit"] is False


# ============================================================
# CLI DISK_SPACE_LOW
# ============================================================

class TestCliDiskSpaceLow:
    """CLI 层磁盘预检集成。"""

    def test_precheck_disk_empty_dir(self, tmp_workspace):
        from mini_note.cli import main
        empty_dir = tmp_workspace / "empty"
        empty_dir.mkdir()
        result = main([
            "ingest", "precheck-disk",
            "--workspace", str(tmp_workspace),
            "--dir", str(empty_dir),
            "--json",
        ])
        assert result["ok"] is True
        assert result["file_count"] == 0
        assert "would_fit" in result
        assert "available_bytes" in result
        assert "safe_margin_bytes" in result

    def test_precheck_disk_with_files(self, tmp_workspace):
        from mini_note.cli import main
        f1 = tmp_workspace / "test.txt"
        f1.write_text("hello world")
        result = main([
            "ingest", "precheck-disk",
            "--workspace", str(tmp_workspace),
            "--files", str(f1),
            "--json",
        ])
        assert result["ok"] is True
        assert result["file_count"] == 1
        assert "would_fit" in result

    def test_ingest_scan_with_disk_space_low(self, tmp_workspace):
        """inbox 扫描时磁盘不足应返回 DISK_SPACE_LOW。"""
        from mini_note.cli import main
        # 在 inbox 中放一个文件
        inbox_file = tmp_workspace / "raw" / "inbox" / "users" / "big.bin"
        inbox_file.parent.mkdir(parents=True, exist_ok=True)
        inbox_file.write_bytes(b"\x00" * 1024 * 1024)  # 1MB

        fake_usage = mock.MagicMock()
        fake_usage.free = 1024 * 1024  # 仅 1MB
        with mock.patch("shutil.disk_usage", return_value=fake_usage):
            result = main([
                "ingest", "--scan-inbox",
                "--workspace", str(tmp_workspace),
                "--json",
            ])
            assert result["ok"] is False
            assert result["error_code"] == "DISK_SPACE_LOW"

    def test_ingest_scan_with_force_bypasses_check(self, tmp_workspace):
        """--force 应跳过磁盘预检直接摄入。"""
        from mini_note.cli import main
        # 创建一个小文本文件
        inbox_file = tmp_workspace / "raw" / "inbox" / "users" / "note.md"
        inbox_file.parent.mkdir(parents=True, exist_ok=True)
        inbox_file.write_text("# Test\ncontent\n", encoding="utf-8")

        fake_usage = mock.MagicMock()
        fake_usage.free = 0  # 零可用空间
        with mock.patch("shutil.disk_usage", return_value=fake_usage):
            result = main([
                "ingest", "--scan-inbox", "--force",
                "--workspace", str(tmp_workspace),
                "--json",
            ])
            # 应跳过预检成功摄入
            assert result["ok"] is True
            assert len(result.get("results", [])) > 0


# ============================================================
# large_ingest.lock — PID 过期重入
# ============================================================

class TestLargeLockPidStale:
    """大文件 worker 锁的 PID 过期检测。"""

    def test_stale_lock_reacquired(self, tmp_workspace):
        from mini_note.ingest.large_file_queue import (
            acquire_large_worker_lock, release_large_worker_lock,
        )
        ws = tmp_workspace
        lock_file = ws / ".state" / "large_ingest.lock"
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock_file.write_text(json.dumps({"pid": 99999, "timestamp": "2026-01-01T00:00:00"}))

        assert acquire_large_worker_lock(ws) is True
        data = json.loads(lock_file.read_text())
        assert data["pid"] == os.getpid()
        release_large_worker_lock(ws)

    def test_valid_lock_not_stolen(self, tmp_workspace):
        from mini_note.ingest.large_file_queue import (
            acquire_large_worker_lock, release_large_worker_lock,
        )
        ws = tmp_workspace
        assert acquire_large_worker_lock(ws) is True
        try:
            # 第二个 worker 被拒绝
            assert acquire_large_worker_lock(ws) is False
        finally:
            release_large_worker_lock(ws)
