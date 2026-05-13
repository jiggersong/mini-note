# Notes System V2 — OpenClaw LLM Wiki 智能笔记系统正式设计方案

> 版本: v2.4
> 日期: 2026-05-13
> 状态: 正式设计定稿，已覆盖环境搭建、安装流程、跨平台兼容，可作为实现基线
> 操作主体: OpenClaw Agent
> 目标用户: 个人或 10 人以下小团队

---

## 1. 执行摘要

本方案把笔记系统从“Markdown 文件 + JSON 缓存索引”升级为“OpenClaw 操作的 LLM Wiki 知识编译系统”。

系统不以传统 RAG 为中心，也不把向量数据库作为第一阶段核心。核心设计是：原始资料只追加不修改，OpenClaw 驱动大模型把资料增量编译成结构化 Markdown Wiki，并持续维护 `index.md`、`overview.md`、`log.md`、实体页、概念页、来源页和综合页。

v2 的核心取舍：

- 数据安全优先于检索性能。
- OSS 快照优先于 Git 备份。
- SQLite 只是派生索引，不是事实源。
- LLM 不能直接写正式 Wiki，必须先生成变更计划并通过校验。
- 关键事实必须绑定 claim 级证据，避免长期幻觉漂移。
- 高风险变更由 OpenClaw 向用户确认，不要求用户直接操作系统文件。

---

## 2. 已确认决策

| 决策 | 结论 |
|---|---|
| 操作方式 | 系统主要由 OpenClaw 操作，不建设人工 UI |
| 审核方式 | OpenClaw 可以在需要时向用户确认 |
| 多用户隔离 | 不做强保密隔离，只通过 owner/scope 避免管理混用 |
| 备份方式 | 优先 OSS 快照，Git 不作为知识库数据备份核心 |
| OSS 使用 | 复用 OpenClaw 已有 OSS bucket；快照必须客户端加密 |
| 旧数据迁移 | 不迁移旧版 `notes-manager`，按新项目设计 |
| 模型能力 | 可使用 OpenClaw 配置的 DeepSeekV4 pro 和 Qwen 3.5-plus |
| 部署资源 | 参考阿里云个人 ECS，2C4G 到 4C8G，无 GPU |
| 默认协作模型 | 不要求具体团队定义；多人场景通过 `owner_id` 区分操作者，默认共享空间为 `shared` |
| MVP 文件上限 | 默认采用 `PDF <= 100 页`、`Office <= 20MB`、`文本 <= 2MB`，后续保留配置化能力 |
| OpenClaw 接口形态 | 采用 A 方案 — Skill 编排 + 本地 CLI，OpenClaw 负责模型调用与决策，mini-note CLI 负责确定性状态变更与校验 |

---

## 3. 目标与非目标

### 3.1 目标

1. 支持个人和小团队把常见办公资料编译成结构化 Wiki。
2. 支持 OpenClaw 通过 CLI 或后续 MCP 工具执行摄入、查询、Lint、备份、恢复验证。
3. 长期运行后仍能追溯事实来源，降低幻觉累积导致的认知漂移。
4. 系统故障后可根据 operation manifest、Markdown、raw、OSS 快照恢复。
5. 即使 LLM 或 SQLite 不可用，Wiki Markdown 与 raw 资料仍可读。

### 3.2 非目标

1. 不做 Web UI、桌面 UI、图谱可视化。
2. 不做企业级 RBAC、OAuth、多租户隔离。
3. MVP 不引入 LanceDB、向量数据库、复杂图算法。
4. MVP 不解析大型音视频全文，只保存元数据和简短描述。
5. 不把 Git 当作知识库数据备份系统。

---

## 4. 核心原则

### 4.1 权威数据分层

权威性从高到低：

1. `raw/archive/`：原始资料，事实源，不可变。
2. `raw/extracted/`：解析后的文本、图片描述、元数据，可由 raw 重建。
3. `wiki/`：LLM 编译后的 Markdown 知识，可重建但应长期维护。
4. `.state/notes.db`：SQLite 派生索引，可删除重建。
5. OSS snapshots：容灾副本，不参与日常查询。

### 4.2 LLM 写入约束

LLM 只能输出结构化分析和变更计划，不能直接修改正式 Wiki。

写入必须经过：

1. JSON schema 校验。
2. 路径白名单校验。
3. claim 来源校验。
4. wikilink 校验。
5. staging 写入。
6. health check。
7. OSS 备份记录。

### 4.3 证据优先

关键事实、数字、定义、决策、结论必须绑定 claim。没有证据的内容只能写成假设、观察、待验证或问题，不能写成确定事实。

