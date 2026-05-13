# Changelog

## v0.1.0 (2026-05-13)

首次发布，核心功能完整可用。

### 可靠性地基
- 标准 workspace 目录结构（`meta/`、`raw/`、`wiki/`、`.state/`）
- 一键安装脚本 `install.sh` + CLI 包装器 `run.sh` + 验证脚本 `verify.sh`
- OSS 云端增量快照备份（阿里云 OSS + AES-256-GCM 客户端加密）
- 快照恢复演练（本地/OSS 双路径）
- operation manifest 状态机（planned → staged → applied → indexed → backed_up）
- 备份日志（`.state/backup_log.jsonl`）

### 多格式摄入
- Markdown / 纯文本
- PDF（pdfplumber 文本提取，支持扫描版 fallback）
- DOCX（Word 段落与表格提取）
- XLSX（Excel 工作表 → Markdown 表格转换）
- PPTX（PowerPoint 幻灯片文本与表格提取）
- 图片（PNG/JPG 元数据提取，Pillow）
- 代码（Python AST 结构化提取，通用语言 regex fallback）
- 音视频（mutagen 元数据标签提取）
- 批量摄入（`--scan-inbox` 扫描 inbox 目录）

### 知识检索
- SQLite FTS5 全文检索 + 中文 bigram 分词
- 查询引擎（页面 + claim 双路径检索，rank 排序）
- FTS 未建立时自动 fallback 到关键词扫描

### Lint 检查
- wikilink 断链检测
- 孤立页面检测
- claim 来源验证（grounding）
- 数值矛盾检测
- partial 摄入误用告警

### 审核系统
- review task 创建与持久化（YAML）
- 白名单动作（`mark_old_claim_deprecated` / `mark_new_claim_rejected` / `keep_both_as_conflict`）
- 任务列表、状态过滤

### CLI
- 11 个子命令：`init`、`health`、`lint`、`ingest`、`query`、`index`、`backup`、`restore`、`review`
- 统一 JSON 输出（`--json`）
- 标准错误格式（`ok`/`error_code`/`message`/`operation_id`/`retryable`）

### 测试
- 233 个测试用例（单元 + 集成）
- OSS 云端测试自动 skip（无凭证时）
- pytest fixtures 隔离，临时 workspace 独立运行
