# Changelog

## v0.2.2 (2026-05-15)

三轮 Code Review 修复 — relevance 语义修正、摄入失败分支闭环、claim/lint 质量提升。

### 相关度归一化
- FTS5 BM25 relevance 从 sigmoid `1/(1+|rank|)` 改为当次查询 min-max 批量归一化（修复 rank 负值与绝对值方向相反问题）
- `_apply_bm25_relevance()`：`1.0 - (rank - best) / (worst - best)`，best=1.0，worst=0.0
- 关键词回退使用 `score/(score+5)` 归一化
- 查询结果同时返回 `rank`（原始）和 `relevance`（归一化 [0,1]）

### 摄入失败分支闭环
- 索引重建失败返回 `ok: false` + `INDEX_REBUILD_FAILED`，不执行 cleanup
- 健康检查失败返回 `ok: false` + `HEALTH_CHECK_FAILED`，不执行 cleanup
- 两失败返回均显式包含 `cleaned_count: 0`
- 批次 finalization 阶段以 `_acquire_lock`/`_release_lock` 保护（rebuild + health + cleanup）

### cleanup 语义修正
- 仅移动 `r.ok` 且 `dedup_status != "queued_large_file"` 的成功文件
- inbox 扫描排除条件收窄为 `rel_parts[0] == "processed"`，仅跳过根 `raw/inbox/processed/`
- symlink 等失败文件保留在 inbox，不被 cleanup 误移

### dedup 统计修正
- `dedup_summary` 新增 `failed` 计数键
- `r.ok` 才按 `dedup_status` 归类（new/existing/queued_large_file），`not r.ok` 归入 `failed`

### claim 提取增强
- 三层启发式策略：数字事实句（≥15字）→ bullet/编号列表项（8-300字）→ 会议关键词句（≥15字）
- 同源文本去重（`seen_texts` 集合）
- `quote_hash` 写入 `sha256:` + hexdigest；`verified_at` 初始化为空字符串

### lint 分级降噪
- 5 项检查统一返回 `severity`/`category`/`confidence`
- contradictions 从 error 降为 warning（confidence 0.5，启发式推断）
- broken_wikilinks / claim_grounding / partial_misuse：warning，confidence 1.0
- orphan_pages：info，confidence 1.0
- 新增 `--min-severity` 过滤（error/warning/info），默认 warning
- 返回 `lint_summary`（total_before_filter / total_after_filter / suppressed_count）

### 进度追踪优化
- 时间间隔 60s → 30s
- 里程碑扩展至 10%/25%/50%/75%/90%（原 25%/75%）
- EMA 自适应 alpha 衰减：`max(0.1, min(0.5, 3.0/(processed+3)))`

### 文档与脚本
- `import.sh` fmt_bytes 使用 `$VENV_PYTHON` 替代裸 `python3`
- `mini-note.skill.md` 错误处理表补 `INDEX_REBUILD_FAILED` / `HEALTH_CHECK_FAILED`
- `README.md` 同步 `--cleanup`、`--min-severity`、relevance 字段说明

### 测试
- 新增 `tests/unit/test_pipeline.py`（6 个 claim 构建用例 + 2 个 lint summary 用例）
- 新增 `tests/unit/test_cli.py::TestScanInboxFailureBranches`（4 个失败分支用例）
- `tests/unit/test_query_engine.py` 补 `TestRelevanceNormalization`（4 个用例）
- 全量：358 passed, 10 skipped

## v0.2.1 (2026-05-14)

批量导入磁盘空间预检 + PID 锁文件过期自动清理。

### 磁盘空间预检
- 新增 `check_import_disk_space()` — 导入前评估文件总大小与可用空间，预估需求 = 原始 × 2.0，保留 100MB 安全余量
- 新增 `ingest precheck-disk` CLI 子命令（`--dir` / `--files`），返回结构化 JSON 含 `would_fit`
- `--scan-inbox` 批量摄入前自动运行预检，空间不足返回 `DISK_SPACE_LOW` 错误码，`--force` 可跳过
- `import.sh` 外部源导入使用 ×3.0 估算（含 inbox 副本），预检失败 fail-closed，`--force` 传递到 CLI

