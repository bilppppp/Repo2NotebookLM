from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from repo2nlm.cli import ingest


class CliSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.base = Path(self._td.name)
        self.repo_dir = self.base / "git_repo"
        self.repo_dir.mkdir()
        self.out_dir = self.base / "out"

        # Initialize real local git repo
        subprocess.run(["git", "init", "-b", "main"], cwd=self.repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=self.repo_dir, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.repo_dir, check=True)

    def tearDown(self) -> None:
        self._td.cleanup()

    def _commit(self, msg: str) -> str:
        subprocess.run(["git", "add", "."], cwd=self.repo_dir, check=True)
        subprocess.run(["git", "commit", "-m", msg], cwd=self.repo_dir, check=True, capture_output=True)
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo_dir, check=True, capture_output=True, text=True)
        return proc.stdout.strip()

    def test_local_git_ingest_update_cycle(self) -> None:
        # 1. Initial commit
        (self.repo_dir / "README.md").write_text("# Smoke Test Repo\n", encoding="utf-8")
        src_dir = self.repo_dir / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text("def hello(): return 'world'\n", encoding="utf-8")
        (src_dir / "old.py").write_text("def legacy(): pass\n", encoding="utf-8")
        c1 = self._commit("initial commit")

        # Initial ingest
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
        )

        self.assertEqual(stats1["commit"], c1)
        self.assertEqual(stats1["file_count"], 3)
        self.assertTrue((self.out_dir / "ChangeBook.md").exists())
        self.assertTrue((self.out_dir / "GraphBook.md").exists())
        self.assertTrue((self.out_dir / "RepoBook" / "00_overview.md").exists())

        cb1 = (self.out_dir / "ChangeBook.md").read_text(encoding="utf-8")
        self.assertIn("Initial snapshot", cb1)
        self.assertIn("README.md", cb1)

        # 2. Modify app.py, add new.py, delete old.py
        (src_dir / "app.py").write_text("def hello(): return 'updated world'\n", encoding="utf-8")
        (src_dir / "new.py").write_text("def new_func(): pass\n", encoding="utf-8")
        (src_dir / "old.py").unlink()
        c2 = self._commit("modify, add, delete files")

        # Incremental update
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
        )

        self.assertEqual(stats2["commit"], c2)
        changes = stats2["changes"]
        self.assertEqual(changes["previous_commit"], c1)
        self.assertEqual(changes["added"], ["src/new.py"])
        self.assertEqual(changes["modified"], ["src/app.py"])
        self.assertEqual(changes["deleted"], ["src/old.py"])

        cb2 = (self.out_dir / "ChangeBook.md").read_text(encoding="utf-8")
        self.assertIn(f"- Previous commit: `{c1}`", cb2)
        self.assertIn(f"- Current commit: `{c2}`", cb2)
        self.assertIn("## Added Files\n\n- `src/new.py`", cb2)
        self.assertIn("## Modified Files\n\n- `src/app.py`", cb2)
        self.assertIn("## Deleted Files\n\n- `src/old.py`", cb2)

        # 3. No-op update with zero changes to git repo
        import hashlib
        cb_path = self.out_dir / "ChangeBook.md"
        sha_before_noop = hashlib.sha256(cb_path.read_bytes()).hexdigest()

        stats3 = ingest(
            repo_url=str(self.repo_dir),
            out_dir=self.out_dir,
            branch="main",
            commit=None,
            include=None,
            exclude=None,
            max_file_kb=200,
            split_repobook=True,
            previous_manifest=self.out_dir / "manifest.json",
        )

        changes3 = stats3["changes"]
        self.assertEqual(changes3["added"], [])
        self.assertEqual(changes3["modified"], [])
        self.assertEqual(changes3["deleted"], [])
        self.assertEqual(changes3["previous_commit"], c2)

        sha_after_noop = hashlib.sha256(cb_path.read_bytes()).hexdigest()
        self.assertEqual(sha_before_noop, sha_after_noop)


if __name__ == "__main__":
    unittest.main()
