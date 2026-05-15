"""Lint Engine — claim grounding、冲突检测、断链检查、孤立页检测。"""

import re
from pathlib import Path

import yaml


class LintEngine:
    """Lint 检查引擎：扫描 workspace 中的不一致和问题。"""

    def __init__(self, workspace: Path):
        self.workspace = workspace

    # ================================================================
    # Claim Grounding
    # ================================================================

    def check_claim_grounding(self) -> list[dict]:
        """检查所有 claim 是否能在 extracted 目录中找到对应 source。

        Returns:
            [{"claim_id": str, "source_id": str, "grounded": bool, "detail": str}]
        """
        results = []
        ext_dir = self.workspace / "raw" / "extracted"
        if not ext_dir.exists():
            return results

        # 收集所有存在的 source_id
        existing_sources = set()
        archive_dir = self.workspace / "raw" / "archive"
        if archive_dir.exists():
            for d in archive_dir.iterdir():
                if d.is_dir():
                    existing_sources.add(d.name)

        for claims_yaml in sorted(ext_dir.glob("*/claims.yaml")):
            try:
                data = yaml.safe_load(claims_yaml.read_text())
                if not data or "claims" not in data:
                    continue
                for c in data["claims"]:
                    source_id = c.get("source_id", "")
                    grounded = source_id in existing_sources
                    results.append({
                        "claim_id": c.get("claim_id"),
                        "source_id": source_id,
                        "grounded": grounded,
                        "detail": "OK" if grounded else f"source {source_id} 不存在",
                        "severity": "info" if grounded else "warning",
                        "category": "claim_grounding",
                        "confidence": 1.0,
                    })
            except Exception:
                continue

        return results

    # ================================================================
    # Broken Wikilinks
    # ================================================================

    def check_broken_wikilinks(self) -> list[dict]:
        """检测 wiki/ 中所有损坏的 wikilink（目标文件不存在）。

        Returns:
            [{"source": str, "target": str, "line": int}]
        """
        broken = []
        wiki_dir = self.workspace / "wiki"
        if not wiki_dir.exists():
            return broken

        wikilink_re = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

        for md_file in sorted(wiki_dir.rglob("*.md")):
            try:
                lines = md_file.read_text(encoding="utf-8").split("\n")
                for i, line in enumerate(lines, 1):
                    for m in wikilink_re.finditer(line):
                        target = m.group(1).strip()
                        # claim: 前缀是虚拟引用，不解析为文件路径
                        if target.startswith("claim:"):
                            continue
                        target_path = self.workspace / target
                        if not target_path.exists():
                            broken.append({
                                "source": str(md_file.relative_to(self.workspace)),
                                "target": target,
                                "line": i,
                                "severity": "warning",
                                "category": "broken_wikilinks",
                                "confidence": 1.0,
                            })
            except Exception:
                continue

        return broken

    # ================================================================
    # Orphan Pages
    # ================================================================

    def check_orphan_pages(self) -> list[dict]:
        """检测孤立页面（无入链且无出链的 wiki 页面）。

        index.md 和 overview.md 自动豁免。
        """
        wiki_dir = self.workspace / "wiki"
        if not wiki_dir.exists():
            return []

        wikilink_re = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

        # 构建图：每个页面的出链和入链
        out_links = {}  # source -> [target]
        in_links = {}   # target -> [source]
        all_pages = []

        for md_file in sorted(wiki_dir.rglob("*.md")):
            rel = str(md_file.relative_to(self.workspace))
            all_pages.append(rel)
            out_links.setdefault(rel, [])
            in_links.setdefault(rel, [])

            try:
                text = md_file.read_text(encoding="utf-8")
                for m in wikilink_re.finditer(text):
                    target = m.group(1).strip()
                    out_links[rel].append(target)
                    in_links.setdefault(target, []).append(rel)
            except Exception:
                continue

        # 豁免页面
        exempt = {"wiki/index.md", "wiki/overview.md"}

        orphans = []
        for page in all_pages:
            if page in exempt:
                continue
            has_in = bool(in_links.get(page))
            has_out = bool(out_links.get(page))
            if not has_in and not has_out:
                orphans.append({"path": page, "reason": "无入链且无出链",
                                "severity": "info", "category": "orphan_pages", "confidence": 1.0})
            elif not has_in:
                orphans.append({"path": page, "reason": "无入链",
                                "severity": "info", "category": "orphan_pages", "confidence": 1.0})
            elif not has_out:
                orphans.append({"path": page, "reason": "无出链",
                                "severity": "info", "category": "orphan_pages", "confidence": 1.0})

        return orphans

    # ================================================================
    # Contradiction Detection
    # ================================================================

    def check_contradictions(self) -> list[dict]:
        """检测同 source 内可能冲突的 claim（含数字但数值不同）。

        Returns:
            [{"claim_a": str, "claim_b": str, "reason": str}]
        """
        conflicts = []
        ext_dir = self.workspace / "raw" / "extracted"
        if not ext_dir.exists():
            return conflicts

        number_re = re.compile(r"(\d+(?:\.\d+)?)\s*(个|条|次|Mbps|Gbps|ms|秒|分钟|小时|GB|MB|KB|%)?")

        for claims_yaml in sorted(ext_dir.glob("*/claims.yaml")):
            try:
                data = yaml.safe_load(claims_yaml.read_text())
                if not data or "claims" not in data:
                    continue
                claims = data["claims"]
                for i in range(len(claims)):
                    for j in range(i + 1, len(claims)):
                        a = claims[i]
                        b = claims[j]
                        nums_a = set(number_re.findall(a.get("text", "")))
                        nums_b = set(number_re.findall(b.get("text", "")))
                        # 提取纯数字
                        vals_a = {m[0] for m in nums_a}
                        vals_b = {m[0] for m in nums_b}
                        common = vals_a & vals_b
                        diff = (vals_a - vals_b) | (vals_b - vals_a)
                        # 有共同关键词且数值不同 → 可能冲突
                        if common and diff:
                            conflicts.append({
                                "claim_a": a.get("claim_id"),
                                "claim_b": b.get("claim_id"),
                                "reason": f"同 source 但数值不一致: {sorted(common)} vs {sorted(diff)}",
                                "severity": "warning",
                                "category": "contradictions",
                                "confidence": 0.5,
                            })
            except Exception:
                continue

        return conflicts

    # ================================================================
    # Partial Source Misuse
    # ================================================================

    def check_partial_misuse(self) -> list[dict]:
        """检查 partial 摄入的 source 是否被用于生成强事实 claim。

        Returns:
            [{"claim_id": str, "source_id": str, "warning": str}]
        """
        warnings = []
        archive_dir = self.workspace / "raw" / "archive"
        ext_dir = self.workspace / "raw" / "extracted"

        if not archive_dir.exists() or not ext_dir.exists():
            return warnings

        # 收集所有 partial 的 source_id
        partial_sources = set()
        for source_yaml in archive_dir.glob("*/source.yaml"):
            try:
                data = yaml.safe_load(source_yaml.read_text())
                if data and data.get("ingestion_status") == "partial":
                    partial_sources.add(data.get("source_id"))
            except Exception:
                continue

        # 检查引用 partial source 的 active claim
        for claims_yaml in sorted(ext_dir.glob("*/claims.yaml")):
            try:
                data = yaml.safe_load(claims_yaml.read_text())
                if not data or "claims" not in data:
                    continue
                for c in data["claims"]:
                    sid = c.get("source_id", "")
                    if sid in partial_sources and c.get("status") == "active":
                        warnings.append({
                            "claim_id": c.get("claim_id"),
                            "source_id": sid,
                            "warning": f"claim 引用 partial 摄入的 source {sid}，数据可能不完整",
                            "severity": "warning",
                            "category": "partial_misuse",
                            "confidence": 1.0,
                        })
            except Exception:
                continue

        return warnings
