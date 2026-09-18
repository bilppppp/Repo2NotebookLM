# Repo2NotebookLM

[中文](README.md) | [English](README.en.md)

**Git repository → structured, versioned Gemini Notebook knowledge base**

把 Git 仓库转换为适合 Gemini Notebook（原 NotebookLM）长期使用的结构化知识库。

> **当前版本**：`v0.4.0`

---

## Why Repo2NotebookLM?

虽然直接在各类 LLM 网页中粘贴代码或上传仓库能完成一次性代码问答，但将其作为**长期演进的工程项目知识库**时面临几大挑战：

- **内容组织分散**：大代码库若缺乏结构化切分，容易造成上下文断裂与检索失效。
- **缺乏架构拓扑感知**：单纯的代码文件缺失模块依赖、目录职责和核心调用关系。
- **无法跟踪版本演进**：代码迭代后，全量重新上传会破坏笔记引用并产生大量重复 Source。
- **手工笔记易受破坏**：自动同步工具容易误删用户在 Notebook 中手动撰写的架构笔记与分析。

Repo2NotebookLM 把 **Git Repo → 结构化 Sources → Gemini Notebook → 增量同步** 长期连接起来：

- **RepoBook**：代码与文档按目录结构化归纳为篇章，每段代码均精确附带 GitHub Commit 永久链接。
- **GraphBook**：静态推断目录架构职责与 import 依赖拓扑，快速定位核心模块与依赖 Hub。
- **ChangeBook**：自动检测版本差异，记录新增、修改与删除文件；零代码变更时绝不重写或重复上传。
- **真正增量同步 (Incremental Sync)**：基于 Source 内容 SHA256，无变化源零上传、零覆盖。
- **所有权安全守护 (Ownership Guard)**：严格受管 ID 白名单机制，绝不误删用户手动创建的私有笔记与文档。
- **多仓库工作区**：支持将多个关联仓库合并注入同一个 Notebook，并生成跨仓导航入口 `WorkspaceIndex.md`。

---

## What's New in v0.4.0

- **自适应 RepoBook 细粒度分片 (Adaptive RepoBook Partitioning)**：彻底根除大型真实代码库中的单体 `src/` 爆炸陷阱。在 v0.3 中，仓库顶级目录被合并为一个单一的 RepoBook 章节；当修改 `src/` 深层某个叶子文件时，整个数兆字节的单体文件必须全量重新上传。v0.4.0 引入自适应分片机制：当目录文件数或体积超出设定阈值时，自动沿子目录树层级向下递归细分，并将当前目录直接代码文件精准收敛为独立的 `<dir>__root` 模块，同时支持叶子超大目录保底顺序切分（`__part01`）与单文件超限独立切分。
- **大型工程变更爆炸半径降低 >80% (Massive Blast Radius Reduction on Large Repos)**：
  在大型开源工程 `honojs/hono`（488 files，~3.5 MB）的标准 mutation benchmark 测试中：
  - **叶子逻辑修改 (M1 Leaf Body)**：远端替换载荷从 v0.3.1 的 **2558 KB (75.2%)** 剧降至 **188 KB (5.5%)**，重传载荷下降 **92.7%**！
  - **核心逻辑修改 (M2 Core Body)**：替换载荷从 **2558 KB (75.2%)** 下降至 **451 KB (13.2%)**，下降 **82.4%**！
  - **Import 拓扑依赖调整 (M3 Topology)**：替换载荷从 **2722 KB** 下降至 **615 KB (18.0%)**，下降 **77.4%**！
  - **新增与删除文件 (M4/M5 Add/Delete)**：替换载荷分别下降 **69.9%** 与 **91.3%**！
- **中小型仓库零碎片化与 100% 向后兼容 (Zero Over-Fragmentation & Backward Compatibility)**：
  - 中型工程如 `encode/httpx`（125 files，~1.0 MB）在默认配置下依然稳定保持 8 个 Sources，不超限绝不产生多余切分。
  - 提供 `--no-adaptive-partition` 显式开关，可随时无缝退回 v0.3 传统顶级目录分组行为。
  - 源码 100% 完整性保障：零代码丢弃、零截断、零语义漂移，逐文件 stable permalink 机制与分阶段安全替换（Staged Replacement）及所有权安全守护（Ownership Guard）完全保持不变。
