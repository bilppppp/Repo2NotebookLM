# repo2nlm

[中文](README.md) | [English](README.en.md)

Convert GitHub repositories into NotebookLM-ready structured learning material.

Outputs:

- `RepoBook/` for code and documentation content (with permanent commit permalinks)
- `GraphBook.md` for directory responsibilities and import relationships
- `ChangeBook.md` for version diff detection and incremental change tracking
- `manifest.json` for scanned file index and hashes
- `graph.json` for dependency graph data
- `stats.json` for scan and update statistics

## Install for AI Agents

You can send this directly to your AI agent:

```text
Help me install repo2nlm: https://raw.githubusercontent.com/bilppppp/Repo2NotebookLM/main/install.md
```

Installation document: [`install.md`](install.md)

## Environment Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e .
# Tested & verified notebooklm-py release (tested: 0.8.2, targeted compatibility: >=0.8.2,<0.9.0)
pip install "notebooklm-py[browser]>=0.8.2,<0.9.0"
playwright install chromium
```

> **Verified CLI Subcommands**:
> - `notebooklm --version` (detect version)
> - `notebooklm list --json` (list notebooks)
> - `notebooklm create <title> --json` (create notebook)
> - `notebooklm source list -n <nb> --json` (query remote sources status)
> - `notebooklm source add <file> -n <nb> --json` (upload source file)
> - `notebooklm source wait <id> -n <nb> --timeout 300` (wait for source ready)
> - `notebooklm source delete <id> -n <nb> -y` (delete managed source)
> - `notebooklm source rename <id> <new_title> -n <nb>` (failure-safe staged replacement)

> notebooklm-py repo: https://github.com/teng-lin/notebooklm-py

## Recommended Usage (Unified Incremental Sync)

```bash
# First run: snapshot -> scan -> graph -> render -> create notebook -> upload -> verify
# Subsequent runs: compare previous manifest -> re-render -> true incremental source sync
repo2nlm sync https://github.com/owner/repo \
  --notebook my-project \
  --create-if-missing
```

### Advanced / Step-by-Step Usage

```bash
# Standalone ingest & rendering (supports --no-split-repobook for single file RepoBook)
repo2nlm ingest <repo_url> --branch main --out ./out --max-file-kb 200 \
  --exclude "node_modules/**,dist/**,.git/**"

# Incremental update generating ChangeBook.md based on previous manifest
repo2nlm update <repo_url> --out ./out

# Standalone upload to notebook
repo2nlm upload ./out --notebook <name_or_id> --create-if-missing
# Force full re-upload of matching remote sources
repo2nlm upload ./out --notebook <name_or_id> --replace-existing

# Merge multiple repository outputs into one NotebookLM notebook
repo2nlm upload ./out-mlflow ./out-dispatch ./out-hermes-agent \
  --notebook <name_or_id> --create-if-missing
```

## Key Features & Details

- **Unified Sync Command (`sync`)**: Automatically detects whether a previous manifest exists, performing a full initial ingest or a fine-grained incremental sync accordingly.
- **Ownership Guard**:
  - Remote deletion is strictly guarded by `remote_source_id in all_prev_managed_ids`.
  - **Never deletes personal documents or notes manually added to the notebook by the user**, even if titles collide with generated chapters, purge titles, or split parts.
- **Failure-Safe Staged Replacement**:
  - Modified sources are first uploaded under a temporary staging name and verified `ready`.
  - Only after successful verification is the old managed source deleted and the staged source renamed to its canonical title.
  - If upload or processing fails, the old version and user documents remain intact, and sync fails visibly.
- **ChangeBook.md Lifecycle Semantics**:
  - Represents the "most recent actual repository change" (added, modified, deleted files with commit SHAs).
  - In zero-diff no-op syncs, ChangeBook.md is **never rewritten**, preserving bit-for-bit SHA equality and triggering 0 remote additions and 0 deletions.
- **Permanent GitHub Permalinks**: For GitHub repositories, each file in RepoBook includes a permalink pinned to the exact commit SHA.
- **Transport Stability Workarounds**:
  - Client-side 4 MB splitting and batching prevents network timeouts when uploading large sources via reverse-engineered APIs.
  - *Note*: Official Gemini Notebook limits are 200 MB / 500,000 words per file and 50 sources for free tiers (up to 600 for paid tiers). The local 4 MB/2 MB chunks are empirical stability workarounds, not official Google constraints.

## Should You Keep Local `out` Directories?

Recommended policy: keep audit artifacts, delete regenerable content when needed.

- Recommended to keep:
  - `stats.json` for commit and scan statistics
  - `upload_map.json` for remote reconciliation; `missing_titles` must be empty
  - `manifest.json` / `graph.json` for future diffing and structure analysis
- Safe to delete:
  - `RepoBook/*.md`
  - `GraphBook.md` / `GraphBook.part*.md`
  - temporary artifacts, screenshots, and debug output

Cleanup example:

```bash
bash skills/repo2notebooklm/scripts/cleanup_out.sh ./out-<name> --audit-only
```

## Skills

- `skills/repo2notebooklm`: convert Git repositories into RepoBook + GraphBook and upload them to NotebookLM
- `skills/notebooklm-py`: operate NotebookLM through the CLI for notebooks, sources, chat, artifacts, and research workflows