---

## 5. 总体架构

```text
OpenClaw Agent
  |
  |-- CLI / future MCP tools
  |
  v
mini-note runtime
  |
  |-- Ingest Engine
  |-- Query Engine
  |-- Lint Engine
  |-- Backup Engine
  |-- Review Engine
  |
  v
Workspace
  |
  |-- raw/       原始资料和解析结果
  |-- wiki/      LLM 编译后的 Markdown Wiki
  |-- meta/      规则、目的、身份、配置
  |-- .state/    SQLite、任务、manifest、审核、健康报告
```

### 5.1 模块职责

| 模块 | 职责 |
|---|---|
| Ingest Engine | 文件登记、解析、claim 提取、接收 LLM 分析结果、生成变更计划、应用变更 |
| Query Engine | 读取 index/overview、定位 Wiki 页面、组装证据与引用素材，返回结构化结果供 Skill 合成回答 |
| Lint Engine | 检查 claim grounding、冲突、断链、孤立页、部分摄入误用 |
| Backup Engine | 生成 OSS 快照、记录校验值、执行恢复演练 |
| Review Engine | 生成 OpenClaw 可处理的审核任务，执行白名单审核动作 |
| Indexer | 从 Markdown、claim、manifest 重建 SQLite 派生索引 |

---

## 6. 目录结构

```text
mini-note/
├── meta/
│   ├── purpose.md
│   ├── schema.md
│   ├── config.yaml
│   └── identities.yaml
├── raw/
│   ├── inbox/
│   │   ├── users/
│   │   └── teams/
│   ├── archive/
│   │   └── src-YYYYMMDD-HHMMSS-xxxx/
│   │       ├── original.ext
│   │       ├── source.yaml
│   │       └── attachments/
│   └── extracted/
│       └── src-YYYYMMDD-HHMMSS-xxxx/
│           ├── content.md
│           ├── claims.yaml
│           └── extraction.yaml
├── wiki/
│   ├── index.md
│   ├── overview.md
│   ├── log.md
│   ├── entities/
│   ├── concepts/
│   ├── sources/
│   ├── synthesis/
│   └── queries/
└── .state/
    ├── notes.db
    ├── operations/
    ├── review_tasks/
    ├── health/
    ├── staging/
    └── backup_log.jsonl
```

### 6.1 路径规则

- 新目录和系统文件名必须使用英文。
- 用户上传的原始文件可保留原文件名，但归档目录必须使用 `source_id`。
- Wiki 页面文件名使用 slug，避免空格和特殊符号。
- `.state/` 是系统内部目录，OpenClaw 可读写，用户不直接编辑。

---

## 7. 数据模型

### 7.1 Source

`raw/archive/{source_id}/source.yaml`：

```yaml
source_id: src-20260513-120000-a1b2
original_name: "ecs-guide.pdf"
stored_path: "raw/archive/src-20260513-120000-a1b2/original.pdf"
sha256: "..."
owner_id: "user-jigger"
scope: "shared"
media_type: "application/pdf"
size_bytes: 1234567
ingestion_status: "full"
created_at: "2026-05-13T12:00:00+08:00"
```

`ingestion_status` 取值：

- `full`：已完整解析。
- `partial`：只解析部分内容。
- `metadata_only`：只记录元数据和简短描述。
- `failed`：解析失败，保留失败原因。

### 7.2 Extraction

`raw/extracted/{source_id}/extraction.yaml`：

```yaml
source_id: src-20260513-120000-a1b2
extractor: "pdfplumber"
extractor_version: "0.11.x"
status: "full"
coverage:
  pages_total: 42
  pages_processed: [1, 2, 3, 4, 5]
  reason: null
warnings: []
created_at: "2026-05-13T12:01:00+08:00"
```

### 7.3 Claim

`raw/extracted/{source_id}/claims.yaml`：

```yaml
claims:
  - claim_id: claim-20260513-120100-0001
    source_id: src-20260513-120000-a1b2
    text: "ECS 突发性能实例适合低负载且偶发突增的场景。"
    locator: "page=6 paragraph=3"
    quote_hash: "sha256:..."
    extraction_method: "pdf_text"
    confidence: 0.88
    status: "active"
    verified_at: "2026-05-13T12:01:00+08:00"
```

Claim 状态：

- `active`：当前有效。
- `conflicted`：存在冲突，等待审核或保留冲突。
- `deprecated`：已被更新来源取代。
- `unverified`：模型推断或来源不足，不可作为强事实。

### 7.4 Wiki Page Frontmatter

