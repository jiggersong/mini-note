"""Operation Manifest — 每次写入操作的事务边界记录。"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

import yaml

CST = timezone(timedelta(hours=8))

VALID_TYPES = {"ingest", "lint", "backup", "review", "rebuild"}
VALID_STATUSES = {"planned", "staged", "applied", "indexed", "backed_up", "failed"}

# 正向状态流：每个状态只能单向推进到下一个（failed 除外）
FORWARD_FLOW = ["planned", "staged", "applied", "indexed", "backed_up"]

# 各状态的恢复动作
RECOVERY_ACTIONS = {
    "planned": "discard_staging_retry",
    "staged": "discard_staging_retry",
    "applied": "rebuild_index_continue",
    "indexed": "retry_backup",
}


@dataclass
class OperationManifest:
    """记录一次操作的计划、执行、校验和备份状态。

    Attributes:
        operation_id: 唯一标识
        type: 操作类型 (ingest/lint/backup/review/rebuild)
        status: 当前状态
        source_ids: 关联的 source
        planned_changes: 计划变更列表
        validation: 校验结果
    """

    operation_id: str
    type: str
    source_ids: list[str] = field(default_factory=list)
    status: str = "planned"
    planned_changes: list[dict] = field(default_factory=list)
    validation: dict = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if self.type not in VALID_TYPES:
            raise ValueError(f"无效 operation type: {self.type}")
        if self.status not in VALID_STATUSES:
            raise ValueError(f"无效 operation status: {self.status}")
        if not self.created_at:
            self.created_at = datetime.now(CST).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def transition_to(self, target: str) -> None:
        """状态流转。"""
        if target not in VALID_STATUSES:
            raise ValueError(f"无效状态: {target}")
        if target == self.status:
            return

        # failed 状态可以从任意状态转入
        if target == "failed":
            self.status = target
            self.updated_at = datetime.now(CST).isoformat()
            return

        # 不能从 failed 转出
        if self.status == "failed":
            raise ValueError("不允许从 failed 转换到其他状态")

        # backed_up 是终态，只能转 failed
        if self.status == "backed_up":
            raise ValueError("backed_up 是终态，只能转 failed")

        # 正向流：只能下一步
        try:
            current_idx = FORWARD_FLOW.index(self.status)
            next_idx = FORWARD_FLOW.index(target)
        except ValueError:
            raise ValueError(f"不允许从 {self.status} 转换到 {target}")

        if next_idx != current_idx + 1:
            raise ValueError(f"不允许从 {self.status} 跳过中间状态到 {target}")

        self.status = target
        self.updated_at = datetime.now(CST).isoformat()

    def is_recoverable(self) -> bool:
        """是否可恢复。"""
        return self.status in RECOVERY_ACTIONS

    def needs_recovery(self) -> bool:
        """是否需要恢复操作。"""
        return self.is_recoverable()

    def recovery_action(self) -> str | None:
        """返回应该执行的恢复动作。"""
        return RECOVERY_ACTIONS.get(self.status)
