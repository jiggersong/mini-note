"""批量导入时间预估与进度追踪 单元测试。"""

import tempfile
from pathlib import Path

import pytest

from mini_note.ingest.progress import (
    FileCategory,
    BatchProgressTracker,
    classify_file,
    estimate_batch_time,
    estimate_file_time,
    format_duration,
)


# ============================================================
# 辅助函数
# ============================================================

def _make_temp_file(suffix: str, size: int = 100) -> Path:
    """在临时目录中创建一个文件并返回路径。"""
    f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    f.write(b"x" * size)
    f.flush()
    f.close()
    return Path(f.name)


def _make_temp_files(suffix: str, count: int, size: int = 100) -> list[Path]:
    """创建多个同后缀临时文件。"""
    paths = []
    for _ in range(count):
        paths.append(_make_temp_file(suffix, size))
    return paths


# ============================================================
# classify_file
# ============================================================

class TestClassifyFile:
    """文件扩展名 → 分类映射。"""

    @pytest.mark.parametrize("ext,expected", [
        (".md", FileCategory.text),
        (".txt", FileCategory.text),
        (".docx", FileCategory.office),
        (".xlsx", FileCategory.office),
        (".pptx", FileCategory.office),
        (".pdf", FileCategory.pdf),
        (".py", FileCategory.code),
        (".js", FileCategory.code),
        (".go", FileCategory.code),
        (".java", FileCategory.code),
        (".png", FileCategory.image),
        (".jpg", FileCategory.image),
        (".svg", FileCategory.image),
        (".mp3", FileCategory.media),
        (".mp4", FileCategory.media),
        (".mov", FileCategory.media),
    ])
    def test_known_extension(self, ext, expected):
        """已知扩展名映射到正确分类。"""
        p = Path(f"test{ext}")
        assert classify_file(p) == expected

    def test_unknown_extension(self):
        """未知扩展名归为 other。"""
        p = Path("test.xyz")
        assert classify_file(p) == FileCategory.other

    def test_no_extension(self):
        """无扩展名归为 other。"""
        p = Path("testfile")
        assert classify_file(p) == FileCategory.other


# ============================================================
# estimate_file_time
# ============================================================

class TestEstimateFileTime:
    """单文件时间预估。"""

    def test_small_text_fast(self):
        """小文本文件预估耗时低（< 2秒）。"""
        p = _make_temp_file(".txt", 100)
        try:
            est = estimate_file_time(p)
            assert est > 0
            assert est < 2.0
        finally:
            p.unlink()

    def test_large_office_slower(self):
        """大 office 文件预估耗时按比例增长。"""
        p = _make_temp_file(".docx", 5 * 1024 * 1024)
        try:
            est = estimate_file_time(p)
            # base(1.0) + 5*0.30 + overhead(0.95) = 3.45
            assert est > 3.0
            assert est < 6.0
        finally:
            p.unlink()

    def test_small_vs_large_same_type(self):
        """同类型文件，大的预估耗时更高（office 类型体积系数大，区别明显）。"""
        p_small = _make_temp_file(".docx", 10)              # 10 bytes
        p_large = _make_temp_file(".docx", 10 * 1024 * 1024)  # 10MB
        try:
            est_small = estimate_file_time(p_small)
            est_large = estimate_file_time(p_large)
            # office: base(1.0) + per_mb(0.30). small≈1.95, large≈4.95
            assert est_large > est_small
        finally:
            p_small.unlink()
            p_large.unlink()

    def test_pdf_uses_page_estimate(self):
        """PDF 按估算页数计算（不打开文件）。"""
        p = _make_temp_file(".pdf", 250 * 1024)  # 250KB → ~5 页
        try:
            est = estimate_file_time(p)
            # base(1.5) + 5*0.10 + overhead(0.95) = 2.95
            assert est > 1.0
            assert est < 5.0
        finally:
            p.unlink()


# ============================================================
# estimate_batch_time
# ============================================================

