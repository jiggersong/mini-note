"""Source Registry — 原始资料登记、SHA256 哈希、重复检测、归档。"""

import hashlib
import shutil
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

CST = timezone(timedelta(hours=8))


def compute_sha256(path: Path) -> str:
    """计算文件的 SHA256 哈希值（hex 字符串）。"""
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_source_id() -> str:
    """生成 source_id，格式: src-YYYYMMDD-HHMMSS-xxxx。"""
    now = datetime.now(CST)
    suffix = secrets.token_hex(4)  # 4 hex chars ≈ 65536 可能值/秒，同秒碰撞概率极低
    return f"src-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}-{suffix}"


class SourceRegistry:
    """原始资料注册与归档。

    负责计算文件哈希、检测重复、归档到 archive/、写入 source.yaml。
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.archive_dir = workspace / "raw" / "archive"

    def register(
        self,
        path: Path,
        owner_id: str,
        max_text_mb: int = 2,
        max_pdf_pages: int = 100,
    ) -> str:
        """注册一个文件，返回 source_id。

        如果文件 SHA256 已存在，返回已有的 source_id 而不再归档。
        如果文件超过大小限制，标记 ingestion_status 为 partial。
        """
        sha = compute_sha256(path)
        size_bytes = path.stat().st_size

        # 检测重复
        existing = self._find_by_sha256(sha)
        if existing:
            return existing

        # 生成 source_id 并归档
        source_id = generate_source_id()
        dest_dir = self.archive_dir / source_id
        dest_dir.mkdir(parents=True, exist_ok=True)

        # 确定文件类型和摄入状态
        ext = path.suffix.lower()
        media_type = self._guess_media_type(ext)
        status = self._determine_status(path, size_bytes, max_text_mb)

        # 复制原始文件
        dest_file = dest_dir / path.name
        shutil.copy2(path, dest_file)

        # 写入 source.yaml
        source_data = {
            "source_id": source_id,
            "original_name": path.name,
            "stored_path": str(dest_file.relative_to(self.workspace)),
            "sha256": sha,
            "owner_id": owner_id,
            "scope": "shared",
            "media_type": media_type,
            "size_bytes": size_bytes,
            "ingestion_status": status,
            "created_at": datetime.now(CST).isoformat(),
        }
        source_yaml = dest_dir / "source.yaml"
        source_yaml.write_text(yaml.dump(source_data, allow_unicode=True))

        return source_id

    def _find_by_sha256(self, sha: str) -> str | None:
        """扫描所有 source.yaml，查找重复 SHA256。"""
        if not self.archive_dir.exists():
            return None
        for source_yaml in self.archive_dir.glob("*/source.yaml"):
            try:
                data = yaml.safe_load(source_yaml.read_text())
                if data and data.get("sha256") == sha:
                    return data["source_id"]
            except Exception:
                continue
        return None

    def _guess_media_type(self, ext: str) -> str:
        """根据扩展名推断 media type。"""
        mapping = {
            ".md": "text/markdown",
            ".txt": "text/plain",
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".svg": "image/svg+xml",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".flac": "audio/flac",
            ".ogg": "audio/ogg",
            ".m4a": "audio/mp4",
            ".mp4": "video/mp4",
            ".avi": "video/x-msvideo",
            ".mov": "video/quicktime",
            ".mkv": "video/x-matroska",
            ".webm": "video/webm",
            ".py": "text/x-python",
            ".js": "text/javascript",
            ".ts": "text/typescript",
            ".go": "text/x-go",
            ".java": "text/x-java",
            ".rs": "text/x-rust",
        }
        return mapping.get(ext, "application/octet-stream")

    def _determine_status(
        self, path: Path, size_bytes: int, max_text_mb: int
    ) -> str:
        """根据文件大小判断摄入状态。"""
        ext = path.suffix.lower()
        if ext in (".md", ".txt"):
            limit = max_text_mb * 1024 * 1024
            if size_bytes > limit:
                return "partial"
        return "full"
