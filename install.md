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

- Ingest Git repositories into structured RepoBook, GraphBook, and ChangeBook formats
- Incrementally sync codebooks to Gemini Notebook (formerly NotebookLM)
- Support multi-repo workspaces with a generated navigation index (`WorkspaceIndex.md`)

### Boundaries

- Do not use `sudo` unless the user explicitly approves it
- Do not modify files outside this project unless required by Python/venv setup
- Prefer using the project-local virtual environment at `.venv/`
- If Gemini Notebook authentication is missing or expired, stop and ask the user to log in

---

### Step 1: Set up the virtual environment

```bash
git clone https://github.com/bilppppp/Repo2NotebookLM.git
cd Repo2NotebookLM

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
```

---

### Step 2: Install repo2nlm

#### Option A: Full Install (with Gemini Notebook sync, recommended)

```bash
pip install -e '.[notebooklm]'
playwright install chromium
```

> **Note**: `playwright install chromium` is only required for the interactive `notebooklm login` browser flow. Routine `repo2nlm sync` calls run headless without launching a browser.

#### Option B: Core-Only Install (local analysis, no cloud upload)

```bash
pip install -e .
```

---

### Step 3: Verify commands

```bash
repo2nlm --help
repo2nlm sync --help

# If Option A was installed:
notebooklm --help
notebooklm --version  # Tested version: 0.8.2
```

---

### Step 4: Check NotebookLM authentication (Option A only)

```bash
notebooklm auth check --test
```

If auth is not ready or expired, ask the user to run:

```bash
notebooklm login
```

---

### Step 5: Smoke test

#### Single repo incremental sync (recommended):

```bash
repo2nlm sync <repo_url> --notebook "<name_or_id>" --create-if-missing
```

#### Local-only analysis:

```bash
repo2nlm ingest <repo_url> --out ./out-<name> --max-file-kb 200
repo2nlm update <repo_url> --out ./out-<name>
```

#### Multi-repo merge upload:

```bash
repo2nlm upload ./out-foo ./out-bar --notebook "<name_or_id>" --create-if-missing
```

---

### Step 6: Verify upload correctness

Check `upload_map.json` in the output directory:

```bash
jq '{requested_notebook, expected_titles_count, ready_titles_count, missing_titles}' ./out-<name>/upload_map.json
```

Acceptance rule:
- `missing_titles` must be empty (`[]`)
- all expected titles must have `ready` status on remote