```yaml
---
page_id: page-20260513-ecs-performance
title: "ECS 性能优化"
type: "concept"
scope: "shared"
owner_id: "user-jigger"
status: "published"
source_ids:
  - src-20260513-120000-a1b2
claim_ids:
  - claim-20260513-120100-0001
created_at: "2026-05-13T12:10:00+08:00"
updated_at: "2026-05-13T12:20:00+08:00"
---
```

### 7.5 Operation Manifest

`.state/operations/{operation_id}.yaml`：

```yaml
operation_id: op-20260513-120000-a1b2
type: "ingest"
status: "backed_up"
source_ids:
  - src-20260513-120000-a1b2
planned_changes:
  - action: "create_page"
    path: "wiki/sources/src-20260513-120000-a1b2.md"
  - action: "update_page"
    path: "wiki/index.md"
validation:
  frontmatter_valid: true
  wikilinks_valid: true
  claims_have_sources: true
backup:
  oss_object: "snapshots/incremental/2026/05/13/op-20260513-120000-a1b2.tar.zst.enc"
  sha256: "..."
created_at: "2026-05-13T12:00:00+08:00"
updated_at: "2026-05-13T12:15:00+08:00"
```

Operation 状态：

- `planned`
- `staged`
- `applied`
- `indexed`
- `backed_up`
- `failed`

---

## 8. SQLite 派生索引

SQLite 不保存唯一事实，只保存可重建索引和任务状态。

### 8.1 MVP 表

| 表 | 用途 |
|---|---|
| `sources` | 原始资料登记、hash、owner、scope、摄入状态 |
| `pages` | Wiki 页面路径、标题、类型、更新时间 |
| `claims` | claim 文本、locator、状态、验证时间 |
| `links` | `[[wikilink]]` 解析结果 |
| `jobs` | ingest/lint/backup 任务状态 |
| `review_tasks` | OpenClaw 可处理的审核项 |
| `backups` | OSS 对象、校验值、恢复演练结果 |

### 8.2 搜索策略

MVP 不实现自定义 FTS tokenizer。

第一阶段搜索输入：

- 页面标题。
- 页面摘要。
- tags。
- `search_terms`。
- claim 文本。

中文增强方式：

- 写入时生成 `search_terms`。
- 简单 CJK bigram 可作为补充字段。
- FTS5 可选使用默认 tokenizer，但不把它作为正确性的前提。

向量搜索放到 Phase 4，根据真实查询失败案例再决定是否引入。

---

## 9. Ingest 流程

### 9.1 主流程

```text
1. Acquire lock                          [CLI]
2. Register source                       [CLI]
3. Extract content                       [CLI]
4. Build evidence map                    [CLI]
5. Skill calls LLM to analyze            [Skill → LLM]
6. Skill generates change plan (JSON)    [Skill → LLM]
7. CLI validates change plan             [CLI]
8. CLI applies staged changes            [CLI]
9. Rebuild derived index                 [CLI]
10. Health check                         [CLI]
11. OSS backup                           [CLI]
12. Emit review tasks                    [CLI]
```

### 9.2 步骤说明

| 步骤 | 行为 | 失败处理 |
|---|---|---|
| Acquire lock | 创建单写锁 | 已有锁且未超时则拒绝写入 |
| Register source | 计算 SHA256，生成 `source_id` | 重复 hash 跳过编译或追加引用 |
| Extract content | 解析文本、图片描述、元数据 | 标记 `failed` 或 `metadata_only` |
| Build evidence map | 生成关键 claim | 无 claim 时只建 source page |
| Skill calls LLM to analyze | OpenClaw Skill 组装 prompt（purpose/schema/index/overview/extracted），调用模型分析 | 失败后 job pending，Skill 稍后重试 |
| Skill generates change plan | Skill 驱动 LLM 输出 JSON 变更计划，传回 CLI | JSON schema 校验失败则 Skill 重试一次 |
| CLI validates change plan | CLI 校验路径白名单、claim 引用、frontmatter、wikilink | 失败则不写入正式 Wiki，返回错误给 Skill |
| Apply staged changes | staging 写入后 rename | manifest 支持恢复 |
| Rebuild derived index | 从文件重建 SQLite | SQLite 损坏则删除重建 |
| Health check | 检查 Wiki 健康 | 严重失败则生成 review task |
| OSS backup | 上传增量快照 | 不回滚 Wiki，标记 backup pending |
| Emit review tasks | 生成审核任务 | OpenClaw 后续处理 |

### 9.3 成功标准

