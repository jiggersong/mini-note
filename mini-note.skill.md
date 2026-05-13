# mini-note Skill

给 OpenClaw 用的笔记管理软件，参考 Karpathy LLM Wiki 理念实现。

## 触发条件

当用户表达以下意图时激活本 skill：

| 意图 | 触发短语示例 |
|------|-------------|
| 记笔记/摄入 | "记下这篇""保存这个文档""摄入""导入""记笔记" |
| 查笔记 | "查一下""之前关于 X 的笔记""搜索知识库""找一下" |
| 健康检查 | "知识库健康吗""检查笔记系统""状态怎么样" |
| 整理检查 | "检查断链""lint 一下""有没有矛盾" |
| 备份 | "备份笔记""创建快照" |
| 审核 | "审核任务""处理冲突""确认这条" |

## 配置

```bash
# 在 .env 或 skill 配置中设置 workspace 路径
MINI_NOTE_WORKSPACE=/path/to/mini-note
```

未设置时默认使用 mini-note 项目根目录。

## 命令映射

以下命令均在 mini-note 项目目录下执行，通过 `./run.sh` 调用。

### 摄入资料

```bash
# 摄入单个文件
./run.sh ingest --file <文件路径> --owner <归属人> --scope shared --json

# 扫描 inbox 批量摄入
./run.sh ingest --scan-inbox --owner <归属人> --scope shared --json

# 批量导入目录
./import.sh <目录路径> --owner <归属人>
```

行为说明：
- 文件会被复制到 `raw/archive/` 并生成 source.yaml
- 提取的文本和 claim 写入 `raw/extracted/`
- LLM 编译的 Wiki 页面写入 `wiki/`
- 返回 `source_id`、`ingestion_status`、`source_page_path`

### 查询知识库

```bash
./run.sh query --question "<问题>" --scope shared --json
```

返回结构：
- `pages[]` — 匹配的 Wiki 页面（含路径、标题、摘要）
- `claims[]` — 匹配的 claim（含原文、来源、定位、置信度）
- `question` — 原始查询

AI 应基于返回的 pages 和 claims 合成自然语言回答，并引用来源。

### 健康检查

```bash
./run.sh health --json
```

返回 checks 列表，每项含 `name`、`passed`、`detail`。全部 passed 则 `ok: true`。

### Lint 检查

```bash
# 增量检查（仅检查变更文件）
./run.sh lint --changed-only --json

# 全量检查
./run.sh lint --full --json
```

返回：
- `broken_wikilinks` — 断链列表
- `orphan_pages` — 孤立页面
- `claim_grounding` — claim 来源缺失
- `contradictions` — 矛盾检测（同源数值冲突）
- `partial_misuse` — partial 摄入的 claim 被当作完整事实

### 审核任务

```bash
# 列出待审核任务
./run.sh review list --json

# 执行审核动作
./run.sh review answer --id <任务ID> --action <动作> --comment "<备注>" --json
```

可用的审核动作：
- `keep_both_as_conflict` — 保留新旧 claim，标记冲突
- `mark_old_claim_deprecated` — 废弃旧 claim
- `mark_new_claim_rejected` — 拒绝新 claim

### 索引重建

```bash
./run.sh index rebuild --json
```

从 Markdown 文件和 YAML 元数据重建 SQLite 索引（含 FTS5 全文检索）。

### 备份与恢复

```bash
# 创建备份（本地 + OSS）
./run.sh backup create --reason "<原因>" --json

# 恢复验证
./run.sh restore verify --snapshot <快照路径或OSS key> --json
```

## 典型工作流

### 工作流 1：摄入 → 检查 → 审核

```
用户：帮我把这份 PDF 记下来

1. [调用 ingest] → 得到 source_id、claims 列表
2. [调用 lint --changed-only] → 检查新产生的断链或矛盾
3. 如有 review task → 告知用户存在冲突，询问如何处理
4. 用户确认 → [调用 review answer] 执行审核
5. 汇报结果
```

### 工作流 2：深度查询

```
用户：ECS 性能优化有哪些要点？

1. [调用 query] → 获取相关 pages 和 claims
2. 根据 claims 的 source_id 追溯原文
3. 用置信度高 + 状态为 active 的 claim 合成回答
4. 标注每条要点的来源（source_id + locator）
```

### 工作流 3：定期维护

```
用户：帮我检查一下笔记系统

1. [调用 health] → 确认目录结构、SQLite、核心文件正常
2. [调用 lint --full] → 全量检查
3. [调用 review list] → 确认无积压审核任务
4. [调用 backup create] → 创建快照
5. 汇总报告
```

## 错误处理

所有命令返回的 JSON 中，`ok: false` 表示失败。检查 `error_code` 判断类型：

| error_code | 含义 | 处理方式 |
|-----------|------|---------|
| `MISSING_FILE` | 未指定文件 | 提示用户提供文件路径 |
| `UNKNOWN_COMMAND` | 命令参数错误 | 检查参数拼写 |
| `SNAPSHOT_NOT_FOUND` | 快照文件不存在 | 确认路径或 OSS key |
| `OSS_NOT_CONFIGURED` | OSS 未配置 | 本地备份正常，云端不可用 |

`retryable: true` 的错误可以重试一次。

## 设计约束

- CLI 只做确定性操作，不做 LLM 调用
- 摄入时的 LLM 编译由 OpenClaw Skill 侧调用模型完成
- SQLite 是派生数据，可随时 `./run.sh index rebuild` 重建
- 原始资料在 `raw/archive/` 中不可变，只追加不修改