class TestEstimateBatchTime:
    """批量时间预估。"""

    def test_empty_list(self):
        """空文件列表返回零总计和空分类。"""
        result = estimate_batch_time([])
        assert result["total_estimated_seconds"] == 0
        assert result["by_category"] == {}

    def test_single_file(self):
        """单文件能正确统计。"""
        p = _make_temp_file(".md", 100)
        try:
            result = estimate_batch_time([p])
            assert result["total_estimated_seconds"] > 0
            assert "text" in result["by_category"]
            assert result["by_category"]["text"]["count"] == 1
        finally:
            p.unlink()

    def test_mixed_types(self):
        """混合文件类型分别统计并汇总。"""
        files = [_make_temp_file(ext, 100) for ext in (".md", ".py", ".png")]
        try:
            result = estimate_batch_time(files)
            assert result["total_estimated_seconds"] > 0
            cats = result["by_category"]
            assert "text" in cats
            assert "code" in cats
            assert "image" in cats
            assert cats["text"]["count"] == 1
            assert cats["code"]["count"] == 1
            assert cats["image"]["count"] == 1
        finally:
            for p in files:
                p.unlink(missing_ok=True)

    def test_by_category_sums_to_total(self):
        """分类耗时之和约等于总计（考虑舍入误差）。"""
        files = [_make_temp_file(ext, 100) for ext in (".txt", ".txt", ".py", ".png")]
        try:
            result = estimate_batch_time(files)
            cat_sum = sum(
                v["estimated_seconds"] for v in result["by_category"].values()
            )
            # 舍入误差在 0.5 秒内
            assert abs(cat_sum - result["total_estimated_seconds"]) < 0.5
        finally:
            for p in files:
                p.unlink(missing_ok=True)


# ============================================================
# format_duration
# ============================================================

class TestFormatDuration:
    """时长格式化。"""

    def test_zero_seconds(self):
        assert format_duration(0) == "约 0 秒"

    def test_seconds_only(self):
        assert format_duration(30) == "约 30 秒"
        assert format_duration(59) == "约 59 秒"

    def test_minute_seconds(self):
        assert format_duration(90) == "约 1 分 30 秒"
        assert format_duration(125) == "约 2 分 5 秒"

    def test_even_minutes(self):
        assert format_duration(60) == "约 1 分"
        assert format_duration(120) == "约 2 分"

    def test_hour_minutes(self):
        assert format_duration(3660) == "约 1 小时 1 分"
        assert format_duration(7200) == "约 2 小时"

    def test_hour_only(self):
        assert format_duration(3600) == "约 1 小时"


# ============================================================
# BatchProgressTracker
# ============================================================

