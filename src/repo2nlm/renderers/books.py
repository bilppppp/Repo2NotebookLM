from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from typing import Any

from ..config import DEFAULT_MAX_GROUP_FILES, DEFAULT_MAX_GROUP_KB
from ..types import FileRecord, ImportEdge

_PART_SLUG_RE = re.compile(r"^(?P<base>.+)__part(?P<part>\d+)(?:__sub(?P<sub>\d+))?$")


def get_github_permalink(repo_url: str, commit: str, file_path: str) -> str | None:
    if not repo_url or not commit:
        return None
    clean_url = repo_url.strip()
    m = re.match(
        r"^(?:https?://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+)/([^/]+?)(?:\.git)?/?$",
        clean_url,
    )
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    norm_path = file_path.lstrip("/").replace("\\", "/")
    return f"https://github.com/{owner}/{repo}/blob/{commit}/{norm_path}"


def _render_tree(paths: list[str]) -> str:
    tree: dict = {}
    for p in paths:
        cur = tree
        for part in p.split("/"):
            cur = cur.setdefault(part, {})

    lines: list[str] = []

    def walk(node: dict, prefix: str = "") -> None:
        keys = sorted(node.keys())
        for i, k in enumerate(keys):
            last = i == len(keys) - 1
            branch = "└── " if last else "├── "
            lines.append(prefix + branch + k)
            walk(node[k], prefix + ("    " if last else "│   "))

    walk(tree)
    return "\n".join(lines)


def _clean_segment(p: str) -> str:
    cp = re.sub(r"[^a-zA-Z0-9_-]+", "_", p)
    cp = re.sub(r"_+", "_", cp)
    cp = cp.strip("_")
    return cp or "_"


def _path_slug(path_str: str) -> str:
    parts = [_clean_segment(part) for part in path_str.strip("/").split("/") if part]
    return "__".join(parts) if parts else "root"


def _partition_flat_items(
    base_slug: str,
    items: list[FileRecord],
    file_bytes: dict[str, int],
    max_group_kb: int,
    max_group_files: int,
) -> list[tuple[str, list[FileRecord]]]:
    """Partition flat files into stable chunks with isolated namespaces, preventing naming cascades.

    1. Primary grouping by max_group_files ensures stable file-count base buckets.
    2. Local refinement: If an individual bucket exceeds max_group_kb, it is locally
       subdivided under its own namespace (__subNN) without disturbing sibling bucket names.
    """
    if not items:
        return []

    # Step 1: Stable file-count buckets
    base_buckets: list[list[FileRecord]] = []
    if max_group_files > 0:
        for i in range(0, len(items), max_group_files):
            base_buckets.append(items[i : i + max_group_files])
    else:
        base_buckets.append(items)

    # Step 2: Deterministic local refinement with isolated namespace
    final_parts: list[tuple[str, list[FileRecord]]] = []
    for b_idx, b_items in enumerate(base_buckets):
        part_name = f"{base_slug}__part{b_idx+1:02d}"
        b_total = sum(file_bytes[f.path] for f in b_items) + 150
        needs_local_split = (len(b_items) > 1) and (max_group_kb > 0 and b_total > max_group_kb * 1024)
        if needs_local_split:
            sub_parts: list[list[FileRecord]] = []
            cur_part: list[FileRecord] = []
            cur_bytes = 0
            for f in b_items:
                f_size = file_bytes[f.path]
                if cur_part and (cur_bytes + f_size > max_group_kb * 1024):
                    sub_parts.append(cur_part)
                    cur_part = [f]
                    cur_bytes = f_size
                else:
                    cur_part.append(f)
                    cur_bytes += f_size
            if cur_part:
                sub_parts.append(cur_part)

            if len(sub_parts) > 1:
                for sub_idx, sub_part in enumerate(sub_parts):
                    final_parts.append((f"{part_name}__sub{sub_idx+1:02d}", sub_part))
            else:
                final_parts.append((part_name, sub_parts[0]))
        else:
            final_parts.append((part_name, b_items))

    return final_parts


