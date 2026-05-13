"""Ingest Pipeline — 摄入文件的全流程编排（CLI 的确定性部分）。"""

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

from mini_note.models.source_registry import SourceRegistry, generate_source_id, compute_sha256
from mini_note.models.operation import OperationManifest
from mini_note.models.claim import Claim
from mini_note.ingest.extraction import extract_by_type
from mini_note.ingest.staging import write_to_staging, apply_staged_changes
from mini_note.indexer import Indexer
from mini_note.backup.snapshot import create_snapshot

CST = timezone(timedelta(hours=8))


@dataclass
class IngestResult:
    """摄入操作的结果。"""
    ok: bool
    operation_id: str | None = None
    source_id: str | None = None
    ingestion_status: str = "full"
    backup_status: str = "none"
    error_code: str | None = None
    message: str | None = None
    retryable: bool = False
    source_page_path: str | None = None


class IngestPipeline:
    """摄入管线的确定性部分。

    Skill 负责调用 LLM 进行分析并生成变更计划（JSON），
    CLI 负责文件登记、解析、校验、写入、索引、备份。
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace

    def run(
        self,
        file_path: Path,
        owner_id: str,
        scope: str = "shared",
    ) -> IngestResult:
        """执行摄入流程（不含 LLM 分析步骤）。

        LLM 分析和变更计划生成由 OpenClaw Skill 完成，
        此方法只执行 CLI 侧的确定性操作。
        """
        operation_id = _gen_operation_id()
        op = None

        try:
            # 1. Acquire lock (MVP: 简化为文件锁)
            _acquire_lock(self.workspace)

            # 安全检查：拒绝符号链接指向 workspace 外的文件
            real_path = file_path.resolve()
            try:
                real_path.relative_to(self.workspace.resolve())
            except ValueError:
                # 文件不在 workspace 内，可能是外部文件或恶意路径
                _release_lock(self.workspace)
                return IngestResult(
                    ok=False,
                    error_code="PATH_TRAVERSAL",
                    message="文件不在 workspace 内，路径穿越被拒绝",
                    retryable=False,
                )

            # 拒绝符号链接（symlink）
            if file_path.is_symlink():
                _release_lock(self.workspace)
                return IngestResult(
                    ok=False,
                    error_code="SYMLINK_REJECTED",
                    message="不支持符号链接文件",
                    retryable=False,
                )

            # 2. Register source
            registry = SourceRegistry(self.workspace)
            source_id = registry.register(file_path, owner_id=owner_id, scope=scope)
            sha = compute_sha256(file_path)

            # 3. Extract content
            ext_result = extract_by_type(file_path)

            # 写入 extracted 目录
            ext_dir = self.workspace / "raw" / "extracted" / source_id
            ext_dir.mkdir(parents=True, exist_ok=True)
            (ext_dir / "content.md").write_text(ext_result.content, encoding="utf-8")

            # 4. Build evidence map — 生成基础 claim
            claims = _build_claims(source_id, ext_result.content, file_path.suffix)
            (ext_dir / "claims.yaml").write_text(
                yaml.dump({"claims": claims}, allow_unicode=True), encoding="utf-8"
            )

            # 写入 extraction.yaml
            extraction_data = {
                "source_id": source_id,
                "extractor": ext_result.extractor,
                "extractor_version": ext_result.extractor_version,
                "status": ext_result.status,
                "coverage": ext_result.coverage,
                "warnings": ext_result.warnings,
                "created_at": datetime.now(CST).isoformat(),
            }
            (ext_dir / "extraction.yaml").write_text(
                yaml.dump(extraction_data, allow_unicode=True), encoding="utf-8"
            )

            # 5-6. Skill calls LLM (outside scope of CLI)
            # 7. Validate change plan (由 Skill 传回 JSON，CLI 校验)
            # 此处 MVP 做最小化处理：直接生成 source page

            # 8. Apply staged changes — 生成 source page 并更新 index
            source_page_rel = _generate_source_page(
                self.workspace, source_id, file_path.name, sha,
                ext_result.content, ext_result.status, claims, owner_id, scope,
            )
            _update_index(self.workspace, source_page_rel)

            # 9. Rebuild derived index
            idx = Indexer(self.workspace)
            idx.rebuild()

            # 10. Health check
            from mini_note.lint.health import run_health_check
            health = run_health_check(self.workspace)
            if not health["ok"]:
                raise RuntimeError("Health check 失败: " + str(health["checks"]))

            # 11. Create local snapshot
            snapshot_path = self.workspace / ".state" / "staging" / f"{operation_id}.tar.gz"
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_sha = create_snapshot(self.workspace, snapshot_path, compression="gzip")

            # 12. OSS upload — 有配置就必须上传，否则如实记录状态
            oss_ok = False
            oss_error = None
            try:
                from mini_note.backup.oss import OSSBackup
                oss = OSSBackup()
                if oss.enabled:
                    oss_result = oss.upload(snapshot_path, operation_id)
                    oss_ok = oss_result.get("ok", False)
                    if not oss_ok:
                        oss_error = oss_result.get("error")
            except Exception as e:
                oss_error = str(e)

            if oss_ok:
                backup_status = "backed_up"
                # OSS 上传成功，清理本地临时快照
                snapshot_path.unlink(missing_ok=True)
            elif oss_error:
                backup_status = "backup_failed"
                # 上传失败，保留本地快照作为 fallback，但只保留最近 3 个
                _prune_staging_snapshots(self.workspace, keep=3)
            else:
                backup_status = "indexed"
                # 无 OSS 配置，本地快照即为唯一备份，保留但限制数量
                _prune_staging_snapshots(self.workspace, keep=5)

            # 13. Emit review tasks (MVP: 简化)
            # 如有冲突 claim 则生成 review task

            # 记录 operation manifest
            op = OperationManifest(
                operation_id=operation_id,
                type="ingest",
                status=backup_status,
                source_ids=[source_id],
                planned_changes=[
                    {"action": "create_page", "path": source_page_rel},
                    {"action": "update_page", "path": "wiki/index.md"},
                ],
                validation={
                    "frontmatter_valid": True,
                    "wikilinks_valid": True,
                    "claims_have_sources": bool(claims),
                },
            )

            # 持久化 manifest
            op_dir = self.workspace / ".state" / "operations"
            op_dir.mkdir(parents=True, exist_ok=True)
            op_file = op_dir / f"{operation_id}.yaml"
            op_file.write_text(_manifest_to_yaml(op), encoding="utf-8")

            _release_lock(self.workspace)

            return IngestResult(
                ok=True,
                operation_id=operation_id,
                source_id=source_id,
                ingestion_status=ext_result.status,
                backup_status=backup_status,
                source_page_path=source_page_rel,
            )

        except Exception as e:
            _release_lock(self.workspace)
            return IngestResult(
                ok=False,
                operation_id=operation_id,
                error_code="INGEST_FAILED",
                message=str(e),
                retryable=True,
            )


# ============================================================
# 内部辅助函数
# ============================================================

def _gen_operation_id() -> str:
    now = datetime.now(CST)
    import secrets
    return f"op-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}-{secrets.token_hex(2)}"


def _acquire_lock(workspace: Path) -> None:
    lock_file = workspace / ".state" / "ingest.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    # MVP: 简单文件锁
    if lock_file.exists():
        # 检查超时
        age = datetime.now().timestamp() - lock_file.stat().st_mtime
        if age < 300:
            raise RuntimeError("已有 ingest 操作正在执行")
    lock_file.write_text("locked")


def _prune_staging_snapshots(workspace: Path, keep: int) -> None:
    """清理 .state/staging/ 中的旧快照，只保留最近 keep 个 .tar.gz。"""
    staging = workspace / ".state" / "staging"
    if not staging.exists():
        return
    tars = sorted(
        staging.glob("*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in tars[keep:]:
        old.unlink(missing_ok=True)


def _release_lock(workspace: Path) -> None:
    lock_file = workspace / ".state" / "ingest.lock"
    if lock_file.exists():
        lock_file.unlink()


def _build_claims(source_id: str, content: str, ext: str) -> list[dict]:
    """从解析内容中提取基础 claim（简单的启发式方法）。

    MVP 阶段：提取包含数字、百分比、关键动词的句子作为候选 claim。
    完整 claim 提取由 LLM (Skill 侧) 完成。
    """
    import re

    claims = []
    # 简单的句子分割
    sentences = re.split(r"[。\n](?=\s*[A-Z一-鿿])", content)
    idx = 0

    for sent in sentences:
        sent = sent.strip()
        if len(sent) < 10 or len(sent) > 300:
            continue
        # 只提取包含数字或关键模式的句子
        if re.search(r"\d+", sent) and len(sent) > 15:
            idx += 1
            claim_id = f"claim-{datetime.now(CST).strftime('%Y%m%d')}-{datetime.now(CST).strftime('%H%M%S')}-{idx:04d}"
            claims.append({
                "claim_id": claim_id,
                "source_id": source_id,
                "text": sent[:200],
                "locator": f"content paragraph={idx}",
                "quote_hash": "",
                "extraction_method": "heuristic" if ext in (".md", ".txt") else "extractor",
                "confidence": 0.6,
                "status": "unverified",
                "verified_at": datetime.now(CST).isoformat(),
            })

    return claims


def _generate_source_page(
    workspace: Path,
    source_id: str,
    filename: str,
    sha256: str,
    content: str,
    ingestion_status: str,
    claims: list[dict],
    owner_id: str,
    scope: str,
) -> str:
    """生成 source page 并写入 wiki/sources/。"""
    now = datetime.now(CST).isoformat()
    page_id = f"page-{source_id}"

    # 摘要：取内容前 200 字符
    summary = content[:200].replace("\n", " ")
    if len(content) > 200:
        summary += "..."

    claim_refs = "\n".join(
        f"- [[claim:{c['claim_id']}]] {c['text'][:80]}" for c in claims[:5]
    )

    page = f"""---
