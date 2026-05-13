"""Indexer — 从 Markdown 文件和 YAML 重建 SQLite 派生索引。"""

import sqlite3
from pathlib import Path

import yaml


class Indexer:
    """从文件系统重建 SQLite 索引。

    SQLite 是可删除重建的派生数据。Indexer 扫描 wiki/ 和 raw/archive/
    目录，将 source、page、claim 等元数据写入 notes.db。
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.db_path = workspace / ".state" / "notes.db"

    def rebuild(self) -> None:
        """删除已有数据库（如存在），从文件重建全部索引。"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # 删除已有数据库（包括损坏的）
        if self.db_path.exists():
            self.db_path.unlink()

        conn = sqlite3.connect(str(self.db_path))
        try:
            self._create_tables(conn)
            self._index_sources(conn)
            self._index_pages(conn)
            self._index_claims(conn)

            # FTS5 全文索引
            from mini_note.indexer.fts import FTSIndex
            fts = FTSIndex(self.workspace)
            fts.rebuild(conn)

            conn.commit()
        finally:
            conn.close()

    def _create_tables(self, conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sources (
                source_id TEXT PRIMARY KEY,
                original_name TEXT,
                sha256 TEXT,
                owner_id TEXT,
                scope TEXT,
                media_type TEXT,
                size_bytes INTEGER,
                ingestion_status TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS pages (
                page_id TEXT PRIMARY KEY,
                path TEXT UNIQUE,
                title TEXT,
                page_type TEXT,
                scope TEXT DEFAULT 'shared',
                owner_id TEXT,
                status TEXT DEFAULT 'published',
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS claims (
                claim_id TEXT PRIMARY KEY,
                source_id TEXT,
                text TEXT,
                locator TEXT,
                quote_hash TEXT,
                status TEXT DEFAULT 'active',
                verified_at TEXT,
                FOREIGN KEY (source_id) REFERENCES sources(source_id)
            );
            CREATE TABLE IF NOT EXISTS links (
                from_page TEXT,
                to_page TEXT,
                PRIMARY KEY (from_page, to_page)
            );
        """)

    def _index_sources(self, conn: sqlite3.Connection) -> None:
        archive = self.workspace / "raw" / "archive"
        if not archive.exists():
            return

        for source_yaml in sorted(archive.glob("*/source.yaml")):
            try:
                data = yaml.safe_load(source_yaml.read_text())
                if not data:
                    continue
                conn.execute(
                    """INSERT OR REPLACE INTO sources
                       (source_id, original_name, sha256, owner_id, scope,
                        media_type, size_bytes, ingestion_status, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        data.get("source_id"),
                        data.get("original_name"),
                        data.get("sha256"),
                        data.get("owner_id"),
                        data.get("scope", "shared"),
                        data.get("media_type"),
                        data.get("size_bytes"),
                        data.get("ingestion_status"),
                        data.get("created_at"),
                    ),
                )
            except Exception:
                continue

    def _index_pages(self, conn: sqlite3.Connection) -> None:
        wiki = self.workspace / "wiki"
        if not wiki.exists():
            return

        for md_file in sorted(wiki.rglob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8")
                rel_path = str(md_file.relative_to(self.workspace))

                frontmatter = self._parse_frontmatter(text)
                page_id = frontmatter.get("page_id", rel_path)
                title = frontmatter.get("title", md_file.stem)
                page_type = frontmatter.get("type", "")
                scope = frontmatter.get("scope", "shared")
                owner_id = frontmatter.get("owner_id", "")
                status = frontmatter.get("status", "published")
                created_at = frontmatter.get("created_at", "")
                updated_at = frontmatter.get("updated_at", "")

                conn.execute(
                    """INSERT OR REPLACE INTO pages
                       (page_id, path, title, page_type, scope, owner_id,
                        status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (page_id, rel_path, title, page_type, scope, owner_id,
                     status, created_at, updated_at),
                )
            except Exception:
                continue

    def _index_claims(self, conn: sqlite3.Connection) -> None:
        extracted = self.workspace / "raw" / "extracted"
        if not extracted.exists():
            return

        for claims_yaml in sorted(extracted.glob("*/claims.yaml")):
            try:
                data = yaml.safe_load(claims_yaml.read_text())
                if not data or "claims" not in data:
                    continue
                for c in data["claims"]:
                    conn.execute(
                        """INSERT OR REPLACE INTO claims
                           (claim_id, source_id, text, locator, quote_hash,
                            status, verified_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            c.get("claim_id"),
                            c.get("source_id"),
                            c.get("text"),
                            c.get("locator"),
                            c.get("quote_hash", ""),
                            c.get("status", "active"),
                            c.get("verified_at", ""),
                        ),
                    )
            except Exception:
                continue

    def _parse_frontmatter(self, text: str) -> dict:
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
