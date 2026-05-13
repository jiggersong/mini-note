"""图片/代码/音视频 摄入集成测试。"""

import pytest


class TestIngestImage:
    """测试图片文件摄入。"""

    def test_ingest_image_success(self, tmp_workspace, sample_image_file):
        """图片摄入成功。"""
        from mini_note.ingest.pipeline import IngestPipeline

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=sample_image_file,
            owner_id="user-default",
            scope="shared",
        )
        assert result.ok is True
        assert result.ingestion_status == "metadata_only"

    def test_ingest_image_source_page_created(self, tmp_workspace, sample_image_file):
        """图片摄入后 source page 存在且含元数据。"""
        from mini_note.ingest.pipeline import IngestPipeline

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=sample_image_file,
            owner_id="user-default",
            scope="shared",
        )
        source_page = tmp_workspace / result.source_page_path
        assert source_page.exists()
        content = source_page.read_text()
        assert "640" in content or "PNG" in content


class TestIngestCode:
    """测试代码文件摄入。"""

    def test_ingest_code_success(self, tmp_workspace, sample_python_file):
        """Python 代码摄入成功。"""
        from mini_note.ingest.pipeline import IngestPipeline

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=sample_python_file,
            owner_id="user-default",
            scope="shared",
        )
        assert result.ok is True

    def test_ingest_code_source_page_contains_structure(self, tmp_workspace, sample_python_file):
        """代码摄入后 source page 包含类/函数信息。"""
        from mini_note.ingest.pipeline import IngestPipeline

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=sample_python_file,
            owner_id="user-default",
            scope="shared",
        )
        source_page = tmp_workspace / result.source_page_path
        content = source_page.read_text()
        assert "InstanceSpec" in content
        assert "compute_credit_balance" in content


class TestIngestMedia:
    """测试音视频文件摄入。"""

    def test_ingest_mp3_success(self, tmp_workspace, sample_mp3_file):
        """MP3 摄入成功（至少不崩溃）。"""
        from mini_note.ingest.pipeline import IngestPipeline

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=sample_mp3_file,
            owner_id="user-default",
            scope="shared",
        )
        assert result.ok is True
        assert result.ingestion_status == "metadata_only"
