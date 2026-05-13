"""
Claim 数据模型单元测试 — 必填字段、状态流转、quote_hash。

测试目标（v2.4 §18.1）:
- claim 必填字段完整
- 状态机流转正确
- quote_hash 格式校验
- 非法数据拒绝
"""

import pytest


# ============================================================
# Claim 创建
# ============================================================

class TestClaimCreation:
    """测试 claim 创建和必填字段。"""

    def test_valid_claim_created(self, sample_claim_data):
        """合法数据创建 claim 成功。"""
        from mini_note.models.claim import Claim

        claim = Claim(**sample_claim_data)
        assert claim.claim_id == sample_claim_data["claim_id"]
        assert claim.status == "active"

    def test_missing_claim_id_raises(self, sample_claim_data):
        """缺少 claim_id 抛出异常。"""
        from mini_note.models.claim import Claim

        data = {**sample_claim_data}
        del data["claim_id"]
        with pytest.raises(TypeError):
            Claim(**data)

    def test_missing_source_id_raises(self, sample_claim_data):
        """缺少 source_id 抛出异常。"""
        from mini_note.models.claim import Claim

        data = {**sample_claim_data}
        del data["source_id"]
        with pytest.raises(TypeError):
            Claim(**data)

    def test_missing_text_raises(self, sample_claim_data):
        """缺少 text 抛出异常。"""
        from mini_note.models.claim import Claim

        data = {**sample_claim_data}
        del data["text"]
        with pytest.raises(TypeError):
            Claim(**data)

    def test_missing_locator_raises(self, sample_claim_data):
        """缺少 locator 抛出异常。"""
        from mini_note.models.claim import Claim

        data = {**sample_claim_data}
        del data["locator"]
        with pytest.raises(TypeError):
            Claim(**data)

    def test_empty_text_raises(self, sample_claim_data):
        """空文本抛出异常。"""
        from mini_note.models.claim import Claim

        data = {**sample_claim_data, "text": ""}
        with pytest.raises(ValueError, match="不能为空"):
            Claim(**data)

    def test_whitespace_only_text_raises(self, sample_claim_data):
        """纯空白文本抛出异常。"""
        from mini_note.models.claim import Claim

        data = {**sample_claim_data, "text": "   "}
        with pytest.raises(ValueError, match="不能为空"):
            Claim(**data)

    def test_confidence_range_validated(self, sample_claim_data):
        """confidence 必须在 0~1 之间。"""
        from mini_note.models.claim import Claim

        with pytest.raises(ValueError):
            Claim(**{**sample_claim_data, "confidence": -0.1})

        with pytest.raises(ValueError):
            Claim(**{**sample_claim_data, "confidence": 1.5})

    def test_confidence_boundary_values(self, sample_claim_data):
        """confidence 边界值 0.0 和 1.0 通过。"""
        from mini_note.models.claim import Claim

        c0 = Claim(**{**sample_claim_data, "confidence": 0.0})
        assert c0.confidence == 0.0

        c1 = Claim(**{**sample_claim_data, "confidence": 1.0})
        assert c1.confidence == 1.0


# ============================================================
# Claim 状态流转
# ============================================================

class TestClaimStatusTransitions:
    """测试 claim 状态机流转规则。"""

    def test_active_to_conflicted(self, sample_claim_data):
        """active → conflicted 合法。"""
        from mini_note.models.claim import Claim

        claim = Claim(**sample_claim_data)
        claim.transition_to("conflicted")
        assert claim.status == "conflicted"

    def test_active_to_deprecated(self, sample_claim_data):
        """active → deprecated 合法。"""
        from mini_note.models.claim import Claim

        claim = Claim(**sample_claim_data)
        claim.transition_to("deprecated")
        assert claim.status == "deprecated"

    def test_unverified_to_active(self, sample_claim_data):
        """unverified → active 合法。"""
        from mini_note.models.claim import Claim

        claim = Claim(**{**sample_claim_data, "status": "unverified"})
        claim.transition_to("active")
        assert claim.status == "active"

    def test_conflicted_can_be_deprecated(self, sample_claim_data):
        """conflicted → deprecated 合法。"""
        from mini_note.models.claim import Claim

        claim = Claim(**{**sample_claim_data, "status": "conflicted"})
        claim.transition_to("deprecated")
        assert claim.status == "deprecated"

    def test_deprecated_to_active_fails(self, sample_claim_data):
        """deprecated → active 非法（不可复活）。"""
        from mini_note.models.claim import Claim

        claim = Claim(**{**sample_claim_data, "status": "deprecated"})
        with pytest.raises(ValueError, match="不允许"):
            claim.transition_to("active")

    def test_invalid_status_raises(self, sample_claim_data):
        """无效状态名抛出异常。"""
        from mini_note.models.claim import Claim

        claim = Claim(**sample_claim_data)
        with pytest.raises(ValueError):
            claim.transition_to("deleted")


# ============================================================
# quote_hash 校验
# ============================================================

class TestQuoteHash:
    """测试 quote_hash 格式和校验。"""

    def test_sha256_format_accepted(self, sample_claim_data):
        """sha256: 前缀格式通过。"""
        from mini_note.models.claim import Claim

        claim = Claim(**{**sample_claim_data, "quote_hash": "sha256:d34db33f"})
        assert claim.quote_hash == "sha256:d34db33f"

    def test_non_prefixed_hash_rejected(self, sample_claim_data):
        """无前缀的 hash 被拒绝。"""
        from mini_note.models.claim import Claim

        with pytest.raises(ValueError, match="quote_hash"):
            Claim(**{**sample_claim_data, "quote_hash": "d34db33f"})

    def test_empty_quote_hash_for_unverified_claim(self, sample_claim_data):
        """unverified 状态的 claim 允许空 quote_hash。"""
        from mini_note.models.claim import Claim

        claim = Claim(**{
            **sample_claim_data,
            "status": "unverified",
            "quote_hash": "",
            "confidence": 0.3,
        })
        assert claim.quote_hash == ""

    def test_active_claim_requires_quote_hash(self, sample_claim_data):
        """active 状态的 claim 必须有 quote_hash。"""
        from mini_note.models.claim import Claim

        with pytest.raises(ValueError, match="quote_hash"):
            Claim(**{**sample_claim_data, "quote_hash": ""})


# ============================================================
# Claim 序列化
# ============================================================

class TestClaimSerialization:
    """测试 claim 的 YAML 序列化和反序列化。"""

    def test_to_dict_roundtrip(self, sample_claim_data):
        """to_dict 输出的字典可重建相同 Claim。"""
        from mini_note.models.claim import Claim

        claim = Claim(**sample_claim_data)
        d = claim.to_dict()
        restored = Claim(**d)
        assert restored.claim_id == claim.claim_id
        assert restored.status == claim.status
        assert restored.text == claim.text

    def test_to_yaml_produces_valid_yaml(self, sample_claim_data):
        """to_yaml 输出合法 YAML。"""
        from mini_note.models.claim import Claim
        import yaml

        claim = Claim(**sample_claim_data)
        yaml_str = claim.to_yaml()
        parsed = yaml.safe_load(yaml_str)
        assert parsed["claim_id"] == claim.claim_id
