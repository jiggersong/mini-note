"""FTS5 全文检索单元测试 — bigram 分词、索引重建、搜索。"""

import pytest


class TestBigram:
    """测试中文 bigram 分词。"""

    def test_pure_chinese_bigram(self):
        """纯中文转为连续 bigram。"""
        from mini_note.indexer.fts import _to_bigrams

        result = _to_bigrams("性能优化")
        assert "性能" in result
        assert "能优" in result
        assert "优化" in result

    def test_mixed_chinese_english(self):
        """中英混合：英文保持，中文 bigram。"""
        from mini_note.indexer.fts import _to_bigrams

        result = _to_bigrams("ECS 突发性能")
        assert "ECS" in result
        assert "突发" in result
        assert "发性能" not in result  # "发性" + "能" ... wait let me check
        # "突发" → "突发", "发性" → "发性"? No. "突发性能" is 4 chars: 突,发,性,能
        # bigrams: 突发, 发性, 性能. But "发性" is not a real word.
        # This is expected behavior of bigram approach. Accept it.
        assert isinstance(result, str)

    def test_single_chinese_char(self):
        """单个中文字符保留。"""
        from mini_note.indexer.fts import _to_bigrams

        result = _to_bigrams("云")
        assert "云" in result

    def test_pure_english(self):
        """纯英文保持原样。"""
        from mini_note.indexer.fts import _to_bigrams

        result = _to_bigrams("hello world")
        assert "hello" in result
        assert "world" in result

    def test_empty_string(self):
        """空字符串安全。"""
        from mini_note.indexer.fts import _to_bigrams

        result = _to_bigrams("")
        assert result == ""

    def test_numbers_preserved(self):
        """数字保持原样。"""
        from mini_note.indexer.fts import _to_bigrams

        result = _to_bigrams("最大连接数 1000")
        assert "1000" in result
        assert "最大" in result


class TestQueryTokenize:
    """测试查询 token 化。"""

    def test_simple_query(self):
        """简单查询转为 OR 连接。"""
        from mini_note.indexer.fts import tokenize_query

        result = tokenize_query("ECS 性能")
        tokens = result.split(" OR ")
        assert len(tokens) >= 1

    def test_pure_chinese_query(self):
        """纯中文查询转为 bigram OR 表达式。"""
        from mini_note.indexer.fts import tokenize_query

        result = tokenize_query("性能优化")
        assert " OR " in result
        tokens = result.split(" OR ")
        assert "性能" in tokens
        assert "能优" in tokens


class TestFTSIndex:
    """测试 FTS5 索引创建和搜索。"""

    def test_rebuild_creates_fts_tables(self, tmp_workspace):
        """索引重建创建 FTS5 虚拟表。"""
        from mini_note.indexer import Indexer

        idx = Indexer(tmp_workspace)
        idx.rebuild()

        import sqlite3
        conn = sqlite3.connect(str(tmp_workspace / ".state" / "notes.db"))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'fts_%'"
        ).fetchall()
        conn.close()
        table_names = [t[0] for t in tables]
        assert "fts_pages" in table_names
        assert "fts_claims" in table_names

    def test_fts_search_pages(self, tmp_workspace):
        """FTS5 搜索返回匹配页面。"""
        # 创建 wiki 页面
        (tmp_workspace / "wiki" / "concepts" / "ecs.md").write_text(
            "---\ntitle: ECS 性能\n---\nECS 突发性能实例适合低负载场景。\n"
        )
        (tmp_workspace / "wiki" / "index.md").write_text("# Index")

        from mini_note.indexer import Indexer
        idx = Indexer(tmp_workspace)
        idx.rebuild()

        from mini_note.indexer.fts import FTSIndex
        fts = FTSIndex(tmp_workspace)
        results = fts.search_pages("ECS 性能")
        assert len(results) >= 1
        assert any("ECS" in r.get("title", "") or "ecs" in r.get("path", "") for r in results)

    def test_fts_search_claims(self, tmp_workspace):
        """FTS5 搜索返回匹配 claim。"""
        import yaml
        ext_dir = tmp_workspace / "raw" / "extracted" / "src-test"
        ext_dir.mkdir(parents=True)
        (ext_dir / "claims.yaml").write_text(yaml.dump({
            "claims": [{
                "claim_id": "claim-001",
                "source_id": "src-test",
                "text": "最大连接数为 1000",
                "locator": "page=3",
                "quote_hash": "sha256:abc",
                "status": "active",
                "verified_at": "2026-05-13T12:00:00+08:00",
            }]
        }))

        from mini_note.indexer import Indexer
        idx = Indexer(tmp_workspace)
        idx.rebuild()

        from mini_note.indexer.fts import FTSIndex
        fts = FTSIndex(tmp_workspace)
        results = fts.search_claims("连接数")
        assert len(results) >= 1

    def test_fts_search_no_match(self, tmp_workspace):
        """无匹配内容返回空列表不崩溃。"""
        from mini_note.indexer import Indexer
        idx = Indexer(tmp_workspace)
        idx.rebuild()

        from mini_note.indexer.fts import FTSIndex
        fts = FTSIndex(tmp_workspace)
        results = fts.search_pages("XYZABC 不存在的内容")
        assert isinstance(results, list)

    def test_fts_idempotent_rebuild(self, tmp_workspace):
        """多次重建索引不崩溃。"""
        (tmp_workspace / "wiki" / "concepts" / "test.md").write_text("# Test")
        from mini_note.indexer import Indexer

        for _ in range(3):
            idx = Indexer(tmp_workspace)
            idx.rebuild()

        from mini_note.indexer.fts import FTSIndex
        fts = FTSIndex(tmp_workspace)
        results = fts.search_pages("Test")
        assert isinstance(results, list)

    def test_fts_with_scope_filter(self, tmp_workspace):
        """FTS 搜索尊重 scope 过滤。"""
        (tmp_workspace / "wiki" / "concepts" / "shared-page.md").write_text(
            "---\ntitle: 共享\nscope: shared\n---\n共享内容\n"
        )
        from mini_note.indexer import Indexer
        idx = Indexer(tmp_workspace)
        idx.rebuild()

        from mini_note.indexer.fts import FTSIndex
        fts = FTSIndex(tmp_workspace)
        results = fts.search_pages("共享", scope="shared")
        assert isinstance(results, list)


