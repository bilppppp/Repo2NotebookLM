# Repo2NotebookLM

[中文](README.md) | [English](README.en.md)

**Git repository → structured, versioned Gemini Notebook knowledge base**

Convert Git repositories into structured knowledge bases tailored for Gemini Notebook (formerly NotebookLM).

> **Current Version**: `v0.4.4`

---

## Why Repo2NotebookLM?

While pasting code or uploading repositories directly into LLM chats works for one-off Q&A, maintaining a **long-term evolving project knowledge base** in Gemini Notebook faces unique challenges:

- **Unstructured context**: Dumping raw files without structural boundaries causes prompt truncation and retrieval noise.
- **Missing topological awareness**: Raw code files lack module dependency graphs, directory architectural roles, and core hubs.
- **Poor version tracking**: Re-uploading everything on code updates breaks notebook citations and clutters sources with duplicates.
- **Risk to personal notes**: Naive automation easily deletes user-authored notes and research documents during cleanup.

Repo2NotebookLM bridges **Git Repo → Structured Sources → Gemini Notebook → Incremental Sync**:

- **RepoBook**: Code and docs organized into notebook-friendly chapters, with commit-pinned GitHub permalinks.
- **GraphBook**: Directory roles, dependency hubs, and import topologies inferred statically.
- **ChangeBook**: Tracks actual commit-to-commit file changes (added/modified/deleted); strictly unchanged on zero-diff syncs.
- **True Incremental Sync**: Compares SHA256 hashes against prior state; unchanged sources incur zero re-uploads.
- **Ownership Guard**: Whitelist protection ensures manually added user notes and collision files are never deleted.
- **Multi-Repo Workspaces**: Merge multiple repositories into a single Notebook with namespaces and a `WorkspaceIndex.md` cross-repo guide.

---

## What's New in v0.4

> **v0.4.4 Patch**: Fixed a v0.4.3 regression where the `upload` subcommand crashed because partition-specific CLI fields were not defined for that subcommand.
>
> **v0.4.3 Patch**:
> - Existing outputs preserve their previous partition strategy by default (legacy remains legacy, adaptive remains adaptive), preventing full-source deletion/re-upload churn on upgrade;
> - Fresh repositories still default to adaptive partitioning;
> - Added `--adaptive-partition` CLI flag for explicit migration/opt-in, forming a mutually exclusive tri-state with `--no-adaptive-partition`;
> - Fixed a path parsing bug where paths containing `__part` substrings (e.g. `partial`, `counterpart`, `department`) were incorrectly identified as partition numbers.
>
> **v0.4.2 Patch**: Further stabilized adaptive leaf partition source identities. When a base file bucket requires local refinement due to size growth, sibling base buckets preserve their exact source names and content, preventing remote rename/replacement cascades.
>
> **v0.4.1 Patch**:
> - Tightened repository source integrity and Notebook source quota claims;
> - Clarified existing `--max-file-kb` head/tail truncation semantics;
> - Narrowed cross-source reasoning conclusions to tested benchmarks (`encode/httpx` and `honojs/hono`);
> - Fixed flat leaf fallback partitioning to eliminate partition boundary cascades on small body-only file edits.

- **Adaptive RepoBook Partitioning**:
  Mitigates the "monolithic `src/` churn trap" on large repositories. In v0.3, a repository's top-level directory was bundled into a single RepoBook chapter; editing a single leaf file in `src/` forced the entire multi-megabyte `src.md` to be re-uploaded. v0.4 introduces an adaptive partitioning algorithm: whenever a directory exceeds size or file count thresholds, it recursively subdivides down the directory hierarchy, isolating direct files into a dedicated `<dir>__root` chapter, with leaf fallback chunking (`__part01`) and single huge file isolation.

