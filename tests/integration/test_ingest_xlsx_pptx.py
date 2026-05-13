"""XLSX/PPTX 摄入集成测试。"""

import pytest


class TestIngestXLSX:
    """测试 .xlsx 文件摄入。"""

    def test_ingest_xlsx_success(self, tmp_workspace, sample_xlsx_file):
        """XLSX 摄入成功生成 source page。"""
        from mini_note.ingest.pipeline import IngestPipeline

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=sample_xlsx_file,
            owner_id="user-default",
            scope="shared",
        )
        assert result.ok is True
        assert result.source_id is not None
        assert result.ingestion_status in ("full", "partial")

    def test_ingest_xlsx_source_page_created(self, tmp_workspace, sample_xlsx_file):
        """XLSX 摄入后 source page 存在。"""
        from mini_note.ingest.pipeline import IngestPipeline

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=sample_xlsx_file,
            owner_id="user-default",
            scope="shared",
        )
        source_page = tmp_workspace / result.source_page_path
        assert source_page.exists()
        assert "ecs.t6-c1m1" in source_page.read_text()

    def test_ingest_xlsx_creates_extraction(self, tmp_workspace, sample_xlsx_file):
        """XLSX 摄入后 extracted 目录有内容。"""
        from mini_note.ingest.pipeline import IngestPipeline

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=sample_xlsx_file,
            owner_id="user-default",
            scope="shared",
        )
        ext_dir = tmp_workspace / "raw" / "extracted" / result.source_id
        assert ext_dir.is_dir()
        assert (ext_dir / "content.md").exists()


class TestIngestPPTX:
    """测试 .pptx 文件摄入。"""

    def test_ingest_pptx_success(self, tmp_workspace, sample_pptx_file):
        """PPTX 摄入成功生成 source page。"""
        from mini_note.ingest.pipeline import IngestPipeline

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=sample_pptx_file,
            owner_id="user-default",
            scope="shared",
        )
        assert result.ok is True
        assert result.source_id is not None

    def test_ingest_pptx_source_page_created(self, tmp_workspace, sample_pptx_file):
        """PPTX 摄入后 source page 存在。"""
        from mini_note.ingest.pipeline import IngestPipeline

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=sample_pptx_file,
            owner_id="user-default",
            scope="shared",
        )
        source_page = tmp_workspace / result.source_page_path
        assert source_page.exists()
        content = source_page.read_text()
        assert "ECS 性能优化方案" in content

    def test_ingest_pptx_creates_extraction(self, tmp_workspace, sample_pptx_file):
        """PPTX 摄入后 extracted 目录有内容。"""
        from mini_note.ingest.pipeline import IngestPipeline

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=sample_pptx_file,
            owner_id="user-default",
            scope="shared",
        )
        ext_dir = tmp_workspace / "raw" / "extracted" / result.source_id
        assert ext_dir.is_dir()
        assert (ext_dir / "content.md").exists()
