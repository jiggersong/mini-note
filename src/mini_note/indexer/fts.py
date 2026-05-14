"""FTS5 全文检索 — 中文 bigram 分词、内置 rank 排序。

FTS5 虚拟表存储于 notes.db，可从文件重建。
中文使用 bigram 预处理后由 unicode61 tokenizer 索引。
"""

import re
import sqlite3
from pathlib import Path


_CJK_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")
_NON_CJK_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+", re.ASCII)


def _to_bigrams(text: str) -> str:
    """将中文部分转为 bigram，英文/数字 token 保持原样。

    "ECS 性能优化" → "ECS 性能 能优 优化"
    """
    result: list[str] = []
    pos = 0

    for m in _NON_CJK_TOKEN_RE.finditer(text):
        # 处理中文段 (pos 到 m.start())
        cjk_seg = text[pos:m.start()]
        if cjk_seg:
            result.extend(_segment_cjk(cjk_seg))
        # 英文/数字 token
        result.append(m.group())
        pos = m.end()

    # 尾部中文
    if pos < len(text):
        result.extend(_segment_cjk(text[pos:]))

    return " ".join(result)


def _segment_cjk(text: str) -> list[str]:
    """将 CJK 文本转为 bigram 列表（含空格分隔的连续 CJK）。"""
    chars = [ch for ch in text if _CJK_RE.match(ch)]
    if not chars:
        return []
    if len(chars) == 1:
        return [chars[0]]
    grams = []
    for i in range(len(chars) - 1):
        grams.append(chars[i] + chars[i + 1])
    return grams


def tokenize_query(query: str) -> str:
    """将查询文本转为 FTS5 查询表达式（bigram OR 连接）。"""
    text = _to_bigrams(query)
    tokens = text.split()
    if not tokens:
        return query
    return " OR ".join(tokens)


class FTSIndex:
    """管理 FTS5 全文索引的创建和搜索。"""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.db_path = workspace / ".state" / "notes.db"

    def rebuild(self, conn: sqlite3.Connection) -> None:
        """在已有数据库连接上创建/重建 FTS5 表。"""
        self._create_fts_tables(conn)
        self._index_fts_pages(conn)
        self._index_fts_claims(conn)

    def _create_fts_tables(self, conn: sqlite3.Connection) -> None:
        """创建 FTS5 虚拟表（如已存在则删除重建）。"""
        conn.execute("DROP TABLE IF EXISTS fts_pages")
        conn.execute("DROP TABLE IF EXISTS fts_claims")

        conn.execute("""
            CREATE VIRTUAL TABLE fts_pages USING fts5(
                page_id,
                path,
                title,
                body,
                scope UNINDEXED,
                type UNINDEXED,
                updated_at UNINDEXED,
                tokenize='unicode61'
            )
        """)
        conn.execute("""
            CREATE VIRTUAL TABLE fts_claims USING fts5(
                claim_id,
                source_id,
                text,
                tokenize='unicode61'
            )
        """)

    def _index_fts_pages(self, conn: sqlite3.Connection) -> None:
        """将 wiki/ 下所有页面内容写入 FTS5 索引。"""
        wiki_dir = self.workspace / "wiki"
        if not wiki_dir.exists():
            return

        rows: list[tuple] = []
        for md_file in sorted(wiki_dir.rglob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8")
                rel_path = str(md_file.relative_to(self.workspace))

                page_id = rel_path
                title = md_file.stem
                body = text
                scope = "shared"
                page_type = ""
                updated_at = ""
                if text.startswith("---"):
                    end = text.find("---", 3)
                    if end != -1:
                        import yaml
                        try:
                            fm = yaml.safe_load(text[3:end]) or {}
                        except yaml.YAMLError:
                            fm = {}
                        page_id = fm.get("page_id", rel_path)
                        title = fm.get("title", md_file.stem)
                        scope = fm.get("scope", "shared")
                        page_type = fm.get("type", "")
                        updated_at = fm.get("updated_at", "")
                        body = text[end + 3:]

                indexed_body = _to_bigrams(body)

                rows.append((page_id, rel_path, title, indexed_body, scope, page_type, updated_at))
            except Exception:
                continue

        if rows:
            conn.executemany(
                "INSERT INTO fts_pages (page_id, path, title, body, scope, type, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def _index_fts_claims(self, conn: sqlite3.Connection) -> None:
        """将 raw/extracted/ 下所有 claim 写入 FTS5 索引。"""
        ext_dir = self.workspace / "raw" / "extracted"
        if not ext_dir.exists():
            return

        rows: list[tuple] = []
        for claims_yaml in sorted(ext_dir.glob("*/claims.yaml")):
            try:
                import yaml
                data = yaml.safe_load(claims_yaml.read_text())
                if not data or "claims" not in data:
                    continue
                for c in data["claims"]:
                    indexed_text = _to_bigrams(c.get("text", ""))
                    rows.append((
                        c.get("claim_id", ""),
                        c.get("source_id", ""),
                        indexed_text,
                    ))
            except Exception:
                continue

        if rows:
            conn.executemany(
                "INSERT INTO fts_claims (claim_id, source_id, text) VALUES (?, ?, ?)",
                rows,
            )

    def search_pages(self, question: str, scope: str = "shared", limit: int = 10, offset: int = 0) -> list[dict]:
        """FTS5 搜索页面，返回 rank 排序结果。scope 非 shared 时在 SQL 层过滤。"""
        query = tokenize_query(question)
        if not query.strip():
            return []

        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            if scope and scope != "shared":
                cur = conn.execute(
                    """
                    SELECT page_id, path, title, scope, type, updated_at,
                           snippet(fts_pages, 3, '<mark>', '</mark>', '...', 32) AS snippet,
                           rank
                    FROM fts_pages
                    WHERE fts_pages MATCH ? AND scope = ?
                    ORDER BY rank
                    LIMIT ? OFFSET ?
                    """,
                    (query, scope, limit, offset),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT page_id, path, title, scope, type, updated_at,
                           snippet(fts_pages, 3, '<mark>', '</mark>', '...', 32) AS snippet,
                           rank
                    FROM fts_pages
                    WHERE fts_pages MATCH ?
                    ORDER BY rank
                    LIMIT ? OFFSET ?
                    """,
                    (query, limit, offset),
                )
            results = []
            for row in cur:
                results.append({
                    "page_id": row["page_id"],
                    "path": row["path"],
                    "title": row["title"],
                    "scope": row["scope"],
                    "type": row["type"],
                    "updated_at": row["updated_at"],
                    "snippet": row["snippet"],
                    "rank": row["rank"],
                })
            conn.close()
        except sqlite3.OperationalError:
            return []

        return results

    def search_claims(self, question: str, limit: int = 10) -> list[dict]:
        """FTS5 搜索 claim，返回 rank 排序结果。"""
        query = tokenize_query(question)
        if not query.strip():
            return []

        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                """
                SELECT claim_id, source_id,
                       snippet(fts_claims, 2, '<mark>', '</mark>', '...', 32) AS snippet,
                       rank
                FROM fts_claims
                WHERE fts_claims MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            )
            results = []
            for row in cur:
                results.append({
                    "claim_id": row["claim_id"],
                    "source_id": row["source_id"],
                    "snippet": row["snippet"],
                    "rank": row["rank"],
                })
            conn.close()
        except sqlite3.OperationalError:
            return []

        return results
