"""Ingest Pipeline — 摄入文件的全流程编排（CLI 的确定性部分）。"""

import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

from mini_note.models.source_registry import SourceRegistry, generate_source_id, compute_sha256
from mini_note.models.operation import OperationManifest
from mini_note.models.claim import Claim
from mini_note.ingest.extraction import extract_by_type, ExtractionResult
from mini_note.ingest.staging import write_to_staging, apply_staged_changes
from mini_note.indexer import Indexer

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
    dedup_status: str = "new"  # "new" | "existing" | "queued_large_file"


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
        skip_precheck: bool = False,
        use_lock: bool = True,
        pre_extracted: ExtractionResult | None = None,
        rebuild_index: bool = True,
        run_health_check: bool = True,
    ) -> IngestResult:
        """执行摄入流程（不含 LLM 分析步骤）。

        skip_precheck=True 时跳过预检分流（大文件 worker 使用）。
        use_lock=False 时不获取 ingest.lock（调用方自行管理锁）。
        pre_extracted 为 ExtractionResult 时跳过提取步骤，直接使用已有结果。
        rebuild_index=False 时跳过单文件索引重建（批量模式在批次末尾统一重建）。
        run_health_check=False 时跳过单文件健康检查（批量模式在批次末尾统一检查）。
        """
        operation_id = _gen_operation_id()
        op = None

        try:
            # 1. Acquire lock（大文件 worker 使用独立 large_ingest.lock）
            if use_lock:
                _acquire_lock(self.workspace)

            # 拒绝符号链接（symlink），防止指向敏感路径
            real_path = file_path.resolve()
            if file_path.is_symlink():
                if use_lock:
                    _release_lock(self.workspace)
                return IngestResult(
                    ok=False,
                    error_code="SYMLINK_REJECTED",
                    message="不支持符号链接文件",
                    retryable=False,
                )

            # 加载限制配置
            from mini_note.config import get_limits
            limits = get_limits(self.workspace)

            # 预检：大文件分流（大文件 worker 跳过此步）
            if not skip_precheck:
                precheck = _precheck_file(file_path, limits)
                if precheck["is_large_file"]:
                    if use_lock:
                        _release_lock(self.workspace)
                    from mini_note.ingest.large_file_queue import enqueue
                    large_op_id = enqueue(
                        self.workspace, file_path, owner_id, scope,
                        precheck["limit_type"], precheck["actual_value"],
                    )
                    return IngestResult(
                        ok=True,
                        operation_id=large_op_id,
                        ingestion_status="queued_large_file",
                        backup_status="none",
                        dedup_status="queued_large_file",
                        message=f"大文件已进入后台队列（{precheck['limit_type']}: {precheck['actual_value']}）",
                    )

            # 2. 检查重复 — SHA256 已存在则跳过提取与 wiki 生成
            sha = compute_sha256(file_path)
            registry = SourceRegistry(self.workspace)
            existing_id = registry.find_by_sha256(sha)
            if existing_id:
                if use_lock:
                    _release_lock(self.workspace)
                return IngestResult(
                    ok=True,
                    operation_id=operation_id,
                    source_id=existing_id,
                    ingestion_status="full",
                    backup_status="none",
                    dedup_status="existing",
                    message="文件已存在，跳过重复摄入",
                )

            # 3. Register source（传入完整 limits）
            source_id = registry.register(
                file_path, owner_id=owner_id, scope=scope,
                max_text_mb=limits.max_text_mb,
                max_pdf_pages=limits.max_pdf_pages,
                max_office_mb=limits.max_office_mb,
                max_image_mb=limits.max_image_mb,
                max_audio_minutes=limits.max_audio_minutes,
                max_video_minutes=limits.max_video_minutes,
            )

            # 4. Extract content（传入 limits 以强制截断；pre_extracted 跳过）
            if pre_extracted is not None:
                ext_result = pre_extracted
            else:
                ext_result = extract_by_type(file_path, limits=limits)

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

            # 9. Rebuild derived index（批量模式可由调用方在批次末尾统一执行）
            if rebuild_index:
                idx = Indexer(self.workspace)
                idx.rebuild()

            # 10. Health check（批量模式可由调用方在批次末尾统一执行）
            if run_health_check:
                from mini_note.lint.health import run_health_check
                health = run_health_check(self.workspace)
                if not health["ok"]:
                    raise RuntimeError("Health check 失败: " + str(health["checks"]))

            # 11. Emit review tasks (MVP: 简化)
            # 如有冲突 claim 则生成 review task

            # 记录 operation manifest
            op = OperationManifest(
                operation_id=operation_id,
                type="ingest",
                status="indexed",
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

            if use_lock:
                _release_lock(self.workspace)

            return IngestResult(
                ok=True,
                operation_id=operation_id,
                source_id=source_id,
                ingestion_status=ext_result.status,
                backup_status="none",
                source_page_path=source_page_rel,
            )

        except Exception as e:
            if use_lock:
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

def _precheck_file(file_path: Path, limits) -> dict:
    """轻量预检文件是否超过摄入上限（不执行完整抽取）。

    返回：
        is_large_file: bool
        limit_type: str   — 超限类型（text_mb / pdf_pages / office_mb / image_mb / audio_minutes / video_minutes）
        actual_value: str  — 实际值（用于提示）
    """
    size_bytes = file_path.stat().st_size
    ext = file_path.suffix.lower()

    # 文本：检查文件大小
    if ext in (".md", ".txt"):
        if size_bytes > limits.max_text_bytes:
            return {
                "is_large_file": True,
                "limit_type": "text_mb",
                "actual_value": f"{size_bytes / 1024 / 1024:.1f}MB",
            }

    # Office：检查文件大小
    if ext in (".docx", ".xlsx", ".pptx"):
        if size_bytes > limits.max_office_bytes:
            return {
                "is_large_file": True,
                "limit_type": "office_mb",
                "actual_value": f"{size_bytes / 1024 / 1024:.1f}MB",
            }

    # 图片：检查文件大小
    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".svg"}
    if ext in image_exts:
        if size_bytes > limits.max_image_bytes:
            return {
                "is_large_file": True,
                "limit_type": "image_mb",
                "actual_value": f"{size_bytes / 1024 / 1024:.1f}MB",
            }

    # PDF：仅读页数（轻量，不抽文本）
    if ext == ".pdf":
        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                pages = len(pdf.pages)
            if pages > limits.max_pdf_pages:
                return {
                    "is_large_file": True,
                    "limit_type": "pdf_pages",
                    "actual_value": f"{pages} 页",
                }
        except Exception:
            pass  # 无法读取 PDF 页数则放行，由提取层处理

    # 音视频：仅读时长（轻量，mutagen 只读头部）
    media_exts = {
        ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac",
        ".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv",
    }
    audio_exts = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma"}
    if ext in media_exts:
        try:
            from mutagen import File as MutagenFile
            mf = MutagenFile(str(file_path))
            if mf is not None and hasattr(mf, "info") and mf.info:
                duration_sec = mf.info.length
                if ext in audio_exts and duration_sec > limits.max_audio_seconds:
                    return {
                        "is_large_file": True,
                        "limit_type": "audio_minutes",
                        "actual_value": f"{duration_sec / 60:.1f} 分钟",
                    }
                if ext not in audio_exts and duration_sec > limits.max_video_seconds:
                    return {
                        "is_large_file": True,
                        "limit_type": "video_minutes",
                        "actual_value": f"{duration_sec / 60:.1f} 分钟",
                    }
        except Exception:
            pass  # 无法读取时长则放行

    return {"is_large_file": False, "limit_type": "", "actual_value": ""}

