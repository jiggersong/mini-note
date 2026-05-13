"""
集成测试：DOCX 文件摄入全流程。

验证（v2.4 §18.2）:
- DOCX 文件正确解析
- 段落和标题被提取
- 表格内容被保留（如有）
"""

import pytest


class TestIngestDocx:
    """测试 .docx 文件的完整摄入流程。"""

    def test_ingest_docx_success(self, tmp_workspace, sample_docx_file):
        """DOCX 文件摄入成功。"""
        from mini_note.ingest.pipeline import IngestPipeline

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=sample_docx_file,
            owner_id="user-default",
            scope="shared",
        )

        assert result.ok is True
        assert result.source_id is not None

    def test_ingest_docx_content_extracted(self, tmp_workspace, sample_docx_file):
        """DOCX 内容被正确提取到 extracted/ 目录。"""
        from mini_note.ingest.pipeline import IngestPipeline

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=sample_docx_file,
            owner_id="user-default",
            scope="shared",
        )

        content_md = (
            tmp_workspace / "raw" / "extracted" / result.source_id / "content.md"
        )
        assert content_md.exists()
        extracted = content_md.read_text()
        assert "测试 DOCX 文档" in extracted

    def test_ingest_docx_source_page_created(self, tmp_workspace, sample_docx_file):
        """DOCX 摄入后生成 source page。"""
        from mini_note.ingest.pipeline import IngestPipeline

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=sample_docx_file,
            owner_id="user-default",
            scope="shared",
        )

        source_page = tmp_workspace / "wiki" / "sources" / f"{result.source_id}.md"
        assert source_page.exists()

    def test_corrupt_docx_handled(self, tmp_workspace):
        """伪装的 DOCX 文件被优雅处理。"""
        from mini_note.ingest.pipeline import IngestPipeline

        fake_docx = tmp_workspace / "raw" / "inbox" / "users" / "fake.docx"
        fake_docx.write_text("this is not a docx")

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=fake_docx,
            owner_id="user-default",
            scope="shared",
        )

        # 不应崩溃，应标记为 failed 或 metadata_only
        assert result.ok is True or result.error_code is not None