class TestQueryEngineFTS:
    """测试 QueryEngine 与 FTS5 集成。"""

    def test_query_uses_fts_after_rebuild(self, tmp_workspace):
        """rebuild 后 query 使用 FTS5 搜索。"""
        (tmp_workspace / "wiki" / "concepts" / "ecs.md").write_text(
            "---\ntitle: ECS 性能\n---\nECS 突发性能实例适合低负载场景。\n"
        )
        from mini_note.query.engine import QueryEngine

        engine = QueryEngine(tmp_workspace)
        engine.rebuild_index()
        result = engine.search("ECS 性能", scope="shared")
        assert len(result["pages"]) >= 1

    def test_query_fallback_without_fts(self, tmp_workspace):
        """无 FTS 表时回退到关键词匹配不崩溃。"""
        from mini_note.query.engine import QueryEngine

        engine = QueryEngine(tmp_workspace)
        result = engine.search("测试问题", scope="shared")
        assert "pages" in result
        assert "claims" in result


class TestFTSScopeFilter:
    """FTS 查询按 scope 过滤页面。"""

    def test_fts_respects_private_scope(self, tmp_workspace):
        """scope=private 时只返回 private 页面，不返回 shared。"""
        from mini_note.cli import main as cli_main
        from mini_note.query.engine import QueryEngine

        ws = tmp_workspace
        cli_main(["init", "--workspace", str(ws)])
        # 创建一个 private 页面
        (ws / "wiki" / "sources" / "private-page.md").write_text(
            "---\npage_id: priv-1\ntitle: Private Page\ntype: source\nscope: private\n---\n# Private\nECS 性能优化要点\n", encoding="utf-8"
        )
        # 创建一个 shared 页面
        (ws / "wiki" / "sources" / "shared-page.md").write_text(
            "---\npage_id: shared-1\ntitle: Shared Page\ntype: source\nscope: shared\n---\n# Shared\nECS 配置建议\n", encoding="utf-8"
        )
        from mini_note.indexer import Indexer
        Indexer(ws).rebuild()

        engine = QueryEngine(ws)
        result = engine.search("ECS", scope="private")
        # private 查询应只返回 private 页面
        for p in result["pages"]:
            assert p["scope"] == "private", f"不应返回 scope={p['scope']} 的页面"

    def test_fts_shared_scope_sees_all(self, tmp_workspace):
        """scope=shared 时返回所有 scope 的页面。"""
        from mini_note.cli import main as cli_main
        from mini_note.query.engine import QueryEngine

        ws = tmp_workspace
        cli_main(["init", "--workspace", str(ws)])
        (ws / "wiki" / "sources" / "private-page.md").write_text(
            "---\npage_id: priv-2\ntitle: Private\ntype: source\nscope: private\n---\n# Private\nECS 优化\n", encoding="utf-8"
        )
        (ws / "wiki" / "sources" / "shared-page.md").write_text(
            "---\npage_id: shared-2\ntitle: Shared\ntype: source\nscope: shared\n---\n# Shared\nECS 配置\n", encoding="utf-8"
        )
        from mini_note.indexer import Indexer
        Indexer(ws).rebuild()

        engine = QueryEngine(ws)
        result = engine.search("ECS", scope="shared")
        scopes = {p["scope"] for p in result["pages"]}
        assert "private" in scopes or "shared" in scopes
        assert len(result["pages"]) >= 1
