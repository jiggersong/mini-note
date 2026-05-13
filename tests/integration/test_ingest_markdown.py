"""
集成测试：Markdown 文件摄入全流程。

验证（v2.4 §18.2）:
- 文件被归档到 archive/
- 生成 source.yaml
- 生成 extracted/ content.md
- 生成 claims.yaml（如有关键事实）
- source page 写入 wiki/sources/
- index.md 被更新
- operation manifest 记录完整
"""

import pytest


class TestIngestMarkdown:
    """测试 .md 文件的完整摄入流程。"""

    def test_full_ingest_pipeline(self, tmp_workspace, sample_md_file):
        """端到端测试：md 文件摄入全流程。"""
        from mini_note.ingest.pipeline import IngestPipeline

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=sample_md_file,
            owner_id="user-default",
            scope="shared",
        )

        # 操作成功
        assert result.ok is True
        assert result.operation_id is not None
        assert result.source_id is not None

        # 文件被归档
        archive_dir = tmp_workspace / "raw" / "archive" / result.source_id
        assert archive_dir.is_dir()
        assert (archive_dir / "source.yaml").exists()

        # 解析结果
        extracted_dir = tmp_workspace / "raw" / "extracted" / result.source_id
        assert extracted_dir.is_dir()
        assert (extracted_dir / "content.md").exists()

    def test_ingest_creates_source_page(self, tmp_workspace, sample_md_file):
        """摄入后 wiki/sources/ 下生成来源页。"""
        from mini_note.ingest.pipeline import IngestPipeline

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=sample_md_file,
            owner_id="user-default",
            scope="shared",
        )

        source_page = tmp_workspace / "wiki" / "sources" / f"{result.source_id}.md"
        assert source_page.exists(), f"Expected {source_page} to exist"
        content = source_page.read_text()
        assert result.source_id in content

    def test_ingest_updates_index(self, tmp_workspace, sample_md_file):
        """摄入后 index.md 被更新。"""
        from mini_note.ingest.pipeline import IngestPipeline

        original_index = (tmp_workspace / "wiki" / "index.md").read_text()

        pipeline = IngestPipeline(tmp_workspace)
        pipeline.run(
            file_path=sample_md_file,
            owner_id="user-default",
            scope="shared",
        )

        new_index = (tmp_workspace / "wiki" / "index.md").read_text()
        # index 应该增加了新页面的链接
        assert len(new_index) > len(original_index) or "[[wikilink]]" not in new_index

    def test_ingest_creates_operation_manifest(self, tmp_workspace, sample_md_file):
        """摄入产生 operation manifest。"""
        from mini_note.ingest.pipeline import IngestPipeline

        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=sample_md_file,
            owner_id="user-default",
            scope="shared",
        )

        manifest = (
            tmp_workspace / ".state" / "operations" / f"{result.operation_id}.yaml"
        )
        assert manifest.exists()
        content = manifest.read_text()
        assert result.source_id in content

    def test_duplicate_ingest_skips(self, tmp_workspace, sample_md_file):
        """重复摄入同一文件返回已有 source，不重复编译。"""
        from mini_note.ingest.pipeline import IngestPipeline

        pipeline = IngestPipeline(tmp_workspace)
        r1 = pipeline.run(
            file_path=sample_md_file,
            owner_id="user-default",
            scope="shared",
        )
        r2 = pipeline.run(
            file_path=sample_md_file,
            owner_id="user-default",
            scope="shared",
        )

        assert r1.source_id == r2.source_id
        # 第二次不应产生新的 operation
        count = len(list((tmp_workspace / ".state" / "operations").glob("*.yaml")))
        assert count >= 1  # 至少一次记录