| 标准 | 验证方式 |
|---|---|
| 重复摄入不会重复编译 | 同一 SHA256 返回 existing source |
| 每个 source 都有状态 | `source.yaml` 和 SQLite `sources` 一致 |
| 关键事实有证据 | claim 必须包含 `source_id`、`locator`、`quote_hash` |
| Wiki 写入可恢复 | operation manifest 可解释当前状态 |
| SQLite 可重建 | 删除 `notes.db` 后 rebuild 结果一致 |
| 备份可用 | OSS 上存在 snapshot 且 hash 匹配 |

---

## 10. 文件类型策略

| 类型 | MVP 行为 | 风险控制 |
|---|---|---|
| `.md` / `.txt` | 直接读取 | 超限标记 partial |
| `.docx` | 提取段落、标题、表格文本 | 保留解析 warning |
| `.pdf` | 提取文本 | 扫描版标记 metadata_only 或 pending OCR |
| `.xlsx` / `.xls` | Phase 3 支持 | MVP 可只记录元数据 |
| `.pptx` | Phase 3 支持 | MVP 可只记录元数据 |
| 图片 | Phase 3 调用多模态描述 | 视觉描述标记为模型生成 |
| 小音视频 | MVP 记录 ffprobe 元数据 | 不做强事实 claim |
| 大音视频 | 只记录元数据和用户描述 | 不解析全文 |
| 代码文件 | Phase 3 生成结构摘要 | 不执行代码 |
| 配置文件 | 直接读取或结构摘要 | 敏感字段脱敏 |

### 10.1 建议默认上限

| 类型 | 上限 | 超限处理 |
|---|---|---|
| 文本 | 2MB | partial |
| PDF | 100 页 | partial |
| Office | 20MB | metadata_only 或 partial |
| 图片 | 20MB | metadata_only |
| 音频 | 30 分钟 | metadata_only，后置转写 |
| 视频 | 5 分钟 | metadata_only，后置抽帧 |

---

## 11. Query 流程

### 11.1 设计目标

查询不是重新对 raw 做 RAG，而是优先读取已经编译好的 Wiki。

### 11.2 流程

```text
[CLI]
1. Resolve scope
2. Read wiki/index.md and wiki/overview.md
3. Search pages and claims from SQLite
4. Expand by wikilink
5. Load selected Wiki pages
6. Load supporting claims
7. Return structured context (JSON) to Skill

[Skill → LLM]
8. Skill assembles prompt with context + question
9. LLM generates answer with citations
10. Optionally save answer to wiki/queries/ (via CLI)
```

CLI 的 `query` 命令只做检索，**不调模型**。它返回包含 Wiki 页面内容、claim 引用、来源标注的结构化 JSON，由 Skill 负责最终的回答合成。

### 11.3 回答规则

- 必须引用 Wiki 页面或 claim。
- 证据不足时必须明确说”当前知识库证据不足”。
- 不能把 partial source 中的内容作为强结论。
- 如果问题触发新综合洞察，可以把回答保存为 query page，再走轻量 ingest。

---

## 12. Lint 与漂移治理

### 12.1 风险模型

长期运行的主要风险不是单次回答错误，而是错误被写入 Wiki 后被后续摄入当成事实，形成认知漂移。

### 12.2 Lint 检查项

| 检查 | 说明 |
|---|---|
| Claim grounding | claim 是否仍能在 extracted 内容中定位 |
| Quote hash drift | claim 对应原文片段 hash 是否一致 |
| Contradiction | 同主题 claim 是否冲突 |
| Stale claim | 时间敏感 claim 是否超过复查周期 |
| Missing claim | 页面关键事实是否缺少 claim 引用 |
| Broken wikilink | `[[wikilink]]` 是否指向不存在页面 |
| Orphan page | 页面是否没有入链和出链 |
| Partial misuse | partial source 是否被用于强事实 |

### 12.3 冲突处理

默认策略：

1. 保留新旧 claim。
2. 标记 `conflicted`。
3. 生成 review task。
4. OpenClaw 向用户确认。
5. 根据白名单动作更新 claim 状态。

允许动作：

- `mark_old_claim_deprecated`
- `mark_new_claim_rejected`
- `keep_both_as_conflict`
- `request_more_sources`

### 12.4 周期任务

| 频率 | 任务 |
|---|---|
| 每次 ingest 后 | changed-area lint |
| 每日 | health check + backup check |
| 每周 | 抽样 claim grounding + OSS 恢复演练 |
| 每月 | 重点页面从 raw 重新编译并对比 |
| 每季度 | 输出漂移报告 |

