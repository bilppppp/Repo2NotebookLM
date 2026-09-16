# repo2nlm

[中文](README.md) | [English](README.en.md)

把 GitHub 仓库转换为 NotebookLM 结构化学习材料，输出：

- `RepoBook/`（代码与文档正文，支持 commit 永久链接）
- `GraphBook.md`（目录职责 + import 关系）
- `ChangeBook.md`（版本变更检测与增量对比）
- `manifest.json`（文件索引与 Hash）
- `graph.json`（依赖图数据）
- `stats.json`（统计与变更数据）

## 给 AI Agent 安装

可以直接把这句话发给你的 AI agent：

```text
帮我安装 repo2nlm：https://raw.githubusercontent.com/bilppppp/Repo2NotebookLM/main/install.md
```

安装说明文档：[`install.md`](install.md)

## 环境准备（venv）

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e .
# 经过真实环境严格验证的 notebooklm-py 版本 (实测版本: 0.8.2，目标兼容: >=0.8.2,<0.9.0)
pip install "notebooklm-py[browser]>=0.8.2,<0.9.0"
playwright install chromium
```

> **实测验证的 CLI 子命令**：
> - `notebooklm --version`（版本探测）
> - `notebooklm list --json`（获取 Notebook 列表）
> - `notebooklm create <title> --json`（创建缺失的 Notebook）
> - `notebooklm source list -n <nb> --json`（拉取远端 Sources 状态）
> - `notebooklm source add <file> -n <nb> --json`（上传 Markdown）
> - `notebooklm source wait <id> -n <nb> --timeout 300`（等待 Source 达到 ready 状态）
> - `notebooklm source delete <id> -n <nb> -y`（严格受控删除废弃受控 Source）
> - `notebooklm source rename <id> <new_title> -n <nb>`（故障安全的分阶段替换，保证上传失败时不破坏旧 Source）

> notebooklm-py 官方仓库: https://github.com/teng-lin/notebooklm-py

## 推荐用法（一键增量同步）

```bash
# 第一次运行：快照 -> 分析 -> 渲染 -> 创建 Notebook -> 上传 -> 校验
# 之后再次运行：比较上次状态 -> 重新渲染 -> 真正的增量 Source 替换同步
repo2nlm sync https://github.com/owner/repo \
  --notebook my-project \
  --create-if-missing
```

### 高级与分步用法

```bash
# 单独解析与渲染（支持 --no-split-repobook 输出单文件 RepoBook）
repo2nlm ingest <repo_url> --branch main --out ./out --max-file-kb 200 \
  --exclude "node_modules/**,dist/**,.git/**"

# 基于旧 manifest 增量生成 ChangeBook.md
repo2nlm update <repo_url> --out ./out

# 单独上传 / 同步到已有 notebook
repo2nlm upload ./out --notebook <name_or_id> --create-if-missing
# 强制全量覆盖替换同名 source
repo2nlm upload ./out --notebook <name_or_id> --replace-existing

# 多仓库合并上传：自动使用命名空间并生成 WorkspaceIndex.md
repo2nlm upload ./out-mlflow ./out-dispatch ./out-hermes-agent \
  --notebook <name_or_id> --create-if-missing
```

## 核心特性与说明

- **一键统一命令 (`sync`)**：自动识别是否存在旧 manifest，初次自动完整导入，再次运行自动进行增量更新与同步。
- **所有权安全守护 (Ownership Guard)**：
  - 远端删除操作受 `remote_source_id in all_prev_managed_ids` 强约束。
  - **绝不依据标题相同就误删用户的个人手工文档或笔记**（即使标题与生成的章节、Purge 标题或 Split 分片重名也受到绝对保护）。
- **故障安全的分阶段替换 (Failure-Safe Staged Replacement)**：
  - 当某个受管 Source 发生变更时，先上传临时暂存 Source 并确认其达到 `ready` 状态。
  - 唯有在上传与就绪成功后，才删除旧 Source 并将新 Source 重命名为规范标题。
  - 若上传或就绪中途失败，旧 Source 保持完整无损，个人文档保持完整无损，同步操作显式报错。
- **ChangeBook.md 生命周期语义**：
  - 代表“最近一次实际仓库变更”（新增、修改、删除的文件列表及前后的 Commit SHA）。
  - 在无代码变更的 no-op sync 场景下，**绝不改写现有 ChangeBook.md**，保证文件 Hash 不变且远端发生 0 次上传与 0 次删除。
- **永久 GitHub Permalink**：对于 GitHub 仓库，RepoBook 中每个文件条目均生成精确绑定到当前 Commit SHA 的永久链接。
- **上传稳定性防护与工作机制**：
  - 针对逆向 API 长连接与传输限制，客户端默认启用 4 MB 分割与分批上传策略。
  - *说明*：Google Gemini Notebook 官方文档单文件上限为 200 MB / 50 万字，免费版支持 50 个 sources（付费版最高 600 个）。repo2nlm 内部的 4 MB / 2 MB 分块是保证非官方 API 上传稳定性的经验工作区，避免超时或断连。

## 上传后是否保留本地 out 目录

建议按“审计优先、正文可再生”保留：

- 建议保留（体积小，便于追溯）：
  - `stats.json`（本次 commit、扫描统计）
  - `upload_map.json`（远端 source 对账结果，`missing_titles` 必须为空）
  - `manifest.json` / `graph.json`（可选，做后续 diff 或结构分析）
- 可删除（体积大，可重新生成）：
  - `RepoBook/*.md`
  - `GraphBook.md` / `GraphBook.part*.md`
  - `artifacts/`、截图、临时调试输出

清理示例（仅保留最小审计文件）：

```bash
bash skills/repo2notebooklm/scripts/cleanup_out.sh ./out-<name> --audit-only
```

## Skills（根目录）

- `skills/repo2notebooklm`: 把 Git 仓库转换为 RepoBook + GraphBook，并上传 NotebookLM。
- `skills/notebooklm-py`: 使用 `notebooklm` CLI 执行 Notebook/Source/Chat/Artifact/Research 全流程。