def _gen_operation_id() -> str:
    now = datetime.now(CST)
    import secrets
    return f"op-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}-{secrets.token_hex(2)}"


def _is_pid_alive(pid: int) -> bool:
    """检查指定 PID 的进程是否仍在运行（跨平台）。

    仅捕获 ProcessLookupError（进程不存在）。
    PermissionError 向上抛出，由调用方回退到 mtime 判断。
    """
    try:
        os.kill(pid, 0)  # 不发送信号，仅检测进程存在性
        return True
    except ProcessLookupError:
        return False


def _is_lock_stale(lock_file: Path, timeout_seconds: int) -> bool:
    """判断锁文件是否过期。

    优先级：
    1. 读取锁文件 JSON 中的 PID，通过 os.kill(pid, 0) 判断进程存活
    2. PID 不存在 → 过期
    3. PermissionError（跨用户）→ 回退到 mtime 超时判断
    4. JSON 解析失败（旧格式锁）→ 回退到 mtime 超时判断
    """
    try:
        raw = lock_file.read_text(encoding="utf-8")
        data = json.loads(raw)
        pid = data.get("pid")
        if isinstance(pid, int) and pid > 0:
            try:
                if _is_pid_alive(pid):
                    return False  # 进程仍存活，锁有效
                return True  # 进程已死，锁过期
            except PermissionError:
                pass  # 跨用户无法检测，回退到 mtime
            except (TypeError, ValueError):
                pass  # pid 类型异常，回退到 mtime
    except FileNotFoundError:
        return True  # 锁文件在读之前被并发删除，视为过期
    except (json.JSONDecodeError, ValueError, KeyError):
        pass  # 旧格式或损坏 JSON，回退到 mtime

    # 回退：基于 mtime 的超时判断
    age = datetime.now().timestamp() - lock_file.stat().st_mtime
    return age >= timeout_seconds


