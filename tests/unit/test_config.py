"""Config 单元测试 — 运行时配置读取、默认值、配置文件覆盖。"""

from pathlib import Path

import pytest


class TestLimitsDefaults:
    """默认限制值对齐新方案。"""

    def test_default_limits(self):
        from mini_note.config import Limits
        limits = Limits()
        assert limits.max_text_mb == 2
        assert limits.max_pdf_pages == 40
        assert limits.max_office_mb == 10
        assert limits.max_image_mb == 20
        assert limits.max_audio_minutes == 10
        assert limits.max_video_minutes == 5

    def test_derived_properties(self):
        from mini_note.config import Limits
        limits = Limits()
        assert limits.max_text_bytes == 2 * 1024 * 1024
        assert limits.max_office_bytes == 10 * 1024 * 1024
        assert limits.max_image_bytes == 20 * 1024 * 1024
        assert limits.max_audio_seconds == 10 * 60
        assert limits.max_video_seconds == 5 * 60


class TestGetLimits:
    """从 meta/config.yaml 读取配置。"""

    def test_no_config_returns_defaults(self, tmp_path):
        from mini_note.config import get_limits
        limits = get_limits(tmp_path)
        assert limits.max_pdf_pages == 40
        assert limits.max_office_mb == 10

    def test_full_config_overrides(self, tmp_workspace):
        from mini_note.config import get_limits
        config = tmp_workspace / "meta" / "config.yaml"
        config.write_text("""limits:
  max_text_mb: 5
  max_pdf_pages: 20
  max_office_mb: 8
  max_image_mb: 30
  max_audio_minutes: 15
  max_video_minutes: 10
""")
        limits = get_limits(tmp_workspace)
        assert limits.max_text_mb == 5
        assert limits.max_pdf_pages == 20
        assert limits.max_office_mb == 8
        assert limits.max_image_mb == 30
        assert limits.max_audio_minutes == 15
        assert limits.max_video_minutes == 10

    def test_partial_config_merges_defaults(self, tmp_workspace):
        from mini_note.config import get_limits
        config = tmp_workspace / "meta" / "config.yaml"
        config.write_text("limits:\n  max_pdf_pages: 15\n")
        limits = get_limits(tmp_workspace)
        assert limits.max_pdf_pages == 15        # 来自配置
        assert limits.max_text_mb == 2           # 默认
        assert limits.max_office_mb == 10        # 默认

    def test_malformed_config_returns_defaults(self, tmp_workspace):
        from mini_note.config import get_limits
        config = tmp_workspace / "meta" / "config.yaml"
        config.write_text("{ invalid yaml {{{")
        limits = get_limits(tmp_workspace)
        assert limits.max_pdf_pages == 40  # 回退到默认

    def test_config_without_limits_key(self, tmp_workspace):
        from mini_note.config import get_limits
        config = tmp_workspace / "meta" / "config.yaml"
        config.write_text("default_scope: private\nlog_level: DEBUG\n")
        limits = get_limits(tmp_workspace)
        assert limits.max_pdf_pages == 40  # 全默认
