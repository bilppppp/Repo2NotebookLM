from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from repo2nlm.cli import ingest
from repo2nlm.uploader import (
    UploadSource,
    _collect_upload_sources,
    _plan_sync,
    _read_previous_upload_map,
)


class SourceChurnTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.base = Path(self._td.name)
        self.git_repo = self.base / "repo"
        self.git_repo.mkdir()

        subprocess.run(["git", "init", "-b", "main"], cwd=self.git_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=self.git_repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.git_repo, check=True)

        self.fake_github_url = "https://github.com/test-owner/test-repo"
        subprocess.run(
            ["git", "config", "--global", f"url.{self.git_repo}.insteadOf", self.fake_github_url],
            check=True,
        )

        self.out_dir = self.base / "out"

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "config", "--global", "--unset", f"url.{self.git_repo}.insteadOf"],
            check=False,
        )
        self._td.cleanup()

    def _commit(self, msg: str) -> str:
        subprocess.run(["git", "add", "."], cwd=self.git_repo, check=True)
        subprocess.run(["git", "commit", "-m", msg], cwd=self.git_repo, check=True, capture_output=True)
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.git_repo, check=True, capture_output=True, text=True)
        return proc.stdout.strip()

    def _sha(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _setup_initial_repo(self) -> str:
        (self.git_repo / "README.md").write_text("# Test Repo\n\nA initial README.\n", encoding="utf-8")
        src_dir = self.git_repo / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "utils.py").write_text("def helper():\n    return 42\n", encoding="utf-8")
        (src_dir / "app.py").write_text("from utils import helper\n\ndef main():\n    return helper()\n", encoding="utf-8")
        return self._commit("c1: initial commit")

    def test_a_body_only_change_stabilizes_unrelated_repobook_and_graphbook(self) -> None:
        c1 = self._setup_initial_repo()

        # Ingest c1
        ingest(
            repo_url=self.fake_github_url,
            out_dir=self.out_dir,
            branch="main",
            commit=None,
            include=None,
            exclude=None,
            max_file_kb=200,
            split_repobook=True,
            previous_manifest=None,
        )

        sha1_overview = self._sha(self.out_dir / "RepoBook" / "00_overview.md")
        sha1_root = self._sha(self.out_dir / "RepoBook" / "01_root.md")
        sha1_src = self._sha(self.out_dir / "RepoBook" / "02_src.md")
        sha1_graph = self._sha(self.out_dir / "GraphBook.md")
        sha1_change = self._sha(self.out_dir / "ChangeBook.md")

        # Mock initial upload map to simulate remote state
        staged1 = self.base / "staged1"
        upload_sources = _collect_upload_sources([self.out_dir], staged_dir=staged1)
        upload_specs = [
            UploadSource(
                out_dir=self.out_dir,
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
            })
            remote_sources.append({"id": rid, "title": s.original_title, "status": "ready"})

        (self.out_dir / "upload_map.json").write_text(
            json.dumps({"notebook_id": "nb-test", "items": items}),
            encoding="utf-8",
        )

        # Commit c2: body-only change in src/app.py (imports, tree, dirs unchanged)
        (self.git_repo / "src" / "app.py").write_text(
            "from utils import helper\n\ndef main():\n    val = helper()\n    return val + 100\n",
            encoding="utf-8",
        )
        c2 = self._commit("c2: body change in app.py")

        # Ingest c2 with previous_manifest
        ingest(
            repo_url=self.fake_github_url,
            out_dir=self.out_dir,
            branch="main",
            commit=None,
            include=None,
            exclude=None,
            max_file_kb=200,
            split_repobook=True,
            previous_manifest=self.out_dir / "manifest.json",
        )

        sha2_overview = self._sha(self.out_dir / "RepoBook" / "00_overview.md")
        sha2_root = self._sha(self.out_dir / "RepoBook" / "01_root.md")
        sha2_src = self._sha(self.out_dir / "RepoBook" / "02_src.md")
        sha2_graph = self._sha(self.out_dir / "GraphBook.md")
        sha2_change = self._sha(self.out_dir / "ChangeBook.md")

        # Invariant checks:
        # 1. Affected chapter MUST change
        self.assertNotEqual(sha1_src, sha2_src, "02_src.md must change when src/app.py changes")
        # 2. ChangeBook MUST change
        self.assertNotEqual(sha1_change, sha2_change, "ChangeBook.md must change on git commit")
        # 3. Snapshot metadata source (00_overview.md) changes to reflect commit
        self.assertNotEqual(sha1_overview, sha2_overview, "00_overview.md reflects snapshot commit metadata")
        # 4. Unrelated chapter (01_root.md) MUST remain byte-identical
        self.assertEqual(sha1_root, sha2_root, "01_root.md must be byte-identical when README is unchanged")
        # 5. GraphBook MUST remain byte-identical
        self.assertEqual(sha1_graph, sha2_graph, "GraphBook.md must be byte-identical when graph is unchanged")

        # Sync plan check
        staged2 = self.base / "staged2"
        upload_sources2 = _collect_upload_sources([self.out_dir], staged_dir=staged2)
        upload_specs2 = [
            UploadSource(
                out_dir=self.out_dir,
                namespace="",
                original_title=p.name,
                upload_path=p,
            )
            for p in upload_sources2
        ]
        plan = _plan_sync(
            out_dirs=[self.out_dir],
            upload_specs=upload_specs2,
            purge_titles=set(),
            remote_sources=remote_sources,
            replace_existing=False,
        )

        # Before v0.3: 5/5 changed.
        # After v0.3: exactly 3/5 changed (00_overview, 02_src, ChangeBook), exactly 2 unchanged (01_root, GraphBook)
        self.assertEqual(plan.unchanged_titles, {"01_root.md", "GraphBook.md"})
        to_upload_titles = {spec.upload_path.name for spec in plan.to_upload}
        self.assertEqual(to_upload_titles, {"00_overview.md", "02_src.md", "ChangeBook.md"})
        self.assertEqual(plan.stats["unchanged"], 2)
        self.assertEqual(plan.stats["uploading"], 3)

    def test_b_import_change_triggers_graphbook_change(self) -> None:
        c1 = self._setup_initial_repo()

        ingest(
            repo_url=self.fake_github_url,
            out_dir=self.out_dir,
            branch="main",
            commit=None,
            include=None,
            exclude=None,
            max_file_kb=200,
            split_repobook=True,
            previous_manifest=None,
        )
        sha1_graph = self._sha(self.out_dir / "GraphBook.md")
        sha1_src = self._sha(self.out_dir / "RepoBook" / "02_src.md")

        # Modify imports in src/app.py: import math as well
        (self.git_repo / "src" / "app.py").write_text(
            "import math\nfrom utils import helper\n\ndef main():\n    return math.sqrt(helper())\n",
            encoding="utf-8",
        )
        c2 = self._commit("c2: add math import")

        ingest(
            repo_url=self.fake_github_url,
            out_dir=self.out_dir,
            branch="main",
            commit=None,
            include=None,
            exclude=None,
            max_file_kb=200,
            split_repobook=True,
            previous_manifest=self.out_dir / "manifest.json",
        )
        sha2_graph = self._sha(self.out_dir / "GraphBook.md")
        sha2_src = self._sha(self.out_dir / "RepoBook" / "02_src.md")

        # GraphBook MUST change because an import edge was added
        self.assertNotEqual(sha1_graph, sha2_graph, "GraphBook.md must change when imports change")
        self.assertNotEqual(sha1_src, sha2_src)
        graph_content = (self.out_dir / "GraphBook.md").read_text(encoding="utf-8")
        self.assertIn("math", graph_content)

    def test_c_tree_change_triggers_graphbook_and_repobook_change(self) -> None:
        c1 = self._setup_initial_repo()

        ingest(
            repo_url=self.fake_github_url,
            out_dir=self.out_dir,
            branch="main",
            commit=None,
            include=None,
            exclude=None,
            max_file_kb=200,
            split_repobook=True,
            previous_manifest=None,
        )
        sha1_graph = self._sha(self.out_dir / "GraphBook.md")
        sha1_src = self._sha(self.out_dir / "RepoBook" / "02_src.md")

        # Add new file
        (self.git_repo / "src" / "new_module.py").write_text(
            "def new_feature(): pass\n",
            encoding="utf-8",
        )
        c2 = self._commit("c2: add new_module.py")

        ingest(
            repo_url=self.fake_github_url,
            out_dir=self.out_dir,
            branch="main",
            commit=None,
            include=None,
            exclude=None,
            max_file_kb=200,
            split_repobook=True,
            previous_manifest=self.out_dir / "manifest.json",
        )
        sha2_graph = self._sha(self.out_dir / "GraphBook.md")
        sha2_src = self._sha(self.out_dir / "RepoBook" / "02_src.md")

        self.assertNotEqual(sha1_graph, sha2_graph, "GraphBook.md must change when file tree changes")
        self.assertNotEqual(sha1_src, sha2_src, "02_src.md must change when new file is added to src/")
        src_content = (self.out_dir / "RepoBook" / "02_src.md").read_text(encoding="utf-8")
        self.assertIn("src/new_module.py", src_content)

    def test_d_true_noop_sync_leaves_all_artifacts_identical(self) -> None:
        c1 = self._setup_initial_repo()

        ingest(
            repo_url=self.fake_github_url,
            out_dir=self.out_dir,
            branch="main",
            commit=None,
            include=None,
            exclude=None,
            max_file_kb=200,
            split_repobook=True,
            previous_manifest=None,
        )

        all_md1 = {p.name: self._sha(p) for p in (self.out_dir / "RepoBook").glob("*.md")}
        all_md1["GraphBook.md"] = self._sha(self.out_dir / "GraphBook.md")
        all_md1["ChangeBook.md"] = self._sha(self.out_dir / "ChangeBook.md")

        # Ingest again without any git changes
        ingest(
            repo_url=self.fake_github_url,
            out_dir=self.out_dir,
            branch="main",
            commit=None,
            include=None,
            exclude=None,
            max_file_kb=200,
            split_repobook=True,
            previous_manifest=self.out_dir / "manifest.json",
        )

        all_md2 = {p.name: self._sha(p) for p in (self.out_dir / "RepoBook").glob("*.md")}
        all_md2["GraphBook.md"] = self._sha(self.out_dir / "GraphBook.md")
        all_md2["ChangeBook.md"] = self._sha(self.out_dir / "ChangeBook.md")

        self.assertEqual(all_md1, all_md2, "Every single markdown artifact must have identical SHA on true no-op")

    def test_e_permalink_correctness_for_changed_and_unchanged_files(self) -> None:
        readme_v1 = "# Test Repo\n\nA initial README.\n"
        app_v1 = "from utils import helper\n\ndef main():\n    return helper()\n"
        app_v2 = "from utils import helper\n\ndef main():\n    return helper() * 2\n"

        (self.git_repo / "README.md").write_text(readme_v1, encoding="utf-8")
        src_dir = self.git_repo / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "utils.py").write_text("def helper():\n    return 42\n", encoding="utf-8")
        (src_dir / "app.py").write_text(app_v1, encoding="utf-8")
        c1 = self._commit("c1: initial")

        ingest(
            repo_url=self.fake_github_url,
            out_dir=self.out_dir,
            branch="main",
            commit=None,
            include=None,
            exclude=None,
            max_file_kb=200,
            split_repobook=True,
            previous_manifest=None,
        )

        # Commit c2: modify only app.py
        (src_dir / "app.py").write_text(app_v2, encoding="utf-8")
        c2 = self._commit("c2: update app.py")

        ingest(
            repo_url=self.fake_github_url,
            out_dir=self.out_dir,
            branch="main",
            commit=None,
            include=None,
            exclude=None,
            max_file_kb=200,
            split_repobook=True,
            previous_manifest=self.out_dir / "manifest.json",
        )

        root_content = (self.out_dir / "RepoBook" / "01_root.md").read_text(encoding="utf-8")
        src_content = (self.out_dir / "RepoBook" / "02_src.md").read_text(encoding="utf-8")

        # 1. Verify permalink format and pinned commits
        re_source = re.compile(r"- Source: `https://github\.com/test-owner/test-repo/blob/([0-9a-f]{40})/([^`]+)`")

        root_matches = re_source.findall(root_content)
        self.assertEqual(len(root_matches), 1)
        readme_commit, readme_path = root_matches[0]
        self.assertEqual(readme_path, "README.md")
        # Unchanged file: commit MUST be c1
        self.assertEqual(readme_commit, c1)

        src_matches = dict([(path, c) for c, path in re_source.findall(src_content)])
        self.assertIn("src/app.py", src_matches)
        self.assertIn("src/utils.py", src_matches)
        # Changed file: commit MUST be c2
        self.assertEqual(src_matches["src/app.py"], c2)
        # Unchanged file in same chapter: commit MUST remain c1
        self.assertEqual(src_matches["src/utils.py"], c1)

        # 2. Critical verification: Test that link commit + path resolves to exact snapshot content in Git!
        # Unchanged file README.md at commit c1:
        git_readme = subprocess.run(
            ["git", "show", f"{readme_commit}:{readme_path}"],
            cwd=self.git_repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertEqual(git_readme, (self.git_repo / "README.md").read_text(encoding="utf-8"))

        # Changed file src/app.py at commit c2:
        git_app = subprocess.run(
            ["git", "show", f"{src_matches['src/app.py']}:src/app.py"],
            cwd=self.git_repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertEqual(git_app, (self.git_repo / "src" / "app.py").read_text(encoding="utf-8"))
        self.assertEqual(git_app, app_v2)

        # Unchanged file src/utils.py at commit c1:
        git_utils = subprocess.run(
            ["git", "show", f"{src_matches['src/utils.py']}:src/utils.py"],
            cwd=self.git_repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertEqual(git_utils, (self.git_repo / "src" / "utils.py").read_text(encoding="utf-8"))

    def test_f_v02_manifest_migration_and_git_history_backfill(self) -> None:
        # Step 1: Create git history with 3 commits
        # c1: README and utils created
        (self.git_repo / "README.md").write_text("# Project V1\n", encoding="utf-8")
        src_dir = self.git_repo / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "utils.py").write_text("def helper(): return 1\n", encoding="utf-8")
        (src_dir / "app.py").write_text("from utils import helper\n\ndef run(): return helper()\n", encoding="utf-8")
        c1 = self._commit("c1: initial")

        # c2: modify app.py
        (src_dir / "app.py").write_text("from utils import helper\n\ndef run(): return helper() + 10\n", encoding="utf-8")
        c2 = self._commit("c2: app update in v0.2 era")

        # Step 2: Write a genuine v0.2-compatible manifest (NO file.commit field anywhere)
        readme_bytes = (self.git_repo / "README.md").read_bytes()
        utils_bytes = (src_dir / "utils.py").read_bytes()
        app_bytes = (src_dir / "app.py").read_bytes()

        v02_manifest = {
            "repo": {
                "url": self.fake_github_url,
                "default_branch": "main",
                "commit": c2,
            },
            "files": [
                {
                    "path": "README.md",
                    "sha": hashlib.sha256(readme_bytes).hexdigest(),
                    "size": len(readme_bytes),
                    "lang": "md",
                    "text": True,
                },
                {
                    "path": "src/utils.py",
                    "sha": hashlib.sha256(utils_bytes).hexdigest(),
                    "size": len(utils_bytes),
                    "lang": "py",
                    "text": True,
                },
                {
                    "path": "src/app.py",
                    "sha": hashlib.sha256(app_bytes).hexdigest(),
                    "size": len(app_bytes),
                    "lang": "py",
                    "text": True,
                },
            ],
            "filters": {
                "exclude": [".git/*"],
                "max_file_kb": 200,
            },
        }
        self.out_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = self.out_dir / "manifest.json"
        manifest_path.write_text(json.dumps(v02_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        # Step 3: Commit c3 modifying app.py again
        (src_dir / "app.py").write_text("from utils import helper\n\ndef run(): return helper() + 20\n", encoding="utf-8")
        c3 = self._commit("c3: app update in v0.3 era")

        # Step 4: Run v0.3 ingest with the legacy v0.2 manifest
        stats = ingest(
            repo_url=self.fake_github_url,
            out_dir=self.out_dir,
            branch="main",
            commit=None,
            include=None,
            exclude=None,
            max_file_kb=200,
            split_repobook=True,
            previous_manifest=manifest_path,
        )

        # Verification 1: Ingest succeeds without crash
        self.assertEqual(stats["commit"], c3)
        self.assertEqual(stats["changes"]["previous_commit"], c2)
        self.assertEqual(stats["changes"]["modified"], ["src/app.py"])
        self.assertEqual(stats["changes"]["added"], [])
        self.assertEqual(stats["changes"]["deleted"], [])

        # Verification 2: Upgraded manifest now has commit for all files
        upgraded_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files_by_path = {f["path"]: f for f in upgraded_manifest["files"]}
        for path in ["README.md", "src/utils.py", "src/app.py"]:
            self.assertIn("commit", files_by_path[path], f"{path} must have commit after migration")

        # Verification 3: Backfill from git history derives correct per-file last-touch commit
        # README.md was last modified in c1:
        self.assertEqual(files_by_path["README.md"]["commit"], c1)
        # src/utils.py was last modified in c1:
        self.assertEqual(files_by_path["src/utils.py"]["commit"], c1)
        # src/app.py was modified in c3:
        self.assertEqual(files_by_path["src/app.py"]["commit"], c3)

        # Verification 4: ChangeBook correctly reflects version transition from c2 to c3
        cb_content = (self.out_dir / "ChangeBook.md").read_text(encoding="utf-8")
        self.assertIn(f"- Previous commit: `{c2}`", cb_content)
        self.assertIn(f"- Current commit: `{c3}`", cb_content)
        self.assertIn("## Modified Files\n\n- `src/app.py`", cb_content)

        # Verification 5: GraphBook is semantically correct
        gb_content = (self.out_dir / "GraphBook.md").read_text(encoding="utf-8")
        self.assertIn("# GraphBook", gb_content)
        self.assertNotIn("- Commit:", gb_content)
        self.assertIn("src/app.py", gb_content)

        # Verification 6: Git show validates permalink targets
        for path, expected_commit in [("README.md", c1), ("src/utils.py", c1), ("src/app.py", c3)]:
            git_content = subprocess.run(
                ["git", "show", f"{expected_commit}:{path}"],
                cwd=self.git_repo,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            current_snapshot_content = (self.git_repo / path).read_text(encoding="utf-8")
            self.assertEqual(git_content, current_snapshot_content)

    def test_g_permalink_content_equality_proof(self) -> None:
        c1 = self._setup_initial_repo()

        ingest(
            repo_url=self.fake_github_url,
            out_dir=self.out_dir,
            branch="main",
            commit=None,
            include=None,
            exclude=None,
            max_file_kb=200,
            split_repobook=True,
            previous_manifest=None,
        )

        # Modify app.py in c2
        (self.git_repo / "src" / "app.py").write_text("def main(): return 'v2'\n", encoding="utf-8")
        c2 = self._commit("c2: v2")

        ingest(
            repo_url=self.fake_github_url,
            out_dir=self.out_dir,
            branch="main",
            commit=None,
            include=None,
            exclude=None,
            max_file_kb=200,
            split_repobook=True,
            previous_manifest=self.out_dir / "manifest.json",
        )

        manifest = json.loads((self.out_dir / "manifest.json").read_text(encoding="utf-8"))
        proof_records = []
        for item in manifest["files"]:
            p = item["path"]
            pinned_commit = item["commit"]
            # 1. Content in git at pinned commit
            git_data = subprocess.run(
                ["git", "show", f"{pinned_commit}:{p}"],
                cwd=self.git_repo,
                capture_output=True,
                check=True,
            ).stdout
            git_sha = hashlib.sha256(git_data).hexdigest()

            # 2. Content in current snapshot file
            snapshot_data = (self.git_repo / p).read_bytes()
            snapshot_sha = hashlib.sha256(snapshot_data).hexdigest()

            self.assertEqual(git_sha, snapshot_sha)
            proof_records.append({
                "path": p,
                "commit": pinned_commit,
                "git_show_hash": git_sha,
                "snapshot_hash": snapshot_sha,
                "equal": (git_sha == snapshot_sha),
            })

        self.assertEqual(len(proof_records), 3)
        self.assertTrue(all(r["equal"] for r in proof_records))


if __name__ == "__main__":
    unittest.main()