### 12.5 周期任务触发机制

按 A 方案，定时任务由 OpenClaw 触发。MVP 推荐方式：

**方案：系统 cron + `run.sh` 子命令**

```bash
# 每日 health check（例：每天 03:07）
7 3 * * * cd /path/to/mini-note && ./run.sh health --json >> health.log 2>&1

# 每周 lint（例：周日 04:13）
13 4 * * 0 cd /path/to/mini-note && ./run.sh lint --full --json >> lint.log 2>&1
```

关键原则：

- **定时任务只调 CLI 的只读或诊断命令**（`health`、`lint`、`backup create`、`restore verify`），不动 Wiki。
- 需要 LLM 参与的周期任务（如每月重编译对比、每季漂移报告）由 cron 触发一个轻量 Skill 调用，由 Skill 驱动 LLM 完成。
- `backup create` 和 `restore verify` 由 cron 独立触发，不依赖 Skill。
- 单写锁保护：即使 cron 和 Skill 同时触发 ingest，只有一个能进入写阶段。

此机制在 Phase 0 搭建基础骨架时一并实现并验证。

---

## 13. Review Engine

### 13.1 审核任务格式

`.state/review_tasks/{review_id}.yaml`：

```yaml
review_id: review-20260513-001
severity: high
status: open
reason: "新资料与已有 ECS 计费规则存在冲突"
question_for_user: "是否以 2026-05-12 的阿里云文档为准，替换旧的计费说明？"
recommended_action: "mark_old_claim_deprecated"
allowed_actions:
  - mark_old_claim_deprecated
  - keep_both_as_conflict
  - mark_new_claim_rejected
related_claims:
  - claim-old-001
  - claim-new-002
created_at: "2026-05-13T12:30:00+08:00"
```

### 13.2 OpenClaw 行为

OpenClaw 可执行：

```bash
./run.sh review list --json
./run.sh review show REVIEW_ID --json
./run.sh review answer REVIEW_ID --action ACTION --comment "..."
```

系统只接受 `allowed_actions` 中的动作。

---

## 14. 备份与恢复

### 14.1 OSS 快照结构

```text
snapshots/
├── incremental/YYYY/MM/DD/op-xxx.tar.zst.enc
├── daily/YYYY/MM/DD/full.tar.zst.enc
├── weekly/YYYY-WW/full.tar.zst.enc
└── restore-tests/YYYY/MM/DD/report.json
```

快照对象必须客户端加密后再上传 OSS。OSS bucket 复用 OpenClaw 现有配置；系统只新增独立前缀，不创建新 bucket。

### 14.2 备份内容

快照应包含：

- `meta/`
- `raw/`
- `wiki/`
- `.state/operations/`
- `.state/review_tasks/`
- `.state/backup_log.jsonl`
- `.state/notes.db`，作为恢复加速文件。

SQLite 损坏时以 Markdown、raw、manifest 为准重建。

### 14.3 保留策略

默认建议：

- 增量快照保留 14 天。
- 每日全量保留 30 天。
- 每周全量保留 12 周。
- 每月全量保留 12 个月。

如果 OSS 成本敏感，MVP 可改为：

- 每次 ingest 增量快照。
- 每周全量快照。
- 每周恢复演练。

### 14.4 恢复演练

恢复演练流程：

1. 下载最新快照到临时目录。
2. 解压。
3. 删除 SQLite。
4. 从文件重建 SQLite。
5. 运行 health check。
6. 写入 restore report。
7. 上传 report 到 OSS。

---

## 15. OpenClaw 集成接口

### 15.1 CLI

```bash
# 确定性操作（CLI 独立完成，不调 LLM）
./run.sh init --workspace PATH
./run.sh health --json
./run.sh lint --changed-only
./run.sh lint --full
./run.sh backup create --reason ingest
./run.sh restore verify --snapshot OSS_OBJECT
./run.sh index rebuild

# Skill 协作操作（CLI 做确定性部分，Skill 调 LLM 做推理部分）
./run.sh ingest --file PATH --owner USER_ID --scope shared
./run.sh ingest --scan-inbox --owner USER_ID --scope shared
./run.sh query --question "..." --owner USER_ID --scope shared   # 只检索，不调模型
./run.sh review list --json
./run.sh review answer REVIEW_ID --action ACTION --comment "..."
```

**关键约定：**

- `query` 命令只检索 Wiki 页面和 claim，返回结构化 JSON 素材；回答合成由 Skill 调用 LLM 完成。
- `ingest` 命令的确定部分（文件登记、解析、校验、写入、索引、备份）由 CLI 完成；LLM 分析和变更计划生成由 Skill 完成。
- 所有命令支持 `--json`。

