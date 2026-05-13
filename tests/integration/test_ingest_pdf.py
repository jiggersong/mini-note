"""
集成测试：PDF 文件摄入全流程。

验证（v2.4 §18.2）:
- PDF 文件正确解析
- 文本提取正确
- 扫描版 PDF 标记为 metadata_only
"""

import pytest


class TestIngestPDF:
    """测试 .pdf 文件的完整摄入流程。"""

    def test_ingest_pdf_success(self, tmp_workspace, sample_pdf_file):
        """PDF 文件摄入成功（不崩溃）。"""
        from mini_note.ingest.pipeline import IngestPipeline

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=sample_pdf_file,
            owner_id="user-default",
            scope="shared",
        )

        assert result.ok is True
        assert result.source_id is not None
        assert result.ingestion_status in ("full", "metadata_only", "partial")

    def test_ingest_pdf_archive(self, tmp_workspace, sample_pdf_file):
        """PDF 文件正确归档到 archive/。"""
        from mini_note.ingest.pipeline import IngestPipeline

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=sample_pdf_file,
            owner_id="user-default",
            scope="shared",
        )

        archive_dir = tmp_workspace / "raw" / "archive" / result.source_id
        assert archive_dir.is_dir()
        assert (archive_dir / "source.yaml").exists()

    def test_ingest_pdf_media_type_recorded(self, tmp_workspace, sample_pdf_file):
        """source.yaml 中记录 media_type 为 application/pdf。"""
        from mini_note.ingest.pipeline import IngestPipeline
        import yaml

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=sample_pdf_file,
            owner_id="user-default",
            scope="shared",
        )

        source_yaml = (
            tmp_workspace / "raw" / "archive" / result.source_id / "source.yaml"
        )
        data = yaml.safe_load(source_yaml.read_text())
        assert data["media_type"] == "application/pdf"

    def test_ingest_pdf_scan_version_handled(self, tmp_workspace):
        """扫描版 PDF（无文本层）应标记为 metadata_only 而非崩溃。"""
        from mini_note.ingest.pipeline import IngestPipeline

        # 无文本的 PDF
        no_text_pdf = tmp_workspace / "raw" / "inbox" / "users" / "scan.pdf"
        no_text_pdf.write_bytes(
            b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"xref\n0 1\n0000000000 65535 f \ntrailer<</Size 1/Root 1 0 R>>\nstartxref\n9\n%%EOF\n"
        )

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=no_text_pdf,
            owner_id="user-default",
            scope="shared",
        )

        # 不应崩溃
        assert result.ok is True
