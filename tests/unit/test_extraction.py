"""
Extraction 单元测试 — 文件内容解析。

测试目标（v2.4 §18.1）:
- 各格式解析成功
- 解析失败有明确原因
- partial 标记正确
- metadata_only 处理
"""

import pytest


# ============================================================
# Markdown 解析
# ============================================================

class TestMarkdownExtraction:
    """测试 .md 文件解析。"""

    def test_extract_markdown_success(self, sample_md_file):
        """解析 Markdown 文件成功，提取文本和标题。"""
        from mini_note.ingest.extraction import extract_markdown

        result = extract_markdown(sample_md_file)
        assert result.status == "full"
        assert "测试文档" in result.content
        assert "ECS 突发性能实例" in result.content

    def test_extract_markdown_empty_file(self, tmp_workspace):
        """空 Markdown 文件解析成功但内容为空。"""
        from mini_note.ingest.extraction import extract_markdown

        empty_md = tmp_workspace / "empty.md"
        empty_md.write_text("")
        result = extract_markdown(empty_md)
        assert result.status == "full"


# ============================================================
# 纯文本解析
# ============================================================

class TestTextExtraction:
    """测试 .txt 文件解析。"""

    def test_extract_text_success(self, sample_txt_file):
        """纯文本文件解析成功。"""
        from mini_note.ingest.extraction import extract_text

        result = extract_text(sample_txt_file)
        assert result.status == "full"
        assert "关键数字：42" in result.content

    def test_extract_text_encoding_detection(self, tmp_workspace):
        """UTF-8 BOM 文件正确解析。"""
        from mini_note.ingest.extraction import extract_text

        utf8_bom = tmp_workspace / "bom.txt"
        utf8_bom.write_bytes(b"\xef\xbb\xbfhello world")
        result = extract_text(utf8_bom)
        assert "hello world" in result.content
        assert "﻿" not in result.content


# ============================================================
# DOCX 解析
# ============================================================

class TestDocxExtraction:
    """测试 .docx 文件解析。"""

    def test_extract_docx_success(self, sample_docx_file):
        """DOCX 文件解析成功，提取段落和标题。"""
        from mini_note.ingest.extraction import extract_docx

        result = extract_docx(sample_docx_file)
        assert result.status == "full"
        assert "测试 DOCX 文档" in result.content
        assert "最大连接数为 1000" in result.content

    def test_extract_docx_not_a_docx(self, tmp_workspace):
        """非 DOCX 文件（zip 伪装）返回失败。"""
        from mini_note.ingest.extraction import extract_docx

        fake_docx = tmp_workspace / "fake.docx"
        fake_docx.write_text("not a docx file")
        result = extract_docx(fake_docx)
        assert result.status in ("failed", "partial")


# ============================================================
# PDF 解析
# ============================================================

class TestPDFExtraction:
    """测试 .pdf 文件解析。"""

    def test_extract_pdf_no_text(self, sample_pdf_file):
        """无文本 PDF 返回成功但内容可能为空。"""
        from mini_note.ingest.extraction import extract_pdf

        result = extract_pdf(sample_pdf_file)
        assert result.status in ("full", "metadata_only")
        assert result.extractor == "pdfplumber"

    def test_extract_pdf_not_a_pdf(self, tmp_workspace):
        """非 PDF 文件返回失败。"""
        from mini_note.ingest.extraction import extract_pdf

        fake_pdf = tmp_workspace / "fake.pdf"
        fake_pdf.write_text("not a pdf")
        result = extract_pdf(fake_pdf)
        assert result.status in ("failed", "metadata_only")


# ============================================================
# XLSX 解析
# ============================================================

class TestXLSXExtraction:
    """测试 .xlsx 文件解析。"""

    def test_extract_xlsx_success(self, sample_xlsx_file):
        """XLSX 文件解析成功，提取表格数据。"""
        from mini_note.ingest.extraction import extract_xlsx

        result = extract_xlsx(sample_xlsx_file)
        assert result.status == "full"
        assert result.extractor == "openpyxl"
        assert "ecs.t6-c1m1" in result.content
        assert "ecs.g6.large" in result.content

    def test_extract_xlsx_not_a_xlsx(self, tmp_workspace):
        """非 XLSX 文件返回失败。"""
        from mini_note.ingest.extraction import extract_xlsx

        fake = tmp_workspace / "fake.xlsx"
        fake.write_text("not a xlsx")
        result = extract_xlsx(fake)
        assert result.status in ("failed", "partial")


# ============================================================
# PPTX 解析
# ============================================================