- **灵活的 CLI 控制阈值**：
  - `--max-group-kb <kb>`：每个 RepoBook 章节最大 KB 阈值（默认 `512` KB，设为 0 禁用按体积切分）。
  - `--max-group-files <n>`：每个 RepoBook 章节最大文件数量阈值（默认 `40` 个文件，设为 0 禁用按数量切分）。
  - `--no-adaptive-partition`：禁用自适应拆分，严格使用传统顶级目录归类。
- **客观工程定位**：
  在系统性跨 Source 推理基准测试中已证实：拆分 Source **完全不影响** Gemini Notebook 的跨文件跨源代码理解与架构推理能力。v0.4.0 专注于解决大型仓库在增量更新时的单体巨型文件替换风暴与网络抖动。

---

## What's New in v0.3

- **大幅降低元数据驱动的源抖动 (Reduce Metadata-Induced Source Churn)**：普通单文件代码修改（body-only change）不再因为全局 HEAD Commit SHA 变化导致无关 Sources 被全量重传。在真实 Gemini Notebook E2E 测试中，远端变更替换量从 v0.2 的 **5/5 (100%)** 显著下降至 **3/5 (60%)**。
- **逐文件稳定 GitHub 永久链接 (Stable Per-File Permalinks)**：代码段落的 GitHub 永久链接不再全量绑定全局 HEAD，而是精准锚定该文件最后一次产生实质修改的 Commit SHA。未修改文件的 Permalink 永久保持稳定，确保对应的 RepoBook 章节哈希不变（byte-stable），同时严格保证链接所指代码与章节正文的绝对一致。
- **拓扑幂等的 GraphBook 架构图 (Stable GraphBook)**：`GraphBook.md` 不再携带易变的快照 Commit 元数据。当项目模块导入关系、目录职责和代码拓扑结构未发生变化时，`GraphBook.md` 保持逐字节完全一致（byte-identical），消除无意义重传；依赖图变更时仍精准触发更新。
- **v0.2 → v0.3 Manifest 平滑迁移与回填 (v0.2 → v0.3 Migration)**：自动兼容未记录单文件 Commit 的 v0.2 旧版 `manifest.json`。增量更新时自动从 Git 历史中高效回填每个文件的最后修改 Commit 并持久化升级，在浅克隆（shallow clone）或历史受限场景下具备安全的 fallback 保障。

> **v0.3.1 补丁**：修复了 entry candidate 非确定性排序导致的零改动 Source churn。

---

## What's New in v0.2

- **一键统一增量同步 (`repo2nlm sync`)**：自动比对历史状态，首次运行完整导入，再次运行执行精确增量更新。
- **真正增量同步 (True Incremental Sync)**：基于 Source SHA256 识别无变化、新增、修改与废弃，无变化文件零重复上传。
- **变更跟踪账本 (`ChangeBook.md`)**：自动记录两次 Commit 间的文件变动；no-op 同步时严格保持哈希不变。
- **GitHub Commit 永久链接 (Commit Permalinks)**：RepoBook 代码段落精确绑定对应 Commit SHA 的 GitHub 源码链接。
- **所有权安全守护 (Ownership Guard)**：远端删除操作受受管 ID 白名单强约束，绝不误删用户在 Notebook 中手动添加的笔记或碰撞文件。
- **故障安全的分阶段替换 (Failure-Safe Staged Replacement)**：修改源采用“上传暂存源 → 验证 Ready → 清理旧源 → 规范更名”流程，上传失败保证零数据丢失。
- **多仓库工作区支持 (Multi-Repo Workspace)**：支持将多个子工程输出合并上传至同一 Notebook，自动添加前缀并生成跨仓索引 `WorkspaceIndex.md`。
- **单文件模式修复 (`--no-split-repobook`)**：支持按需生成单一完整的 RepoBook 文件。
- **JS/TS 相对与多扩展名 Import 解析修复**：增强前端工程 import 依赖图解析精度。

