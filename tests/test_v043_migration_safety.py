from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from repo2nlm.cli import build_parser, ingest
from repo2nlm.config import DEFAULT_MAX_GROUP_FILES, DEFAULT_MAX_GROUP_KB
from repo2nlm.renderers.books import (
    _PART_SLUG_RE,
    derive_legacy_repobook_filenames,
    render_repobook,
    resolve_partition_config,
)
from repo2nlm.types import FileRecord
from repo2nlm.uploader import (
    SyncPlan,
    UploadSource,
    _collect_upload_sources,
    _plan_sync,
)


def _make_record(path: str, content: str = "print('hello')", commit: str = "c0ffee") -> FileRecord:
    b = content.encode("utf-8")
    return FileRecord(
        path=path,
        abs_path=Path(path),
        size=len(b),
        sha256=hashlib.sha256(b).hexdigest(),
        lang="py",
        text=True,
        truncated=False,
        content=content,
        commit=commit,
    )


class TestPartSlugRegexAndLabels(unittest.TestCase):
    """Test issue #2: strict __part and __sub slug parsing without substring false positives."""

    def test_part_slug_regex_matches_valid_parts(self) -> None:
        m1 = _PART_SLUG_RE.fullmatch("src__part01")
        self.assertIsNotNone(m1)
        self.assertEqual(m1.group("base"), "src")
        self.assertEqual(m1.group("part"), "01")
        self.assertIsNone(m1.group("sub"))

        m2 = _PART_SLUG_RE.fullmatch("src__part01__sub02")
        self.assertIsNotNone(m2)
        self.assertEqual(m2.group("base"), "src")
        self.assertEqual(m2.group("part"), "01")
        self.assertEqual(m2.group("sub"), "02")

        m3 = _PART_SLUG_RE.fullmatch("lib__internal__utils__part10__sub05")
        self.assertIsNotNone(m3)
        self.assertEqual(m3.group("base"), "lib__internal__utils")
        self.assertEqual(m3.group("part"), "10")
        self.assertEqual(m3.group("sub"), "05")

    def test_part_slug_regex_rejects_substring_false_positives(self) -> None:
        """Verify real-world paths containing '__part' substrings do not match."""
        false_positives = [
            "snapshots__session__partial-landlock-child-failure",
            "partial",
            "counterpart",
            "department",
            "partition",
            "__partial-landlock-child-failure",
            "part",
            "part01",
            "src__part",
            "src__partXX",
            "src__part01__sub",
            "src__part01__subXX",
        ]
        for slug in false_positives:
            with self.subTest(slug=slug):
                self.assertIsNone(
                    _PART_SLUG_RE.fullmatch(slug),
                    f"Slug '{slug}' should not match _PART_SLUG_RE",
                )

    def test_render_repobook_handles_partial_paths_without_exception(self) -> None:
        """Verify render_repobook successfully renders directories containing 'partial' without ValueError."""
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            files = [
                _make_record("README.md", "# Test"),
                _make_record("snapshots/session/partial-landlock-child-failure/test.py", "def test_fail(): pass\n"),
                _make_record("snapshots/session/normal/ok.py", "def test_ok(): pass\n"),
                _make_record("counterpart/code.py", "def foo(): pass\n"),
                _make_record("department/org.py", "def bar(): pass\n"),
                _make_record("partial/piece.py", "def baz(): pass\n"),
            ]
            paths = render_repobook(
                out_dir=out_dir,
                repo_url="https://github.com/example/repo.git",
                branch="main",
                commit="abcdef",
                files=files,
                entries=[],
                split_repobook=True,
                max_group_kb=512,
                max_group_files=2,
                adaptive_partition=True,
            )
            self.assertTrue(len(paths) > 0)
            rendered_texts = {p.name: p.read_text(encoding="utf-8") for p in paths}
            # Verify no crash and chapter headers are generated properly
            found_snapshots = any("partial-landlock-child-failure" in content for content in rendered_texts.values())
            self.assertTrue(found_snapshots)