def _partition_directory(
    curr_dir: str,
    items: list[FileRecord],
    file_bytes: dict[str, int],
    max_group_kb: int,
    max_group_files: int,
    seen_slugs: dict[str, str],
) -> list[tuple[str, list[FileRecord]]]:
    items = sorted(items, key=lambda x: x.path)
    if not items:
        return []

    curr_slug = _path_slug(curr_dir)
    if curr_slug in seen_slugs and seen_slugs[curr_slug] != curr_dir:
        short_hash = hashlib.sha256(curr_dir.encode("utf-8")).hexdigest()[:6]
        curr_slug = f"{curr_slug}__{short_hash}"
    seen_slugs[curr_slug] = curr_dir

    total_bytes = sum(file_bytes[f.path] for f in items) + 150
    is_oversized = (len(items) > 1) and (
        (max_group_kb > 0 and total_bytes > max_group_kb * 1024)
        or (max_group_files > 0 and len(items) > max_group_files)
    )

    if not is_oversized:
        return [(curr_slug, items)]

    prefix = "" if curr_dir == "root" else curr_dir + "/"
    direct_files: list[FileRecord] = []
    sub_dirs: dict[str, list[FileRecord]] = defaultdict(list)

    for f in items:
        if curr_dir == "root":
            rel = f.path
        else:
            rel = f.path[len(prefix) :] if f.path.startswith(prefix) else f.path

        if "/" not in rel:
            direct_files.append(f)
        else:
            first_sub = rel.split("/")[0]
            sub_dirs[first_sub].append(f)

    if not sub_dirs:
        return _partition_flat_items(curr_slug, items, file_bytes, max_group_kb, max_group_files)

    results: list[tuple[str, list[FileRecord]]] = []

    if direct_files:
        direct_slug = f"{curr_slug}__root"
        if direct_slug in seen_slugs and seen_slugs[direct_slug] != f"{curr_dir}:root":
            short_hash = hashlib.sha256(f"{curr_dir}:root".encode("utf-8")).hexdigest()[:6]
            direct_slug = f"{direct_slug}__{short_hash}"
        seen_slugs[direct_slug] = f"{curr_dir}:root"

        direct_total = sum(file_bytes[f.path] for f in direct_files) + 150
        is_direct_oversized = (len(direct_files) > 1) and (
            (max_group_kb > 0 and direct_total > max_group_kb * 1024)
            or (max_group_files > 0 and len(direct_files) > max_group_files)
        )
        if is_direct_oversized:
            parts = _partition_flat_items(direct_slug, direct_files, file_bytes, max_group_kb, max_group_files)
            results.extend(parts)
        else:
            results.append((direct_slug, direct_files))

    for sub in sorted(sub_dirs.keys()):
        sub_dir = sub if curr_dir == "root" else f"{curr_dir}/{sub}"
        results.extend(
            _partition_directory(
                sub_dir,
                sub_dirs[sub],
                file_bytes,
                max_group_kb,
                max_group_files,
                seen_slugs,
            )
        )

    return results


