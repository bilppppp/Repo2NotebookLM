from __future__ import annotations

import ast
import posixpath
import re
from collections import Counter, defaultdict
from pathlib import Path

from .config import ENTRY_CANDIDATES
from .types import FileRecord, ImportEdge

RE_IMPORT_FROM = re.compile(r"^\s*import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]")
RE_REQUIRE = re.compile(r"require\(\s*['\"]([^'\"]+)['\"]\s*\)")
RE_DYNAMIC_IMPORT = re.compile(r"import\(\s*['\"]([^'\"]+)['\"]\s*\)")


def _module_from_path(path: str) -> str:
    p = Path(path)
    if p.name == "__init__.py":
        return ".".join(p.parent.parts)
    return ".".join(p.with_suffix("").parts)


def _python_module_index(files: list[FileRecord]) -> dict[str, str]:
    idx: dict[str, str] = {}
    for f in files:
        if f.path.endswith(".py"):
            mod = _module_from_path(f.path)
            if mod:
                idx[mod] = f.path
    return idx


def _resolve_python_import(module_index: dict[str, str], current_path: str, module: str | None, level: int) -> tuple[str, bool]:
    current_mod = _module_from_path(current_path)
    current_pkg = current_mod if current_path.endswith("__init__.py") else ".".join(current_mod.split(".")[:-1])

    target_mod = module or ""
    if level > 0:
        parts = current_pkg.split(".") if current_pkg else []
        base_parts = parts[: max(0, len(parts) - level + 1)]
        if target_mod:
            base_parts.extend(target_mod.split("."))
        target_mod = ".".join(p for p in base_parts if p)

    if target_mod in module_index:
        return module_index[target_mod], False

    probe = target_mod
    while probe:
        if probe in module_index:
            return module_index[probe], False
        if "." not in probe:
            break
        probe = probe.rsplit(".", 1)[0]

    return (target_mod or module or "<unknown>"), True


