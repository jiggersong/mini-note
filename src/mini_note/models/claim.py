"""Claim 数据模型 — 关键事实的 claim 级证据追踪。"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta

import yaml

CST = timezone(timedelta(hours=8))

VALID_STATUSES = {"active", "conflicted", "deprecated", "unverified"}

# 状态流转规则：每个状态可以转向哪些状态
ALLOWED_TRANSITIONS = {
    "active": {"conflicted", "deprecated"},
    "conflicted": {"active", "deprecated"},
    "deprecated": set(),  # 终态
    "unverified": {"active", "deprecated"},
}


@dataclass
class Claim:
    """关键事实 claim，绑定原文证据。

    Attributes:
        claim_id: 唯一标识
        source_id: 来源 source
        text: claim 文本
        locator: 原文定位（如 page=6 paragraph=3）
        quote_hash: 原文片段哈希（格式: sha256:xxx）
        extraction_method: 提取方式
        confidence: 置信度 [0, 1]
        status: 状态 (active/conflicted/deprecated/unverified)
        verified_at: 验证时间
    """

    claim_id: str
    source_id: str
    text: str
    locator: str
    quote_hash: str = ""
    extraction_method: str = "pdf_text"
    confidence: float = 0.5
    status: str = "active"
    verified_at: str = ""

    def __post_init__(self):
        # 校验 text 不为空
        if not self.text or not self.text.strip():
            raise ValueError("claim text 不能为空")

        # 校验 confidence 范围
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence 必须在 0~1 之间，当前: {self.confidence}")

        # 校验 status 合法
        if self.status not in VALID_STATUSES:
            raise ValueError(f"无效 claim 状态: {self.status}")

        # 校验 quote_hash 格式
        if self.quote_hash:
            if not self.quote_hash.startswith("sha256:"):
                raise ValueError(
                    f"quote_hash 必须以 'sha256:' 开头，当前: {self.quote_hash}"
                )
        else:
            # 空 quote_hash 只有 unverified 状态允许
            if self.status != "unverified":
                raise ValueError("active/conflicted/deprecated 状态的 claim 必须有 quote_hash")

        # 默认 verified_at
        if not self.verified_at:
            self.verified_at = datetime.now(CST).isoformat()

    def transition_to(self, target: str) -> None:
        """状态流转。"""
        if target not in VALID_STATUSES:
            raise ValueError(f"无效状态: {target}")

        if target == self.status:
            return

        allowed = ALLOWED_TRANSITIONS.get(self.status, set())
        if target not in allowed:
            raise ValueError(
                f"不允许从 {self.status} 转换到 {target}"
            )

        self.status = target

    def to_dict(self) -> dict:
        """转换为字典。"""
        return asdict(self)

    def to_yaml(self) -> str:
        """序列化为 YAML 字符串。"""
        return yaml.dump(self.to_dict(), allow_unicode=True)