def _acquire_lock(workspace: Path) -> None:
    """用 O_CREAT|O_EXCL 原子创建 PID 锁文件。

    锁文件内容为 JSON：{"pid": <pid>, "timestamp": "<iso8601>"}
    遇到已有锁时，通过 PID 存活检测判断是否过期。
    """
    from mini_note.config import get_lock_timeout

    lock_file = workspace / ".state" / "ingest.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    timeout_seconds = get_lock_timeout(workspace)

    def _write_lock(lock_file: Path) -> None:
        fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            payload = json.dumps({
                "pid": os.getpid(),
                "timestamp": datetime.now(CST).isoformat(),
            })
            os.write(fd, payload.encode("utf-8"))
        finally:
            os.close(fd)

    for _ in range(3):
        try:
            _write_lock(lock_file)
            return
        except FileExistsError:
            if _is_lock_stale(lock_file, timeout_seconds):
                try:
                    os.remove(lock_file)
                except FileNotFoundError:
                    pass  # 已被其他并发进程清理
                continue  # 重试创建
            # 锁有效，读取持有者 PID 以提供排查信息
            holder_pid = "unknown"
            try:
                data = json.loads(lock_file.read_text(encoding="utf-8"))
                holder_pid = str(data.get("pid", "unknown"))
            except Exception:
                pass
            raise RuntimeError(f"已有 ingest 操作正在执行 (PID={holder_pid})")

    raise RuntimeError("获取 ingest 锁超时，系统繁忙")


def _release_lock(workspace: Path) -> None:
    lock_file = workspace / ".state" / "ingest.lock"
    if lock_file.exists():
        lock_file.unlink()


def _cleanup_stale_locks(workspace: Path) -> list[str]:
    """清理过期的锁文件，返回已清理的锁文件路径列表。"""
    from mini_note.config import get_lock_timeout

    timeout_seconds = get_lock_timeout(workspace)
    cleaned = []
    for lock_name in ("ingest.lock", "large_ingest.lock"):
        lock_file = workspace / ".state" / lock_name
        if lock_file.exists() and _is_lock_stale(lock_file, timeout_seconds):
            lock_file.unlink(missing_ok=True)
            cleaned.append(str(lock_file.relative_to(workspace)))
    return cleaned


