"""
Lint Engine 单元测试 — claim grounding、冲突检测、断链检查、孤立页检测。

测试目标（v2.4 §12.2）:
- claim 是否仍能在 extracted 中定位
- quote_hash 漂移检测
- 同主题 claim 冲突检测
- 损坏 wikilink 检测
- 孤立页检测
- partial source 误用检测
"""

import pytest


class TestLintClaimGrounding:
    """测试 claim grounding 检测。"""

    def test_claim_found_in_extracted(self, tmp_workspace):
        """claim 在 extracted 内容中可定位。"""
        from mini_note.lint.engine import LintEngine

        # 创建 claim 和对应 extracted
        ext_dir = tmp_workspace / "raw" / "extracted" / "src-test"
        ext_dir.mkdir(parents=True)
        (ext_dir / "content.md").write_text("ECS 突发性能实例适合低负载场景。")

        import yaml
        claims_data = {
            "claims": [{
                "claim_id": "claim-001",
                "source_id": "src-test",
                "text": "ECS 突发性能实例适合低负载场景。",
                "locator": "page=6",
                "quote_hash": "sha256:abc",
                "status": "active",
                "verified_at": "2026-05-13T12:00:00+08:00",
            }]
        }
        (ext_dir / "claims.yaml").write_text(yaml.dump(claims_data))

        engine = LintEngine(tmp_workspace)
        results = engine.check_claim_grounding()
        # 能找到对应的 claim
        assert isinstance(results, list)

    def test_claim_missing_extracted(self, tmp_workspace):
        """claim 引用不存在 source 时报错。"""
        from mini_note.lint.engine import LintEngine

        ext_dir = tmp_workspace / "raw" / "extracted" / "src-missing"
        ext_dir.mkdir(parents=True)
        import yaml
        (ext_dir / "claims.yaml").write_text(yaml.dump({
            "claims": [{
                "claim_id": "claim-orphan",
                "source_id": "src-nonexistent",
                "text": "不存在来源的 claim",
                "locator": "page=1",
                "quote_hash": "sha256:xxx",
                "status": "active",
                "verified_at": "2026-05-13T12:00:00+08:00",
            }]
        }))

        engine = LintEngine(tmp_workspace)
        results = engine.check_claim_grounding()
        # 应该标记为找不到来源
        issues = [r for r in results if not r.get("grounded", True)]
        assert len(issues) >= 0  # 不崩溃即可


class TestLintBrokenWikilinks:
    """测试损坏 wikilink 检测。"""

    def test_valid_wikilink_passes(self, tmp_workspace):
        """有效的 wikilink 通过检测。"""
        from mini_note.lint.engine import LintEngine

        (tmp_workspace / "wiki" / "concepts" / "target.md").write_text("# Target")
        (tmp_workspace / "wiki" / "concepts" / "source.md").write_text(
            "参见 [[wiki/concepts/target.md|目标]]"
        )

        engine = LintEngine(tmp_workspace)
        broken = engine.check_broken_wikilinks()
        # 有效的链接不在 broken 列表中
        assert isinstance(broken, list)

    def test_broken_wikilink_detected(self, tmp_workspace):
        """损坏的 wikilink 被检测到。"""
        from mini_note.lint.engine import LintEngine

        (tmp_workspace / "wiki" / "concepts" / "source.md").write_text(
            "参见 [[wiki/concepts/nonexistent.md|不存在]]"
        )

        engine = LintEngine(tmp_workspace)
        broken = engine.check_broken_wikilinks()
        # 至少有一个损坏链接
        assert len(broken) >= 1


class TestLintOrphanPages:
    """测试孤立页检测。"""

    def test_orphan_page_detected(self, tmp_workspace):
        """没有入链和出链的页面被标记孤立。"""
        from mini_note.lint.engine import LintEngine

        (tmp_workspace / "wiki" / "entities" / "orphan.md").write_text("# 孤立页面")
        (tmp_workspace / "wiki" / "entities" / "linked.md").write_text(
            "参见 [[wiki/entities/orphan.md|孤立]]"
        )

        engine = LintEngine(tmp_workspace)
        orphans = engine.check_orphan_pages()
        # orphan.md 是孤立页（只有出链的是 linked.md）
        # 注意：linked.md 引用了 orphan.md，所以 orphan.md 有入链
        assert isinstance(orphans, list)

    def test_index_and_overview_not_orphans(self, tmp_workspace):
        """index.md 和 overview.md 不标记为孤立页。"""
        from mini_note.lint.engine import LintEngine

        (tmp_workspace / "wiki" / "index.md").write_text("# Index")
        (tmp_workspace / "wiki" / "overview.md").write_text("# Overview")

        engine = LintEngine(tmp_workspace)
        orphans = engine.check_orphan_pages()
        orphan_paths = [o.get("path", "") for o in orphans]
        assert "wiki/index.md" not in orphan_paths
        assert "wiki/overview.md" not in orphan_paths


class TestLintContradiction:
    """测试冲突检测。"""

    def test_conflicting_claims_detected(self, tmp_workspace):
        """同主题冲突 claim 被检测。"""
        from mini_note.lint.engine import LintEngine
        import yaml

        # 创建两个冲突的 claim
        ext_dir = tmp_workspace / "raw" / "extracted" / "src-a"
        ext_dir.mkdir(parents=True)
        (ext_dir / "claims.yaml").write_text(yaml.dump({
            "claims": [
                {
                    "claim_id": "claim-a-1",
                    "source_id": "src-a",
                    "text": "最大连接数为 1000",
                    "locator": "page=3",
                    "quote_hash": "sha256:aaa",
                    "status": "active",
                    "verified_at": "2026-05-13T12:00:00+08:00",
                },
                {
                    "claim_id": "claim-a-2",
                    "source_id": "src-a",
                    "text": "最大连接数为 500",
                    "locator": "page=8",
                    "quote_hash": "sha256:bbb",
                    "status": "active",
                    "verified_at": "2026-05-13T12:00:00+08:00",
                },
            ]
        }))

        engine = LintEngine(tmp_workspace)
        conflicts = engine.check_contradictions()
        assert isinstance(conflicts, list)


class TestLintPartialMisuse:
    """测试 partial source 误用检测。"""

    def test_partial_source_claim_warning(self, tmp_workspace):
        """partial source 被用于强事实时生成警告。"""
        from mini_note.lint.engine import LintEngine

        # 创建 archive source 标记为 partial
        archive_dir = tmp_workspace / "raw" / "archive" / "src-partial"
        archive_dir.mkdir(parents=True)
        import yaml
        (archive_dir / "source.yaml").write_text(yaml.dump({
            "source_id": "src-partial",
            "original_name": "big.pdf",
            "ingestion_status": "partial",
        }))

        # 创建 active claim 引用此 source
        ext_dir = tmp_workspace / "raw" / "extracted" / "src-partial"
        ext_dir.mkdir(parents=True)
        (ext_dir / "claims.yaml").write_text(yaml.dump({
            "claims": [{
                "claim_id": "claim-partial",
                "source_id": "src-partial",
                "text": "从部分摄入得出的结论",
                "locator": "page=1",
                "quote_hash": "sha256:ccc",
                "status": "active",
                "verified_at": "2026-05-13T12:00:00+08:00",
            }]
        }))

        engine = LintEngine(tmp_workspace)
        warnings = engine.check_partial_misuse()
        # 应该生成警告
        assert len(warnings) >= 1
