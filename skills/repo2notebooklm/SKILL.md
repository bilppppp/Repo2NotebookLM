---
name: repo2notebooklm
description: Use when the user wants to ingest one or more code repositories into NotebookLM, refresh existing repo outputs, merge multiple repos into one notebook, or verify uploaded sources against local repo2nlm artifacts.
---

# repo2notebooklm

Use this skill to run the local `repo2nlm` tool end-to-end.

## When to use

- User asks to ingest a GitHub repo to NotebookLM
- User asks to generate RepoBook/GraphBook from code repositories
- User asks to update previously generated outputs incrementally
- User wants to upload multiple `out-*` directories into one NotebookLM notebook
- User wants a cross-repo NotebookLM workspace with a generated navigation/index source
- User wants exact upload verification using `upload_map.json`

## Preconditions

- Run in project root: `/Users/gravity/Desktop/AI/Repo2NotebookLM`
- Activate venv: `. .venv/bin/activate`
- `repo2nlm` executable exists in root

## Workflow

### Recommended: One-step Incremental Sync

```bash
./repo2nlm sync <repo_url> --notebook "<name_or_id>" --create-if-missing
```

### Advanced: Step-by-Step Workflow

1. Ingest repository

```bash
./repo2nlm ingest <repo_url> --out ./out-<name> --max-file-kb 200
```

2. Incremental update (optional)

```bash
./repo2nlm update <repo_url> --out ./out-<name>
```

3. Upload to NotebookLM (optional)

```bash
./repo2nlm upload ./out-<name> --notebook "<name_or_id>" --create-if-missing
# 强制替换同名远端 source，避免保留旧内容
./repo2nlm upload ./out-<name> --notebook "<name_or_id>" --replace-existing

# 多个 repo 合并进同一个 notebook 时，自动使用 <repo>__<filename>.md 命名空间
# 并生成一个 WorkspaceIndex.md 作为跨 repo 导航入口
./repo2nlm upload ./out-foo ./out-bar --notebook "<name_or_id>" --create-if-missing
```

3a. Verify upload correctness (recommended)

```bash
# 单仓：检查当前 out 目录的 upload_map.json
jq '{requested_notebook, expected_titles_count, ready_titles_count, missing_titles}' ./out-<name>/upload_map.json

# 多仓合并：把多个 upload_map.json 的 uploaded_titles 合集，与远端 source list 对账
notebooklm source list -n <notebook_id> --json
```

4. Cleanup local outputs (optional)

```bash
# 仅保留审计文件（stats/upload_map/manifest/graph）
bash skills/repo2notebooklm/scripts/cleanup_out.sh ./out-<name> --audit-only
```

## Expected outputs

- `out-<name>/RepoBook/*.md`
- `out-<name>/GraphBook.md`
- `out-<name>/ChangeBook.md`
- `out-<name>/manifest.json`
- `out-<name>/graph.json`
- `out-<name>/stats.json`
- `out-<name>/upload_map.json` (generated after `upload` or `sync`)
- Multi-repo upload only: remote `WorkspaceIndex.md`

## Notes

- Verified with `notebooklm-py==0.8.2` (Target compatibility range: `>=0.8.2,<0.9.0`).
- Subcommands used: `source list`, `source add`, `source wait`, `source delete`, `source rename`, `create`, `list`.
- `ingest` supports `--branch`, `--commit`, `--include`, `--exclude`, `--max-file-kb`
- `update` compares with existing `manifest.json` and reports changed/deleted files
- `ChangeBook.md` reflects "最近一次实际仓库变更"; in no-op syncs with no changes, it is not rewritten.
- `sync` uses Ownership Guard (only deletes managed IDs) and Staged Replacement (uploads staging source before deleting old version).
- If upload fails, verify NotebookLM login with `notebooklm login`
- `upload` includes auto-recovery behavior:
  - auto-split large markdown files to `*.partNN.md`
  - clean stale/errored duplicate sources before retry
  - auto-switch to `large-auto` batching mode for very large uploads
  - reconcile local expected titles vs remote ready sources
  - when uploading multiple `out-*` directories together, namespace titles as `<repo>__<filename>.md`
  - generate `WorkspaceIndex.md` to summarize the combined repositories and provide cross-repo query hints
- `upload_map.json` is the audit artifact for upload correctness:
  - `upload_mode` / `batch_size` / `file_count` / `total_bytes`: upload strategy evidence
  - `items[].original`: original local markdown file
  - `items[].uploaded_titles`: actual source titles uploaded to NotebookLM
  - `items[].split`: whether file was split
  - `items[].remote_sources[]`: remote `id/status/type/created_at`
  - acceptance rule: `missing_titles` must be empty
- For a merged notebook, the strict correctness rule is:
  - union all `items[].uploaded_titles` across the relevant `upload_map.json` files
  - compare that union with `notebooklm source list -n <notebook_id> --json`
  - acceptance rule: no missing titles, no extra titles, all remote sources are `ready`
