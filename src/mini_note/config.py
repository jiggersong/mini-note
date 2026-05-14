"""运行时配置 — 读取 meta/config.yaml，缺失时使用内置默认值。

不读取 .env 密钥，仅非敏感配置。
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Limits:
    """文件摄入上限。"""
    max_text_mb: int = 2
    max_pdf_pages: int = 40
    max_office_mb: int = 10
    max_image_mb: int = 20
    max_audio_minutes: int = 10
    max_video_minutes: int = 5

    @property
    def max_text_bytes(self) -> int:
        return self.max_text_mb * 1024 * 1024

    @property
    def max_office_bytes(self) -> int:
        return self.max_office_mb * 1024 * 1024

    @property
    def max_image_bytes(self) -> int:
        return self.max_image_mb * 1024 * 1024

    @property
    def max_audio_seconds(self) -> int:
        return self.max_audio_minutes * 60

    @property
    def max_video_seconds(self) -> int:
        return self.max_video_minutes * 60


def get_limits(workspace: Path | None = None) -> Limits:
    """从 meta/config.yaml 读取 limits，缺失键使用内置默认值。"""
    limits = Limits()

    config_path = _find_config(workspace)
    if config_path is None:
        return limits

    try:
        import yaml
        data = yaml.safe_load(config_path.read_text())
        if data and "limits" in data:
            raw = data["limits"]
            if "max_text_mb" in raw:
                limits.max_text_mb = int(raw["max_text_mb"])
            if "max_pdf_pages" in raw:
                limits.max_pdf_pages = int(raw["max_pdf_pages"])
            if "max_office_mb" in raw:
                limits.max_office_mb = int(raw["max_office_mb"])
            if "max_image_mb" in raw:
                limits.max_image_mb = int(raw["max_image_mb"])
            if "max_audio_minutes" in raw:
                limits.max_audio_minutes = int(raw["max_audio_minutes"])
            if "max_video_minutes" in raw:
                limits.max_video_minutes = int(raw["max_video_minutes"])
    except Exception:
        pass

    return limits


def get_lock_timeout(workspace: Path | None = None) -> int:
    """从 meta/config.yaml 读取 lock_timeout_seconds，默认 300 秒。"""
    config_path = _find_config(workspace)
    if config_path is None:
        return 300
    try:
        import yaml
        data = yaml.safe_load(config_path.read_text())
        if data and "lock_timeout_seconds" in data:
            return int(data["lock_timeout_seconds"])
    except Exception:
        pass
    return 300


def _find_config(workspace: Path | None) -> Path | None:
    """定位 meta/config.yaml。"""
    if workspace is not None:
        p = workspace / "meta" / "config.yaml"
        if p.exists():
            return p
    # 回退到当前目录
    cwd = Path.cwd()
    p = cwd / "meta" / "config.yaml"
    if p.exists():
        return p
    return None
