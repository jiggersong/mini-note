# mini-note

> 给 OpenClaw 用的笔记管理软件，参考 Karpathy LLM Wiki 理念实现，仅为个人使用。

**核心理念：** 原始资料只追加不修改，LLM 驱动增量编译为 Markdown Wiki。每条关键事实绑定原文证据（claim），避免长期幻觉漂移。SQLite 只是派生索引，可随时删除重建；真正的数据资产是 Markdown + raw 文件。

---

## 架构概览

```
OpenClaw Agent (Skill)          ← 大模型思考与决策
       │
       ▼
   run.sh CLI                    ← 确定性状态变更与校验
       │
       ▼
  ┌─────────────────────┐
  │  raw/  原始资料       │  ← 事实源，不可变
  │  wiki/ 编译知识       │  ← LLM 编译后的结构化 Markdown
  │  meta/ 规则与配置     │  ← 目的、schema、身份
  │  .state/ 派生索引     │  ← SQLite、manifest、备份日志
  └─────────────────────┘
```

权威层级：**raw > extracted > wiki > SQLite > OSS 快照**

---

## 快速开始

### 前置要求

- Python >= 3.10
- macOS 或 Linux（Windows 用户建议 WSL2）
- 可选：阿里云 OSS bucket（用于备份）

### 安装

```bash
git clone https://github.com/jiggersong/mini-note.git
cd mini-note
./install.sh
```

`install.sh` 会完成：Python 版本检测 → 创建 venv → 安装依赖 → 生成配置模板 → 初始化 workspace。

安装完成后编辑 `.env` 填写 OSS 凭证（如需备份），编辑 `meta/purpose.md` 描述你的知识库目标。

### 验证安装

```bash
./verify.sh          # 完整验证（CLI 冒烟 + 测试套件）
./verify.sh --quick  # 快速冒烟（仅 CLI 命令，跳过 pytest）
```

`verify.sh` 会检测：Python 版本、核心依赖、所有 CLI 命令、测试套件、OSS 配置状态。

### 使用

```bash
# 摄入单个文件
./run.sh ingest --file doc.xlsx --owner user-default --scope shared

# 扫描 inbox 目录批量摄入
./run.sh ingest --scan-inbox --owner user-default --scope shared

# 查询知识库（只检索素材，回答合成由 OpenClaw Skill 完成）
./run.sh query --question "ECS 性能优化要点？" --scope shared

# 健康检查
./run.sh health --json

# Lint 检查
./run.sh lint --changed-only

# OSS 备份
./run.sh backup create --reason ingest

# 恢复验证
./run.sh restore verify --snapshot OSS_OBJECT
```

---

## CLI 命令速览

| 命令 | 说明 |
|------|------|
| `init --workspace PATH` | 初始化知识库目录 |
| `ingest --file PATH` | 摄入文件，生成 Wiki 页面和 claim |
| `ingest --scan-inbox` | 批量摄入 inbox 目录 |
| `query --question "..."` | 检索 Wiki 页面和 claim 素材 |
| `health --json` | 健康检查报告 |
| `lint --changed-only` | 增量 Lint 检查 |
| `lint --full` | 全量 Lint 检查 |
| `backup create --reason ...` | 创建 OSS 增量快照 |
| `restore verify --snapshot ...` | 恢复演练 |
| `review list --json` | 列出待审核任务 |
| `review answer --id ID --action ...` | 执行审核动作 |
| `index rebuild` | 从文件重建 SQLite 索引 |

---

## 目录结构

```
mini-note/
├── meta/                     # 规则、目的、身份、配置
│   ├── purpose.md            # 知识库目标描述
│   ├── schema.md             # 数据结构定义（自动生成）
│   ├── config.yaml           # 非密钥配置
│   └── identities.yaml       # 用户与团队身份
├── raw/                      # 原始资料与解析结果
│   ├── inbox/                # 待处理文件
│   │   ├── users/
│   │   └── teams/
│   ├── archive/              # 已归档原始文件（不可变）
│   └── extracted/            # 解析后的文本和 claim
├── wiki/                     # LLM 编译的 Markdown Wiki
│   ├── index.md              # 全局导航索引
│   ├── overview.md           # 知识库概览
│   ├── log.md                # 变更日志
│   ├── entities/             # 实体页
│   ├── concepts/             # 概念页
│   ├── sources/              # 来源页
│   ├── synthesis/            # 综合页
│   └── queries/              # 已保存的查询结果
├── src/mini_note/            # Python 源码
│   ├── cli.py                # CLI 入口
│   ├── models/               # 数据模型
│   ├── ingest/               # 摄入引擎
│   ├── query/                # 查询引擎
│   ├── lint/                 # Lint 引擎
│   ├── backup/               # 备份引擎
│   ├── review/               # 审核引擎
│   └── indexer/              # 索引重建
├── tests/                    # 测试代码
│   ├── unit/                 # 单元测试
│   └── integration/          # 集成测试
├── .state/                   # 系统内部状态（gitignore）
├── install.sh                # 一键安装脚本
├── run.sh                    # CLI 入口包装器
├── verify.sh                 # 安装验证脚本
├── requirements.txt          # Python 依赖
└── pyproject.toml            # 项目元数据
```

---

## 设计理念

### 证据优先

关键事实、数字、定义、决策、结论必须绑定 **claim**——每条 claim 包含 `source_id`、`locator`（原文定位）、`quote_hash`（原文片段校验值）。没有证据的内容只能写成假设、观察或待验证，不能写成确定事实。

### SQLite 可重建

SQLite 数据库只是派生索引。`rm -rf .state/notes.db` 后可随时从 Markdown 文件和 operation manifest 完整重建。数据资产的真正载体是 `raw/` 和 `wiki/` 目录下的纯文本文件。

### 写入必校验

LLM 不能直接写正式 Wiki。写入必须经过：JSON schema 校验 → 路径白名单校验 → claim 来源校验 → wikilink 校验 → staging 写入 → health check → OSS 备份记录。全流程由 operation manifest 追踪。

### 冲突不静默覆盖

新资料与旧知识冲突时，默认保留新旧 claim 并标记 `conflicted`，生成 review task 交由用户确认。系统只接受白名单动作，不能自行决定覆盖。

---

## 路线图

| Phase | 目标 | 状态 |
|-------|------|------|
| 0 | 可靠性地基：目录结构、schema、单写锁、staging、SQLite、OSS 快照 | ✅ 完成 |
| 1 | 文本类 MVP：md/txt/pdf/docx 摄入、claim 提取、Wiki 编译、查询 | ✅ 完成 |
| 2 | Lint 与审核：claim grounding、冲突检测、review task | ✅ 完成 |
| 3 | 多格式增强：xlsx/pptx/图片/音视频/代码 | ✅ 完成 |
| 4 | 检索增强：FTS5 中文 bigram 全文检索 + rank 排序 | ✅ 完成 |

---

## 测试

```bash
source venv/bin/activate
PYTHONPATH=src python -m pytest tests/ -v
./verify.sh
```

当前测试：233 passed, 10 skipped（OSS 云端测试需配置凭证）

---

## 许可证

MIT License

---

## 参考

- [Karpathy LLM Wiki Gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- [nashsu/llm_wiki](https://github.com/nashsu/llm_wiki)
- [SQLite FTS5 文档](https://www.sqlite.org/fts5.html)