### 15.2 OpenClaw 接口形态 — 已确认

OpenClaw 与 mini-note runtime 的分工已确认：**采用方案 A — Skill 编排 + 本地 CLI**。

| 方案 | 说明 | 优点 | 风险 | 结论 |
|---|---|---|---|---|
| A. Skill 编排 + 本地 CLI | OpenClaw Skill 负责调用模型和组织流程，`run.sh` 只做确定性文件、索引、校验、备份操作 | 最简单，复用 OpenClaw 已配置模型，不重复管理 API key | 定时任务必须由 OpenClaw 触发 | **MVP 采用** |
| B. MCP 工具服务 | mini-note 提供 MCP tools，OpenClaw 通过工具调用 ingest/query/lint/backup | Agent 集成最自然，后续可扩展 | 需要维护本地服务和工具协议 | Phase 2 后评估 |
| C. 本地 HTTP 服务 | mini-note 常驻 daemon，OpenClaw 调 HTTP API | 适合多客户端和后台任务 | 引入服务生命周期、鉴权和端口管理 | 不采用 |
| D. 独立 CLI 直接调模型 API | mini-note 自己读取模型 API key 并直接调用 DeepSeek/Qwen | 脱离 OpenClaw 也能运行 | 重复 OpenClaw 模型配置，密钥面扩大 | 不采用 |

**分工边界：** OpenClaw 负责”大模型思考和决策”，mini-note CLI 负责”确定性状态变更和校验”。后续如果 OpenClaw 更适合通过工具协议集成，可在 Phase 2 后评估升级到 B。

### 15.3 输出要求

所有命令必须支持 `--json`。

错误输出必须包含：

```json
{
  "ok": false,
  "error_code": "BACKUP_PENDING",
  "message": "OSS backup failed and can be retried.",
  "operation_id": "op-20260513-120000-a1b2",
  "retryable": true
}
```

### 15.4 日志要求

- 使用标准 logging。
- 不使用 `print()` 输出日志。
- CLI 的业务结果写 stdout。
- 日志写 stderr 或日志文件。
- API key、OSS secret、用户敏感字段必须脱敏。

---

## 16. 技术选型

| 组件 | 选型 | 理由 |
|---|---|---|
| 语言 | Python 3.10+ | 与现有 skill 生态接近，部署简单 |
| 数据库 | SQLite | 嵌入式、可重建、零运维 |
| 配置 | YAML + `.env` | 可读，密钥不入库 |
| Markdown | frontmatter + Markdown | Obsidian 兼容，退化可读 |
| PDF | pdfplumber | MVP 足够，扫描版后置 OCR |
| DOCX | python-docx | 提取文本、标题、表格 |
| XLSX | openpyxl | Phase 3 支持 |
| PPTX | python-pptx | Phase 3 支持 |
| 图片 | OpenClaw 多模态模型 | Phase 3 支持 |
| OSS | 阿里云 OSS SDK | 备份核心 |
| 压缩 | tar + zstd 或 gzip | zstd 优先，环境不支持则 gzip |

### 16.1 依赖策略

只引入主流、维护活跃、用途明确的依赖。非常规依赖必须单独说明风险并获得确认。

MVP 依赖建议：

```text
pyyaml
python-dotenv
python-docx
pdfplumber
oss2
```

Phase 3 再加入：

```text
openpyxl
python-pptx
```

### 16.2 环境搭建与首次安装

开源项目应做到一条命令完成环境初始化。

**前置条件：**

| 条件 | 要求 | 检测方式 |
|---|---|---|
| Python | >= 3.10 | `python3 -c "import sys; assert sys.version_info >= (3,10)"` |
| pip | 任意 | 随 Python 附带，无需单独安装 |
| 操作系统 | macOS / Linux | 不对 Windows 做原生兼容；Windows 用户建议 WSL |

**`install.sh` 脚本职责：**

```bash
#!/bin/bash
set -e

# 1. 检测 Python 版本
python3 -c "import sys; v=sys.version_info; sys.exit(0 if v>=(3,10) else 1)" || {
    echo "❌ 需要 Python >= 3.10，当前: $(python3 --version)"
    exit 1
}

# 2. 创建虚拟环境
if [ ! -d venv ]; then
    python3 -m venv venv
fi
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 生成配置模板
[ ! -f .env ] && cp .env.example .env && echo "⚠ 请编辑 .env 填写 OSS 凭证"
[ ! -f meta/config.yaml ] && cp meta/config.example.yaml meta/config.yaml

# 5. 初始化 workspace
./run.sh init --workspace .

echo "✅ mini-note 安装完成"
```

