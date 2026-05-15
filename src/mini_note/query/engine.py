"""Query Engine — 检索 Wiki 页面和 claim，返回结构化 JSON 素材。

使用 FTS5 全文索引（BM25 排序），如 FTS 表不存在则回退到关键词匹配。
CLI 的 query 命令只做检索不调模型。回答合成由 OpenClaw Skill 完成。
"""

from pathlib import Path

import yaml


class QueryEngine:
    """检索引擎：优先使用 FTS5，无 FTS 表时回退到关键词扫描。"""

    def __init__(self, workspace: Path):
        self.workspace = workspace

    def search(self, question: str, scope: str = "shared") -> dict:
        """检索知识库，返回结构化 JSON 素材。

        空输入不抛异常，返回 ok: false + error_code，便于 CLI/OpenClaw 解析。
        """
        if not question or not question.strip():
            return {
                "ok": False,
                "error_code": "EMPTY_QUESTION",
                "message": "查询问题不能为空",
                "pages": [],
                "claims": [],
                "question": "",
            }

        pages = self._search_pages_fts(question, scope)
        if pages is None:
            pages = self._search_pages_fallback(question, scope)

        claims = self._search_claims_fts(question)
        if claims is None:
            claims = self._search_claims_fallback(question)

        return {
            "ok": True,
            "pages": pages,
            "claims": claims,
            "question": question.strip(),
        }

    def rebuild_index(self) -> None:
        """重建搜索索引（委托给 Indexer，含 FTS5）。"""
        from mini_note.indexer import Indexer
        idx = Indexer(self.workspace)
        idx.rebuild()

    # ================================================================
    # FTS5 搜索
    # ================================================================

    def _search_pages_fts(self, question: str, scope: str) -> list[dict] | None:
        """FTS5 页面搜索（scope 过滤由 SQL 层完成），失败返回 None 以触发回退。"""
        try:
            from mini_note.indexer.fts import FTSIndex
        except ImportError:
            return None

        fts = FTSIndex(self.workspace)
        raw = fts.search_pages(question, scope=scope, limit=10, offset=0)
        if not raw:
            return None

        results: list[dict] = []
        for item in raw:
            results.append({
                "page_id": item.get("page_id", ""),
                "path": item["path"],
                "title": item.get("title", ""),
                "type": item.get("type", ""),
                "scope": item.get("scope", "shared"),
                "rank": item.get("rank", 0),
                "snippet": item.get("snippet", ""),
                "updated_at": item.get("updated_at", ""),
            })

        _apply_bm25_relevance(results)
        return results

    def _search_claims_fts(self, question: str) -> list[dict] | None:
        """FTS5 claim 搜索，失败返回 None 以触发回退。"""
        try:
            from mini_note.indexer.fts import FTSIndex
        except ImportError:
            return None

        fts = FTSIndex(self.workspace)
        raw = fts.search_claims(question)
        if not raw:
            return None

        # 补充完整 claim 数据
        results = []
        for item in raw:
            rank = item.get("rank", 0)
            full = self._lookup_claim(item.get("claim_id", ""))
            if full:
                full["rank"] = rank
                full["snippet"] = item.get("snippet", "")
                results.append(full)
            else:
                results.append({
                    "claim_id": item.get("claim_id"),
                    "source_id": item.get("source_id"),
                    "text": "",
                    "locator": "",
                    "quote_hash": "",
                    "status": "active",
                    "verified_at": "",
                    "rank": rank,
                    "snippet": item.get("snippet", ""),
                })

        _apply_bm25_relevance(results)

        return results

    def _lookup_claim(self, claim_id: str) -> dict | None:
        """从文件系统查找单个 claim 的完整数据。"""
        ext_dir = self.workspace / "raw" / "extracted"
        if not ext_dir.exists():
            return None
        for claims_yaml in sorted(ext_dir.glob("*/claims.yaml")):
            try:
                data = yaml.safe_load(claims_yaml.read_text())
                if not data or "claims" not in data:
                    continue
                for c in data["claims"]:
                    if c.get("claim_id") == claim_id:
                        return {
                            "claim_id": c.get("claim_id"),
                            "source_id": c.get("source_id"),
                            "text": c.get("text", ""),
                            "locator": c.get("locator", ""),
                            "quote_hash": c.get("quote_hash", ""),
                            "status": c.get("status", "active"),
                            "verified_at": c.get("verified_at", ""),
                        }
            except Exception:
                continue
        return None

    # ================================================================
    # 回退：关键词扫描
    # ================================================================

    def _search_pages_fallback(self, question: str, scope: str) -> list[dict]:
        """关键词匹配页面（FTS 不可用时的回退方案）。"""
        results = []
        wiki_dir = self.workspace / "wiki"
        if not wiki_dir.exists():
            return results

        keywords = self._tokenize(question)

        for md_file in sorted(wiki_dir.rglob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8")
                rel_path = str(md_file.relative_to(self.workspace))

                fm = self._parse_frontmatter(text)
                page_scope = fm.get("scope", "shared")
                if scope != "shared" and page_scope != scope:
                    continue

                title = fm.get("title", md_file.stem)
                body = text.split("---\n", 2)[-1] if text.startswith("---") else text

                score = self._score(body, keywords)
                if score > 0:
                    results.append({
                        "page_id": fm.get("page_id", rel_path),
                        "path": rel_path,
                        "title": title,
                        "type": fm.get("type", ""),
                        "scope": page_scope,
                        "rank": score,
                        "relevance": _normalize_keyword_score(score),
                        "snippet": body[:300].strip(),
                        "updated_at": fm.get("updated_at", ""),
                    })
            except Exception:
                continue

        results.sort(key=lambda r: r["relevance"], reverse=True)
        return results

    def _search_claims_fallback(self, question: str) -> list[dict]:
        """关键词匹配 claim（FTS 不可用时的回退方案）。"""
        results = []
        ext_dir = self.workspace / "raw" / "extracted"
        if not ext_dir.exists():
            return results

        keywords = self._tokenize(question)

        for claims_yaml in sorted(ext_dir.glob("*/claims.yaml")):
            try:
                data = yaml.safe_load(claims_yaml.read_text())
                if not data or "claims" not in data:
                    continue
                for c in data["claims"]:
                    text = c.get("text", "")
                    score = self._score(text, keywords)
                    if score > 0:
                        results.append({
                            "claim_id": c.get("claim_id"),
                            "source_id": c.get("source_id"),
                            "text": text,
                            "locator": c.get("locator", ""),
                            "quote_hash": c.get("quote_hash", ""),
                            "status": c.get("status", "active"),
                            "verified_at": c.get("verified_at", ""),
                            "rank": score,
                            "relevance": _normalize_keyword_score(score),
                        })
            except Exception:
                continue

        results.sort(key=lambda r: r["relevance"], reverse=True)
        return results

    # ================================================================
    # 工具方法
    # ================================================================

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """简单的中文分词：bigram + 英文 token。"""
        import re
        tokens = []
        chinese = re.findall(r"[一-鿿]+", text)
        for seg in chinese:
            for i in range(len(seg) - 1):
                tokens.append(seg[i:i + 2])
            if len(seg) >= 3:
                tokens.append(seg[:3])
        english = re.findall(r"[a-zA-Z0-9]+", text)
        tokens.extend(t.lower() for t in english)
        return tokens

    @staticmethod
    def _score(content: str, keywords: list[str]) -> int:
        """计算关键词命中次数。"""
        content_lower = content.lower()
        score = 0
        for kw in keywords:
            if kw.lower() in content_lower:
                score += 1
        return score

    @staticmethod
    def _parse_frontmatter(text: str) -> dict:
        """提取 Markdown frontmatter。"""
        if not text.startswith("---"):
            return {}
        end = text.find("---", 3)
        if end == -1:
            return {}
        try:
            return yaml.safe_load(text[3:end]) or {}
        except Exception:
            return {}


def _apply_bm25_relevance(results: list[dict]) -> None:
    """对当次查询结果做 min-max 归一化，BM25 rank 越小（越负）越相关。

    最佳条目 relevance=1.0，最差条目 relevance=0.0。
    单结果或所有 rank 相同时全部设为 1.0。
    """
    if not results:
        return
    ranks = [r["rank"] for r in results]
    best = min(ranks)
    worst = max(ranks)
    for r in results:
        if best == worst:
            r["relevance"] = 1.0
        else:
            r["relevance"] = round(1.0 - (r["rank"] - best) / (worst - best), 4)


def _normalize_keyword_score(score: int) -> float:
    """将关键词命中次数归一化到 [0, 1]，5 次命中 ≈ 0.5。"""
    return round(score / (score + 5), 4)
