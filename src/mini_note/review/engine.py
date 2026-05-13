"""Review Engine — 审核任务生成、白名单动作执行。"""

import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

CST = timezone(timedelta(hours=8))


class ReviewEngine:
    """审核引擎：管理 review task 的生命周期。

    任务持久化到 .state/review_tasks/，每个任务一个 YAML 文件。
    answer() 只接受白名单动作，禁止自行决定覆盖。
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self._tasks_dir = workspace / ".state" / "review_tasks"
        self._tasks_dir.mkdir(parents=True, exist_ok=True)

    def create_task(
        self,
        severity: str,
        reason: str,
        question_for_user: str,
        recommended_action: str,
        allowed_actions: list[str],
        related_claims: list[str],
    ) -> str:
        """创建审核任务。

        Args:
            severity: 严重程度 (low/medium/high)
            reason: 触发审核的原因
            question_for_user: 向用户提出的问题
            recommended_action: 推荐动作
            allowed_actions: 白名单动作列表
            related_claims: 关联的 claim_id 列表

        Returns:
            task_id (以 "review-" 开头)
        """
        now = datetime.now(CST)
        task_id = f"review-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}-{secrets.token_hex(3)}"

        task = {
            "review_id": task_id,
            "severity": severity,
            "reason": reason,
            "question_for_user": question_for_user,
            "recommended_action": recommended_action,
            "allowed_actions": allowed_actions,
            "related_claims": related_claims,
            "status": "open",
            "created_at": now.isoformat(),
            "answered_at": None,
            "answer": None,
            "comment": None,
        }

        task_file = self._tasks_dir / f"{task_id}.yaml"
        task_file.write_text(yaml.dump(task, allow_unicode=True), encoding="utf-8")
        return task_id

    def list_tasks(self, status: str | None = None) -> list[dict]:
        """列出审核任务，可按状态过滤。

        Args:
            status: 过滤状态 (open/closed)，None 返回全部
        """
        tasks = []
        for tf in sorted(self._tasks_dir.glob("review-*.yaml")):
            try:
                data = yaml.safe_load(tf.read_text())
                if data is None:
                    continue
                if status is None or data.get("status") == status:
                    tasks.append(data)
            except Exception:
                continue
        return tasks

    def show_task(self, task_id: str) -> dict:
        """查看单个审核任务详情。

        Args:
            task_id: 审核任务 ID

        Returns:
            任务详情 dict

        Raises:
            ValueError: 任务不存在
        """
        task_file = self._tasks_dir / f"{task_id}.yaml"
        if not task_file.exists():
            raise ValueError(f"审核任务 {task_id} 不存在")
        data = yaml.safe_load(task_file.read_text())
        if data is None:
            raise ValueError(f"审核任务 {task_id} 不存在")
        return data

    def answer(self, task_id: str, action: str, comment: str = "") -> dict:
        """执行审核动作（白名单校验）。

        Args:
            task_id: 审核任务 ID
            action: 执行的动作（必须在 allowed_actions 中）
            comment: 用户备注

        Returns:
            {"ok": True, "review_id": task_id}

        Raises:
            ValueError: 任务不存在或动作不在白名单中
        """
        task = self.show_task(task_id)

        if action not in task.get("allowed_actions", []):
            raise ValueError(f"动作 '{action}' 不允许，仅允许: {task.get('allowed_actions')}")

        now = datetime.now(CST)
        task["status"] = "closed"
        task["answer"] = action
        task["comment"] = comment
        task["answered_at"] = now.isoformat()

        task_file = self._tasks_dir / f"{task_id}.yaml"
        task_file.write_text(yaml.dump(task, allow_unicode=True), encoding="utf-8")

        return {"ok": True, "review_id": task_id}
