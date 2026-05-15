"""批量导入时间预估与进度追踪。

提供预检阶段的时间预估（按文件类型和大小），以及导入过程中的
自适应 EMA 进度追踪，每 30 秒或里程碑节点向 stderr 输出 JSON Lines 快照。
"""

import time as _time
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

CST = timezone(timedelta(hours=8))

# 每文件固定开销（秒）：SHA256 校验 + source registry + 写入 claims/extraction yaml
# + 生成 source page + 索引重建 + health check 的均摊
FIXED_OVERHEAD = 0.95


class FileCategory(Enum):
    """文件处理分类，每类有不同的处理速度基准。"""
    text = "text"
    office = "office"
    pdf = "pdf"
    code = "code"
    image = "image"
    media = "media"
    other = "other"


# 速度基准表： (base_seconds, per_mb_seconds)
# base_seconds: 该类型文件的最小处理耗时（不含体积因素）
# per_mb_seconds: 每 MB 额外增加的秒数
# PDF 特殊：per_mb_seconds 被解释为 per_page_seconds，页数按 size/50000 估算
SPEED_TABLE: dict[FileCategory, tuple[float, float]] = {
    FileCategory.text:   (0.15, 0.02),
    FileCategory.office: (1.00, 0.30),
    FileCategory.pdf:    (1.50, 0.10),  # per_page
    FileCategory.code:   (0.15, 0.01),
    FileCategory.image:  (0.15, 0.01),
    FileCategory.media:  (0.15, 0.01),
    FileCategory.other:  (0.25, 0.02),
}

# 扩展名 → 分类映射
_EXT_CATEGORY: dict[str, FileCategory] = {
    # text
    ".md": FileCategory.text,
    ".txt": FileCategory.text,
    # office
    ".docx": FileCategory.office,
    ".xlsx": FileCategory.office,
    ".pptx": FileCategory.office,
    # pdf
    ".pdf": FileCategory.pdf,
    # code
    ".py": FileCategory.code, ".js": FileCategory.code, ".ts": FileCategory.code,
    ".go": FileCategory.code, ".java": FileCategory.code, ".rs": FileCategory.code,
    ".cpp": FileCategory.code, ".c": FileCategory.code, ".h": FileCategory.code,
    ".sh": FileCategory.code, ".bash": FileCategory.code, ".yaml": FileCategory.code,
    ".yml": FileCategory.code, ".toml": FileCategory.code, ".json": FileCategory.code,
    ".xml": FileCategory.code, ".sql": FileCategory.code, ".rb": FileCategory.code,
    ".php": FileCategory.code, ".swift": FileCategory.code, ".kt": FileCategory.code,
    ".scala": FileCategory.code,
    # image
    ".png": FileCategory.image, ".jpg": FileCategory.image, ".jpeg": FileCategory.image,
    ".gif": FileCategory.image, ".webp": FileCategory.image, ".bmp": FileCategory.image,
    ".tiff": FileCategory.image, ".svg": FileCategory.image,
    # media
    ".mp3": FileCategory.media, ".wav": FileCategory.media, ".flac": FileCategory.media,
    ".ogg": FileCategory.media, ".m4a": FileCategory.media, ".aac": FileCategory.media,
    ".wma": FileCategory.media,
    ".mp4": FileCategory.media, ".avi": FileCategory.media, ".mov": FileCategory.media,
    ".mkv": FileCategory.media, ".webm": FileCategory.media, ".flv": FileCategory.media,
}


def classify_file(file_path: Path) -> FileCategory:
    """根据扩展名返回文件处理分类，未知后缀归为 other。"""
    ext = file_path.suffix.lower()
    return _EXT_CATEGORY.get(ext, FileCategory.other)


def estimate_file_time(file_path: Path) -> float:
    """预估单个文件的处理耗时（秒），基于类型和体积。

    仅做 stat() 调用，不打开文件。PDF 页数按 50KB/页估算。
    """
    cat = classify_file(file_path)
    base, factor = SPEED_TABLE[cat]
    size_bytes = file_path.stat().st_size
    size_mb = size_bytes / (1024 * 1024)

    if cat == FileCategory.pdf:
        # PDF 按估算页数：~50KB/页
        estimated_pages = max(1, size_bytes / 50000)
        return round(base + factor * estimated_pages + FIXED_OVERHEAD, 1)

    return round(base + factor * size_mb + FIXED_OVERHEAD, 1)


