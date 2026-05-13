# Changelog

## v0.1.0 (2026-05-13)

首次发布。MiniNote 已具备个人知识库的基本工作流：资料摄入、Wiki 生成、检索、检查、备份和恢复验证。

### 可靠性
- 标准 workspace 目录结构（`meta/`、`raw/`、`wiki/`、`.state/`）
- 一键安装脚本 `install.sh` + CLI 包装器 `run.sh` + 验证脚本 `verify.sh`
- OSS 快照备份（阿里云 OSS，支持 AES-256-GCM 客户端加密）
- 快照恢复演练（本地/OSS 双路径）
- operation manifest 记录摄入过程和恢复所需信息
- 备份日志（`.state/backup_log.jsonl`）

### 多格式摄入
- Markdown / 纯文本
- PDF（pdfplumber 文本提取，扫描版可回退为元数据记录）
- DOCX（Word 段落与表格提取）
- XLSX（Excel 工作表 → Markdown 表格转换）
- PPTX（PowerPoint 幻灯片文本与表格提取）
- 图片（PNG/JPG 元数据提取，Pillow）
- 代码（Python AST 结构化提取，其他语言使用正则提取结构摘要）
- 音视频（mutagen 元数据标签提取）
- 批量摄入（`--scan-inbox` 扫描 inbox 目录）
- 目录批量导入（`import.sh` 一键导入已有目录）

### 知识检索
- SQLite FTS5 全文检索 + 中文 bigram 分词
- 查询引擎（页面 + claim 双路径检索，rank 排序）
- FTS 未建立时自动回退到关键词扫描

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
- 目录批量导入脚本（`import.sh`）

### OpenClaw Skill
- `mini-note.skill.md` — OpenClaw/WorkBuddy Skill 定义文件
- 自然语言触发：记笔记、查笔记、健康检查、审核、备份
- 覆盖摄入、检查、审核、查询和定期维护等常见操作
- 根据 Skill 配置调用 CLI，解析 JSON 结果并生成回复
