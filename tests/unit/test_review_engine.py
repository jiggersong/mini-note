"""
Review Engine 单元测试 — 审核任务生成、白名单动作执行。

测试目标（v2.4 §13）:
- 审核任务格式正确
- 只接受 allowed_actions 中的动作
- review answer 更新任务状态
"""

import pytest


class TestReviewTaskCreation:
    """测试审核任务创建。"""

    def test_create_review_task(self, tmp_workspace):
        """创建审核任务成功。"""
        from mini_note.review.engine import ReviewEngine

        engine = ReviewEngine(tmp_workspace)
        task_id = engine.create_task(
            severity="high",
            reason="新旧资料冲突",
            question_for_user="以哪个为准？",
            recommended_action="mark_old_claim_deprecated",
            allowed_actions=[
                "mark_old_claim_deprecated",
                "keep_both_as_conflict",
            ],
            related_claims=["claim-old", "claim-new"],
        )
        assert task_id is not None
        assert task_id.startswith("review-")

    def test_review_task_persisted(self, tmp_workspace):
        """审核任务持久化到 .state/review_tasks/。"""
        from mini_note.review.engine import ReviewEngine

        engine = ReviewEngine(tmp_workspace)
        task_id = engine.create_task(
            severity="medium",
            reason="测试",
            question_for_user="确认？",
            recommended_action="keep_both_as_conflict",
            allowed_actions=["keep_both_as_conflict"],
            related_claims=["c1"],
        )

        task_file = tmp_workspace / ".state" / "review_tasks" / f"{task_id}.yaml"
        assert task_file.exists()

    def test_list_review_tasks(self, tmp_workspace):
        """列出审核任务。"""
        from mini_note.review.engine import ReviewEngine

        engine = ReviewEngine(tmp_workspace)
        engine.create_task(
            severity="low",
            reason="测试列表",
            question_for_user="?",
            recommended_action="keep_both_as_conflict",
            allowed_actions=["keep_both_as_conflict"],
            related_claims=[],
        )

        tasks = engine.list_tasks()
        assert len(tasks) >= 1

    def test_list_tasks_filter_by_status(self, tmp_workspace):
        """按状态过滤审核任务。"""
        from mini_note.review.engine import ReviewEngine

        engine = ReviewEngine(tmp_workspace)
        engine.create_task(
            severity="low", reason="测试", question_for_user="?",
            recommended_action="keep_both_as_conflict",
            allowed_actions=["keep_both_as_conflict"], related_claims=[],
        )

        open_tasks = engine.list_tasks(status="open")
        assert all(t["status"] == "open" for t in open_tasks)

    def test_show_task(self, tmp_workspace):
        """查看单个审核任务详情。"""
        from mini_note.review.engine import ReviewEngine

        engine = ReviewEngine(tmp_workspace)
        task_id = engine.create_task(
            severity="high", reason="冲突",
            question_for_user="以哪个为准？",
            recommended_action="keep_both_as_conflict",
            allowed_actions=["keep_both_as_conflict", "mark_old_claim_deprecated"],
            related_claims=["c1", "c2"],
        )

        task = engine.show_task(task_id)
        assert task["review_id"] == task_id
        assert task["severity"] == "high"
        assert len(task["allowed_actions"]) == 2


class TestReviewActions:
    """测试白名单动作执行。"""

    def test_allowed_action_accepted(self, tmp_workspace):
        """allowed_actions 中的动作可执行。"""
        from mini_note.review.engine import ReviewEngine

        engine = ReviewEngine(tmp_workspace)
        task_id = engine.create_task(
            severity="medium",
            reason="冲突",
            question_for_user="以哪个为准？",
            recommended_action="keep_both_as_conflict",
            allowed_actions=["keep_both_as_conflict", "mark_old_claim_deprecated"],
            related_claims=["claim-old"],
        )

        result = engine.answer(
            task_id,
            action="keep_both_as_conflict",
            comment="两个都保留",
        )
        assert result["ok"] is True
        assert result["review_id"] == task_id

    def test_disallowed_action_rejected(self, tmp_workspace):
        """不在 allowed_actions 中的动作被拒绝。"""
        from mini_note.review.engine import ReviewEngine

        engine = ReviewEngine(tmp_workspace)
        task_id = engine.create_task(
            severity="medium",
            reason="冲突",
            question_for_user="?",
            recommended_action="keep_both_as_conflict",
            allowed_actions=["keep_both_as_conflict"],
            related_claims=["c1"],
        )

        with pytest.raises(ValueError, match="不允许"):
            engine.answer(task_id, action="mark_old_claim_deprecated", comment="覆盖")

    def test_answer_updates_task_status(self, tmp_workspace):
        """回答后任务状态更新为 closed。"""
        from mini_note.review.engine import ReviewEngine

        engine = ReviewEngine(tmp_workspace)
        task_id = engine.create_task(
            severity="low",
            reason="测试关闭",
            question_for_user="?",
            recommended_action="keep_both_as_conflict",
            allowed_actions=["keep_both_as_conflict"],
            related_claims=[],
        )

        engine.answer(task_id, action="keep_both_as_conflict", comment="已处理")
        task = engine.show_task(task_id)
        assert task["status"] == "closed"

    def test_answer_nonexistent_task_raises(self, tmp_workspace):
        """对不存在的任务回答抛出异常。"""
        from mini_note.review.engine import ReviewEngine

        engine = ReviewEngine(tmp_workspace)
        with pytest.raises(ValueError, match="不存在"):
            engine.answer("review-nonexistent", action="keep_both_as_conflict")