- **Significant Replacement Blast Radius Reduction on Large Repositories (Up to 92.7%)**:
  In standardized mutation benchmarks on `honojs/hono` (488 files, ~3.5 MB):
  - **Leaf Body Modification (M1)**: Remote replacement payload drops from **2558 KB (75.2%)** in v0.3.1 to **188 KB (5.5%)**—a **92.7% reduction**!
  - **Core Body Modification (M2)**: Replacement payload drops from **2558 KB (75.2%)** to **451 KB (13.2%)**—an **82.4% reduction**!
  - **Import Topology Change (M3)**: Replacement payload drops from **2722 KB** to **615 KB (18.0%)**—an **77.4% reduction**!
  - **Add & Delete File (M4/M5)**: Replacement payloads drop by **69.9%** and **91.3%** respectively!

- **Zero Over-Fragmentation & Backward Compatibility Design**:
  - Medium repositories like `encode/httpx` (125 files) maintain clean directory-level grouping under default settings—no unnecessary fragmentation occurs for subdirectories within limits.
  - `--no-adaptive-partition` CLI flag provides full backward compatibility with v0.3 top-level directory grouping.
  - Adaptive RepoBook partitioning itself introduces no additional summarization, truncation, or source omission. File scanning still respects `--max-file-kb`; files exceeding that limit continue to use the existing head/tail truncation behavior. Stable per-file permalinks, Ownership Guard, and Failure-Safe Staged Replacement remain unchanged.

- **Configurable CLI Thresholds**:
  - `--max-group-kb <kb>`: Maximum KB per RepoBook chapter before adaptive split (default: `512` KB, 0 to disable).
  - `--max-group-files <n>`: Maximum files per RepoBook chapter before adaptive split (default: `40` files, 0 to disable).
  - `--adaptive-partition`: Explicitly enable/migrate to adaptive partitioning (default for fresh repositories).
  - `--no-adaptive-partition`: Disable adaptive partitioning and use legacy top-level directory grouping (default for existing legacy outputs).

- **Clear Engineering Positioning**:
  In NotebookLM benchmarks on `encode/httpx` and `honojs/hono`, adaptive module partitioning showed no observed degradation in cross-source code reasoning. This is an empirical result for the tested repositories, not a universal guarantee. v0.4 focuses specifically on drastically slashing incremental sync payload sizes and API replacement blast radiuses on large repositories.

---

## What's New in v0.3

- **Reduce Metadata-Induced Source Churn**: Standard body-only code modifications no longer trigger unnecessary remote source re-uploads due to global HEAD commit shifts. In real Gemini Notebook E2E testing, remote replacements for single-file edits drop from **5/5 (100%)** in v0.2 down to **3/5 (60%)**.
- **Stable Per-File Permalinks**: GitHub permalinks in RepoBook chapters no longer anchor indiscriminately to the latest repository HEAD. Unchanged files pin strictly to their last content-changing commit SHA, ensuring chapter byte-stability while keeping permalinks aligned with the intended code version.
- **Stable GraphBook**: `GraphBook.md` omits volatile snapshot commit metadata. When import relationships, directory roles, and file topologies remain unchanged, `GraphBook.md` stays byte-identical, eliminating churn while still updating reliably when dependencies actually change.
- **v0.2 → v0.3 Manifest Migration**: Seamlessly upgrades legacy v0.2 `manifest.json` files lacking per-file commit records. Automatically backfills each file's last-touch commit from Git history into the upgraded manifest, with safe fallbacks for shallow clones.

> **v0.3.1 Patch**: Fixes nondeterministic entry-candidate ordering that could cause source churn on unchanged repositories.

---

## What's New in v0.2

- **Unified Incremental Sync (`repo2nlm sync`)**: Detects previous state to run full initial import or surgical incremental updates.
- **True Incremental Source Sync**: Hashes each source to skip unchanged files and replace only modified parts.
- **Version Change Ledger (`ChangeBook.md`)**: Records diffs between commits; preserves bit-for-bit SHA equality on no-op syncs.
- **GitHub Commit Permalinks**: Every code section links directly to the permanent commit SHA on GitHub.
- **Ownership Guard**: Strict managed ID whitelist prevents deleting personal notes or files with colliding titles.
- **Failure-Safe Staged Replacement**: Modified sources upload under staging names before deleting old sources and renaming.
- **Multi-Repo Workspace Support**: Combines multiple projects into one notebook with namespacing and `WorkspaceIndex.md`.
- **Single-File RepoBook Fix (`--no-split-repobook`)**: Supports exporting an un-split single-file RepoBook.
- **JS/TS Import Resolution Fix**: Resolves relative paths and multi-extension imports accurately across JavaScript and TypeScript projects.