def render_repobook(
    out_dir: Path,
    repo_url: str,
    branch: str,
    commit: str,
    files: list[FileRecord],
    entries: list[dict[str, str]],
    split_repobook: bool = True,
    max_group_kb: int = DEFAULT_MAX_GROUP_KB,
    max_group_files: int = DEFAULT_MAX_GROUP_FILES,
    adaptive_partition: bool = True,
) -> list[Path]:
    repodir = out_dir / "RepoBook"
    repodir.mkdir(parents=True, exist_ok=True)
    for old in repodir.glob("*.md"):
        old.unlink()

    text_files = [f for f in files if f.text]
    paths = [f.path for f in files]
    tree = _render_tree(paths)

    root_readmes = [f for f in text_files if Path(f.path).name.lower().startswith("readme")]
    readme_summary = "\n\n".join(f"## {f.path}\n\n{f.content[:2000]}" for f in root_readmes[:2])

    overview = [
        "# RepoBook Overview",
        "",
        f"- Repo: `{repo_url}`",
        f"- Branch: `{branch}`",
        f"- Commit: `{commit}`",
        f"- Files scanned: `{len(files)}`",
        f"- Text files: `{len(text_files)}`",
        "",
        "## Entry Candidates",
        "",
    ]
    if entries:
        overview.extend([f"- `{e['path']}`: {e['why']}" for e in entries])
    else:
        overview.append("- (none)")

    overview.extend(["", "## Directory Tree", "", "```text", tree, "```", "", "## README Summary", "", readme_summary or "(no README found)"])

    def _render_file_section(item: FileRecord) -> list[str]:
        lines = [f"## {item.path}", ""]
        file_commit = getattr(item, "commit", None) or commit
        permalink = get_github_permalink(repo_url, file_commit, item.path)
        if permalink:
            lines.append(f"- Source: `{permalink}`")
        lines.extend(
            [
                f"- Size: `{item.size}` bytes",
                f"- SHA256: `{item.sha256}`",
                f"- Truncated: `{item.truncated}`",
                "",
                f"```{item.lang or ''}",
                item.content,
                "```",
                "",
            ]
        )
        return lines

    if not split_repobook:
        single_lines = list(overview)
        single_lines.extend(["", "# Files", ""])
        for item in sorted(text_files, key=lambda x: x.path):
            single_lines.extend(_render_file_section(item))
        repobook_path = repodir / "RepoBook.md"
        repobook_path.write_text("\n".join(single_lines), encoding="utf-8")
        return [repobook_path]

    overview_path = repodir / "00_overview.md"
    overview_path.write_text("\n".join(overview), encoding="utf-8")

    file_bytes = {
        f.path: len("\n".join(_render_file_section(f)).encode("utf-8")) + 1
        for f in text_files
    }

    groups: dict[str, list[FileRecord]] = defaultdict(list)
    for f in text_files:
        top = f.path.split("/")[0] if "/" in f.path else "root"
        groups[top].append(f)

    generated = [overview_path]
    idx = 1
    seen_slugs: dict[str, str] = {}

    for group, items in sorted(groups.items()):
        items.sort(key=lambda x: x.path)
        group_slug = group.replace("/", "_").replace(".", "_")

        group_total = sum(file_bytes[f.path] for f in items) + 150
        is_oversized = (
            adaptive_partition
            and (len(items) > 1)
            and (
                (max_group_kb > 0 and group_total > max_group_kb * 1024)
                or (max_group_files > 0 and len(items) > max_group_files)
            )
        )

        if not is_oversized:
            chapters = [(group_slug, group, items)]
        else:
            parts = _partition_directory(
                group,
                items,
                file_bytes,
                max_group_kb,
                max_group_files,
                seen_slugs,
            )
            chapters = []
            for p_slug, p_items in parts:
                m = _PART_SLUG_RE.fullmatch(p_slug)
                if p_slug.endswith("__root"):
                    dir_label = f"{p_slug[:-6].replace('__', '/')} (root files)"
                elif m:
                    base_p = m.group("base")
                    p_num = int(m.group("part"))
                    sub_num = m.group("sub")
                    if sub_num is not None:
                        dir_label = f"{base_p.replace('__', '/')} (part {p_num} subpart {int(sub_num)})"
                    else:
                        dir_label = f"{base_p.replace('__', '/')} (part {p_num})"
                else:
                    dir_label = p_slug.replace("__", "/")
                chapters.append((p_slug, dir_label, p_items))

        for sub_slug, dir_label, chapter_items in chapters:
            chapter_items.sort(key=lambda x: x.path)
            ext_count = Counter(Path(i.path).suffix.lower() for i in chapter_items)
            summary = ", ".join([f"{k or 'noext'}:{v}" for k, v in ext_count.most_common(6)])

            lines = [
                f"# RepoBook Chapter: {dir_label}",
                "",
                f"- Directory: `{dir_label}`",
                f"- Files: `{len(chapter_items)}`",
                f"- Types: {summary or '(none)'}",
                "",
            ]

            for item in chapter_items:
                lines.extend(_render_file_section(item))

            chapter_path = repodir / f"{idx:02d}_{sub_slug}.md"
            chapter_path.write_text("\n".join(lines), encoding="utf-8")
            generated.append(chapter_path)

        idx += 1

    return generated


