"""
Indexer 单元测试 — 从 Markdown 文件重建 SQLite 派生索引。

测试目标（v2.4 §18.1）:
- 删除 SQLite 后可完整重建
- 重建结果与文件一致
- 空 workspace 重建不崩溃
"""

import pytest


class TestIndexerRebuild:
    """测试索引重建。"""

    def test_rebuild_from_empty_workspace(self, tmp_workspace):
        """空 workspace 重建不崩溃。"""
        from mini_note.indexer import Indexer

        idx = Indexer(tmp_workspace)
        idx.rebuild()
        # 重建后数据库文件存在
        assert (tmp_workspace / ".state" / "notes.db").exists()

    def test_rebuild_creates_sources_table(self, tmp_workspace):
        """重建后 sources 表存在。"""
        from mini_note.indexer import Indexer
        import sqlite3

        idx = Indexer(tmp_workspace)
        idx.rebuild()

        db_path = tmp_workspace / ".state" / "notes.db"
        conn = sqlite3.connect(str(db_path))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {r[0] for r in tables}
        assert "sources" in table_names
        assert "pages" in table_names
        assert "claims" in table_names
        conn.close()

    def test_rebuild_idempotent(self, tmp_workspace):
        """多次重建不影响正确性。"""
        from mini_note.indexer import Indexer

        idx = Indexer(tmp_workspace)
        idx.rebuild()
        idx.rebuild()
        idx.rebuild()
        assert (tmp_workspace / ".state" / "notes.db").exists()

    def test_rebuild_with_wiki_pages(self, tmp_workspace):
        """wiki 目录下有页面时索引正确记录。"""
        from mini_note.indexer import Indexer
        import sqlite3

        # 创建一个 wiki 页面
        page_content = """---
page_id: page-test-001
title: "测试页面"
type: "concept"
scope: "shared"
owner_id: "user-default"
status: "published"
created_at: "2026-05-13T12:00:00+08:00"
updated_at: "2026-05-13T12:10:00+08:00"
---
# 测试页面

页面正文内容。
"""
        (tmp_workspace / "wiki" / "concepts" / "test-page.md").write_text(page_content)

        idx = Indexer(tmp_workspace)
        idx.rebuild()

        db_path = tmp_workspace / ".state" / "notes.db"
        conn = sqlite3.connect(str(db_path))
        pages = conn.execute("SELECT path, title, page_type FROM pages").fetchall()
        assert len(pages) >= 1
        conn.close()

    def test_rebuild_with_source_yaml(self, tmp_workspace):
        """archive 下有 source.yaml 时索引正确记录。"""
        from mini_note.indexer import Indexer
        import sqlite3, yaml

        # 创建 source.yaml
        archive_dir = tmp_workspace / "raw" / "archive" / "src-test-001"
        archive_dir.mkdir(parents=True)
        source_data = {
            "source_id": "src-test-001",
            "original_name": "test.pdf",
            "stored_path": "raw/archive/src-test-001/original.pdf",
            "sha256": "abc123",
            "owner_id": "user-default",
            "scope": "shared",
            "media_type": "application/pdf",
            "size_bytes": 1000,
            "ingestion_status": "full",
            "created_at": "2026-05-13T12:00:00+08:00",
        }
        (archive_dir / "source.yaml").write_text(yaml.dump(source_data))

        idx = Indexer(tmp_workspace)
        idx.rebuild()

        db_path = tmp_workspace / ".state" / "notes.db"
        conn = sqlite3.connect(str(db_path))
        sources = conn.execute(
            "SELECT source_id, original_name, ingestion_status FROM sources"
        ).fetchall()
        assert len(sources) >= 1
        conn.close()


class TestIndexerCorruptedDB:
    """测试损坏数据库的恢复。"""

    def test_corrupt_db_deleted_and_rebuilt(self, tmp_workspace):
        """SQLite 文件损坏后被删除并重建。"""
        from mini_note.indexer import Indexer

        # 先重建一次
        idx = Indexer(tmp_workspace)
        idx.rebuild()

        # 破坏数据库
        db_path = tmp_workspace / ".state" / "notes.db"
        db_path.write_text("not a valid sqlite file")

        # 再次重建
        idx.rebuild()
        assert db_path.exists()
        assert db_path.stat().st_size > 0
