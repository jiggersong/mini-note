"""Large File Queue 单元测试 — 队列操作、锁语义、状态迁移。"""

import tempfile
from pathlib import Path

import pytest


class TestQueueOperations:
    """队列基本操作：入队、出队、标记完成/失败、状态。"""

    @pytest.fixture
    def ws(self):
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    def test_enqueue_creates_pending_entry(self, ws):
        from mini_note.ingest.large_file_queue import enqueue
        src = ws / "test.pdf"
        src.write_bytes(b"%PDF-1.4 fake")
        op_id = enqueue(ws, src, "user1", "shared", "pdf_pages", "50 页")
        pending = ws / ".state" / "large_ingest_queue" / "pending" / f"{op_id}.yaml"
        assert pending.exists()

        import yaml
        data = yaml.safe_load(pending.read_text())
        assert data["operation_id"] == op_id
        assert data["limit_type"] == "pdf_pages"
        assert "stabilized_path" in data  # 文件已被复制到 staging

    def test_enqueue_copies_to_staging(self, ws):
        from mini_note.ingest.large_file_queue import enqueue
        src = ws / "test.pdf"
        src.write_bytes(b"%PDF-1.4 fake content for staging")
        op_id = enqueue(ws, src, "user1", "shared", "pdf_pages", "50 页")

        import yaml
        pending = ws / ".state" / "large_ingest_queue" / "pending" / f"{op_id}.yaml"
        data = yaml.safe_load(pending.read_text())
        staging_path = Path(data["stabilized_path"])
        assert staging_path.exists()
        assert staging_path.read_bytes() == b"%PDF-1.4 fake content for staging"

    def test_status_counts_correctly(self, ws):
        from mini_note.ingest.large_file_queue import enqueue, status
        src = ws / "a.pdf"; src.write_bytes(b"pdf")
        enqueue(ws, src, "u", "s", "type", "val")
        src2 = ws / "b.docx"; src2.write_bytes(b"docx" * 1024 * 1024 * 11)
        enqueue(ws, src2, "u", "s", "office_mb", "11MB")

        s = status(ws)
        assert s["pending"] == 2
        assert s["running"] == 0
        assert s["done"] == 0
        assert s["failed"] == 0

    def test_dequeue_moves_to_running(self, ws):
        from mini_note.ingest.large_file_queue import (
            enqueue, dequeue, status, acquire_large_worker_lock,
            release_large_worker_lock,
        )
        src = ws / "a.pdf"; src.write_bytes(b"pdf")
        enqueue(ws, src, "u", "s", "type", "val")

        assert acquire_large_worker_lock(ws) is True
        try:
            entry = dequeue(ws)
            assert entry is not None
            assert entry["limit_type"] == "type"
            s = status(ws)
            assert s["pending"] == 0
            assert s["running"] == 1
        finally:
            release_large_worker_lock(ws)

    def test_dequeue_empty_returns_none(self, ws):
        from mini_note.ingest.large_file_queue import (
            dequeue, acquire_large_worker_lock, release_large_worker_lock,
        )
        assert acquire_large_worker_lock(ws) is True
        try:
            assert dequeue(ws) is None
        finally:
            release_large_worker_lock(ws)

    def test_mark_done_moves_to_done(self, ws):
        from mini_note.ingest.large_file_queue import (
            enqueue, dequeue, mark_done, status,
            acquire_large_worker_lock, release_large_worker_lock,
        )
        src = ws / "a.pdf"; src.write_bytes(b"pdf")
        enqueue(ws, src, "u", "s", "type", "val")

        assert acquire_large_worker_lock(ws) is True
        try:
            entry = dequeue(ws)
            mark_done(ws, entry["operation_id"])
            s = status(ws)
            assert s["running"] == 0
            assert s["done"] == 1
        finally:
            release_large_worker_lock(ws)

    def test_mark_failed_records_error(self, ws):
        from mini_note.ingest.large_file_queue import (
            enqueue, dequeue, mark_failed, status,
            acquire_large_worker_lock, release_large_worker_lock,
        )
        src = ws / "a.pdf"; src.write_bytes(b"pdf")
        op_id = enqueue(ws, src, "u", "s", "type", "val")

        assert acquire_large_worker_lock(ws) is True
        try:
            entry = dequeue(ws)
            mark_failed(ws, entry["operation_id"], "磁盘满")
            s = status(ws)
            assert s["running"] == 0
            assert s["failed"] == 1

            # 验证错误信息已写入
            import yaml
            failed_file = ws / ".state" / "large_ingest_queue" / "failed" / f"{op_id}.yaml"
            data = yaml.safe_load(failed_file.read_text())
            assert data["error"] == "磁盘满"
        finally:
            release_large_worker_lock(ws)


class TestLockSemantics:
    """大文件 worker 锁语义。"""

    def test_second_worker_rejected(self, tmp_workspace):
        from mini_note.ingest.large_file_queue import (
            acquire_large_worker_lock, release_large_worker_lock,
        )
        ws = tmp_workspace
        assert acquire_large_worker_lock(ws) is True
        try:
            assert acquire_large_worker_lock(ws) is False  # 第二个被拒绝
        finally:
            release_large_worker_lock(ws)

    def test_lock_reacquired_after_release(self, tmp_workspace):
        from mini_note.ingest.large_file_queue import (
            acquire_large_worker_lock, release_large_worker_lock,
        )
        ws = tmp_workspace
        assert acquire_large_worker_lock(ws) is True
        release_large_worker_lock(ws)
        assert acquire_large_worker_lock(ws) is True
        release_large_worker_lock(ws)

    def test_large_lock_independent_from_ingest_lock(self, tmp_workspace):
        """large_ingest.lock 与 ingest.lock 互不影响。"""
        from mini_note.ingest.large_file_queue import (
            acquire_large_worker_lock, release_large_worker_lock,
        )
        from mini_note.ingest.pipeline import _acquire_lock, _release_lock
        ws = tmp_workspace

        # 同时持有两种锁
        assert acquire_large_worker_lock(ws) is True
        _acquire_lock(ws)  # 不抛异常 = 独立
        _release_lock(ws)
        release_large_worker_lock(ws)


class TestWorkerBusy:
    """worker 互斥测试。"""

    def test_run_worker_returns_busy_when_locked(self, tmp_workspace):
        from mini_note.ingest.large_file_queue import (
            acquire_large_worker_lock, release_large_worker_lock,
            run_large_worker,
        )
        ws = tmp_workspace
        assert acquire_large_worker_lock(ws) is True
        try:
            result = run_large_worker(ws, once=True)
            assert result["ok"] is False
            assert result["error_code"] == "WORKER_BUSY"
        finally:
            release_large_worker_lock(ws)

    def test_run_worker_empty_queue(self, tmp_workspace):
        from mini_note.ingest.large_file_queue import run_large_worker
        result = run_large_worker(tmp_workspace, once=True)
        assert result["ok"] is True
        assert "队列为空" in result["message"]
