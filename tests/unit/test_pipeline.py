"""Ingest Pipeline 单元测试 — claim 构建、quote_hash、verified_at 语义。"""

import hashlib


class TestBuildClaims:
    """_build_claims 启发式 claim 提取。"""

    def test_bullet_claim_has_sha256_quote_hash(self):
        """Bullet 要点 claim 应有 sha256: 前缀的 quote_hash。"""
        from mini_note.ingest.pipeline import _build_claims

        content = "- ECS 突发性能实例基线 CPU 为 20%"
        claims = _build_claims("src-test", content, ".md")
        assert len(claims) >= 1, "应至少提取 1 条 bullet claim"
        for c in claims:
            assert c["quote_hash"].startswith("sha256:"), \
                f"quote_hash 应以 sha256: 开头: {c['quote_hash']}"
            # 验证 hash 值正确
            expected = "sha256:" + hashlib.sha256(c["text"].encode("utf-8")).hexdigest()
            assert c["quote_hash"] == expected

    def test_unverified_claim_verified_at_empty(self):
        """unverified claim 的 verified_at 应为空字符串。"""
        from mini_note.ingest.pipeline import _build_claims

        content = "数据库最大连接数为 2000，超时时间 30 秒。"
        claims = _build_claims("src-test", content, ".txt")
        for c in claims:
            assert c["status"] == "unverified"
            assert c["verified_at"] == "", \
                f"unverified claim 的 verified_at 应为空: {c['verified_at']}"

    def test_meeting_keyword_triggers_claim(self):
        """含会议关键词的句子应被提取。"""
        from mini_note.ingest.pipeline import _build_claims

        content = "会议决定将 ECS 实例规格统一为 ecs.c6e.xlarge"
        claims = _build_claims("src-test", content, ".md")
        assert len(claims) >= 1, f"应至少提取 1 条会议 claim: {len(claims)}"

    def test_digit_sentence_triggers_claim(self):
        """含数字 + 关键词句子应被提取。"""
        from mini_note.ingest.pipeline import _build_claims

        content = "RDS 最大 IOPS 为 50000，适用于高并发 OLTP 场景。"
        claims = _build_claims("src-test", content, ".txt")
        assert len(claims) >= 1

    def test_short_text_not_extracted(self):
        """过短文本不应生成 claim。"""
        from mini_note.ingest.pipeline import _build_claims

        content = "短。太短。"
        claims = _build_claims("src-test", content, ".md")
        # 所有句子都 < 10 或 < 8 字符，不应生成 claim
        assert all(len(c["text"]) >= 8 for c in claims)

    def test_duplicate_content_not_double_claimed(self):
        """同一内容不应重复生成 claim。"""
        from mini_note.ingest.pipeline import _build_claims

        content = "ECS 最大带宽 1.5 Gbps\nECS 最大带宽 1.5 Gbps"
        claims = _build_claims("src-test", content, ".txt")
        texts = [c["text"] for c in claims]
        assert len(texts) == len(set(texts)), "不应有重复 claim"


class TestLintSummary:
    """lint 命令返回 summary 统计。"""

    def test_lint_returns_summary(self, tmp_workspace):
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        result = main([
            "lint", "--workspace", str(tmp_workspace),
            "--min-severity", "info", "--json",
        ])
        assert "lint_summary" in result
        s = result["lint_summary"]
        assert "min_severity" in s
        assert "total_before_filter" in s
        assert "total_after_filter" in s
        assert "suppressed_count" in s
        assert s["suppressed_count"] == s["total_before_filter"] - s["total_after_filter"]

    def test_lint_min_severity_error_suppresses_warnings(self, tmp_workspace):
        from mini_note.cli import main

        main(["init", "--workspace", str(tmp_workspace)])
        # 创建孤立页面以生成 info 级 lint
        page = tmp_workspace / "wiki" / "orphan.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("# orphan")
        # 创建 index.md
        (tmp_workspace / "wiki" / "index.md").write_text("# Index")

        result = main([
            "lint", "--workspace", str(tmp_workspace),
            "--min-severity", "error", "--json",
        ])
        assert result["lint_summary"]["suppressed_count"] > 0
        # error 级别过滤后，info 级孤页应被抑制
        assert len(result.get("orphan_pages", [])) == 0
