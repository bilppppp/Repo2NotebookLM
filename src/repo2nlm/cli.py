from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from .config import DEFAULT_EXCLUDES
from .git_ops import prepare_repo_snapshot
from .graph_builder import build_graph
from .renderers.books import (
    render_changebook,
    render_graphbook,
    render_repobook,
    write_graph_json,
    write_manifest,
    write_stats,
)
from .scanner import scan_files
from .uploader import upload_to_notebooklm


def _parse_patterns(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def ingest(repo_url: str, out_dir: Path, branch: str | None, commit: str | None, include: str | None, exclude: str | None, max_file_kb: int, split_repobook: bool = True, previous_manifest: Path | None = None) -> dict[str, object]:
    out_dir.mkdir(parents=True, exist_ok=True)
    default_ex = list(DEFAULT_EXCLUDES)
    extra_ex = _parse_patterns(exclude)
    ex_patterns = default_ex + extra_ex

    # 1. Snapshot previous manifest state before any file generation or clone
    prev: dict[str, str] = {}
    prev_commit: str | None = None
    has_previous = False
    if previous_manifest and previous_manifest.exists():
        try:
            prev_data = json.loads(previous_manifest.read_text(encoding="utf-8"))
            prev = {
                x["path"]: x["sha"]
                for x in prev_data.get("files", [])
                if isinstance(x, dict) and "path" in x and "sha" in x
            }
            prev_commit = prev_data.get("repo", {}).get("commit")
            has_previous = True
        except Exception:
            prev = {}
            prev_commit = None
            has_previous = False

    with tempfile.TemporaryDirectory(prefix="repo2nlm_") as td:
        repo_dir = Path(td) / "repo"
        final_branch, final_commit = prepare_repo_snapshot(repo_url, repo_dir, branch, commit)
        files, skipped = scan_files(repo_dir, ex_patterns, max_file_kb)

        if include:
            include_patterns = _parse_patterns(include)
            import fnmatch
            files = [f for f in files if any(fnmatch.fnmatch(f.path, p) for p in include_patterns)]

        edges, dirs, entries, graph_metrics = build_graph(files)

        curr = {f.path: f.sha256 for f in files}
        if has_previous:
            added = sorted([p for p in curr if p not in prev])
            modified = sorted([p for p in curr if p in prev and curr[p] != prev[p]])
            deleted = sorted([p for p in prev if p not in curr])
        else:
            added = sorted(curr.keys())
            modified = []
            deleted = []

        repobook_files = render_repobook(
            out_dir,
            repo_url,
            final_branch,
            final_commit,
            files,
            entries,
            split_repobook=split_repobook,
        )
        graphbook_file = render_graphbook(out_dir, repo_url, final_branch, final_commit, edges, dirs, entries)

        changebook_file: Path | None = None
        changebook_path = out_dir / "ChangeBook.md"
        if not has_previous:
            changebook_file = render_changebook(
                out_dir=out_dir,
                repo_url=repo_url,
                current_commit=final_commit,
                previous_commit=None,
                added=added,
                modified=modified,
                deleted=deleted,
            )
        elif added or modified or deleted:
            changebook_file = render_changebook(
                out_dir=out_dir,
                repo_url=repo_url,
                current_commit=final_commit,
                previous_commit=prev_commit,
                added=added,
                modified=modified,
                deleted=deleted,
            )
        else:
            if changebook_path.exists():
                changebook_file = changebook_path

        manifest_file = write_manifest(out_dir, repo_url, final_branch, final_commit, files, ex_patterns, max_file_kb)
        graph_file = write_graph_json(out_dir, edges, dirs)

        stats = {
            "repo": repo_url,
            "branch": final_branch,
            "commit": final_commit,
            "file_count": len(files),
            "text_file_count": sum(1 for f in files if f.text),
            "skipped": skipped,
            "graph": graph_metrics,
            "changes": {
                "previous_commit": prev_commit,
                "added": added,
                "modified": modified,
                "deleted": deleted,
            },
            "changed_files": sorted(added + modified) if has_previous else sorted(curr.keys()),
            "deleted_files": deleted,
            "outputs": {
                "repobook_files": [str(x) for x in repobook_files],
                "graphbook": str(graphbook_file),
                "changebook": str(changebook_file) if changebook_file else None,
                "manifest": str(manifest_file),
                "graph": str(graph_file),
            },
        }
        stats_file = write_stats(out_dir, stats)
        stats["outputs"]["stats"] = str(stats_file)
        return stats


def cmd_ingest(args: argparse.Namespace) -> int:
    stats = ingest(
        repo_url=args.repo_url,
        out_dir=Path(args.out),
        branch=args.branch,
        commit=args.commit,
        include=args.include,
        exclude=args.exclude,
        max_file_kb=args.max_file_kb,
        split_repobook=not args.no_split_repobook,
        previous_manifest=None,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    prev_manifest = out_dir / "manifest.json"
    stats = ingest(
        repo_url=args.repo_url,
        out_dir=out_dir,
        branch=args.branch,
        commit=args.commit,
        include=args.include,
        exclude=args.exclude,
        max_file_kb=args.max_file_kb,
        split_repobook=not args.no_split_repobook,
        previous_manifest=prev_manifest,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


def cmd_upload(args: argparse.Namespace) -> int:
    upload_to_notebooklm(
        [Path(out) for out in args.out],
        args.notebook,
        create_if_missing=args.create_if_missing,
        replace_existing=args.replace_existing,
    )
    joined_outs = ", ".join(args.out)
    print(f"uploaded markdown sources from {joined_outs} to notebook {args.notebook}")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    prev_manifest = out_dir / "manifest.json"
    stats = ingest(
        repo_url=args.repo_url,
        out_dir=out_dir,
        branch=args.branch,
        commit=args.commit,
        include=args.include,
        exclude=args.exclude,
        max_file_kb=args.max_file_kb,
        split_repobook=not args.no_split_repobook,
        previous_manifest=prev_manifest if prev_manifest.exists() else None,
    )
    upload_to_notebooklm(
        [out_dir],
        notebook=args.notebook,
        create_if_missing=args.create_if_missing,
        replace_existing=args.replace_existing,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="repo2nlm", description="Repo -> NotebookLM structured importer")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("repo_url")
        p.add_argument("--branch")
        p.add_argument("--commit")
        p.add_argument("--out", default="./out")
        p.add_argument("--include", default=None, help="comma-separated glob patterns")
        p.add_argument("--exclude", default=None, help="comma-separated glob patterns")
        p.add_argument("--max-file-kb", type=int, default=200)
        p.add_argument("--no-split-repobook", action="store_true")

    p_sync = sub.add_parser("sync", help="snapshot repo, generate books, and incrementally sync to notebooklm")
    add_common(p_sync)
    p_sync.add_argument("--notebook", required=True, help="notebook id or name")
    p_sync.add_argument("--create-if-missing", action="store_true")
    p_sync.add_argument(
        "--replace-existing",
        action="store_true",
        help="force full replacement of matching remote sources",
    )
    p_sync.set_defaults(func=cmd_sync)

    p_ingest = sub.add_parser("ingest", help="ingest a repo and generate artifacts")
    add_common(p_ingest)
    p_ingest.set_defaults(func=cmd_ingest)

    p_update = sub.add_parser("update", help="update existing out/ incrementally")
    add_common(p_update)
    p_update.set_defaults(func=cmd_update)

    p_upload = sub.add_parser("upload", help="upload generated markdown to notebooklm")
    p_upload.add_argument("out", nargs="+")
    p_upload.add_argument("--notebook", required=True, help="notebook id or name")
    p_upload.add_argument("--create-if-missing", action="store_true")
    p_upload.add_argument(
        "--replace-existing",
        action="store_true",
        help="delete same-title remote sources before upload to guarantee fresh content",
    )
    p_upload.set_defaults(func=cmd_upload)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