def render_graphbook(out_dir: Path, repo_url: str, branch: str, commit: str, edges: list[ImportEdge], dirs: list[dict[str, object]], entries: list[dict[str, str]]) -> Path:
    indegree = Counter(e.to for e in edges if not e.external)
    top_targets = indegree.most_common(20)

    by_from: dict[str, list[ImportEdge]] = defaultdict(list)
    for e in edges:
        by_from[e.from_file].append(e)

    lines = [
        "# GraphBook",
        "",
        "## Project Overview",
        "",
        f"- Repo: `{repo_url}`",
        f"- Import edges: `{len(edges)}`",
        "",
        "## Entry Candidates",
        "",
    ]

    if entries:
        lines.extend([f"- `{e['path']}`: {e['why']}" for e in entries])
    else:
        lines.append("- (none)")

    lines.extend(["", "## Directory Responsibility Map", ""])
    for d in dirs:
        signals = d.get("signals", [])
        why = "；".join(signals) if signals else "无明显信号"
        lines.append(f"- `{d['path']}`: {d['role']} (why: {why})")

    lines.extend(["", "## Core Dependency Hubs (Top In-Degree)", ""])
    if top_targets:
        for target, score in top_targets:
            lines.append(f"- `{target}`: indegree={score}")
    else:
        lines.append("- (none)")

    lines.extend(["", "## Imports Detail", ""])
    for src in sorted(by_from.keys()):
        lines.append(f"### {src}")
        for e in by_from[src]:
            ext = "external" if e.external else "internal"
            lines.append(f"- -> `{e.to}` ({ext}, line {e.evidence_line}, confidence={e.confidence})")
            lines.append(f"  evidence: `{e.evidence_text}`")
        lines.append("")

    graphbook_path = out_dir / "GraphBook.md"
    graphbook_path.write_text("\n".join(lines), encoding="utf-8")
    return graphbook_path


def write_manifest(
    out_dir: Path,
    repo_url: str,
    branch: str,
    commit: str,
    files: list[FileRecord],
    exclude: list[str],
    max_file_kb: int,
    partition: dict[str, Any] | None = None,
) -> Path:
    manifest = {
        "repo": {"url": repo_url, "default_branch": branch, "commit": commit},
        "files": [
            {
                "path": f.path,
                "sha": f.sha256,
                "size": f.size,
                "lang": f.lang,
                "text": f.text,
                "commit": getattr(f, "commit", None) or commit,
            }
            for f in files
        ],
        "filters": {"exclude": exclude, "max_file_kb": max_file_kb},
        "partition": partition if partition is not None else {
            "adaptive": True,
            "max_group_kb": DEFAULT_MAX_GROUP_KB,
            "max_group_files": DEFAULT_MAX_GROUP_FILES,
            "strategy_version": 2,
        },
    }
    p = out_dir / "manifest.json"
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def derive_legacy_repobook_filenames(files: list[dict[str, Any] | FileRecord]) -> set[str]:
    """Deterministically derive expected legacy RepoBook filenames from a file list."""
    text_paths: list[str] = []
    for f in files:
        if isinstance(f, dict):
            if f.get("text", True):
                text_paths.append(str(f.get("path", "")))
        else:
            if getattr(f, "text", True):
                text_paths.append(str(getattr(f, "path", "")))

    groups: set[str] = set()
    for p in text_paths:
        if not p:
            continue
        top = p.split("/")[0] if "/" in p else "root"
        groups.add(top)

    expected = {"00_overview.md"}
    for idx, group in enumerate(sorted(groups), start=1):
        slug = group.replace("/", "_").replace(".", "_")
        expected.add(f"{idx:02d}_{slug}.md")
    return expected