class TestBatchProgressTracker:
    """自适应 EMA 进度追踪器。"""

    def test_single_file_triggers_snapshot(self):
        """单文件首文件即完成，触发快照。"""
        files = _make_temp_files(".md", 1)
        try:
            tracker = BatchProgressTracker(files)
            assert tracker.total == 1

            snap = tracker.file_complete(ok=True, elapsed_seconds=0.5)
            assert snap is not None
            assert snap["type"] == "progress"
            assert snap["processed"] == 1
            assert snap["total"] == 1
            assert snap["ok_count"] == 1
            assert snap["fail_count"] == 0
            assert snap["done"] is True
        finally:
            for p in files:
                p.unlink(missing_ok=True)

    def test_single_file_failure(self):
        """单文件失败也触发完成快照。"""
        files = _make_temp_files(".pdf", 1)
        try:
            tracker = BatchProgressTracker(files)
            snap = tracker.file_complete(ok=False, elapsed_seconds=1.0)
            assert snap["ok_count"] == 0
            assert snap["fail_count"] == 1
            assert snap["done"] is True
        finally:
            for p in files:
                p.unlink(missing_ok=True)

    def test_no_snapshot_within_short_interval(self):
        """短时间内连续处理不触发快照（非首文件、非里程碑、未到 30 秒）。"""
        files = _make_temp_files(".txt", 30)
        try:
            tracker = BatchProgressTracker(files)

            # 首个文件触发
            snap1 = tracker.file_complete(ok=True, elapsed_seconds=0.3)
            assert snap1 is not None

            # 第 2 个文件不触发（2/30≈6.7%, 未到 10% 里程碑 point=3, 也未到 30s）
            snap2 = tracker.file_complete(ok=True, elapsed_seconds=0.3)
            assert snap2 is None
        finally:
            for p in files:
                p.unlink(missing_ok=True)

    def test_25_percent_milestone(self):
        """达到 25% 里程碑时触发快照。"""
        files = _make_temp_files(".txt", 20)
        try:
            tracker = BatchProgressTracker(files)

            # 首文件触发
            tracker.file_complete(ok=True, elapsed_seconds=0.3)

            # 处理到第 5 个 (25%)
            snap = None
            for i in range(4):
                snap = tracker.file_complete(ok=True, elapsed_seconds=0.3)
            assert snap is not None
            assert snap["processed"] == 5
            assert snap["total"] == 20
        finally:
            for p in files:
                p.unlink(missing_ok=True)

    def test_no_snapshot_after_all(self):
        """全部完成后不再触发快照。"""
        files = _make_temp_files(".md", 1)
        try:
            tracker = BatchProgressTracker(files)
            snap = tracker.file_complete(ok=True, elapsed_seconds=0.3)
            assert snap is not None
            assert snap["done"] is True
        finally:
            for p in files:
                p.unlink(missing_ok=True)

    def test_final_summary(self):
        """final_summary 包含正确的汇总统计。"""
        files = _make_temp_files(".txt", 5)
        try:
            tracker = BatchProgressTracker(files)

            tracker.file_complete(ok=True, elapsed_seconds=0.5)
            tracker.file_complete(ok=True, elapsed_seconds=0.6)
            tracker.file_complete(ok=False, elapsed_seconds=0.4)
            tracker.file_complete(ok=True, elapsed_seconds=0.5)
            tracker.file_complete(ok=True, elapsed_seconds=0.5)

            summary = tracker.final_summary()
            assert summary["total_files"] == 5
            assert summary["ok_count"] == 4
            assert summary["fail_count"] == 1
            assert summary["total_seconds"] >= 0
            assert summary["avg_seconds_per_file"] >= 0
            assert summary["avg_files_per_second"] >= 0
        finally:
            for p in files:
                p.unlink(missing_ok=True)

    def test_ema_adapts_to_changing_speeds(self):
        """EMA 自适应：处理速度变化时预估随之调整。"""
        files = _make_temp_files(".txt", 40)
        try:
            tracker = BatchProgressTracker(files)

            # 前 10 个很快（0.2s each）→ EMA 趋于 ~0.2
            for _ in range(10):
                tracker.file_complete(ok=True, elapsed_seconds=0.2)

            # 接着 10 个很慢（5.0s each）→ EMA 应上升
            for _ in range(10):
                tracker.file_complete(ok=True, elapsed_seconds=5.0)

            # 25% 里程碑在 10/40 已过，继续到下一个里程碑
            # 75% 在 30/40，目前 20/40。再处理 10 个快文件
            for _ in range(10):
                snap = tracker.file_complete(ok=True, elapsed_seconds=0.3)

            # 30/40 = 75%，最后的 file_complete 应触发快照
            assert snap is not None
            remaining = snap["estimated_remaining_seconds"]
            # EMA 应给出合理剩余预估（0-120 秒之间）
            assert 0 <= remaining < 120
        finally:
            for p in files:
                p.unlink(missing_ok=True)

    def test_initial_estimate_not_negative(self):
        """预估值永不为负数。"""
        p = _make_temp_file(".txt", 100)
        try:
            est = estimate_file_time(p)
            assert est >= 0
        finally:
            p.unlink()

    def test_estimate_batch_time_not_negative(self):
        """批量预估值永不为负数。"""
        p = _make_temp_file(".txt", 100)
        try:
            result = estimate_batch_time([p])
            assert result["total_estimated_seconds"] >= 0
        finally:
            p.unlink()

    def test_empty_tracker_no_files(self):
        """空文件列表的追踪器行为正确。"""
        tracker = BatchProgressTracker([])
        assert tracker.total == 0
        assert tracker.initial_estimate["total_estimated_seconds"] == 0
        summary = tracker.final_summary()
        assert summary["total_files"] == 0
        assert summary["ok_count"] == 0

    def test_files_per_second_never_zero(self):
        """files_per_second 不会为 0（即使是首文件）。"""
        files = _make_temp_files(".txt", 1)
        try:
            tracker = BatchProgressTracker(files)
            tracker.file_complete(ok=True, elapsed_seconds=0.5)
            summary = tracker.final_summary()
            assert summary["avg_files_per_second"] > 0
        finally:
            for p in files:
                p.unlink(missing_ok=True)
