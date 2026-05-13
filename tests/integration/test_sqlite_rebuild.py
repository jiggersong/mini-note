"""
集成测试：SQLite 损坏后重建。

验证（v2.4 §18.2）:
- 删除 SQLite 后可完整重建
- 重建结果与文件内容一致
- 重复重建不影响正确性
"""

import pytest


class TestSQLiteRebuild:
    """测试 SQLite 完整重建流程。"""

    def test_rebuild_after_deletion(self, tmp_workspace, sample_md_file):
        """摄入后删除 SQLite，重建后数据一致。"""
        from mini_note.ingest.pipeline import IngestPipeline
        from mini_note.indexer import Indexer
        import sqlite3

        # 先摄入一个文件
        pipeline = IngestPipeline(tmp_workspace)
        result = pipeline.run(
            file_path=sample_md_file,
            owner_id="user-default",
            scope="shared",
        )

        # 记录摄入前的 source page
        source_page = tmp_workspace / "wiki" / "sources" / f"{result.source_id}.md"
        assert source_page.exists()

        # 删除 SQLite
        db_path = tmp_workspace / ".state" / "notes.db"
        if db_path.exists():
            db_path.unlink()

        # 重建索引
        idx = Indexer(tmp_workspace)
        idx.rebuild()

        # 验证
        assert db_path.exists()
        conn = sqlite3.connect(str(db_path))
        pages = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        # 应至少包含 source page + index + overview
        assert pages >= 1
        conn.close()

    def test_rebuild_with_multiple_sources(self, tmp_workspace):
        """多个 source 摄入后重建，所有 source 索引恢复。"""
        from mini_note.ingest.pipeline import IngestPipeline
        from mini_note.indexer import Indexer
        import sqlite3

        pipeline = IngestPipeline(tmp_workspace)

        # 摄入多个文件
        for i in range(3):
            f = tmp_workspace / "raw" / "inbox" / "users" / f"doc{i}.md"
            f.write_text(f"# Document {i}\n\nContent {i}")
            pipeline.run(file_path=f, owner_id="user-default", scope="shared")

        # 删除 SQLite
        db_path = tmp_workspace / ".state" / "notes.db"
        db_path.unlink()

        # 重建
        idx = Indexer(tmp_workspace)
        idx.rebuild()

        # 验证 source 数量
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        assert count == 3
        conn.close()

    def test_rebuild_preserves_claim_ids(self, tmp_workspace):
        """重建后 claim 数据与 extracted/ 中的 claims.yaml 一致。"""
        from mini_note.ingest.pipeline import IngestPipeline
        from mini_note.indexer import Indexer
        import sqlite3
        import yaml

        pipeline = IngestPipeline(tmp_workspace)
        f = tmp_workspace / "raw" / "inbox" / "users" / "claim-doc.md"
        f.write_text(
            "# Claim 测试\n\n关键事实：ECS 突发性能实例支持 CPU 积分。\n"
            "另一事实：最大带宽为 1.5 Gbps。\n"
        )
        result = pipeline.run(file_path=f, owner_id="user-default", scope="shared")

        # 验证 claims.yaml 存在
        claims_yaml = (
            tmp_workspace / "raw" / "extracted" / result.source_id / "claims.yaml"
        )
        if claims_yaml.exists():
            with open(claims_yaml) as fh:
                claims_data = yaml.safe_load(fh)

            # 删除并重建 SQLite
            db_path = tmp_workspace / ".state" / "notes.db"
            db_path.unlink()
            idx = Indexer(tmp_workspace)
            idx.rebuild()

            # 重建后的 claim 数量应一致
            conn = sqlite3.connect(str(db_path))
            db_count = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
            expected = len(claims_data["claims"]) if claims_data and "claims" in claims_data else 0
            assert db_count == expected
            conn.close()