class TestPartitionStrategyResolution(unittest.TestCase):
    """Test partition strategy resolution rules and manifest persistence."""

    def setUp(self) -> None:
        self.td = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.td.name)

    def tearDown(self) -> None:
        self.td.cleanup()

    def test_fresh_repo_defaults_to_adaptive(self) -> None:
        cfg = resolve_partition_config(out_dir=self.out_dir, previous_manifest_path=None)
        self.assertTrue(cfg["adaptive"])
        self.assertEqual(cfg["max_group_kb"], DEFAULT_MAX_GROUP_KB)
        self.assertEqual(cfg["max_group_files"], DEFAULT_MAX_GROUP_FILES)
        self.assertEqual(cfg["strategy_version"], 2)

    def test_existing_manifest_inherits_partition_metadata(self) -> None:
        prev_data = {
            "partition": {
                "adaptive": False,
                "max_group_kb": 256,
                "max_group_files": 20,
                "strategy_version": 2,
            },
            "files": [],
        }
        manifest_p = self.out_dir / "manifest.json"
        manifest_p.write_text(json.dumps(prev_data), encoding="utf-8")

        cfg = resolve_partition_config(out_dir=self.out_dir, previous_manifest_path=manifest_p)
        self.assertFalse(cfg["adaptive"])
        self.assertEqual(cfg["max_group_kb"], 256)
        self.assertEqual(cfg["max_group_files"], 20)

    def test_cli_explicit_flags_override_inherited_metadata(self) -> None:
        prev_data = {
            "partition": {
                "adaptive": False,
                "max_group_kb": 512,
                "max_group_files": 40,
                "strategy_version": 2,
            },
            "files": [],
        }
        manifest_p = self.out_dir / "manifest.json"
        manifest_p.write_text(json.dumps(prev_data), encoding="utf-8")

        # Explicitly opt-in to adaptive migration
        cfg = resolve_partition_config(
            out_dir=self.out_dir,
            previous_manifest_path=manifest_p,
            adaptive_partition=True,
            max_group_kb=1024,
        )
        self.assertTrue(cfg["adaptive"])
        self.assertEqual(cfg["max_group_kb"], 1024)
        self.assertEqual(cfg["max_group_files"], 40)

    def test_legacy_manifest_with_legacy_repobook_conservatively_detected(self) -> None:
        """When manifest has no partition metadata and RepoBook/*.md matches deterministic legacy derivation, keep legacy."""
        prev_data = {
            "files": [
                {"path": "README.md", "text": True},
                {"path": "src/a.py", "text": True},
                {"path": "src/b.py", "text": True},
                {"path": "tests/test_a.py", "text": True},
            ]
        }
        manifest_p = self.out_dir / "manifest.json"
        manifest_p.write_text(json.dumps(prev_data), encoding="utf-8")

        repodir = self.out_dir / "RepoBook"
        repodir.mkdir(parents=True, exist_ok=True)
        # In legacy mode, sorted groups are: root, src, tests -> 01_root, 02_src, 03_tests
        (repodir / "00_overview.md").write_text("# Overview", encoding="utf-8")
        (repodir / "01_root.md").write_text("# Root", encoding="utf-8")
        (repodir / "02_src.md").write_text("# Src", encoding="utf-8")
        (repodir / "03_tests.md").write_text("# Tests", encoding="utf-8")

        cfg = resolve_partition_config(out_dir=self.out_dir, previous_manifest_path=manifest_p)
        self.assertFalse(cfg["adaptive"])

    def test_legacy_manifest_with_adaptive_repobook_preserves_adaptive(self) -> None:
        """When manifest has no partition metadata (v0.4.2) but RepoBook/*.md has adaptive structure, keep adaptive."""
        prev_data = {
            "files": [
                {"path": "README.md", "text": True},
                {"path": "src/a.py", "text": True},
                {"path": "src/b.py", "text": True},
            ]
        }
        manifest_p = self.out_dir / "manifest.json"
        manifest_p.write_text(json.dumps(prev_data), encoding="utf-8")

        repodir = self.out_dir / "RepoBook"
        repodir.mkdir(parents=True, exist_ok=True)
        # Adaptive names don't match legacy 02_src.md
        (repodir / "00_overview.md").write_text("# Overview", encoding="utf-8")
        (repodir / "01_root.md").write_text("# Root", encoding="utf-8")
        (repodir / "02_src__root.md").write_text("# Src Root", encoding="utf-8")
        (repodir / "02_src__part01.md").write_text("# Src Part 1", encoding="utf-8")

        cfg = resolve_partition_config(out_dir=self.out_dir, previous_manifest_path=manifest_p)
        self.assertTrue(cfg["adaptive"])