def estimate_batch_time(file_paths: list[Path]) -> dict:
    """批量预估导入耗时，返回按分类汇总。

    Returns:
        {
            "total_estimated_seconds": float,
            "by_category": {category_name: {"count": int, "estimated_seconds": float}, ...},
        }
    """
    by_cat: dict[str, dict] = {}
    total = 0.0

    for fp in file_paths:
        cat = classify_file(fp)
        est = estimate_file_time(fp)
        total += est
        name = cat.value
        if name not in by_cat:
            by_cat[name] = {"count": 0, "estimated_seconds": 0.0}
        by_cat[name]["count"] += 1
        by_cat[name]["estimated_seconds"] += est

    # round 汇总值
    for v in by_cat.values():
        v["estimated_seconds"] = round(v["estimated_seconds"], 1)

    return {
        "total_estimated_seconds": round(total, 1),
        "by_category": by_cat,
    }


def format_duration(seconds: float) -> str:
    """将秒数格式化为人类可读的中文时长描述。

    >>> format_duration(30)
    '约 30 秒'
    >>> format_duration(90)
    '约 1 分 30 秒'
    >>> format_duration(3700)
    '约 1 小时 1 分'
    """
    s = round(seconds)
    if s < 60:
        return f"约 {s} 秒"
    if s < 3600:
        m, sec = divmod(s, 60)
        if sec == 0:
            return f"约 {m} 分"
        return f"约 {m} 分 {sec} 秒"
    h, rem = divmod(s, 3600)
    m = rem // 60
    if m == 0:
        return f"约 {h} 小时"
    return f"约 {h} 小时 {m} 分"


class BatchProgressTracker:
    """批量导入进度追踪器，使用自适应 EMA 动态修正剩余耗时预估。

    每处理完一个文件调用 file_complete()，当满足以下条件时返回进度快照：
    - 首个文件完成
    - 距上次报告已过 30 秒
    - 达到 10%、25%、50%、75% 或 90% 里程碑
    - 全部文件处理完毕
    """

    def __init__(self, file_paths: list[Path]):
        self.total = len(file_paths)
        self.processed = 0
        self.ok_count = 0
        self.fail_count = 0
        self._start_time = _time.monotonic()
        self._last_report_time = self._start_time
        self._ema: float | None = None  # 每文件耗时的指数移动平均
        self._milestones_triggered: set[int] = set()
        self._initial_estimate = estimate_batch_time(file_paths)

    @property
    def initial_estimate(self) -> dict:
        return self._initial_estimate

    def file_complete(self, ok: bool, elapsed_seconds: float) -> dict | None:
        """记录一个文件处理完毕，必要时返回进度快照。"""
        self.processed += 1
        if ok:
            self.ok_count += 1
        else:
            self.fail_count += 1

        self._update_ema(elapsed_seconds)

        now = _time.monotonic()
        total_elapsed = now - self._start_time
        since_report = now - self._last_report_time

        # 判断是否需要输出快照
        is_first = self.processed == 1
        is_done = self.processed >= self.total
        is_time = since_report >= 30.0
        pct = self.processed / max(self.total, 1)
        at_milestone = False
        for m in (10, 25, 50, 75, 90):
            if pct * 100 >= m and m not in self._milestones_triggered:
                at_milestone = True
                self._milestones_triggered.add(m)

        if not (is_first or is_done or is_time or at_milestone):
            return None

        self._last_report_time = now

        remaining = self._ema * (self.total - self.processed) if self._ema else 0.0

        return {
            "type": "progress",
            "ts": datetime.now(CST).isoformat(),
            "processed": self.processed,
            "total": self.total,
            "ok_count": self.ok_count,
            "fail_count": self.fail_count,
            "elapsed_seconds": round(total_elapsed, 1),
            "files_per_second": round(self.processed / max(total_elapsed, 0.001), 2),
            "estimated_remaining_seconds": round(remaining, 1),
            "estimated_remaining_human": format_duration(remaining),
            "done": is_done,
        }

    def final_summary(self) -> dict:
        """返回最终汇总统计。"""
        total_elapsed = _time.monotonic() - self._start_time
        return {
            "total_seconds": round(total_elapsed, 1),
            "total_files": self.total,
            "avg_seconds_per_file": round(total_elapsed / max(self.processed, 1), 2),
            "avg_files_per_second": round(self.processed / max(total_elapsed, 0.001), 2),
            "ok_count": self.ok_count,
            "fail_count": self.fail_count,
        }

    def _update_ema(self, elapsed: float) -> None:
        """自适应 EMA：alpha 从 0.5 衰减到 0.1，快速收敛后稳定。"""
        alpha = max(0.1, min(0.5, 3.0 / (self.processed + 3)))
        if self._ema is None:
            self._ema = elapsed
        else:
            self._ema = alpha * elapsed + (1 - alpha) * self._ema
