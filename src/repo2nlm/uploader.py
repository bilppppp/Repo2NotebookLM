from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Client-side stability thresholds for notebooklm-py transport.
# Note: Google Gemini Notebook official limits are up to 200 MB per source (500,000 words)
# and 50 sources per notebook (up to 600 on paid plans).
# The thresholds below are empirical client-side workarounds preventing HTTP timeouts
# and upload stream stalls when uploading large Markdown files through reverse-engineered APIs.
_CLIENT_STABILITY_MAX_SOURCE_BYTES = 4 * 1024 * 1024  # 4 MB threshold to trigger chunking
_CLIENT_STABILITY_SPLIT_CHUNK_BYTES = 2 * 1024 * 1024  # 2 MB chunk size for split parts
_AUTO_LARGE_FILE_THRESHOLD = 80
_AUTO_LARGE_TOTAL_BYTES_THRESHOLD = 64 * 1024 * 1024
_AUTO_LARGE_BATCH_SIZE = 20


@dataclass(frozen=True)
class UploadSource:
    out_dir: Path
    namespace: str
    original_title: str
    upload_path: Path


def _run(args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(args, capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _run_json(args: list[str]) -> dict[str, Any]:
    rc, out, err = _run(args)
    if rc != 0:
        raise RuntimeError(f"command failed: {' '.join(args)}: {err or out}")
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid json output from: {' '.join(args)}") from exc


def _resolve_notebook_id(cli: str, notebook: str, create_if_missing: bool) -> str:
    payload = _run_json([cli, "list", "--json"])
    notebooks = payload.get("notebooks", [])
    for nb in notebooks:
        if nb.get("id") == notebook or nb.get("title") == notebook:
            return str(nb["id"])

    if not create_if_missing:
        raise RuntimeError(f"notebook not found: {notebook}")

    created = _run_json([cli, "create", notebook, "--json"])
    nb = created.get("notebook", {})
    nb_id = nb.get("id")
    if not nb_id:
        raise RuntimeError(f"failed to create notebook: {notebook}")
    return str(nb_id)


def _split_markdown(src: Path, dst_dir: Path, chunk_bytes: int = _CLIENT_STABILITY_SPLIT_CHUNK_BYTES) -> list[Path]:
    dst_dir.mkdir(parents=True, exist_ok=True)
    text = src.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    parts: list[str] = []
    buf: list[str] = []
    size = 0
    for line in lines:
        line_size = len(line.encode("utf-8", errors="ignore"))
        if buf and size + line_size > chunk_bytes:
            parts.append("".join(buf))
            buf = []
            size = 0
        buf.append(line)
        size += line_size
    if buf:
        parts.append("".join(buf))

    out: list[Path] = []
    for i, part in enumerate(parts, start=1):
        p = dst_dir / f"{src.stem}.part{i:02d}{src.suffix}"
        header = (
            f"# Split Source: {src.name} (part {i}/{len(parts)})\n\n"
            "This file was auto-split for NotebookLM upload reliability.\n\n"
        )
        p.write_text(header + part, encoding="utf-8")
        out.append(p)
    return out


def _namespace_for_out_dir(out_dir: Path) -> str:
    name = out_dir.name
    if name.startswith("out-") and len(name) > 4:
        return name[4:]
    return name


def _source_title(src: Path, namespace: str | None) -> str:
    if not namespace:
        return src.name
    return f"{namespace}__{src.name}"


def _copy_with_title(src: Path, staged_dir: Path, title: str) -> Path:
    staged_dir.mkdir(parents=True, exist_ok=True)
    dst = staged_dir / title
    shutil.copy2(src, dst)
    return dst


def _iter_markdown_sources(out_dir: Path) -> list[Path]:
    sources = sorted((out_dir / "RepoBook").glob("*.md"))
    graphbook = out_dir / "GraphBook.md"
    if graphbook.exists():
        sources.append(graphbook)
    changebook = out_dir / "ChangeBook.md"
    if changebook.exists():
        sources.append(changebook)
    return sources


def _read_stats(out_dir: Path) -> dict[str, Any]:
    stats_file = out_dir / "stats.json"
    if not stats_file.exists():
        return {}
    try:
        return json.loads(stats_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_workspace_index(out_dirs: list[Path], staged_dir: Path) -> Path:
    staged_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Workspace Index",
        "",
        "This source summarizes the repositories uploaded together into this NotebookLM notebook.",
        "",
        "## Repositories",
        "",
    ]
    repo_names: list[str] = []
    for out_dir in out_dirs:
        stats = _read_stats(out_dir)
        repo_name = _namespace_for_out_dir(out_dir)
        repo_names.append(repo_name)
        outputs = stats.get("outputs", {}) if isinstance(stats, dict) else {}
        repobook_files = outputs.get("repobook_files", []) if isinstance(outputs, dict) else []
        lines.extend(
            [
                f"### {repo_name}",
                "",
                f"- Repo: `{stats.get('repo', '(unknown)')}`",
                f"- Branch: `{stats.get('branch', '(unknown)')}`",
                f"- Commit: `{stats.get('commit', '(unknown)')}`",
                f"- Files scanned: `{stats.get('file_count', '(unknown)')}`",
                f"- Text files: `{stats.get('text_file_count', '(unknown)')}`",
                f"- RepoBook chapters: `{len(repobook_files)}`",
                f"- Graph source title: `{repo_name}__GraphBook.md`",
                "",
                "Suggested source title prefix:",
                "",
                f"- `{repo_name}__...`",
                "",
            ]
        )
    lines.extend(
        [
            "## Cross-Repo Questions",
            "",
            f"- Compare architecture and abstractions across: {', '.join(f'`{name}`' for name in repo_names)}",
            f"- Identify similar modules or responsibilities across: {', '.join(f'`{name}`' for name in repo_names)}",
            f"- Explain how implementation style differs between: {', '.join(f'`{name}`' for name in repo_names)}",
            "",
            "## Query Tips",
            "",
            "- Include the repo prefix in your question when you want a specific repository.",
            "- Ask for contrasts explicitly when you want NotebookLM to compare two or more repositories.",
            "- Start from `WorkspaceIndex.md` when you need a high-level map of the combined notebook.",
            "",
        ]
    )
    index_path = staged_dir / "WorkspaceIndex.md"
    index_path.write_text("\n".join(lines), encoding="utf-8")
    return index_path


def _collect_upload_source_specs(out_dirs: list[Path], staged_dir: Path) -> list[UploadSource]:
    multi_out = len(out_dirs) > 1
    specs: list[UploadSource] = []
    if multi_out:
        index_path = _write_workspace_index(out_dirs, staged_dir)
        specs.append(
            UploadSource(
                out_dir=out_dirs[0],
                namespace="",
                original_title=index_path.name,
                upload_path=index_path,
            )
        )
    for out_dir in out_dirs:
        namespace = _namespace_for_out_dir(out_dir) if multi_out else ""
        for src in _iter_markdown_sources(out_dir):
            upload_path = src if not multi_out else _copy_with_title(
                src,
                staged_dir,
                _source_title(src, namespace),
            )
            specs.append(
                UploadSource(
                    out_dir=out_dir,
                    namespace=namespace,
                    original_title=src.name,
                    upload_path=upload_path,
                )
            )
    return sorted(specs, key=lambda spec: spec.upload_path.name)


def _collect_upload_sources(out_dirs: list[Path], staged_dir: Path) -> list[Path]:
    return [spec.upload_path for spec in _collect_upload_source_specs(out_dirs, staged_dir)]


def _prepare_sources_for_upload(
    sources: list[UploadSource],
    tmp_dir: Path,
    max_bytes: int = _CLIENT_STABILITY_MAX_SOURCE_BYTES,
) -> tuple[list[UploadSource], set[str]]:
    upload_specs: list[UploadSource] = []
    purge_titles: set[str] = set()
    for spec in sources:
        src = spec.upload_path
        if src.stat().st_size <= max_bytes:
            upload_specs.append(spec)
            continue
        purge_titles.add(src.name)
        for split_path in _split_markdown(src, tmp_dir):
            upload_specs.append(
                UploadSource(
                    out_dir=spec.out_dir,
                    namespace=spec.namespace,
                    original_title=spec.original_title,
                    upload_path=split_path,
                )
            )
    return upload_specs, purge_titles


def _check_notebooklm_version(cli: str) -> str:
    rc, out, _ = _run([cli, "--version"])
    if rc != 0 or not out:
        return "unknown"
    return out


def _read_previous_upload_map(out_dir: Path) -> dict[str, Any]:
    p = out_dir / "upload_map.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _list_sources(cli: str, notebook_id: str) -> list[dict[str, Any]]:
    payload = _run_json([cli, "source", "list", "-n", notebook_id, "--json"])
    return payload.get("sources", [])


def _delete_source(
    cli: str,
    notebook_id: str,
    source_id: str,
    allowed_ids: set[str] | None = None,
) -> None:
    if allowed_ids is not None and source_id not in allowed_ids:
        raise PermissionError(
            f"Security guard: refusing to delete unmanaged source ID '{source_id}' "
            f"which is not in previous managed IDs!"
        )
    rc, out, err = _run([cli, "source", "delete", source_id, "-n", notebook_id, "-y"])
    if rc != 0:
        raise RuntimeError(f"failed to delete source {source_id}: {err or out}")


def _upload_source(cli: str, notebook_id: str, src: Path) -> tuple[bool, str | None]:
    rc, out, err = _run(
        [
            cli,
            "source",
            "add",
            str(src.resolve()),
            "-n",
            notebook_id,
            "--follow-symlinks",
            "--json",
        ]
    )
    if rc != 0:
        return False, None
    source_id: str | None = None
    try:
        data = json.loads(out)
        source_id = str(data.get("source", {}).get("id", "")) or None
    except Exception:
        pass
    return True, source_id


def _wait_source(cli: str, notebook_id: str, source_id: str, timeout: int = 300) -> bool:
    rc, out, err = _run([cli, "source", "wait", source_id, "-n", notebook_id, "--timeout", str(timeout)])
    return rc == 0


def _upload_and_wait(cli: str, notebook_id: str, src: Path) -> bool:
    ok, source_id = _upload_source(cli, notebook_id, src)
    if not ok:
        return False
    if source_id:
        return _wait_source(cli, notebook_id, source_id)
    return True


def _is_split_title(title: str) -> bool:
    return bool(re.search(r"\.part\d{2}\.md$", title))


def _chunked(items: list[Any], chunk_size: int) -> list[list[Any]]:
    if chunk_size <= 0:
        return [items]
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


def _choose_upload_strategy(upload_sources: list[Path]) -> dict[str, int | str]:
    total_bytes = sum(p.stat().st_size for p in upload_sources)
    file_count = len(upload_sources)
    large = (
        file_count >= _AUTO_LARGE_FILE_THRESHOLD
        or total_bytes >= _AUTO_LARGE_TOTAL_BYTES_THRESHOLD
    )
    return {
        "mode": "large-auto" if large else "standard",
        "file_count": file_count,
        "total_bytes": total_bytes,
        "batch_size": _AUTO_LARGE_BATCH_SIZE if large else file_count,
    }


def _read_local_commit(out_dir: Path) -> str | None:
    stats_file = out_dir / "stats.json"
    if not stats_file.exists():
        return None
    try:
        payload = json.loads(stats_file.read_text(encoding="utf-8"))
    except Exception:
        return None
    commit = payload.get("commit")
    return str(commit) if commit else None


@dataclass(frozen=True)
class SyncPlan:
    to_delete_ids: set[str]
    to_upload: list[UploadSource]
    unchanged_titles: set[str]
    stats: dict[str, int]
    replacements: dict[str, list[str]] = field(default_factory=dict)
    all_prev_managed_ids: set[str] = field(default_factory=set)


def _plan_sync(
    out_dirs: list[Path],
    upload_specs: list[UploadSource],
    purge_titles: set[str],
    remote_sources: list[dict[str, Any]],
    replace_existing: bool = False,
) -> SyncPlan:
    remote_by_title: dict[str, list[dict[str, Any]]] = {}
    remote_by_id: dict[str, dict[str, Any]] = {}
    for r in remote_sources:
        title = str(r.get("title", ""))
        rid = str(r.get("id", ""))
        remote_by_title.setdefault(title, []).append(r)
        remote_by_id[rid] = r

    all_prev_managed_ids: set[str] = set()
    all_prev_managed_titles: set[str] = set()
    prev_title_to_sha: dict[str, str] = {}

    for out_dir in out_dirs:
        prev_map = _read_previous_upload_map(out_dir)
        for item in prev_map.get("items", []):
            for r in item.get("remote_sources", []):
                if r.get("id"):
                    all_prev_managed_ids.add(str(r["id"]))
            for t in item.get("uploaded_titles", []):
                all_prev_managed_titles.add(t)
            for part in item.get("parts", []):
                if part.get("remote_source_id"):
                    all_prev_managed_ids.add(str(part["remote_source_id"]))
                if part.get("title") and part.get("local_sha256"):
                    prev_title_to_sha[part["title"]] = part["local_sha256"]
            if not item.get("parts") and item.get("local_sha256"):
                for t in item.get("uploaded_titles", []):
                    prev_title_to_sha[t] = item["local_sha256"]

    expected_titles = {spec.upload_path.name for spec in upload_specs}
    to_delete_ids: set[str] = set()

    # 1. Purged titles (e.g., an unsplit source that is now split)
    # Strictly guarded: only delete remote sources if rid in all_prev_managed_ids (or replace_existing)
    for pt in purge_titles:
        for r in remote_by_title.get(pt, []):
            rid = str(r.get("id", ""))
            if replace_existing or rid in all_prev_managed_ids:
                to_delete_ids.add(rid)

    # 2. Stale/deleted titles previously uploaded by this project
    # Strictly guarded: only delete remote sources if rid in all_prev_managed_ids
    for old_title in all_prev_managed_titles:
        if old_title not in expected_titles:
            for r in remote_by_title.get(old_title, []):
                rid = str(r.get("id", ""))
                if replace_existing or rid in all_prev_managed_ids:
                    to_delete_ids.add(rid)

    for pid in all_prev_managed_ids:
        r = remote_by_id.get(pid)
        if r and r.get("title") not in expected_titles:
            to_delete_ids.add(pid)

    # 3. Classify current planned upload specs
    to_upload: list[UploadSource] = []
    unchanged_titles: set[str] = set()
    replacements: dict[str, list[str]] = {}

    for spec in upload_specs:
        title = spec.upload_path.name
        spec_sha = hashlib.sha256(spec.upload_path.read_bytes()).hexdigest()
        remote_matches = [
            r for r in remote_by_title.get(title, [])
            if str(r.get("id", "")) not in to_delete_ids
        ]

        if replace_existing:
            managed_matches = remote_matches
        else:
            managed_matches = [
                r for r in remote_matches
                if str(r.get("id", "")) in all_prev_managed_ids
            ]

        ready_matches = [r for r in managed_matches if r.get("status") == "ready"]
        prev_sha = prev_title_to_sha.get(title)

        is_unchanged = (
            not replace_existing
            and bool(ready_matches)
            and prev_sha is not None
            and prev_sha == spec_sha
        )

        if is_unchanged:
            unchanged_titles.add(title)
            for extra in managed_matches[1:]:
                to_delete_ids.add(str(extra["id"]))
        else:
            to_upload.append(spec)
            old_managed_ids = [str(r["id"]) for r in managed_matches if str(r.get("id", ""))]
            if old_managed_ids:
                replacements[title] = old_managed_ids
            if replace_existing:
                for r in managed_matches:
                    to_delete_ids.add(str(r["id"]))

    stats = {
        "unchanged": len(unchanged_titles),
        "uploading": len(to_upload),
        "deleted": len(to_delete_ids) + sum(len(v) for v in replacements.values()),
        "total_expected": len(expected_titles),
    }
    return SyncPlan(
        to_delete_ids=to_delete_ids,
        to_upload=to_upload,
        unchanged_titles=unchanged_titles,
        stats=stats,
        replacements=replacements,
        all_prev_managed_ids=all_prev_managed_ids,
    )


def _build_upload_maps(
    out_dirs: list[Path],
    notebook_id: str,
    notebook: str,
    replace_existing: bool,
    strategy: dict[str, int | str],
    ready_titles: set[str | None],
    missing: list[str],
    by_title: dict[str, list[dict[str, Any]]],
    by_original: dict[Path, dict[str, list[str]]],
    upload_specs: list[UploadSource],
    cli_version: str = "unknown",
    sync_stats: dict[str, int] | None = None,
    current_managed_ids: set[str] | None = None,
) -> None:
    for out_dir in out_dirs:
        source_items: list[dict[str, Any]] = []
        original_map = by_original.get(out_dir, {})
        out_upload_specs = [spec for spec in upload_specs if spec.out_dir == out_dir]
        expected_titles = {spec.upload_path.name for spec in out_upload_specs}
        for original in sorted(original_map):
            uploaded_titles = sorted(original_map[original])
            remote_sources: list[dict[str, Any]] = []
            parts_info: list[dict[str, Any]] = []

            orig_specs = [
                spec for spec in out_upload_specs
                if (f"{spec.namespace}/{spec.original_title}" if spec.namespace else spec.original_title) == original
            ]
            orig_sha = ""
            if orig_specs:
                orig_file = orig_specs[0].out_dir / "RepoBook" / orig_specs[0].original_title
                if not orig_file.exists():
                    orig_file = orig_specs[0].out_dir / orig_specs[0].original_title
                if orig_file.exists():
                    orig_sha = hashlib.sha256(orig_file.read_bytes()).hexdigest()

            for title in uploaded_titles:
                matching_remotes = by_title.get(title, [])
                if current_managed_ids:
                    managed_matches = [r for r in matching_remotes if str(r.get("id")) in current_managed_ids]
                    chosen_remotes = managed_matches if managed_matches else matching_remotes
                else:
                    chosen_remotes = matching_remotes

                remote_sources.extend(chosen_remotes)
                spec_match = next((s for s in orig_specs if s.upload_path.name == title), None)
                part_sha = (
                    hashlib.sha256(spec_match.upload_path.read_bytes()).hexdigest()
                    if spec_match and spec_match.upload_path.exists()
                    else ""
                )
                r_id = chosen_remotes[0].get("id") if chosen_remotes else None
                r_status = chosen_remotes[0].get("status") if chosen_remotes else None
                parts_info.append(
                    {
                        "title": title,
                        "local_sha256": part_sha,
                        "remote_source_id": r_id,
                        "status": r_status,
                    }
                )

            source_items.append(
                {
                    "original": original,
                    "logical_source": original,
                    "local_sha256": orig_sha or (parts_info[0]["local_sha256"] if parts_info else ""),
                    "uploaded_titles": uploaded_titles,
                    "split": len(uploaded_titles) > 1,
                    "parts": parts_info,
                    "remote_sources": remote_sources,
                }
            )

        upload_map = {
            "notebooklm_version": cli_version,
            "notebook_id": notebook_id,
            "requested_notebook": notebook,
            "local_commit": _read_local_commit(out_dir),
            "replace_existing": replace_existing,
            "upload_mode": strategy["mode"],
            "batch_size": strategy["batch_size"],
            "file_count": len(expected_titles),
            "total_bytes": sum(spec.upload_path.stat().st_size for spec in out_upload_specs),
            "expected_titles_count": len(expected_titles),
            "ready_titles_count": len(
                {title for title in expected_titles if title in ready_titles}
            ),
            "missing_titles": sorted(
                title for title in expected_titles if title in missing
            ),
            "sync_stats": sync_stats or {},
            "items": source_items,
        }
        (out_dir / "upload_map.json").write_text(
            json.dumps(upload_map, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def upload_to_notebooklm(
    out_dirs: list[Path],
    notebook: str,
    create_if_missing: bool = False,
    replace_existing: bool = False,
) -> None:
    cli = shutil.which("notebooklm")
    if not cli:
        raise RuntimeError(
            "notebooklm CLI not found. Activate venv and install notebooklm-py "
            "(e.g., pip install 'notebooklm-py>=0.8.2,<0.9.0')."
        )

    cli_version = _check_notebooklm_version(cli)
    notebook_id = _resolve_notebook_id(cli, notebook, create_if_missing=create_if_missing)

    with tempfile.TemporaryDirectory(prefix="repo2nlm_upload_") as td:
        raw_sources = _collect_upload_source_specs(out_dirs, Path(td) / "staged")
        if not raw_sources:
            raise RuntimeError("no markdown sources found under output directories")

        upload_specs, purge_titles = _prepare_sources_for_upload(raw_sources, Path(td) / "split")
        upload_sources = [spec.upload_path for spec in upload_specs]
        strategy = _choose_upload_strategy(upload_sources)
        expected_titles = {spec.upload_path.name for spec in upload_specs}
        by_original: dict[Path, dict[str, list[str]]] = {}
        for spec in upload_specs:
            original_key = (
                f"{spec.namespace}/{spec.original_title}"
                if spec.namespace
                else spec.original_title
            )
            by_original.setdefault(spec.out_dir, {}).setdefault(original_key, []).append(
                spec.upload_path.name
            )

        # 1. Fetch remote sources
        remote = _list_sources(cli, notebook_id)

        # 2. Plan incremental sync
        plan = _plan_sync(
            out_dirs=out_dirs,
            upload_specs=upload_specs,
            purge_titles=purge_titles,
            remote_sources=remote,
            replace_existing=replace_existing,
        )

        # 3. Safely delete obsolete or purged sources belonging to this repo
        # Ownership guard: only allowed IDs (managed or explicitly requested by replace_existing) can be deleted
        allowed_delete_ids = set(plan.all_prev_managed_ids)
        if replace_existing:
            allowed_delete_ids.update(plan.to_delete_ids)

        for rid in sorted(plan.to_delete_ids):
            _delete_source(cli, notebook_id, rid, allowed_ids=allowed_delete_ids)

        # 4. Upload added or modified sources in batches
        staging_dir = Path(td) / "staging"
        staging_dir.mkdir(parents=True, exist_ok=True)
        active_managed_ids: set[str] = set()

        batches = _chunked(plan.to_upload, int(strategy["batch_size"]))
        for batch in batches:
            for spec in batch:
                title = spec.upload_path.name
                old_managed_ids = plan.replacements.get(title, [])

                if not old_managed_ids or replace_existing:
                    # Direct upload for newly added sources or explicit replace_existing mode
                    src = spec.upload_path
                    ok = False
                    new_id: str | None = None
                    for _ in range(3):
                        ok, new_id = _upload_source(cli, notebook_id, src)
                        if ok:
                            break
                    if not ok:
                        raise RuntimeError(f"failed to upload source {src}")
                    if new_id:
                        _wait_source(cli, notebook_id, new_id)
                        active_managed_ids.add(new_id)
                else:
                    # STAGED REPLACEMENT for modified sources:
                    # Guarantees old source remains intact and queryable if upload fails
                    staged_stem = f"_staging_{uuid.uuid4().hex[:8]}_{spec.upload_path.stem}"
                    staged_path = staging_dir / f"{staged_stem}{spec.upload_path.suffix}"
                    staged_path.write_bytes(spec.upload_path.read_bytes())

                    ok = False
                    staged_id: str | None = None
                    for _ in range(3):
                        ok, staged_id = _upload_source(cli, notebook_id, staged_path)
                        if ok:
                            break
                    if not ok:
                        # Upload failed: old_managed_ids and user manual sources remain intact!
                        raise RuntimeError(f"failed to upload staged source for {title} ({spec.upload_path})")

                    if not staged_id:
                        remotes = _list_sources(cli, notebook_id)
                        for r in remotes:
                            if r.get("title") == staged_path.name:
                                staged_id = str(r.get("id"))
                                break
                    if not staged_id:
                        raise RuntimeError(f"staged source {staged_path.name} was not found on remote")

                    wait_ok = _wait_source(cli, notebook_id, staged_id)
                    if not wait_ok:
                        try:
                            _delete_source(cli, notebook_id, staged_id, allowed_ids={staged_id})
                        except Exception:
                            pass
                        raise RuntimeError(f"staged source {staged_path.name} failed to reach ready")

                    # Staged source verified ready! Delete old managed source(s)
                    for old_id in old_managed_ids:
                        _delete_source(cli, notebook_id, old_id, allowed_ids=plan.all_prev_managed_ids)

                    # Rename staged source to canonical title
                    rc, out, err = _run([cli, "source", "rename", staged_id, title, "-n", notebook_id])
                    if rc != 0:
                        raise RuntimeError(
                            f"failed to rename staged source '{staged_id}' to intended canonical title '{title}': {err or out}. "
                            f"The staged source remains ready and safe on remote with ID '{staged_id}'. "
                            f"No data was lost; new data is preserved and can be manually recovered or renamed."
                        )
                    active_managed_ids.add(staged_id)

        # 5. Final reconciliation: ensure every expected source exists and is ready
        remote = _list_sources(cli, notebook_id)
        by_title: dict[str, list[dict[str, Any]]] = {}
        for r in remote:
            by_title.setdefault(str(r.get("title")), []).append(r)

        for title, rows in by_title.items():
            if title not in expected_titles:
                continue
            if any(r.get("status") == "ready" for r in rows):
                continue
            for r in rows:
                if r.get("status") == "processing":
                    _wait_source(cli, notebook_id, str(r["id"]))

        remote = _list_sources(cli, notebook_id)
        ready_titles = {r.get("title") for r in remote if r.get("status") == "ready"}
        missing = sorted(t for t in expected_titles if t not in ready_titles)
        if missing:
            raise RuntimeError(f"upload verification failed, missing/not-ready sources: {missing}")

        # Build upload reconciliation map
        by_title = {}
        for r in remote:
            by_title.setdefault(str(r.get("title")), []).append(
                {
                    "id": r.get("id"),
                    "status": r.get("status"),
                    "type": r.get("type"),
                    "created_at": r.get("created_at"),
                }
            )

        all_current_managed_ids = active_managed_ids.union(plan.all_prev_managed_ids)

        _build_upload_maps(
            out_dirs=out_dirs,
            notebook_id=notebook_id,
            notebook=notebook,
            replace_existing=replace_existing,
            strategy=strategy,
            ready_titles=ready_titles,
            missing=missing,
            by_title=by_title,
            by_original=by_original,
            upload_specs=upload_specs,
            cli_version=cli_version,
            sync_stats=plan.stats,
            current_managed_ids=all_current_managed_ids,
        )
