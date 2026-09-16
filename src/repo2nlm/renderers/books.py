from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from ..types import FileRecord, ImportEdge


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


def render_repobook(
    out_dir: Path,
    repo_url: str,
    branch: str,
    commit: str,
    files: list[FileRecord],
    entries: list[dict[str, str]],
    split_repobook: bool = True,
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
        permalink = get_github_permalink(repo_url, commit, item.path)
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

    groups: dict[str, list[FileRecord]] = defaultdict(list)
    for f in text_files:
        top = f.path.split("/")[0] if "/" in f.path else "root"
        groups[top].append(f)

    generated = [overview_path]
    idx = 1
    for group, items in sorted(groups.items()):
        items.sort(key=lambda x: x.path)
        ext_count = Counter(Path(i.path).suffix.lower() for i in items)
        summary = ", ".join([f"{k or 'noext'}:{v}" for k, v in ext_count.most_common(6)])

        lines = [
            f"# RepoBook Chapter: {group}",
            "",
            f"- Directory: `{group}`",
            f"- Files: `{len(items)}`",
            f"- Types: {summary or '(none)'}",
            "",
        ]

        for item in items:
            lines.extend(_render_file_section(item))

        chapter_path = repodir / f"{idx:02d}_{group.replace('/', '_').replace('.', '_')}.md"
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
        f"- Branch: `{branch}`",
        f"- Commit: `{commit}`",
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


def write_manifest(out_dir: Path, repo_url: str, branch: str, commit: str, files: list[FileRecord], exclude: list[str], max_file_kb: int) -> Path:
    manifest = {
        "repo": {"url": repo_url, "default_branch": branch, "commit": commit},
        "files": [
            {
                "path": f.path,
                "sha": f.sha256,
                "size": f.size,
                "lang": f.lang,
                "text": f.text,
            }
            for f in files
        ],
        "filters": {"exclude": exclude, "max_file_kb": max_file_kb},
    }
    p = out_dir / "manifest.json"
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


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