---

## Quick Start

### Full Installation (with Gemini Notebook sync, recommended)

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

> **Note**: `playwright install chromium` is only used for the interactive browser login flow in `notebooklm-py`. Once authenticated, daily `repo2nlm sync` operations run fully headless without launching a browser.

#### One-Step Sync

```bash
repo2nlm sync https://github.com/owner/repo \
  --notebook my-project \
  --create-if-missing
```

---

### Core-Only Installation (Local analysis without upload)

If you only want to generate structured Markdown books locally (RepoBook / GraphBook / ChangeBook) without syncing to Gemini Notebook, install core dependencies only:

```bash
pip install -e .
```

Then run local analysis:

```bash
# Generate local knowledge base in out/
repo2nlm ingest https://github.com/owner/repo --out ./out

# Incrementally update ChangeBook.md on new commits
repo2nlm update https://github.com/owner/repo --out ./out
```

> **Note**: Gemini Notebook integration is optional.

---

### Install for AI Agents

You can send this directly to your AI agent:

```text
Help me install repo2nlm: https://raw.githubusercontent.com/bilppppp/Repo2NotebookLM/main/install.md
```

Full agent installation guide: [`install.md`](install.md).

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

### Generated Files

- **`RepoBook/`**: Code and documentation grouped into clean chapter files, each with commit-pinned GitHub permalinks.
- **`GraphBook.md`**: Architectural topology, directory responsibility heuristics, core import hubs, and dependency traces.
- **`ChangeBook.md`**: Recent version changes (added, modified, deleted files and commit diffs); never rewritten on no-op syncs.
- **`manifest.json`**: Local scanned file index and SHA256 hashes recording an incremental state snapshot of current scan results.
- **`graph.json`**: Structured dependency graph and directory role metadata.
- **`stats.json`**: Scanning metrics and commit metadata.
- **`upload_map.json`**: Audit artifact reconciling local sources with remote notebook IDs and statuses (`missing_titles` must be empty).

---

## Usage

### Primary Command (Unified Incremental Sync)

```bash
# First run: clone -> scan -> render -> create notebook -> upload -> audit
# Later runs: read manifest -> incremental diff -> re-render -> replace changed sources
repo2nlm sync https://github.com/owner/repo \
  --notebook my-project \
  --create-if-missing
```

Common options:
- `--out <path>`: output directory (default: `./out`)
- `--branch <branch>`: target branch (defaults to remote default branch)
- `--commit <sha>`: checkout specific commit
- `--include "<patterns>"`: comma-separated glob patterns (e.g. `src/**,lib/**`)
- `--exclude "<patterns>"`: comma-separated glob patterns (e.g. `tests/**,docs/**`)
- `--max-file-kb <kb>`: truncation limit per file (default: `200` KB)
- `--max-group-kb <kb>`: max KB per RepoBook chapter before adaptive split (default: `512` KB, 0 to disable)
- `--max-group-files <n>`: max files per RepoBook chapter before adaptive split (default: `40` files, 0 to disable)
- `--no-adaptive-partition`: disable adaptive partitioning (use legacy top-level directory grouping)
- `--no-split-repobook`: generate a single `RepoBook.md` instead of directory chapters
- `--replace-existing`: force full re-upload of matching remote sources

---

## Safety

- **Ownership Guard**:
  `repo2nlm` only deletes remote sources previously recorded as managed by repo2nlm. Personal notes, PDFs, or research documents manually uploaded by users in the NotebookLM Web UI are strictly preserved, even if their titles collide.
