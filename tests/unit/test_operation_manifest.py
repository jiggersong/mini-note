"""
Operation Manifest 单元测试 — 状态机流转、恢复判断。

测试目标（v2.4 §18.1）:
- operation 状态机全部合法路径
- 每个状态可正确判断是否可恢复
- manifest 序列化/反序列化
"""

import pytest


# ============================================================
# Manifest 创建
# ============================================================

class TestManifestCreation:
    """测试 operation manifest 创建。"""

    def test_valid_manifest_created(self, sample_operation_manifest):
        """合法数据创建 manifest 成功。"""
        from mini_note.models.operation import OperationManifest

        op = OperationManifest(**sample_operation_manifest)
        assert op.operation_id == sample_operation_manifest["operation_id"]
        assert op.status == "planned"

    def test_default_status_is_planned(self, sample_operation_manifest):
        """默认状态为 planned。"""
        from mini_note.models.operation import OperationManifest

        data = {**sample_operation_manifest}
        del data["status"]
        op = OperationManifest(**data)
        assert op.status == "planned"

    def test_missing_operation_id_raises(self, sample_operation_manifest):
        """缺少 operation_id 抛出异常。"""
        from mini_note.models.operation import OperationManifest

        data = {**sample_operation_manifest}
        del data["operation_id"]
        with pytest.raises(TypeError):
            OperationManifest(**data)

    def test_missing_type_raises(self, sample_operation_manifest):
        """缺少 type 抛出异常。"""
        from mini_note.models.operation import OperationManifest

        data = {**sample_operation_manifest}
        del data["type"]
        with pytest.raises(TypeError):
            OperationManifest(**data)

    def test_invalid_type_raises(self, sample_operation_manifest):
        """无效 type 抛出异常。"""
        from mini_note.models.operation import OperationManifest

        with pytest.raises(ValueError, match="type"):
            OperationManifest(**{**sample_operation_manifest, "type": "unknown"})


# ============================================================
# 状态机流转
# ============================================================

class TestStatusTransitions:
    """测试 operation 状态机。"""

    def test_planned_to_staged(self, sample_operation_manifest):
        """planned → staged 合法。"""
        from mini_note.models.operation import OperationManifest

        op = OperationManifest(**sample_operation_manifest)
        op.transition_to("staged")
        assert op.status == "staged"

    def test_staged_to_applied(self, sample_operation_manifest):
        """staged → applied 合法。"""
        from mini_note.models.operation import OperationManifest

        op = OperationManifest(**{**sample_operation_manifest, "status": "staged"})
        op.transition_to("applied")
        assert op.status == "applied"

    def test_applied_to_indexed(self, sample_operation_manifest):
        """applied → indexed 合法。"""
        from mini_note.models.operation import OperationManifest

        op = OperationManifest(**{**sample_operation_manifest, "status": "applied"})
        op.transition_to("indexed")
        assert op.status == "indexed"

    def test_indexed_to_backed_up(self, sample_operation_manifest):
        """indexed → backed_up 合法。"""
        from mini_note.models.operation import OperationManifest

        op = OperationManifest(**{**sample_operation_manifest, "status": "indexed"})
        op.transition_to("backed_up")
        assert op.status == "backed_up"

    def test_any_status_to_failed(self, sample_operation_manifest):
        """任意状态都可以转为 failed。"""
        from mini_note.models.operation import OperationManifest

        for status in ["planned", "staged", "applied", "indexed", "backed_up"]:
            op = OperationManifest(**{**sample_operation_manifest, "status": status})
            op.transition_to("failed")
            assert op.status == "failed"

    def test_failed_any_status_to_failed_any_other(self):
        """failed 状态不能直接转非 failed。"""
        from mini_note.models.operation import OperationManifest

        op = OperationManifest(
            operation_id="op-test",
            type="ingest",
            status="failed",
            source_ids=["src-test"],
            planned_changes=[],
        )
        with pytest.raises(ValueError, match="不允许"):
            op.transition_to("backed_up")

    def test_backed_up_is_terminal(self, sample_operation_manifest):
        """backed_up 是终态，不能转其他（failed 除外）。"""
        from mini_note.models.operation import OperationManifest

        op = OperationManifest(**{**sample_operation_manifest, "status": "backed_up"})
        with pytest.raises(ValueError, match="终态"):
            op.transition_to("applied")

    def test_skip_forward_disallowed(self, sample_operation_manifest):
        """不允许跳过中间状态（如 planned → indexed）。"""
        from mini_note.models.operation import OperationManifest

        op = OperationManifest(**sample_operation_manifest)
        with pytest.raises(ValueError, match="不允许"):
            op.transition_to("indexed")


# ============================================================
# 恢复判断
# ============================================================

class TestRecoveryLogic:
    """测试各状态下的恢复逻辑判断。"""

    def test_planned_failure_discard_and_retry(self):
        """planned/staged 失败：丢弃 staging，重新执行。"""
        from mini_note.models.operation import OperationManifest

        op = OperationManifest(
            operation_id="op-test", type="ingest", status="planned",
            source_ids=["src-test"], planned_changes=[],
        )
        assert op.is_recoverable() is True
        assert op.recovery_action() == "discard_staging_retry"

    def test_staged_failure_discard_and_retry(self):
        """staged 失败同 planned。"""
        from mini_note.models.operation import OperationManifest

        op = OperationManifest(
            operation_id="op-test", type="ingest", status="staged",
            source_ids=["src-test"], planned_changes=[],
        )
        assert op.recovery_action() == "discard_staging_retry"

    def test_applied_failure_rebuild_index(self):
        """applied 失败：从 manifest 重建索引。"""
        from mini_note.models.operation import OperationManifest

        op = OperationManifest(
            operation_id="op-test", type="ingest", status="applied",
            source_ids=["src-test"], planned_changes=[],
        )
        assert op.recovery_action() == "rebuild_index_continue"

    def test_indexed_failure_retry_backup(self):
        """indexed 失败：不回滚数据，重试 OSS 备份。"""
        from mini_note.models.operation import OperationManifest

        op = OperationManifest(
            operation_id="op-test", type="ingest", status="indexed",
            source_ids=["src-test"], planned_changes=[],
        )
        assert op.recovery_action() == "retry_backup"

    def test_backed_up_no_recovery_needed(self):
        """backed_up 状态无需恢复。"""
        from mini_note.models.operation import OperationManifest

        op = OperationManifest(
            operation_id="op-test", type="ingest", status="backed_up",
            source_ids=["src-test"], planned_changes=[],
        )
        assert op.needs_recovery() is False