def _resolve_js_import(current: str, spec: str, file_set: set[str]) -> tuple[str, bool]:
    if not spec.startswith(".") and not spec.startswith("/"):
        return spec, True

    curr_norm = current.replace("\\", "/")
    base_dir = posixpath.dirname(curr_norm)

    if spec.startswith("/"):
        rel_target = spec.lstrip("/")
    else:
        rel_target = posixpath.join(base_dir, spec) if base_dir else spec

    norm_target = posixpath.normpath(rel_target)
    if norm_target == "." or norm_target.startswith("../"):
        return spec, True

    candidates: list[str] = []

    ext = posixpath.splitext(norm_target)[1]
    if ext:
        candidates.append(norm_target)
        if ext in {".js", ".jsx", ".mjs", ".cjs"}:
            stem = posixpath.splitext(norm_target)[0]
            for ts_ext in [".ts", ".tsx", ".mts", ".cts"]:
                candidates.append(stem + ts_ext)

    default_exts = [".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".json"]
    for e in default_exts:
        if not norm_target.endswith(e):
            candidates.append(norm_target + e)

    index_exts = [".ts", ".tsx", ".js", ".jsx", ".mts", ".cts"]
    for e in index_exts:
        candidates.append(posixpath.join(norm_target, f"index{e}"))

    for c in candidates:
        if c in file_set:
            return c, False

    fallback = candidates[0] if candidates else norm_target
    return fallback, not (fallback in file_set)


def _build_python_edges(py_files: list[FileRecord], module_index: dict[str, str]) -> list[ImportEdge]:
    edges: list[ImportEdge] = []
    for f in py_files:
        try:
            tree = ast.parse(f.content)
        except SyntaxError:
            continue
        lines = f.content.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target, external = _resolve_python_import(module_index, f.path, alias.name, 0)
                    line = getattr(node, "lineno", 1)
                    evidence = lines[line - 1].strip() if 0 < line <= len(lines) else f"import {alias.name}"
                    edges.append(ImportEdge("imports", f.path, target, line, evidence, "high", external))
            elif isinstance(node, ast.ImportFrom):
                target, external = _resolve_python_import(module_index, f.path, node.module, node.level)
                line = getattr(node, "lineno", 1)
                evidence = lines[line - 1].strip() if 0 < line <= len(lines) else "from ... import ..."
                edges.append(ImportEdge("imports", f.path, target, line, evidence, "high", external))

    return edges


def _build_js_edges(js_files: list[FileRecord], file_set: set[str]) -> list[ImportEdge]:
    edges: list[ImportEdge] = []
    for f in js_files:
        lines = f.content.splitlines()
        for i, line in enumerate(lines, start=1):
            specs = []
            m = RE_IMPORT_FROM.search(line)
            if m:
                specs.append(m.group(1))
            specs.extend(RE_REQUIRE.findall(line))
            specs.extend(RE_DYNAMIC_IMPORT.findall(line))
            for spec in specs:
                target, external = _resolve_js_import(f.path, spec, file_set)
                edges.append(ImportEdge("imports", f.path, target, i, line.strip(), "high", external))
    return edges


def detect_entries(files: list[FileRecord]) -> list[dict[str, str]]:
    paths = {f.path for f in files}
    entries: list[dict[str, str]] = []

    for p in ENTRY_CANDIDATES["python"]:
        for fp in paths:
            if fp.endswith(p):
                entries.append({"path": fp, "why": f"filename matches {p}"})

    for p in ENTRY_CANDIDATES["jsts"]:
        if p in paths:
            entries.append({"path": p, "why": f"common JS/TS entry {p}"})

    for p in ENTRY_CANDIDATES["config"]:
        if p in paths:
            entries.append({"path": p, "why": f"runtime/build config {p}"})

    uniq = {}
    for e in entries:
        uniq[e["path"]] = e
    return list(uniq.values())


def infer_dir_roles(files: list[FileRecord], edges: list[ImportEdge], entries: list[dict[str, str]]) -> list[dict[str, object]]:
    by_dir: dict[str, list[FileRecord]] = defaultdict(list)
    for f in files:
        d = str(Path(f.path).parent.as_posix())
        by_dir[d].append(f)

    indegree = Counter(e.to for e in edges if not e.external)
    entry_paths = {e["path"] for e in entries}

    roles: list[dict[str, object]] = []
    for d, items in sorted(by_dir.items()):
        if d == ".":
            continue
        signals: list[str] = []
        name = Path(d).name.lower()
        if name in {"routes", "router", "api", "controllers"}:
            role = "接口层（HTTP/API）"
            signals.append(f"目录命名 {name}")
        elif name in {"services", "domain", "business", "core"}:
            role = "业务逻辑层"
            signals.append(f"目录命名 {name}")
        elif name in {"models", "schema", "entities", "db", "repository"}:
            role = "数据/持久化层"
            signals.append(f"目录命名 {name}")
        elif name in {"utils", "common", "lib", "shared"}:
            role = "基础公共层"
            signals.append(f"目录命名 {name}")
        elif name in {"tests", "test"}:
            role = "测试层"
            signals.append(f"目录命名 {name}")
        elif name in {"docs", "doc"}:
            role = "文档层"
            signals.append(f"目录命名 {name}")
        else:
            role = "模块目录"

        ext_count = Counter(Path(f.path).suffix.lower() for f in items)
        if ext_count:
            main_ext, main_count = ext_count.most_common(1)[0]
            signals.append(f"{main_ext or 'noext'} 文件占比最高 ({main_count}/{len(items)})")

        if any(p.startswith(f"{d}/") for p in entry_paths):
            signals.append("包含入口候选文件")

        hot = sum(indegree.get(f.path, 0) for f in items)
        if hot > 0:
            signals.append(f"被其他模块导入总次数 {hot}")

        roles.append({"path": d, "role": role, "signals": signals[:3]})

    return roles


def build_graph(files: list[FileRecord]) -> tuple[list[ImportEdge], list[dict[str, object]], list[dict[str, str]], dict[str, int]]:
    py_files = [f for f in files if f.path.endswith(".py") and f.text]
    js_files = [f for f in files if Path(f.path).suffix.lower() in {".js", ".jsx", ".ts", ".tsx", ".mts", ".cts"} and f.text]

    file_set = {f.path for f in files}
    module_index = _python_module_index(py_files)
    edges = _build_python_edges(py_files, module_index) + _build_js_edges(js_files, file_set)
    entries = detect_entries(files)
    dirs = infer_dir_roles(files, edges, entries)

    indegree = Counter(e.to for e in edges if not e.external)
    metrics = {
        "total_edges": len(edges),
        "internal_edges": sum(1 for e in edges if not e.external),
        "external_edges": sum(1 for e in edges if e.external),
        "top_internal_targets": len(indegree),
    }

    return edges, dirs, entries, metrics