class TestParserTriState(unittest.TestCase):
    """Test CLI argument parsing for mutually exclusive --adaptive-partition and --no-adaptive-partition."""

    def test_parser_tri_state(self) -> None:
        parser = build_parser()

        # Unspecified -> adaptive_partition is None
        args = parser.parse_args(["sync", "https://example.com/repo", "--notebook", "nb1"])
        self.assertIsNone(args.adaptive_partition)
        self.assertIsNone(args.max_group_kb)
        self.assertIsNone(args.max_group_files)

        # --adaptive-partition -> True
        args_adapt = parser.parse_args([
            "sync", "https://example.com/repo", "--notebook", "nb1", "--adaptive-partition"
        ])
        self.assertTrue(args_adapt.adaptive_partition)

        # --no-adaptive-partition -> False
        args_no = parser.parse_args([
            "sync", "https://example.com/repo", "--notebook", "nb1", "--no-adaptive-partition"
        ])
        self.assertFalse(args_no.adaptive_partition)

        # Mutually exclusive -> error
        with self.assertRaises(SystemExit):
            parser.parse_args([
                "sync", "https://example.com/repo", "--notebook", "nb1",
                "--adaptive-partition", "--no-adaptive-partition"
            ])


class TestMigrationSafetyChurnE2E(unittest.TestCase):
    """End-to-end regression tests for partition migration churn prevention.

    Verifies:
    1. A legacy v0.3.x repository upgraded to v0.4.3 defaults to preserving legacy layout,
       producing byte-identical files and upload plan uploading=0, deleted=0.
    2. An existing v0.4.2 adaptive repository upgraded to v0.4.3 preserves adaptive layout.
    3. Explicit opt-in --adaptive-partition permits migration from legacy to adaptive.
    4. Fresh repository defaults to adaptive partitioning.
    """

    def setUp(self) -> None:
        self.td = tempfile.TemporaryDirectory()
        self.base = Path(self.td.name)
        self.repo_dir = self.base / "git_repo"
        self.repo_dir.mkdir()
        self.out_dir = self.base / "out"
        self.out_dir.mkdir()

        self._run_git(["init", "-b", "main"])
        self._run_git(["config", "user.name", "TestUser"])
        self._run_git(["config", "user.email", "test@example.com"])

        # Setup repository with enough files in src/ to cause adaptive split (> 40 files)
        (self.repo_dir / "README.md").write_text("# Large Test Repo\n", encoding="utf-8")
        src_dir = self.repo_dir / "src"
        src_dir.mkdir()
        for i in range(1, 51):
            (src_dir / f"file_{i:02d}.py").write_text(f"def func_{i}():\n    return {i}\n", encoding="utf-8")

        self._commit("initial commit with 50 files")

    def tearDown(self) -> None:
        self.td.cleanup()

    def _run_git(self, args: list[str]) -> None:
        subprocess.run(["git"] + args, cwd=self.repo_dir, check=True, capture_output=True, text=True)

    def _commit(self, msg: str) -> str:
        self._run_git(["add", "."])
        self._run_git(["commit", "-m", msg])
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout.strip()

    def _sha(self, p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()

    def _setup_mock_remote(self, out_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        staged = self.base / "staged_mock"
        if staged.exists():
            shutil.rmtree(staged)
        upload_sources = _collect_upload_sources([out_dir], staged_dir=staged)
        upload_specs = [
            UploadSource(
                out_dir=out_dir,
                namespace="",
                original_title=p.name,
                upload_path=p,
            )
            for p in upload_sources
        ]
        items = []
        remote_sources = []
        for i, s in enumerate(upload_specs, start=1):
            rid = f"r_{i}_{s.upload_path.name}"
            sha = self._sha(s.upload_path)
            items.append({
                "original": s.original_title,
                "uploaded_titles": [s.original_title],
                "parts": [{"title": s.original_title, "local_sha256": sha, "remote_source_id": rid}],
                "remote_sources": [{"id": rid, "status": "ready"}],
                "local_sha256": sha,
            })
            remote_sources.append({"id": rid, "title": s.original_title, "status": "ready"})

        upload_map_data = {"notebook_id": "nb-test", "items": items}
        (out_dir / "upload_map.json").write_text(json.dumps(upload_map_data), encoding="utf-8")
        return upload_map_data, remote_sources

    def test_legacy_repo_upgraded_to_v043_default_preserves_representation_and_zero_churn(self) -> None:
        # Step 1: Initial ingest using legacy mode (simulating v0.3.x output)
        stats1 = ingest(
            repo_url=str(self.repo_dir),
            out_dir=self.out_dir,
            branch="main",
            commit=None,
            include=None,
            exclude=None,
            max_file_kb=200,
            split_repobook=True,
            previous_manifest=None,
            adaptive_partition=False,
        )

        repobook_dir = self.out_dir / "RepoBook"
        legacy_files = sorted(p.name for p in repobook_dir.glob("*.md"))
        # In legacy mode, 50 files in src/ are collapsed into a single 02_src.md
        self.assertEqual(legacy_files, ["00_overview.md", "01_root.md", "02_src.md"])
        legacy_hashes = {f: self._sha(repobook_dir / f) for f in legacy_files}

        # Step 2: Strip 'partition' from manifest.json to simulate an authentic pre-v0.4.3 legacy manifest
        manifest_data = json.loads((self.out_dir / "manifest.json").read_text(encoding="utf-8"))
        if "partition" in manifest_data:
            del manifest_data["partition"]
        (self.out_dir / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

        # Setup mock remote state matching the legacy output
        upload_map_data, remote_sources = self._setup_mock_remote(self.out_dir)

        # Step 3: Run v0.4.3 default sync/update (no partition flags passed)
        stats2 = ingest(
            repo_url=str(self.repo_dir),
            out_dir=self.out_dir,
            branch="main",
            commit=None,
            include=None,
            exclude=None,
            max_file_kb=200,
            split_repobook=True,
            previous_manifest=self.out_dir / "manifest.json",
            adaptive_partition=None,  # default in v0.4.3
        )

        # Step 4: Verify RepoBook filenames and byte hashes are 100% IDENTICAL
        post_upgrade_files = sorted(p.name for p in repobook_dir.glob("*.md"))
        self.assertEqual(post_upgrade_files, legacy_files)
        post_upgrade_hashes = {f: self._sha(repobook_dir / f) for f in post_upgrade_files}
        self.assertEqual(post_upgrade_hashes, legacy_hashes)

        # Verify manifest now records partition configuration for future runs
        upgraded_manifest = json.loads((self.out_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("partition", upgraded_manifest)
        self.assertFalse(upgraded_manifest["partition"]["adaptive"])
        self.assertEqual(upgraded_manifest["partition"]["strategy_version"], 2)

        # Step 5: Verify upload plan produces ZERO uploading and ZERO deleting
        staged = self.base / "staged_verify"
        upload_sources = _collect_upload_sources([self.out_dir], staged_dir=staged)
        upload_specs = [
            UploadSource(out_dir=self.out_dir, namespace="", original_title=p.name, upload_path=p)
            for p in upload_sources
        ]
        plan = _plan_sync(
            out_dirs=[self.out_dir],
            upload_specs=upload_specs,
            purge_titles=set(),
            remote_sources=remote_sources,
        )
        self.assertEqual(plan.stats["uploading"], 0)
        self.assertEqual(plan.stats["deleted"], 0)
        self.assertEqual(plan.stats["unchanged"], len(upload_specs))

    def test_v042_adaptive_out_upgraded_to_v043_preserves_adaptive(self) -> None:
        """Verify an existing v0.4.2 adaptive out (without partition metadata) stays adaptive in v0.4.3."""
        # Initial run with adaptive=True
        ingest(
            repo_url=str(self.repo_dir),
            out_dir=self.out_dir,
            branch="main",
            commit=None,
            include=None,
            exclude=None,
            max_file_kb=200,
            split_repobook=True,
            previous_manifest=None,
            adaptive_partition=True,
        )

        repobook_dir = self.out_dir / "RepoBook"
        v042_files = sorted(p.name for p in repobook_dir.glob("*.md"))
        # 50 files with max_group_files=40 splits into part01 and part02
        self.assertIn("02_src__part01.md", v042_files)
        self.assertIn("02_src__part02.md", v042_files)

        # Strip partition metadata to simulate v0.4.2 manifest
        m_path = self.out_dir / "manifest.json"
        data = json.loads(m_path.read_text(encoding="utf-8"))
        if "partition" in data:
            del data["partition"]
        m_path.write_text(json.dumps(data), encoding="utf-8")

        # Run v0.4.3 default update
        stats = ingest(
            repo_url=str(self.repo_dir),
            out_dir=self.out_dir,
            branch="main",
            commit=None,
            include=None,
            exclude=None,
            max_file_kb=200,
            split_repobook=True,
            previous_manifest=m_path,
            adaptive_partition=None,
        )

        v043_files = sorted(p.name for p in repobook_dir.glob("*.md"))
        self.assertEqual(v043_files, v042_files)
        self.assertTrue(stats["partition"]["adaptive"])

    def test_legacy_out_with_explicit_adaptive_flag_migrates_to_adaptive(self) -> None:
        """Verify legacy out + --adaptive-partition explicitly migrates to adaptive."""
        # Setup legacy out
        ingest(
            repo_url=str(self.repo_dir),
            out_dir=self.out_dir,
            branch="main",
            commit=None,
            include=None,
            exclude=None,
            max_file_kb=200,
            split_repobook=True,
            previous_manifest=None,
            adaptive_partition=False,
        )
        repobook_dir = self.out_dir / "RepoBook"
        self.assertIn("02_src.md", [p.name for p in repobook_dir.glob("*.md")])

        # Explicitly migrate with adaptive_partition=True
        stats = ingest(
            repo_url=str(self.repo_dir),
            out_dir=self.out_dir,
            branch="main",
            commit=None,
            include=None,
            exclude=None,
            max_file_kb=200,
            split_repobook=True,
            previous_manifest=self.out_dir / "manifest.json",
            adaptive_partition=True,
        )
        post_files = [p.name for p in repobook_dir.glob("*.md")]
        self.assertIn("02_src__part01.md", post_files)
        self.assertIn("02_src__part02.md", post_files)
        self.assertNotIn("02_src.md", post_files)
        self.assertTrue(stats["partition"]["adaptive"])

    def test_fresh_repo_defaults_to_adaptive_partitioning(self) -> None:
        """Verify fresh repo defaults to adaptive partitioning."""
        fresh_out = self.base / "fresh_out"
        stats = ingest(
            repo_url=str(self.repo_dir),
            out_dir=fresh_out,
            branch="main",
            commit=None,
            include=None,
            exclude=None,
            max_file_kb=200,
            split_repobook=True,
            previous_manifest=None,
            adaptive_partition=None,
        )
        files = [p.name for p in (fresh_out / "RepoBook").glob("*.md")]
        self.assertIn("02_src__part01.md", files)
        self.assertIn("02_src__part02.md", files)
        self.assertTrue(stats["partition"]["adaptive"])


if __name__ == "__main__":
    unittest.main()
