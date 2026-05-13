"""
路径工具单元测试 — 路径穿越防护、slug 生成、workspace 限制。

测试目标（v2.4 §18.1）:
- 路径穿越攻击必须被拒绝
- slug 生成符合规范：纯英文、无空格、无特殊符号
- 写入路径必须在 workspace 内
"""

import pytest


# ============================================================
# Slug 生成
# ============================================================

class TestSlugify:
    """测试文件名到 slug 的转换。"""

    def test_english_title_converts_to_lowercase(self):
        """英文标题转为小写 slug。"""
        from mini_note.models.path_utils import slugify

        assert slugify("ECS Performance Guide") == "ecs-performance-guide"

    def test_chinese_title_preserves_characters(self):
        """中文标题保留原文，空格转连字符。"""
        from mini_note.models.path_utils import slugify

        result = slugify("ECS 性能优化指南")
        assert "ecs" in result
        assert "性能优化指南" in result

    def test_special_characters_removed(self):
        """特殊字符被移除。"""
        from mini_note.models.path_utils import slugify

        result = slugify("Hello! @World #2024")
        assert "!" not in result
        assert "@" not in result
        assert "#" not in result

    def test_multiple_spaces_collapsed(self):
        """多个连续空格压缩为单个连字符。"""
        from mini_note.models.path_utils import slugify

        assert slugify("a   b") == "a-b"

    def test_leading_trailing_dashes_trimmed(self):
        """首尾连字符被去除。"""
        from mini_note.models.path_utils import slugify

        assert slugify("  hello  ") == "hello"

    def test_empty_string_raises(self):
        """空字符串抛出异常。"""
        from mini_note.models.path_utils import slugify

        with pytest.raises(ValueError):
            slugify("")

    def test_only_special_chars_raises(self):
        """全特殊字符字符串抛出异常。"""
        from mini_note.models.path_utils import slugify

        with pytest.raises(ValueError):
            slugify("!@#$%")


# ============================================================
# 路径安全校验
# ============================================================

class TestPathValidation:
    """测试路径必须在 workspace 内。"""

    def test_path_within_workspace_passes(self, tmp_workspace):
        """合法路径通过校验。"""
        from mini_note.models.path_utils import validate_path_in_workspace

        target = tmp_workspace / "wiki" / "entities" / "test.md"
        validate_path_in_workspace(target, tmp_workspace)  # 不抛异常

    def test_path_equals_workspace_fails(self, tmp_workspace):
        """路径等于 workspace 根目录失败。"""
        from mini_note.models.path_utils import validate_path_in_workspace

        with pytest.raises(ValueError, match="路径必须在 workspace 内"):
            validate_path_in_workspace(tmp_workspace, tmp_workspace)

    def test_path_outside_workspace_fails(self, tmp_workspace):
        """路径在 workspace 外失败。"""
        from mini_note.models.path_utils import validate_path_in_workspace

        target = tmp_workspace.parent / "outside.md"
        with pytest.raises(ValueError, match="路径穿越"):
            validate_path_in_workspace(target, tmp_workspace)

    def test_path_traversal_with_dotdot_fails(self, tmp_workspace):
        """.. 路径穿越被拒绝。"""
        from mini_note.models.path_utils import validate_path_in_workspace

        target = (tmp_workspace / "wiki" / ".." / ".." / "etc" / "passwd").resolve()
        with pytest.raises(ValueError, match="路径穿越"):
            validate_path_in_workspace(target, tmp_workspace)

    def test_symlink_outside_workspace_fails(self, tmp_workspace):
        """符号链接指向 workspace 外被拒绝。"""
        from mini_note.models.path_utils import validate_path_in_workspace
        import os

        outside = tmp_workspace.parent / "outside.txt"
        outside.write_text("data")
        symlink = tmp_workspace / "wiki" / "link.md"
        os.symlink(str(outside), str(symlink))

        with pytest.raises(ValueError, match="路径穿越"):
            validate_path_in_workspace(symlink, tmp_workspace)

    def test_relative_path_resolved(self, tmp_workspace):
        """相对路径被正确 resolve 到绝对路径后校验。"""
        from mini_note.models.path_utils import validate_path_in_workspace

        target = tmp_workspace / "wiki" / "entities" / "test.md"
        validate_path_in_workspace(target, tmp_workspace)  # 不抛异常

    def test_nonexistent_path_still_checked(self, tmp_workspace):
        """不存在的路径也做父目录遍历检查。"""
        from mini_note.models.path_utils import validate_path_in_workspace

        target = tmp_workspace / "wiki" / "entities" / "future.md"
        # 路径不存在但仍在 workspace 内，应通过
        validate_path_in_workspace(target, tmp_workspace)


# ============================================================
# 安全文件名
# ============================================================

class TestSafeFilename:
    """测试文件名安全化处理。"""

    def test_normal_filename_unchanged(self):
        """正常英文文件名不变。"""
        from mini_note.models.path_utils import safe_filename

        assert safe_filename("test-doc.md") == "test-doc.md"

    def test_path_separator_removed(self):
        """路径分隔符被移除。"""
        from mini_note.models.path_utils import safe_filename

        result = safe_filename("a/b/c.md")
        assert "/" not in result

    def test_null_byte_removed(self):
        """空字节被移除。"""
        from mini_note.models.path_utils import safe_filename

        result = safe_filename("test\x00.md")
        assert "\x00" not in result