---

## Quick Start

### 完整安装（支持 Gemini Notebook 同步，推荐）

```bash
git clone https://github.com/bilppppp/Repo2NotebookLM.git
cd Repo2NotebookLM

python3 -m venv .venv
source .venv/bin/activate

pip install -e '.[notebooklm]'
playwright install chromium

notebooklm login
notebooklm auth check --test
```

> **说明**：`playwright install chromium` 仅用于 `notebooklm-py` 的浏览器交互式登录流程；完成登录并取得有效认证后，日常执行 `repo2nlm sync` 完全在后台无头运行，无需启动浏览器。

#### 一键同步

```bash
repo2nlm sync https://github.com/owner/repo \
  --notebook my-project \
  --create-if-missing
```

---

### Core-Only 安装（仅本地解析，不上传）

如果只需将 Git 仓库转为结构化 Markdown（RepoBook / GraphBook / ChangeBook），不使用 Gemini Notebook 云端上传功能，可仅安装核心依赖：

```bash
pip install -e .
```

然后执行本地生成与增量更新：

```bash
# 生成本地知识库文件到 out 目录
repo2nlm ingest https://github.com/owner/repo --out ./out

# 代码变更后增量更新 ChangeBook.md
repo2nlm update https://github.com/owner/repo --out ./out
```

> **注意**：Gemini Notebook 云端集成属于可选依赖（optional dependency）。

---

### 给 AI Agent 安装

可以直接把这句话发给你的 AI agent：

```text
帮我安装 repo2nlm：https://raw.githubusercontent.com/bilppppp/Repo2NotebookLM/main/install.md
```

完整安装指南详见 [`install.md`](install.md)。

---

## How It Works

```text
Git Repository
      ↓
   Scanner
      ↓
RepoBook + GraphBook + ChangeBook
      ↓
Incremental Sync (SHA256 & Ownership Guard)
      ↓
Gemini Notebook
```

### 输出文件说明

- **`RepoBook/`**：代码与文档正文，按目录组织成适合 Notebook 学习的章节文件，每份文件附带精确的 GitHub commit 永久链接。
- **`GraphBook.md`**：项目依赖图与架构拓扑，包含目录职责推断、核心 Import Hub 统计与调用明细。
- **`ChangeBook.md`**：记录最近一次实际版本变更（新增、修改、删除及 commit 对比）；在无代码变更的 no-op 同步中保持文件 Hash 绝对不变。
- **`manifest.json`**：本地文件扫描索引与 SHA256 快照，为增量比对提供事实来源。
- **`graph.json`**：结构化的依赖图与目录推断数据。
- **`stats.json`**：扫描统计与最新提交元数据。
- **`upload_map.json`**：增量同步审计凭据，记录远端 Source ID、状态与本地文件对应关系（`missing_titles` 必须为空）。

---

## Usage

### 基础用法（一键增量同步）

```bash
# 首次运行：克隆快照 -> 扫描分析 -> 渲染生成 -> 创建 Notebook -> 上传 Sources -> 对账核验
# 后续运行：读取旧 manifest -> 增量比对 -> 重新渲染 -> 自动执行增量 Source 替换
repo2nlm sync https://github.com/owner/repo \
  --notebook my-project \
  --create-if-missing
```

常用参数：
- `--out <path>`：输出目录（默认为 `./out`）
- `--branch <branch>`：指定分支（默认自动探测默认分支）
- `--commit <sha>`：指定 Commit 检出快照
- `--include "<patterns>"`：包含文件通配符（逗号分隔，如 `src/**,lib/**`）
- `--exclude "<patterns>"`：排除文件通配符（逗号分隔，如 `tests/**,docs/**`）
- `--max-file-kb <kb>`：单文件截断阈值（默认 `200` KB）
- `--max-group-kb <kb>`：每个 RepoBook 章节大小阈值（默认 `512` KB，设为 0 禁用按体积切分）
- `--max-group-files <n>`：每个 RepoBook 章节文件数阈值（默认 `40`，设为 0 禁用按数量切分）
- `--no-adaptive-partition`：禁用自适应拆分，严格使用传统顶级目录归类
- `--no-split-repobook`：禁用按目录拆分，生成单文件 `RepoBook.md`
- `--replace-existing`：强制全量覆盖远端同名 Source

