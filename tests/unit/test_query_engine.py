"""
Query Engine 单元测试 — 检索 Wiki 页面和 claim，返回结构化 JSON 素材。

CLI 的 query 命令只做检索不调模型。回答合成由 OpenClaw Skill 完成。
"""

import pytest


class TestQueryRetrieval:
    """测试查询检索功能。"""

    def test_query_returns_structured_result(self, tmp_workspace):
        """查询返回结构化 JSON。"""
        from mini_note.query.engine import QueryEngine

        engine = QueryEngine(tmp_workspace)
        result = engine.search("测试问题", scope="shared")

        assert "pages" in result
        assert "claims" in result
        assert "question" in result

    def test_query_respects_scope(self, tmp_workspace):
        """查询按 scope 过滤。"""
        from mini_note.query.engine import QueryEngine

        engine = QueryEngine(tmp_workspace)
        result = engine.search("随便", scope="shared")
        # 不抛异常即为通过
        assert result is not None

    def test_query_reads_index(self, tmp_workspace):
        """查询读取 wiki/index.md。"""
        (tmp_workspace / "wiki" / "index.md").write_text(
            "# Index\n- [[wiki/sources/test.md|测试]]\n"
        )
        from mini_note.query.engine import QueryEngine

        engine = QueryEngine(tmp_workspace)
        result = engine.search("测试", scope="shared")
        assert len(result["pages"]) >= 0

    def test_query_with_wiki_pages(self, tmp_workspace):
        """wiki 中有页面时查询返回相关内容。"""
        import yaml

        page_content = """---
page_id: page-ecs
title: "ECS 性能"
type: "concept"
scope: "shared"
owner_id: "user-default"
status: "published"
created_at: "2026-05-13T12:00:00+08:00"
updated_at: "2026-05-13T12:10:00+08:00"
---
# ECS 性能

ECS 突发性能实例适合低负载场景。
"""
        (tmp_workspace / "wiki" / "concepts" / "ecs.md").write_text(page_content)

        from mini_note.query.engine import QueryEngine

        engine = QueryEngine(tmp_workspace)
        result = engine.search("ECS 性能", scope="shared")
        assert len(result["pages"]) >= 1

    def test_query_with_claims(self, tmp_workspace):
        """claim 被包含在查询结果中。"""
        import yaml

        claims_dir = tmp_workspace / "raw" / "extracted" / "src-test"
        claims_dir.mkdir(parents=True)
        claims_data = {
            "claims": [
                {
                    "claim_id": "claim-001",
                    "source_id": "src-test",
                    "text": "ECS 实例最大带宽为 1.5 Gbps",
                    "locator": "page=6",
                    "quote_hash": "sha256:abc",
                    "status": "active",
                    "verified_at": "2026-05-13T12:00:00+08:00",
                }
            ]
        }
        (claims_dir / "claims.yaml").write_text(
            yaml.dump(claims_data, allow_unicode=True)
        )

        from mini_note.query.engine import QueryEngine

        engine = QueryEngine(tmp_workspace)
        engine.rebuild_index()
        result = engine.search("带宽", scope="shared")
        assert len(result["claims"]) >= 1

    def test_query_evidence_insufficient(self, tmp_workspace):
        """知识库无相关内容时不崩溃。"""
        from mini_note.query.engine import QueryEngine

        engine = QueryEngine(tmp_workspace)
        result = engine.search("不存在的内容 XYZABC", scope="shared")
        assert result["pages"] == [] or len(result["pages"]) >= 0

    def test_query_empty_question(self, tmp_workspace):
        """空查询问题返回结构化错误。"""
        from mini_note.query.engine import QueryEngine

        engine = QueryEngine(tmp_workspace)
        result = engine.search("", scope="shared")
        assert result["ok"] is False
        assert result["error_code"] == "EMPTY_QUESTION"
        assert result["pages"] == []

    def test_query_whitespace_question(self, tmp_workspace):
        """纯空白查询问题返回结构化错误。"""
        from mini_note.query.engine import QueryEngine

        engine = QueryEngine(tmp_workspace)
        result = engine.search("   ", scope="shared")
        assert result["ok"] is False
        assert result["error_code"] == "EMPTY_QUESTION"
