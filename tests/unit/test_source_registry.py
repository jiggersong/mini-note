"""
Source Registry 单元测试 — 原始资料登记、SHA256 校验、重复摄入检测。

测试目标（v2.4 §18.1）:
- SHA256 计算正确
- 同一文件重复摄入被识别
- source_id 生成格式正确
- 文件状态正确记录
"""

import hashlib
from pathlib import Path

import pytest


# ============================================================
# SHA256 哈希
# ============================================================

class TestSHA256:
    """测试文件内容哈希计算。"""

    def test_sha256_of_known_content(self, tmp_workspace):
        """已知内容的 SHA256 计算正确。"""
        from mini_note.models.source_registry import compute_sha256

        path = tmp_workspace / "test.txt"
        path.write_bytes(b"hello world")
        expected = hashlib.sha256(b"hello world").hexdigest()

        assert compute_sha256(path) == expected

    def test_sha256_empty_file(self, tmp_workspace):
        """空文件的 SHA256 计算正确。"""
        from mini_note.models.source_registry import compute_sha256

        path = tmp_workspace / "empty.txt"
        path.write_bytes(b"")
        expected = hashlib.sha256(b"").hexdigest()

        assert compute_sha256(path) == expected

    def test_sha256_binary_file(self, tmp_workspace):
        """二进制文件的 SHA256 计算正确。"""
        from mini_note.models.source_registry import compute_sha256

        data = bytes(range(256))
        path = tmp_workspace / "binary.bin"
        path.write_bytes(data)
        expected = hashlib.sha256(data).hexdigest()

        assert compute_sha256(path) == expected

    def test_different_content_different_hash(self, tmp_workspace):
        """不同内容产生不同哈希。"""
        from mini_note.models.source_registry import compute_sha256

        p1 = tmp_workspace / "a.txt"; p1.write_text("a")
        p2 = tmp_workspace / "b.txt"; p2.write_text("b")

        assert compute_sha256(p1) != compute_sha256(p2)

    def test_nonexistent_file_raises(self, tmp_workspace):
        """不存在文件抛出异常。"""
        from mini_note.models.source_registry import compute_sha256

        with pytest.raises(FileNotFoundError):
            compute_sha256(tmp_workspace / "nope.txt")


# ============================================================
# source_id 生成
# ============================================================

class TestSourceId:
    """测试 source_id 生成格式。"""

    def test_source_id_format(self):
        """source_id 格式为 src-YYYYMMDD-HHMMSS-xxxx。"""
        from mini_note.models.source_registry import generate_source_id

        sid = generate_source_id()
        parts = sid.split("-")
        assert len(parts) == 4
        assert parts[0] == "src"
        assert len(parts[1]) == 8  # YYYYMMDD
        assert len(parts[2]) == 6  # HHMMSS
        assert len(parts[3]) == 8  # token_hex(4) = 8 hex chars

    def test_source_ids_are_unique(self):
        """连续生成的 source_id 不重复。"""
        from mini_note.models.source_registry import generate_source_id

        ids = {generate_source_id() for _ in range(100)}
        assert len(ids) == 100


# ============================================================
# 重复摄入检测
# ============================================================

class TestDuplicateDetection:
    """测试基于 SHA256 的重复检测。"""

    def test_same_hash_rejected(self, tmp_workspace):
        """相同 SHA256 的文件返回已有 source。"""
        from mini_note.models.source_registry import SourceRegistry

        p1 = tmp_workspace / "doc1.pdf"; p1.write_bytes(b"same content")
        p2 = tmp_workspace / "doc2.pdf"; p2.write_bytes(b"same content")

        registry = SourceRegistry(tmp_workspace)
        sid1 = registry.register(p1, owner_id="user-default")
        sid2 = registry.register(p2, owner_id="user-default")

        # 第二个文件应返回已有的 source_id
        assert sid1 == sid2

    def test_different_hash_accepted(self, tmp_workspace):
        """不同 SHA256 的文件分别注册。"""
        from mini_note.models.source_registry import SourceRegistry

        p1 = tmp_workspace / "doc1.pdf"; p1.write_bytes(b"content A")
        p2 = tmp_workspace / "doc2.pdf"; p2.write_bytes(b"content B")

        registry = SourceRegistry(tmp_workspace)
        sid1 = registry.register(p1, owner_id="user-default")
        sid2 = registry.register(p2, owner_id="user-default")

        assert sid1 != sid2


# ============================================================
# 文件归档
# ============================================================

class TestArchive:
    """测试原始文件归档到 archive/ 目录。"""

    def test_file_copied_to_archive(self, tmp_workspace, tmp_path):
        """文件被复制到 archive/{source_id}/ 目录。"""
        from mini_note.models.source_registry import SourceRegistry

        src = tmp_path / "original.txt"; src.write_text("hello archive")
        registry = SourceRegistry(tmp_workspace)
        sid = registry.register(src, owner_id="user-default")

        archive_dir = tmp_workspace / "raw" / "archive" / sid
        assert archive_dir.is_dir()
        assert (archive_dir / "original.txt").read_text() == "hello archive"

    def test_source_yaml_written(self, tmp_workspace, tmp_path):
        """archive 目录下生成 source.yaml。"""
        from mini_note.models.source_registry import SourceRegistry

        src = tmp_path / "original.md"; src.write_text("# hello")
        registry = SourceRegistry(tmp_workspace)
        sid = registry.register(src, owner_id="user-default")

        source_yaml = tmp_workspace / "raw" / "archive" / sid / "source.yaml"
        assert source_yaml.exists()
        content = source_yaml.read_text()
        assert "source_id" in content
        assert "sha256" in content
        assert "original.md" in content


# ============================================================
# 文件大小限制
# ============================================================

class TestFileSizeLimit:
    """测试文件超限处理。"""

    def test_file_within_limit_accepted(self, tmp_workspace, tmp_path):
        """未超限文件正常注册。"""
        from mini_note.models.source_registry import SourceRegistry

        src = tmp_path / "small.txt"; src.write_text("small content")
        registry = SourceRegistry(tmp_workspace)
        sid = registry.register(src, owner_id="user-default", max_text_mb=2)
        assert sid is not None

    def test_file_exceeds_limit_marked_partial(self, tmp_workspace, sample_large_text_file):
        """超限文件标记为 partial，不拒绝。"""
        from mini_note.models.source_registry import SourceRegistry

        registry = SourceRegistry(tmp_workspace)
        sid = registry.register(sample_large_text_file, owner_id="user-default", max_text_mb=2)

        source_yaml = tmp_workspace / "raw" / "archive" / sid / "source.yaml"
        content = source_yaml.read_text()
        assert "partial" in content