page_id: {page_id}
title: "{filename}"
type: "source"
scope: "{scope}"
owner_id: "{owner_id}"
status: "published"
source_ids:
  - {source_id}
claim_ids:
{chr(10).join(f"  - {c['claim_id']}" for c in claims[:5])}
created_at: "{now}"
updated_at: "{now}"
---

# {filename}

**来源 ID**: `{source_id}`
**SHA256**: `{sha256}`
**摄入状态**: {ingestion_status}
**摘要**: {summary}

## 关键事实

{claim_refs if claim_refs else "（暂无已验证的关键事实）"}

## 原始内容摘要

{content[:1000]}
"""

    rel_path = f"wiki/sources/{source_id}.md"
    staging_file = write_to_staging(workspace, rel_path, page)
    apply_staged_changes(workspace, [staging_file])
    return rel_path


def _update_index(workspace: Path, new_page_rel: str) -> None:
    """更新 wiki/index.md，追加新页面链接。"""
    index_path = workspace / "wiki" / "index.md"
    current = index_path.read_text(encoding="utf-8") if index_path.exists() else "# Index\n"

    page_name = Path(new_page_rel).stem
    link = f"- [[{new_page_rel}|{page_name}]]"

    if link not in current:
        current += f"\n{link}\n"

    staging_file = write_to_staging(workspace, "wiki/index.md", current)
    apply_staged_changes(workspace, [staging_file])


def _manifest_to_yaml(op: OperationManifest) -> str:
    """序列化 operation manifest 为 YAML。"""
    data = {
        "operation_id": op.operation_id,
        "type": op.type,
        "status": op.status,
        "source_ids": op.source_ids,
        "planned_changes": op.planned_changes,
        "validation": op.validation,
        "created_at": op.created_at,
        "updated_at": op.updated_at,
    }
    return yaml.dump(data, allow_unicode=True)
