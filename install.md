# repo2nlm — Installation Guide

## For Humans

Copy this to your AI agent:

```text
帮我安装 repo2nlm：https://raw.githubusercontent.com/bilppppp/Repo2NotebookLM/main/install.md
```

English version:

```text
Help me install repo2nlm: https://raw.githubusercontent.com/bilppppp/Repo2NotebookLM/main/install.md
```

---

## For AI Agents

### Goal

Install `repo2nlm` in the current project so the user can:

- ingest GitHub repositories into RepoBook + GraphBook outputs
- upload one or more `out-*` directories to NotebookLM
- merge multiple repos into one NotebookLM notebook
- generate `WorkspaceIndex.md` for cross-repo navigation

### Boundaries

- Do not use `sudo` unless the user explicitly approves it
- Do not modify files outside this project unless required by Python/venv setup
- Prefer using the project-local virtual environment at `.venv/`
- If NotebookLM authentication is missing, stop and ask the user to log in

### Step 1: Set up the virtual environment

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
```

### Step 2: Install repo2nlm and NotebookLM CLI

```bash
pip install -e .
# Tested & verified with notebooklm-py 0.8.2 (Target compatibility: >=0.8.2,<0.9.0)
pip install "notebooklm-py[browser]>=0.8.2,<0.9.0"
playwright install chromium
```

### Step 3: Verify commands

```bash
./repo2nlm --help
./repo2nlm sync --help
notebooklm --help
notebooklm --version  # Tested version: 0.8.2
```

> **Verified CLI Subcommands**:
> - `notebooklm --version`
> - `notebooklm list --json`
> - `notebooklm create <title> --json`
> - `notebooklm source list -n <nb> --json`
> - `notebooklm source add <file> -n <nb> --json`
> - `notebooklm source wait <id> -n <nb> --timeout 300`
> - `notebooklm source delete <id> -n <nb> -y`
> - `notebooklm source rename <id> <new_title> -n <nb>` (used for failure-safe staged replacement)

### Step 4: Check NotebookLM auth

```bash
notebooklm auth check
```

If auth is not ready, ask the user to run:

```bash
notebooklm login
```

### Step 5: Smoke test

Single repo flow (recommended: `sync` for true incremental sync):

```bash
./repo2nlm sync <repo_url> --notebook "<name_or_id>" --create-if-missing
```

Or step-by-step:

```bash
./repo2nlm ingest <repo_url> --out ./out-<name> --max-file-kb 200
./repo2nlm upload ./out-<name> --notebook "<name_or_id>" --create-if-missing
```

Multi-repo flow:

```bash
./repo2nlm upload ./out-foo ./out-bar --notebook "<name_or_id>" --create-if-missing
```

### Step 6: Verify upload correctness

For a single repo:

```bash
jq '{requested_notebook, expected_titles_count, ready_titles_count, missing_titles}' ./out-<name>/upload_map.json
```

For a merged notebook:

1. Read all relevant `upload_map.json` files
2. Union every `items[].uploaded_titles`
3. Compare that union with:

```bash
notebooklm source list -n <notebook_id> --json
```

Acceptance rule:

- no missing titles
- no extra titles
- all remote sources are `ready`

### Quick Reference

```bash
./repo2nlm sync <repo_url> --notebook "<name_or_id>" --create-if-missing
./repo2nlm ingest <repo_url> --out ./out-<name> --max-file-kb 200
./repo2nlm update <repo_url> --out ./out-<name>
./repo2nlm upload ./out-<name> --notebook "<name_or_id>" --create-if-missing
./repo2nlm upload ./out-foo ./out-bar --notebook "<name_or_id>" --create-if-missing
notebooklm auth check
notebooklm source list -n <notebook_id> --json
```