def resolve_partition_config(
    out_dir: Path,
    previous_manifest_path: Path | None = None,
    adaptive_partition: bool | None = None,
    max_group_kb: int | None = None,
    max_group_files: int | None = None,
    previous_manifest_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve partition strategy and parameters following v0.4.3 rules:
    - Fresh repo / no previous manifest: defaults to adaptive (512 KB, 40 files).
    - Existing manifest with partition metadata: inherits existing partition configuration.
    - Existing manifest without partition metadata (v0.3 / v0.4.2 legacy):
        conservatively identifies legacy if existing RepoBook/*.md files exactly match
        deterministic legacy top-level grouping derivation; otherwise preserves adaptive.
    - Explicit CLI parameters override defaults/inherited values and update manifest.
    """
    manifest_p = previous_manifest_path
    if manifest_p is None:
        candidate = out_dir / "manifest.json"
        if candidate.exists():
            manifest_p = candidate

    prev_data = previous_manifest_data
    if prev_data is None and manifest_p and manifest_p.exists():
        try:
            prev_data = json.loads(manifest_p.read_text(encoding="utf-8"))
        except Exception:
            prev_data = None

    if prev_data is not None and isinstance(prev_data, dict):
        if "partition" in prev_data and isinstance(prev_data["partition"], dict):
            part_meta = prev_data["partition"]
            base_adaptive = bool(part_meta.get("adaptive", True))
            base_max_kb = int(part_meta.get("max_group_kb", DEFAULT_MAX_GROUP_KB))
            base_max_files = int(part_meta.get("max_group_files", DEFAULT_MAX_GROUP_FILES))
        else:
            repodir = out_dir / "RepoBook"
            if not repodir.is_dir() and manifest_p:
                cand_repo = manifest_p.parent / "RepoBook"
                if cand_repo.is_dir():
                    repodir = cand_repo
            existing_mds = {p.name for p in repodir.glob("*.md")} if repodir.is_dir() else set()
            prev_files = prev_data.get("files", []) if isinstance(prev_data, dict) else []
            expected_legacy = derive_legacy_repobook_filenames(prev_files)
            if existing_mds and existing_mds == expected_legacy:
                base_adaptive = False
            else:
                base_adaptive = True
            base_max_kb = DEFAULT_MAX_GROUP_KB
            base_max_files = DEFAULT_MAX_GROUP_FILES
    else:
        base_adaptive = True
        base_max_kb = DEFAULT_MAX_GROUP_KB
        base_max_files = DEFAULT_MAX_GROUP_FILES

    resolved_adaptive = adaptive_partition if adaptive_partition is not None else base_adaptive
    resolved_max_kb = max_group_kb if max_group_kb is not None else base_max_kb
    resolved_max_files = max_group_files if max_group_files is not None else base_max_files

    if resolved_max_kb <= 0 and resolved_max_files <= 0:
        resolved_adaptive = False

    return {
        "adaptive": resolved_adaptive,
        "max_group_kb": resolved_max_kb,
        "max_group_files": resolved_max_files,
        "strategy_version": 2,
    }


def write_graph_json(out_dir: Path, edges: list[ImportEdge], dirs: list[dict[str, object]]) -> Path:
    payload = {
        "edges": [
            {
                "type": e.type,
                "from": e.from_file,
                "to": e.to,
                "evidence": {"line": e.evidence_line, "text": e.evidence_text},
                "confidence": e.confidence,
                "external": e.external,
            }
            for e in edges
        ],
        "dirs": dirs,
    }
    p = out_dir / "graph.json"
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def write_stats(out_dir: Path, stats: dict[str, object]) -> Path:
    p = out_dir / "stats.json"
    p.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def render_changebook(
    out_dir: Path,
    repo_url: str,
    current_commit: str,
    previous_commit: str | None,
    added: list[str],
    modified: list[str],
    deleted: list[str],
) -> Path:
    lines = [
        "# ChangeBook",
        "",
        "## Version",
        "",
        f"- Previous commit: `{previous_commit or '(initial snapshot)'}`",
        f"- Current commit: `{current_commit}`",
        "",
        "## Summary",
        "",
    ]
    if previous_commit:
        lines.extend(
            [
                f"- Added: `{len(added)}` files",
                f"- Modified: `{len(modified)}` files",
                f"- Deleted: `{len(deleted)}` files",
            ]
        )
    else:
        lines.append(f"- Initial snapshot with `{len(added)}` files.")

    lines.extend(["", "## Added Files", ""])
    if added:
        lines.extend([f"- `{p}`" for p in added])
    else:
        lines.append("- (none)")

    lines.extend(["", "## Modified Files", ""])
    if modified:
        lines.extend([f"- `{p}`" for p in modified])
    else:
        lines.append("- (none)")

    lines.extend(["", "## Deleted Files", ""])
    if deleted:
        lines.extend([f"- `{p}`" for p in deleted])
    else:
        lines.append("- (none)")

    p = out_dir / "ChangeBook.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p