class TestPPTXExtraction:
    """测试 .pptx 文件解析。"""

    def test_extract_pptx_success(self, sample_pptx_file):
        """PPTX 文件解析成功，提取幻灯片文本。"""
        from mini_note.ingest.extraction import extract_pptx

        result = extract_pptx(sample_pptx_file)
        assert result.status == "full"
        assert result.extractor == "python-pptx"
        assert "ECS 性能优化方案" in result.content
        assert "最大连接数限制为 1000" in result.content

    def test_extract_pptx_not_a_pptx(self, tmp_workspace):
        """非 PPTX 文件返回失败。"""
        from mini_note.ingest.extraction import extract_pptx

        fake = tmp_workspace / "fake.pptx"
        fake.write_text("not a pptx")
        result = extract_pptx(fake)
        assert result.status in ("failed", "partial")


# ============================================================
# 大文件部分摄入
# ============================================================

class TestPartialIngestion:
    """测试超限文件 partial 标记。"""

    def test_text_exceeds_limit_marked_partial(self, sample_large_text_file):
        """超限文本文件标记为 partial。"""
        from mini_note.ingest.extraction import extract_text

        result = extract_text(sample_large_text_file, max_bytes=2 * 1024 * 1024)
        # 大文件应被标记 partial
        assert result.status in ("partial", "full")
        if result.status == "partial":
            assert result.coverage["reason"] is not None

    def test_metadata_only_for_unsupported_type(self, tmp_workspace):
        """不支持的文件类型返回 metadata_only。"""
        from mini_note.ingest.extraction import extract_by_type

        unknown = tmp_workspace / "file.xyz"
        unknown.write_bytes(b"\x00\x01\x02")
        result = extract_by_type(unknown)
        assert result.status == "metadata_only"


# ============================================================
# 图片解析
# ============================================================

class TestImageExtraction:
    """测试图片文件元数据提取。"""

    def test_extract_image_success(self, sample_image_file):
        """图片文件解析成功，提取尺寸和格式信息。"""
        from mini_note.ingest.extraction import extract_image

        result = extract_image(sample_image_file)
        assert result.status == "metadata_only"
        assert result.extractor == "pillow"
        assert result.coverage["width"] == 640
        assert result.coverage["height"] == 480
        assert result.coverage["format"] == "PNG"

    def test_extract_image_content_includes_metadata_table(self, sample_image_file):
        """图片提取内容包含 Markdown 元数据表。"""
        from mini_note.ingest.extraction import extract_image

        result = extract_image(sample_image_file)
        assert "图片元数据" in result.content
        assert "640" in result.content
        assert "480" in result.content

    def test_extract_image_not_an_image(self, tmp_workspace):
        """非图片文件返回失败。"""
        from mini_note.ingest.extraction import extract_image

        fake = tmp_workspace / "fake.png"
        fake.write_text("not an image")
        result = extract_image(fake)
        assert result.status == "failed"


# ============================================================
# 代码解析
# ============================================================

class TestCodeExtraction:
    """测试代码文件结构化提取。"""

    def test_extract_python_code(self, sample_python_file):
        """Python 代码提取函数和类签名。"""
        from mini_note.ingest.extraction import extract_code

        result = extract_code(sample_python_file)
        assert result.status == "full"
        assert result.extractor == "code-parser"
        assert "class InstanceSpec" in result.content
        assert "def compute_credit_balance" in result.content
        assert "def analyze_instances" in result.content

    def test_extract_code_unknown_language(self, tmp_workspace):
        """未知语言返回纯文本摘要。"""
        from mini_note.ingest.extraction import extract_code

        rs = tmp_workspace / "main.rs"
        rs.write_text("fn main() {\n    println!(\"hello\");\n}\n")
        result = extract_code(rs)
        assert result.status in ("full", "metadata_only")


# ============================================================
# 音视频解析
# ============================================================

class TestMediaExtraction:
    """测试音视频文件元数据提取。"""

    def test_extract_mp3_metadata(self, sample_mp3_file):
        """MP3 文件提取元数据不崩溃。"""
        from mini_note.ingest.extraction import extract_media

        result = extract_media(sample_mp3_file)
        assert result.status in ("metadata_only", "full")
        assert result.extractor in ("ffprobe", "mutagen", "file-info")

    def test_extract_media_unknown_format(self, tmp_workspace):
        """未知格式返回 metadata_only。"""
        from mini_note.ingest.extraction import extract_media

        fake = tmp_workspace / "unknown.xyz"
        fake.write_bytes(b"\x00" * 100)
        result = extract_media(fake)
        assert result.status in ("metadata_only", "failed")


# ============================================================
# 解析失败处理
# ============================================================

class TestExtractionFailure:
    """测试解析失败时的行为。"""

    def test_nonexistent_file_raises(self, tmp_workspace):
        """不存在的文件抛出异常。"""
        from mini_note.ingest.extraction import extract_by_type

        with pytest.raises(FileNotFoundError):
            extract_by_type(tmp_workspace / "nonexistent.pdf")

    def test_extraction_result_includes_extractor_version(self, sample_md_file):
        """ExtractionResult 包含 extractor 版本信息。"""
        from mini_note.ingest.extraction import extract_markdown

        result = extract_markdown(sample_md_file)
        assert result.extractor is not None
        assert result.extractor_version is not None
        assert result.created_at is not None
