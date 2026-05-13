"""Staging 写入 — 先写临时目录，校验通过后 rename 到正式 Wiki。"""

from pathlib import Path

from mini_note.models.path_utils import validate_path_in_workspace


def write_to_staging(workspace: Path, rel_path: str, content: str) -> Path:
    """将内容写入 staging 目录。

    Args:
        workspace: knowledge base root
        rel_path: relative path under wiki/ (e.g. "wiki/sources/page.md")
        content: Markdown content

    Returns:
        Path to the staged file

    Raises:
        ValueError: 路径不在 workspace 内或路径不含 wiki/
    """
    # 路径必须包含 wiki/ 前缀
    if not rel_path.startswith("wiki/"):
        raise ValueError("Wiki 页面路径必须在 wiki/ 目录下（workspace 内限制）")

    target = (workspace / rel_path).resolve()
    validate_path_in_workspace(target, workspace)

    # 写入 staging
    staging_dir = workspace / ".state" / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)

    # 保持相对路径结构
    staged_file = staging_dir / rel_path
    staged_file.parent.mkdir(parents=True, exist_ok=True)
    staged_file.write_text(content, encoding="utf-8")

    return staged_file


def apply_staged_changes(workspace: Path, staged_files: list[Path]) -> list[Path]:
    """将 staging 目录下的文件移动到正式 wiki 目录。

    Returns:
        实际写入的正式路径列表
    """
    staging_dir = workspace / ".state" / "staging"
    applied = []

    for sf in staged_files:
        rel = sf.relative_to(staging_dir)
        dest = workspace / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(sf.read_text(encoding="utf-8"))
        sf.unlink()  # 清理 staging
        applied.append(dest)

    return applied
