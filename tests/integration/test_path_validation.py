"""
集成测试：路径校验 — 非法路径和恶意输入拒绝。

验证（v2.4 §18.2）:
- 路径穿越被拒绝
- 非法 slug 和文件名被拒绝
- 写入路径必须在 workspace 内
"""

import pytest


class TestPathValidation:
    """测试路径安全机制。"""

    def test_ingest_rejects_path_traversal(self, tmp_workspace):
        """Ingest pipeline 拒绝路径穿越文件。"""
        from mini_note.ingest.pipeline import IngestPipeline
        import os

        # 创建指向 workspace 外的符号链接
        outside = tmp_workspace.parent / "secret.txt"
        outside.write_text("secret")
        symlink = tmp_workspace / "raw" / "inbox" / "users" / "bad.md"
        os.symlink(str(outside), str(symlink))

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=symlink,
            owner_id="user-default",
            scope="shared",
        )

        # 必须拒绝
        assert result.ok is False

    def test_staging_writes_confined_to_workspace(self, tmp_workspace):
        """Staging 写入不能逃逸 workspace。"""
        from mini_note.ingest.staging import write_to_staging

        with pytest.raises(ValueError, match="workspace"):
            write_to_staging(
                tmp_workspace,
                "/etc/passwd",
                "malicious content",
            )

    def test_wiki_page_path_must_be_in_wiki_dir(self, tmp_workspace):
        """Wiki 页面路径必须在 wiki/ 目录下。"""
        from mini_note.ingest.staging import write_to_staging

        with pytest.raises(ValueError, match="wiki/"):
            write_to_staging(
                tmp_workspace,
                "../outside.md",
                "outside content",
            )

    def test_source_id_from_user_input_rejected(self, tmp_workspace):
        """用户不可控制 source_id 生成。"""
        from mini_note.models.source_registry import generate_source_id

        sid = generate_source_id()
        # source_id 由系统生成，不应包含用户输入
        assert sid.startswith("src-")
        assert "/" not in sid
        assert ".." not in sid
