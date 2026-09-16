from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from repo2nlm.renderers.books import get_github_permalink, render_repobook
from repo2nlm.types import FileRecord


class RepoBookAndPermalinkTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.out_dir = Path(self._td.name)

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_github_permalink_https_and_git(self) -> None:
        commit = "1234567890abcdef1234567890abcdef12345678"
        # Standard HTTPS
        link1 = get_github_permalink("https://github.com/owner/myrepo", commit, "src/main.py")
        self.assertEqual(link1, f"https://github.com/owner/myrepo/blob/{commit}/src/main.py")

        # HTTPS with .git
        link2 = get_github_permalink("https://github.com/owner/myrepo.git", commit, "src/main.py")
        self.assertEqual(link2, f"https://github.com/owner/myrepo/blob/{commit}/src/main.py")

        # HTTPS with trailing slash
        link3 = get_github_permalink("https://github.com/owner/myrepo/", commit, "src/main.py")
        self.assertEqual(link3, f"https://github.com/owner/myrepo/blob/{commit}/src/main.py")

        # SSH git@github.com
        link4 = get_github_permalink("git@github.com:owner/myrepo.git", commit, "src/main.py")
        self.assertEqual(link4, f"https://github.com/owner/myrepo/blob/{commit}/src/main.py")

    def test_github_permalink_non_github_returns_none(self) -> None:
        commit = "abcdef"
        self.assertIsNone(get_github_permalink("https://gitlab.com/owner/myrepo.git", commit, "foo.py"))
        self.assertIsNone(get_github_permalink("https://gitee.com/owner/myrepo.git", commit, "foo.py"))
        self.assertIsNone(get_github_permalink("/local/path/to/repo", commit, "foo.py"))
        self.assertIsNone(get_github_permalink("", commit, "foo.py"))

    def test_render_repobook_split_default(self) -> None:
        files = [
            FileRecord(
                path="src/app.py",
                abs_path=Path("/tmp/app.py"),
                size=10,
                sha256="hash1",
                lang="py",
                text=True,
                truncated=False,
                content="print('hello')",
            ),
            FileRecord(
                path="docs/guide.md",
                abs_path=Path("/tmp/guide.md"),
                size=20,
                sha256="hash2",
                lang="md",
                text=True,
                truncated=False,
                content="# Guide",
            ),
        ]
        repobook_files = render_repobook(
            out_dir=self.out_dir,
            repo_url="https://github.com/owner/demo",
            branch="main",
            commit="commithash123",
            files=files,
            entries=[{"path": "src/app.py", "why": "entry point"}],
            split_repobook=True,
        )
        filenames = [f.name for f in repobook_files]
        self.assertIn("00_overview.md", filenames)
        self.assertIn("01_docs.md", filenames)
        self.assertIn("02_src.md", filenames)

        src_chapter = (self.out_dir / "RepoBook" / "02_src.md").read_text(encoding="utf-8")
        self.assertIn("- Source: `https://github.com/owner/demo/blob/commithash123/src/app.py`", src_chapter)
        self.assertIn("- SHA256: `hash1`", src_chapter)

    def test_render_repobook_no_split(self) -> None:
        files = [
            FileRecord(
                path="src/app.py",
                abs_path=Path("/tmp/app.py"),
                size=10,
                sha256="hash1",
                lang="py",
                text=True,
                truncated=False,
                content="print('hello')",
            ),
            FileRecord(
                path="docs/guide.md",
                abs_path=Path("/tmp/guide.md"),
                size=20,
                sha256="hash2",
                lang="md",
                text=True,
                truncated=False,
                content="# Guide",
            ),
        ]
        repobook_files = render_repobook(
            out_dir=self.out_dir,
            repo_url="https://github.com/owner/demo",
            branch="main",
            commit="commithash123",
            files=files,
            entries=[],
            split_repobook=False,
        )
        self.assertEqual(len(repobook_files), 1)
        self.assertEqual(repobook_files[0].name, "RepoBook.md")
        content = repobook_files[0].read_text(encoding="utf-8")
        self.assertIn("# RepoBook Overview", content)
        self.assertIn("## src/app.py", content)
        self.assertIn("## docs/guide.md", content)
        self.assertIn("- Source: `https://github.com/owner/demo/blob/commithash123/src/app.py`", content)

    def test_render_repobook_non_github_omits_permalink(self) -> None:
        files = [
            FileRecord(
                path="src/app.py",
                abs_path=Path("/tmp/app.py"),
                size=10,
                sha256="hash1",
                lang="py",
                text=True,
                truncated=False,
                content="print('hello')",
            ),
        ]
        repobook_files = render_repobook(
            out_dir=self.out_dir,
            repo_url="https://gitlab.com/owner/demo",
            branch="main",
            commit="commithash123",
            files=files,
            entries=[],
            split_repobook=False,
        )
        content = repobook_files[0].read_text(encoding="utf-8")
        self.assertNotIn("- Source: `https://github.com", content)


    def test_cli_ingest_with_no_split_repobook(self) -> None:
        from repo2nlm.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["ingest", "https://github.com/owner/demo", "--no-split-repobook"])
        self.assertTrue(args.no_split_repobook)


if __name__ == "__main__":
    unittest.main()