### PID 锁文件过期清理
- 锁文件格式从纯文本升级为 JSON（`pid` + `timestamp`），通过 `os.kill(pid, 0)` 判断持有进程是否存活
- 进程存活 → 锁有效；进程死亡 → 自动清理；跨用户 PermissionError / 旧格式 → 回退到 mtime 超时
- 删除-重建竞态窗口添加三重试循环；锁错误消息包含持有者 PID 用于排障
- `maintenance cleanup` 集成过期锁清理，`unlink(missing_ok=True)` 防止并发异常
- `lock_timeout_seconds` 从 `meta/config.yaml` 读取（替代硬编码 300 秒）
- `large_file_queue` 复用 `pipeline._is_lock_stale`，消除双份维护

### 其他
- `check_import_disk_space` 的 `file_count` 仅统计实际存在的文件
- `precheck-disk` 空目录返回值与正常路径 schema 一致（含 `available_bytes`、`safe_margin_bytes`）
- `_is_lock_stale` 处理并发删除（`FileNotFoundError`）和损坏 pid 类型（`isinstance` 校验）

### 测试
- 新增 `tests/unit/test_lock_and_disk.py`（29 个用例），覆盖 PID 存活/死亡/EPERM/ESRCH、锁过期回退、竞态清理、磁盘预检、CLI DISK_SPACE_LOW

## v0.2.0 (2026-05-14)

知识库文件限制收紧 + 大文件独立队列 + 两阶段提交消除并发竞态。

### 文件限制收紧
- 新增 `config.py` — 运行时配置读取模块，`Limits` dataclass 统管所有限制值
- 新默认值：文本 2MB / PDF 40 页 / Office 10MB / 图片 20MB / 音频 10 分钟 / 视频 5 分钟
- `meta/config.yaml` 可覆盖默认值，缺失字段自动合并默认值
- 提取层硬边界：PDF 截断前 N 页、Office/图片超限返回 `metadata_only`、文本流式读取截断
- `SourceRegistry._determine_status()` 覆盖全部文件类型，音视频/未知类型统一返回 `metadata_only`

### 大文件独立队列
- 新增 `large_file_queue.py` — 目录式队列（pending/running/done/failed）+ 独立 worker 锁
- 轻量预检：`_precheck_file()` 用 stat/mutagen/pdfplumber.open 判断是否超限，不执行完整提取
- 超限文件自动分流到 `large_ingest_queue`，不阻塞普通文件摄入
- `ingest-large` CLI 子命令：`enqueue` / `worker` / `status`
- 入队时复制文件到 staging 目录，防止用户在 worker 处理期间移动/删除源文件

### 两阶段提交（消除并发竞态）
- 大文件 worker 重构为两阶段：阶段一在 `large_ingest.lock` 下做重提取（不写共享状态）；阶段二在 `ingest.lock` 下写共享状态
- `large_ingest.lock` 覆盖整个任务生命周期，保证任意时刻最多一个大文件任务处于 running
- 普通 ingest 仅在大文件提交阶段被短暂串行化，不被提取 IO 阻塞
- `IngestPipeline.run()` 新增 `pre_extracted` 参数，支持跳过提取步骤直接使用已有结果

### FTS 优化
- `fts_pages` 虚拟表新增 `scope UNINDEXED` / `type UNINDEXED` / `updated_at UNINDEXED` 列
- `search_pages()` 支持 scope 参数，过滤下推到 SQL 层
- 查询引擎移除磁盘重读循环，委托 FTS 做 scope 过滤

### 其他修复
- OSS 未配置时 backup 消息从"跳过备份"改为诚实提示
- `_acquire_lock` fd 泄漏修复（`os.open` → try/finally `os.close`）
- YAML frontmatter 解析异常不跳过整文件，降级为无元数据
- AST docstring 空首行处理

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