**`requirements.txt` 格式：**

```text
pyyaml>=6.0
python-dotenv>=1.0
python-docx>=1.1
pdfplumber>=0.10
oss2>=2.18
```

**关键设计决策：**

- **venv 而非 conda**：venv 是 Python 标准库，零额外依赖，适合最小化部署。
- **不锁定 patch 版本**：`requirements.txt` 使用 `>=` 下限而不冻结 `==`，降低维护负担；CI 中可额外做 `pip freeze` 快照。
- **zstd 降级策略**：`requirements.txt` 不强制依赖 zstd。CLI 在打包快照时自动检测 `zstd` 命令可用性，不可用则降级为 gzip。`restore verify` 解压时根据文件扩展名选择解码器。
- **跨发行版兼容**：不假设 `python` == `python3`，统一使用 `python3`；不假设 `bash` 路径，使用 `#!/bin/bash`。
- **Windows**：不原生支持。推荐 Windows 用户通过 WSL2 运行，安装流程与 Linux 一致。
- **`config.example.yaml`**：提供完整配置键和默认值注释，用户复制后修改。`.env.example` 列出所有必需和可选环境变量，敏感字段留空。

### 16.3 更新维护

- `git pull` 后执行 `source venv/bin/activate && pip install -r requirements.txt`。
- SQLite schema 变更由 CLI 在 `run.sh init` 时自动检测并迁移，无需用户手工操作。

## 17. 安全与隐私

### 17.1 密钥管理

- OSS 凭证来自 `.env` 或 OpenClaw secret。
- `config.yaml` 只保存非密钥配置。
- 日志必须脱敏。
- 备份日志只保存 OSS object key 和 hash，不保存 secret。

### 17.2 文件安全

- 原始资料归档后不原地修改。
- 写入路径必须限制在 workspace 内。
- 禁止通过输入文件名构造任意路径。
- 代码文件只解析，不执行。

### 17.3 Owner 与 Scope

本系统不提供强保密能力。

`owner_id` 和 `scope` 用于：

- 区分操作者和资料来源。
- 过滤或合并查询。
- 生成管理报告。
- 追踪是谁添加了资料。

默认 `scope` 为 `shared`。如果未来确实需要区分多个团队空间，可以再扩展 `scope` 取值，但 MVP 不要求创建或维护团队定义。

---

## 18. 测试策略

### 18.1 单元测试

| 模块 | 必测项 |
|---|---|
| path utils | 路径穿越、slug、workspace 限制 |
| source registry | SHA256、重复摄入、source_id |
| extraction | 成功、失败、partial、metadata_only |
| claim model | 必填字段、状态流转、quote_hash |
| operation manifest | 状态机、恢复判断 |
| indexer | 删除 SQLite 后重建 |
| backup | 快照 hash、失败重试 |

### 18.2 集成测试

1. 摄入一个 Markdown 文件。
2. 摄入一个 DOCX 文件。
3. 摄入一个 PDF 文件。
4. 模拟 LLM 生成非法路径，必须拒绝。
5. 模拟 backup 失败，operation 保持可恢复。
6. 删除 SQLite，执行 rebuild。
7. 下载快照到临时目录，执行 restore verify。

### 18.3 验收测试

| 场景 | 验收标准 |
|---|---|
| 新资料摄入 | 生成 source page、claim、index、overview、backup |
| 查询 | 回答带 claim 或页面引用 |
| 冲突资料 | 不覆盖旧知识，生成 review task |
| 部分摄入 | 查询中明确提示 partial，不作强结论 |
| SQLite 损坏 | 可删除并重建 |
| OSS 恢复 | 快照可恢复并通过 health check |

---

## 19. 实施路线图

### Phase 0: 可靠性地基

目标：先建立不会丢数据、可恢复的骨架。

| 任务 | 验证 |
|---|---|
| `install.sh` 脚本 | 一条命令完成 venv 创建、依赖安装、配置初始化 |
| `requirements.txt` | 所有依赖可安装，版本兼容 |
| 配置模板 | `.env.example` + `meta/config.example.yaml` 可正常复制并启动系统 |
| 初始化目录结构 | `init` 后目录完整 |
| 定义 schema | source/claim/operation/review 均可校验 |
| 单写锁 | 并发 ingest 只有一个成功进入写阶段 |
| staging 写入 | 校验失败不影响正式 Wiki |
| SQLite schema | 可创建、可迁移、可重建 |
| OSS backup | 可上传和校验快照 |
| 周期任务骨架 | cron 可触发 `health`、`backup create`、`restore verify`，单写锁正常工作 |

