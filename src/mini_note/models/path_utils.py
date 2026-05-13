"""路径工具 — slug 生成、路径安全校验、文件名安全化。"""

import re
import os
from pathlib import Path


def slugify(text: str) -> str:
    """将文本转为 URL 安全的 slug。

    - 英文转小写
    - 特殊字符移除（保留字母、数字、中文、连字符、下划线）
    - 空白压缩为单个连字符
    - 首尾连字符去除

    Raises:
        ValueError: 输入为空字符串或转换后无有效字符
    """
    text = text.strip()
    if not text:
        raise ValueError("slug 输入不能为空字符串")

    # 统一转小写
    text = text.lower()
    # 保留字母、数字、中文（一-鿿）、空白、连字符、下划线
    text = re.sub(r"[^\w\s\-一-鿿]", "", text)
    # 空白转连字符并压缩
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)
    # 去除首尾连字符
    text = text.strip("-")

    if not text:
        raise ValueError("slug 转换后无有效字符")
    return text


def safe_filename(name: str) -> str:
    """过滤文件名中的危险字符（路径分隔符、空字节）。"""
    name = name.replace("\x00", "")
    name = name.replace("/", "-")
    name = name.replace("\\", "-")
    return name


def validate_path_in_workspace(target: Path, workspace: Path) -> None:
    """校验目标路径必须在 workspace 内。

    Raises:
        ValueError: 路径在 workspace 外或等于 workspace 根目录
    """
    # resolve 绝对路径（跟随符号链接）
    try:
        resolved = target.resolve()
    except Exception:
        resolved = Path(os.path.abspath(str(target)))

    ws_resolved = workspace.resolve()

    # 检测路径穿越
    try:
        resolved.relative_to(ws_resolved)
    except ValueError:
        raise ValueError("路径穿越：目标路径不在 workspace 内")

    # 不能等于 workspace 根目录
    if resolved == ws_resolved:
        raise ValueError("路径必须在 workspace 内，不能等于根目录")
