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
        """检索知识库，返回结构化 JSON 素材。"""
        if not question or not question.strip():
            raise ValueError("查询问题不能为空")

        pages = self._search_pages_fts(question, scope)
        if pages is None:
            pages = self._search_pages_fallback(question, scope)

        claims = self._search_claims_fts(question)
        if claims is None:
            claims = self._search_claims_fallback(question)

        return {
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
        """FTS5 页面搜索，失败返回 None 以触发回退。

        通过分页循环拉取 FTS 结果并 scope 过滤，确保 target scope
        命中不在前 N 条时也不会丢失结果。
        """
        try:
            from mini_note.indexer.fts import FTSIndex
        except ImportError:
            return None

        fts = FTSIndex(self.workspace)
        target_limit = 10
        page_size = 20
        results: list[dict] = []
        offset = 0

        while len(results) < target_limit:
            raw = fts.search_pages(question, limit=page_size, offset=offset)
            if not raw:
                break  # 可能 FTS 表不存在或已耗尽

            for item in raw:
                page_path = self.workspace / item["path"]
                fm = {}
                if page_path.exists():
                    try:
                        text = page_path.read_text(encoding="utf-8")
                        fm = self._parse_frontmatter(text)
                    except Exception:
                        pass

                page_scope = fm.get("scope", "shared")
                if scope != "shared" and page_scope != scope:
                    continue

                results.append({
                    "page_id": item.get("page_id", ""),
                    "path": item["path"],
                    "title": item.get("title", ""),
                    "type": fm.get("type", ""),
                    "scope": page_scope,
                    "relevance": round(item.get("rank", 0), 4),
                    "snippet": item.get("snippet", ""),
                    "updated_at": fm.get("updated_at", ""),
                })

                if len(results) >= target_limit:
                    break

            offset += page_size
            # 安全上限：最多拉取 200 条避免无限循环
            if offset >= 200:
                break

        if not results and offset == 0:
            return None
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
            # 从文件读取完整数据
            full = self._lookup_claim(item.get("claim_id", ""))
            if full:
                full["relevance"] = round(item.get("rank", 0), 4)
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
                    "relevance": round(item.get("rank", 0), 4),
                    "snippet": item.get("snippet", ""),
                })

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

                relevance = self._score(body, keywords)
                if relevance > 0:
                    results.append({
                        "page_id": fm.get("page_id", rel_path),
                        "path": rel_path,
                        "title": title,
                        "type": fm.get("type", ""),
                        "scope": page_scope,
                        "relevance": relevance,
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
                    relevance = self._score(text, keywords)
                    if relevance > 0:
                        results.append({
                            "claim_id": c.get("claim_id"),
                            "source_id": c.get("source_id"),
                            "text": text,
                            "locator": c.get("locator", ""),
                            "quote_hash": c.get("quote_hash", ""),
                            "status": c.get("status", "active"),
                            "verified_at": c.get("verified_at", ""),
                            "relevance": relevance,
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