def check_import_disk_space(workspace: Path, file_paths: list[Path]) -> dict:
    """评估导入文件对磁盘空间的需求。

    Args:
        workspace: 工作区根目录
        file_paths: 待导入文件路径列表

    Returns:
        {"ok": bool, "file_count": int, "total_size_bytes": int,
         "available_bytes": int, "estimated_need_bytes": int,
         "safe_margin_bytes": int, "would_fit": bool}
    """
    SAFE_MARGIN_BYTES = 100 * 1024 * 1024  # 100MB 安全余量

    actual_files = [f for f in file_paths if f.is_file()]
    total_size = sum(f.stat().st_size for f in actual_files)
    # 保守估计：原始文件 × 2.0（提取文本 + YAML 元数据 + SQLite 索引 + archive 副本）
    estimated_need = int(total_size * 2.0)

    usage = shutil.disk_usage(workspace)
    available = usage.free

    would_fit = (available - estimated_need) >= SAFE_MARGIN_BYTES

    return {
        "ok": True,
        "file_count": len(actual_files),
        "total_size_bytes": total_size,
        "available_bytes": available,
        "estimated_need_bytes": estimated_need,
        "safe_margin_bytes": SAFE_MARGIN_BYTES,
        "would_fit": would_fit,
    }


def _build_claims(source_id: str, content: str, ext: str) -> list[dict]:
    """从解析内容中提取基础 claim（启发式，待 Skill 补全）。

    三层提取策略：
    1. 含数字的句子（≥15 字）— 数值事实
    2. 列表/要点行（以 - * • 或数字序号开头，8-300 字）— 结构化知识
    3. 会议/讨论关键句（含会议关键词，15-300 字）— 会议纪要
    """
    import hashlib
    import re

    claims = []
    seen_texts: set[str] = set()
    idx = 0

    def _add_claim(text: str, method: str, locator: str) -> int:
        nonlocal idx
        key = text[:80].strip()
        if key in seen_texts:
            return 0
        seen_texts.add(key)
        idx += 1
        claim_id = f"claim-{datetime.now(CST).strftime('%Y%m%d')}-{datetime.now(CST).strftime('%H%M%S')}-{idx:04d}"
        claims.append({
            "claim_id": claim_id,
            "source_id": source_id,
            "text": text[:200],
            "locator": locator,
            "quote_hash": "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "extraction_method": method,
            "confidence": 0.6,
            "status": "unverified",
            "verified_at": "",
        })
        return 1

    bullet_re = re.compile(r"^[\s]*([-*•]|\d+[.)])\s+(.+)$", re.MULTILINE)
    meeting_kw = re.compile(
        r"(会议|讨论|决定|结论|行动项|TODO|纪要|议题|决议|下一步|跟进|待办|共识|备忘|记录|出席|汇报|总结|安排|计划)"
    )
    digit_re = re.compile(r"\d+")

    lines = content.split("\n")
    para_idx = 0

    # Pass 1: bullet/list items
    for i, line in enumerate(lines):
        m = bullet_re.match(line)
        if not m:
            continue
        text = m.group(2).strip()
        if 8 <= len(text) <= 300:
            _add_claim(text, "heuristic_bullet", f"line={i + 1}")

    # Pass 2: sentences (split by 。 or \n\n paragraph breaks)
    paragraphs = re.split(r"\n{2,}", content)
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # 跳过纯列表段落（已在 Pass 1 处理）
        para_idx += 1
        sents = re.split(r"[。；;]\s*", para)
        for sent in sents:
            sent = sent.strip()
            if len(sent) < 10 or len(sent) > 300:
                continue
            # 数字事实
            if digit_re.search(sent) and len(sent) >= 15:
                _add_claim(sent, "heuristic" if ext in (".md", ".txt") else "extractor",
                           f"content paragraph={para_idx}")
            # 会议关键词
            elif meeting_kw.search(sent) and len(sent) >= 15:
                _add_claim(sent, "heuristic_meeting" if ext in (".md", ".txt") else "extractor",
                           f"content paragraph={para_idx}")

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