- **Failure-Safe Staged Replacement**:
  When a managed source changes, sync follows a guarded sequence:
  ```text
  Upload new staging source (_staging_<uuid>_<title>)
  → Wait until staging source is ready
  → Delete old managed source
  → Rename staging source to canonical title
  ```
  If upload or processing fails midway, the old version remains intact. If renaming fails, new data is safely preserved on the remote notebook for manual recovery, and sync fails visibly. (Note: this is an application-level guard, not a database transaction).

---

## Advanced Usage

### Step-by-Step Workflow

```bash
# 1. Standalone local ingest and rendering
repo2nlm ingest <repo_url> --branch main --out ./out --max-file-kb 200

# 2. Local incremental update of ChangeBook.md
repo2nlm update <repo_url> --out ./out

# 3. Standalone upload of existing out directory
repo2nlm upload ./out --notebook <name_or_id> --create-if-missing
```

### Multi-Repo Workspace

Combine outputs from multiple related repositories into one Notebook with `<repo>__<filename>.md` namespaces and a generated navigation hub `WorkspaceIndex.md`:

```bash
repo2nlm upload ./out-frontend ./out-backend ./out-infra \
  --notebook my-project-workspace \
  --create-if-missing
```

### Local `out` Directory Cleanup Policy

Recommended policy: keep audit artifacts, delete regenerable content when needed:
- **Keep** (small, useful for audits and future diffs): `stats.json`, `upload_map.json`, `manifest.json`, `graph.json`.
- **Safe to delete** (regenerable): `RepoBook/*.md`, `GraphBook.md`, `ChangeBook.md`.

Cleanup example:
```bash
bash skills/repo2notebooklm/scripts/cleanup_out.sh ./out-<name> --audit-only
```

---

## Compatibility & Limitations

- **Unofficial Client**: `notebooklm-py` reverse-engineers Google Gemini Notebook web endpoints. Tested and verified on version `0.8.2` (target range: `>=0.8.2,<0.9.0`). Google backend changes may impact CLI behavior.
- **Staged Replacement Semantics**: Staged replacement provides application-level safety rather than atomic database transactions. If network breaks during the final rename step, staged sources remain on the remote notebook for manual recovery.
- **Source Quotas & No Active Budget Compression**: NotebookLM accounts enforce source limits per notebook (e.g. a conservative 50 sources for Free-tier accounts, with higher quotas on Pro/Workspace accounts). `v0.4.2` **does not actively compress or merge sources to fit account quotas**; large repositories (e.g., projects with numerous middleware modules) may produce more sources than an account's quota allows under default settings, requiring higher tier quotas, narrower scope (`--include`), or custom grouping thresholds.
- **Large File Truncation Semantics**: Defaults to `--max-file-kb=200`. For text files exceeding this limit, repo2nlm applies a head/tail preservation policy (keeping the first half and last half, separated by `...TRUNCATED...`), meaning **middle content in oversized files will not enter RepoBook**. This threshold can be adjusted via `--max-file-kb`.
- **Special Git Objects**: The scanner operates on standard working tree files and does not yet fully model special Git objects such as symbolic links (symlinks), submodule gitlinks, or Git LFS pointer assets.
- **Character Encoding**: Text detection and decoding prioritize UTF-8. Non-UTF-8 files may encounter character replacement (`errors="replace"`) or decoding distortion.
- **No Source-Budget-Aware Packing**: Partitioning in `v0.4.2` is governed by directory hierarchy and static thresholds (`--max-group-kb`, `--max-group-files`). It does not dynamically pack files to target an exact source budget constraint (e.g., fitting within 50 sources).
- **Auth Verification Commands**:
  - `notebooklm login`: interactive browser session cookie authentication
  - `notebooklm auth check --test`: test active credentials against Google backend

---

## Skills

- `skills/repo2notebooklm`: agent skill for converting Git repositories into RepoBook + GraphBook and syncing to Gemini Notebook.
- `skills/notebooklm-py`: general agent skill for operating NotebookLM via the CLI for notebooks, sources, chat, and artifacts.
