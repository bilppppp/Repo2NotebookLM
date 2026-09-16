from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from repo2nlm.renderers.books import render_changebook, write_manifest
from repo2nlm.types import FileRecord
from repo2nlm.uploader import _iter_markdown_sources


class ChangeBookTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.out_dir = Path(self._td.name)

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_render_changebook_initial_snapshot(self) -> None:
        cb = render_changebook(
            out_dir=self.out_dir,
            repo_url="https://github.com/owner/repo",
            current_commit="commit100",
            previous_commit=None,
            added=["src/main.py", "README.md"],
            modified=[],
            deleted=[],
        )
        self.assertTrue(cb.exists())
        content = cb.read_text(encoding="utf-8")
        self.assertIn("# ChangeBook", content)
        self.assertIn("- Previous commit: `(initial snapshot)`", content)
        self.assertIn("- Current commit: `commit100`", content)
        self.assertIn("## Added Files", content)
        self.assertIn("- `src/main.py`", content)
        self.assertIn("- `README.md`", content)
        self.assertIn("## Modified Files\n\n- (none)", content)
        self.assertIn("## Deleted Files\n\n- (none)", content)

    def test_render_changebook_update(self) -> None:
        cb = render_changebook(
            out_dir=self.out_dir,
            repo_url="https://github.com/owner/repo",
            current_commit="commit200",
            previous_commit="commit100",
            added=["src/new_feature.py"],
            modified=["src/main.py"],
            deleted=["old_script.py"],
        )
        self.assertTrue(cb.exists())
        content = cb.read_text(encoding="utf-8")
        self.assertIn("- Previous commit: `commit100`", content)
        self.assertIn("- Current commit: `commit200`", content)
        self.assertIn("- Added: `1` files", content)
        self.assertIn("- Modified: `1` files", content)
        self.assertIn("- Deleted: `1` files", content)
        self.assertIn("## Added Files\n\n- `src/new_feature.py`", content)
        self.assertIn("## Modified Files\n\n- `src/main.py`", content)
        self.assertIn("## Deleted Files\n\n- `old_script.py`", content)

    def test_changebook_is_included_in_upload_sources(self) -> None:
        repobook = self.out_dir / "RepoBook"
        repobook.mkdir(parents=True, exist_ok=True)
        (repobook / "00_overview.md").write_text("# Overview", encoding="utf-8")
        (self.out_dir / "GraphBook.md").write_text("# GraphBook", encoding="utf-8")
        (self.out_dir / "ChangeBook.md").write_text("# ChangeBook", encoding="utf-8")

        sources = _iter_markdown_sources(self.out_dir)
        names = [s.name for s in sources]
        self.assertIn("00_overview.md", names)
        self.assertIn("GraphBook.md", names)
        self.assertIn("ChangeBook.md", names)


if __name__ == "__main__":
    unittest.main()