---

## Safety (安全机制)

- **所有权安全守护 (Ownership Guard)**：
  `repo2nlm` 在执行清理时，仅会删除此前由自身同步并记录在案的受管 Source。用户在 NotebookLM Web 界面中手动上传的参考文档或编写的个人笔记，即使文件名碰巧发生碰撞，也受到严格保护，绝不被误删。
- **故障安全的分阶段替换 (Failure-Safe Staged Replacement)**：
  当已有的受管 Source 发生内容变更时，同步流程采用分阶段策略：
  ```text
  上传新暂存源 (_staging_<uuid>_<title>)
  → 等待暂存源达到 ready
  → 删除旧的受管源
  → 将暂存源重命名为正式标题
  ```
  如果上传或就绪中途失败，旧源保持完好无损；若重命名步骤失败，新数据仍作为暂存源完整保留在远端供人工恢复，操作显式报错。该机制提供应用层故障安全性，并非底层数据库事务。

---

## Advanced Usage

### 分步工作流

```bash
# 1. 单独本地解析与渲染（支持 --no-split-repobook）
repo2nlm ingest <repo_url> --branch main --out ./out --max-file-kb 200 \
  --exclude "node_modules/**,dist/**,.git/**"

# 2. 本地增量比对并更新 ChangeBook.md
repo2nlm update <repo_url> --out ./out

# 3. 单独上传已有 out 目录
repo2nlm upload ./out --notebook <name_or_id> --create-if-missing
```

### 多仓库合并工作区 (Multi-Repo Workspace)

支持将多个关联仓库的输出合并注入同一个 Notebook，自动以 `<repo>__<filename>.md` 命名空间隔离，并生成跨仓导航源 `WorkspaceIndex.md`：

```bash
repo2nlm upload ./out-frontend ./out-backend ./out-infra \
  --notebook my-project-workspace \
  --create-if-missing
```

### 本地 out 目录清理建议

建议采用“审计优先、正文可再生”策略：
- **建议保留**（体积小，便于追溯和下次增量对比）：`stats.json`, `upload_map.json`, `manifest.json`, `graph.json`。
- **可删除**（体积大，可重新生成）：`RepoBook/*.md`, `GraphBook.md`, `ChangeBook.md`。

清理示例：
```bash
bash skills/repo2notebooklm/scripts/cleanup_out.sh ./out-<name> --audit-only
```

---

## Compatibility & Limitations

- **依赖非官方客户端**：`notebooklm-py` 为非官方逆向 API 客户端，目前在 `0.8.2` 版本经过完整端到端实测（目标兼容区间：`>=0.8.2,<0.9.0`）。Google Web 端协议或鉴权变动可能影响 CLI 行为。
- **分阶段替换语义**：Staged Replacement 机制为应用层故障安全设计，非底层分布式原子事务。若网络在重命名瞬间中断，新数据安全留存于远端需人工检查。
- **上传经验阈值**：Google Gemini Notebook 官方限制为单文件 200 MB / 50 万字，免费版最多 50 个 Sources。repo2nlm 内部采用 4 MB / 2 MB 分块策略，属于防止逆向 API 长连接超时的客户端经验工作区。
- **认证调试命令**：
  - `notebooklm login`：交互式获取 Google 认证 Cookie
  - `notebooklm auth check --test`：测试现有 Cookie 与认证有效性

---

## Skills

- `skills/repo2notebooklm`：把 Git 仓库转换为 RepoBook + GraphBook 并同步至 Gemini Notebook 的 Agent Skill。
- `skills/notebooklm-py`：通过 CLI 操控 Notebook、Source、Chat 与 Artifacts 的通用 Agent Skill。