### Phase 1: 文本类知识编译 MVP

| 任务 | 验证 |
|---|---|
| 支持 md/txt/pdf/docx | 每种格式有成功和失败测试 |
| claim 提取 | 关键事实有 locator/hash |
| source page | 每个 source 有 Wiki 摘要 |
| index/overview/log | ingest 后自动更新 |
| query | 回答引用 Wiki/claim |
| health check | 能发现断链和缺失 claim |

### Phase 2: Lint 与审核

| 任务 | 验证 |
|---|---|
| claim grounding | claim 找不到来源会报警 |
| conflict detection | 冲突 claim 生成 review task |
| review answer | 只接受 allowed_actions |
| daily health | 输出 JSON 报告 |

### Phase 3: 多格式增强

| 任务 | 验证 |
|---|---|
| xlsx/pptx | 能生成结构摘要 |
| 图片 | 多模态描述带模型证据标记 |
| 音视频 | 元数据记录稳定 |
| 代码文件 | 结构摘要不执行代码 |

### Phase 4: 检索增强

进入条件：真实查询案例证明当前 search_terms + Wiki 导航不够。

候选方案：

| 方案 | 优点 | 风险 |
|---|---|---|
| SQLite FTS5 默认 tokenizer | 简单 | 中文效果一般 |
| 写入时生成 search_terms | 可控 | 依赖 LLM 或分词质量 |
| sqlite-vec | 嵌入式向量 | 增加依赖和模型成本 |
| LanceDB | 向量能力强 | 过重，不适合 MVP |

---

## 20. 运维与资源评估

### 20.1 ECS 资源

| 资源 | 建议 |
|---|---|
| CPU | 2C 可用，4C 更稳 |
| 内存 | 4GB 起步 |
| 磁盘 | 50GB 起步，视 raw 文件增长扩容 |
| GPU | 不需要 |
| 网络 | 需要访问 LLM API 和 OSS |

### 20.2 成本关注点

主要成本不是本地计算，而是：

- LLM token。
- OSS 存储。
- OSS 请求次数。
- 大文件上传下载流量。

控制策略：

- SHA256 去重。
- partial ingestion。
- 增量快照。
- 每周而非每日全量恢复演练。

---

## 21. 决策关闭清单

所有关键决策已确认，无遗留待确认项：

- OSS bucket：复用 OpenClaw 已有 OSS bucket。
- OSS 快照加密：需要客户端加密。
- 默认团队 scope：不要求具体团队定义，默认共享空间为 `shared`，多人通过 `owner_id` 区分。
- MVP 文件上限：采用当前默认值（`PDF <= 100 页`、`Office <= 20MB`、`文本 <= 2MB`），并保留配置化能力。
- OpenClaw 接口形态：采用 A 方案 — Skill 编排 + 本地 CLI，OpenClaw 负责模型调用与决策，mini-note CLI 负责确定性状态变更与校验。

---

## 22. References

- Karpathy LLM Wiki Gist: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
- nashsu/llm_wiki README_CN: https://github.com/nashsu/llm_wiki/blob/main/README_CN.md
- notes-manager SKILL.md: https://raw.githubusercontent.com/jiggersong/skills/main/notes-manager/SKILL.md
- SQLite FTS5 官方文档: https://www.sqlite.org/fts5.html

---

## 23. 版本记录

| 版本 | 日期 | 说明 |
|---|---|---|
| v1.0 | 2026-05-13 | DeepSeek 初稿 |
| v1.1 | 2026-05-13 | Codex Review 与修订建议 |
| v2.0 | 2026-05-13 | 合并用户确认约束后的正式设计草案 |
| v2.1 | 2026-05-13 | 纳入 OSS 客户端加密、复用 OpenClaw OSS、默认 shared scope、MVP 文件上限确认，并补充 OpenClaw 接口形态选项 |
| v2.2 | 2026-05-13 | 确认 OpenClaw 接口形态为 A 方案 (Skill 编排 + 本地 CLI)，关闭所有待确认项 |
| v2.3 | 2026-05-13 | 明确 Skill/CLI 职责边界（ingest/query 流程）、补充周期任务触发机制 (cron + run.sh)、决策表补全 |
| v2.4 | 2026-05-13 | 新增环境搭建与安装章节（install.sh/venv/requirements.txt/配置模板/跨平台/zstd降级），Phase 0 补充安装任务 |
