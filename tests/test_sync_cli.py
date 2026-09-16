from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from repo2nlm.cli import build_parser


class SyncCliEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.base = Path(self._td.name)

        # 1. Fake notebooklm CLI
        self.bin_dir = self.base / "bin"
        self.bin_dir.mkdir()
        self.state_file = self.base / "fake_nlm_state.json"
        self.state_file.write_text(
            json.dumps(
                {
                    "notebooks": [{"id": "nb-test-123", "title": "my-project"}],
                    "sources": [],
                    "calls": [],
                }
            ),
            encoding="utf-8",
        )

        fake_cli = self.bin_dir / "notebooklm"
        fake_cli_script = f"""#!/usr/bin/env python3
import sys, json
from pathlib import Path

state_file = Path({repr(str(self.state_file))})
state = json.loads(state_file.read_text(encoding="utf-8"))

args = sys.argv[1:]
if "calls" not in state:
    state["calls"] = []
state["calls"].append(args)
state_file.write_text(json.dumps(state))

if "--version" in args:
    print("notebooklm, version 0.8.2")
    sys.exit(0)

if not args:
    sys.exit(0)

cmd = args[0]
if cmd == "list" and "--json" in args:
    print(json.dumps({{"notebooks": state["notebooks"]}}))
    sys.exit(0)

if cmd == "create":
    title = args[1]
    nb_nid = state.get("next_nb_id", len(state["notebooks"]) + 1)
    nb_id = f"nb-{{nb_nid}}"
    state["next_nb_id"] = nb_nid + 1
    nb = {{"id": nb_id, "title": title}}
    state["notebooks"].append(nb)
    state_file.write_text(json.dumps(state))
    print(json.dumps({{"notebook": nb}}))
    sys.exit(0)

if cmd == "source":
    sub = args[1]
    if sub == "list" and "--json" in args:
        print(json.dumps({{"sources": state["sources"]}}))
        sys.exit(0)
    if sub == "add":
        if state.get("simulate_fail_upload"):
            sys.stderr.write("simulated upload network error\\n")
            sys.exit(1)
        file_path = Path(args[2])
        nid = state.get("next_id", len(state["sources"]) + 1)
        src_id = f"src-{{nid}}"
        state["next_id"] = nid + 1
        title = file_path.name
        state["sources"].append({{"id": src_id, "title": title, "status": "ready"}})
        state_file.write_text(json.dumps(state))
        print(json.dumps({{"source": {{"id": src_id, "title": title, "status": "ready"}}}}))
        sys.exit(0)
    if sub == "wait":
        if state.get("simulate_fail_wait"):
            sys.stderr.write("simulated wait timeout error\\n")
            sys.exit(1)
        sys.exit(0)
    if sub == "delete":
        src_id = args[2]
        state["sources"] = [s for s in state["sources"] if s.get("id") != src_id]
        state_file.write_text(json.dumps(state))
        sys.exit(0)
    if sub == "rename":
        if state.get("simulate_fail_rename"):
            sys.stderr.write("simulated rename error\\n")
            sys.exit(1)
        src_id = args[2]
        new_title = args[3]
        for s in state["sources"]:
            if s.get("id") == src_id:
                s["title"] = new_title
        state_file.write_text(json.dumps(state))
        sys.exit(0)

sys.exit(0)
"""
        fake_cli.write_text(fake_cli_script, encoding="utf-8")
        fake_cli.chmod(0o755)

        self._old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{self.bin_dir}:{self._old_path}"

        # 2. Local git repo
        self.repo_dir = self.base / "git_repo"
        self.repo_dir.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=self.repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=self.repo_dir, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.repo_dir, check=True)

        self.out_dir = self.base / "out"

    def tearDown(self) -> None:
        os.environ["PATH"] = self._old_path
        self._td.cleanup()

    def _commit(self, msg: str) -> None:
        subprocess.run(["git", "add", "."], cwd=self.repo_dir, check=True)
        subprocess.run(["git", "commit", "-m", msg], cwd=self.repo_dir, check=True, capture_output=True)

    def _read_state(self) -> dict:
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def _write_state(self, state: dict) -> None:
        self.state_file.write_text(json.dumps(state), encoding="utf-8")

    def _clear_calls(self) -> None:
        st = self._read_state()
        st["calls"] = []
        self._write_state(st)

    def _count_calls(self) -> dict[str, int]:
        st = self._read_state()
        calls = st.get("calls", [])
        counts = {"source add": 0, "source delete": 0, "source rename": 0}
        for c in calls:
            if len(c) >= 2 and c[0] == "source":
                key = f"source {c[1]}"
                if key in counts:
                    counts[key] += 1
        return counts

    def _file_sha(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_sync_lifecycle_with_fake_notebooklm(self) -> None:
        # Step 1: Initial files
        (self.repo_dir / "README.md").write_text("# My Repo\n", encoding="utf-8")
        src_dir = self.repo_dir / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text("def run(): pass\n", encoding="utf-8")
        self._commit("initial")

        parser = build_parser()

        # Run sync 1 (initial sync)
        args1 = parser.parse_args(
            [
                "sync",
                str(self.repo_dir),
                "--notebook",
                "my-project",
                "--out",
                str(self.out_dir),
            ]
        )
        rc1 = args1.func(args1)
        self.assertEqual(rc1, 0)

        # Check remote sources
        state1 = self._read_state()
        remote_titles1 = {s["title"] for s in state1["sources"]}
        self.assertIn("00_overview.md", remote_titles1)
        self.assertIn("GraphBook.md", remote_titles1)
        self.assertIn("ChangeBook.md", remote_titles1)
        self.assertIn("02_src.md", remote_titles1)

        changebook_path = self.out_dir / "ChangeBook.md"
        sha_sync1 = self._file_sha(changebook_path)

        upload_map1 = json.loads((self.out_dir / "upload_map.json").read_text(encoding="utf-8"))
        self.assertEqual(upload_map1["notebooklm_version"], "notebooklm, version 0.8.2")
        self.assertEqual(len(upload_map1["missing_titles"]), 0)

        # Step 2: Immediate no-op sync without modifying any repo files
        sha_pre_sync2 = self._file_sha(changebook_path)
        self._clear_calls()

        args2 = parser.parse_args(
            [
                "sync",
                str(self.repo_dir),
                "--notebook",
                "my-project",
                "--out",
                str(self.out_dir),
            ]
        )
        rc2 = args2.func(args2)
        self.assertEqual(rc2, 0)

        sha_post_sync2 = self._file_sha(changebook_path)

        # Audit check: ChangeBook.md SHA256 must remain identical across no-op sync
        self.assertEqual(sha_sync1, sha_pre_sync2)
        self.assertEqual(sha_pre_sync2, sha_post_sync2)

        # Fake CLI call counts during no-op sync: exactly 0 add, 0 delete, 0 rename
        counts2 = self._count_calls()
        self.assertEqual(counts2["source add"], 0)
        self.assertEqual(counts2["source delete"], 0)
        self.assertEqual(counts2["source rename"], 0)

        upload_map2 = json.loads((self.out_dir / "upload_map.json").read_text(encoding="utf-8"))
        self.assertEqual(upload_map2["sync_stats"]["unchanged"], 5)
        self.assertEqual(upload_map2["sync_stats"]["uploading"], 0)
        self.assertEqual(upload_map2["sync_stats"]["deleted"], 0)

        # Step 3: Add user manual sources (including title collision with a repo chapter)
        state2 = self._read_state()
        state2["sources"].append(
            {"id": "user_note_999", "title": "UserHandwrittenDoc.pdf", "status": "ready"}
        )
        state2["sources"].append(
            {"id": "user_colliding_note", "title": "01_root.md", "status": "ready"}
        )
        self._write_state(state2)

        # Step 4: Modify a file, add a file
        (src_dir / "app.py").write_text("def run(): print('v2')\n", encoding="utf-8")
        (src_dir / "new_module.py").write_text("def extra(): pass\n", encoding="utf-8")
        self._commit("update")

        args3 = parser.parse_args(
            [
                "sync",
                str(self.repo_dir),
                "--notebook",
                "my-project",
                "--out",
                str(self.out_dir),
            ]
        )
        rc3 = args3.func(args3)
        self.assertEqual(rc3, 0)

        state3 = self._read_state()
        remote_ids3 = {s["id"] for s in state3["sources"]}
        # Ownership guard: User manual sources (even with colliding title 01_root.md) must NOT be deleted!
        self.assertIn("user_note_999", remote_ids3)
        self.assertIn("user_colliding_note", remote_ids3)

    def test_staged_replacement_failure_preserves_old_source_and_user_sources(self) -> None:
        # Step 1: Initial ingest
        (self.repo_dir / "README.md").write_text("# Smoke Test\n", encoding="utf-8")
        src_dir = self.repo_dir / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text("def run(): pass\n", encoding="utf-8")
        self._commit("v1")

        parser = build_parser()
        args1 = parser.parse_args(
            ["sync", str(self.repo_dir), "--notebook", "my-project", "--out", str(self.out_dir)]
        )
        self.assertEqual(args1.func(args1), 0)

        # Identify existing managed source ID for 02_src.md
        state1 = self._read_state()
        old_src_source = next(s for s in state1["sources"] if s["title"] == "02_src.md")
        old_src_id = old_src_source["id"]

        # Add manual user document
        state1["sources"].append({"id": "user_doc_safeguard", "title": "UserNotes.txt", "status": "ready"})
        self._write_state(state1)

        # Step 2: Modify app.py and trigger sync with simulated upload failure
        (src_dir / "app.py").write_text("def run(): print('broken upload')\n", encoding="utf-8")
        self._commit("v2")

        st = self._read_state()
        st["simulate_fail_upload"] = True
        self._write_state(st)

        args2 = parser.parse_args(
            ["sync", str(self.repo_dir), "--notebook", "my-project", "--out", str(self.out_dir)]
        )
        # Staged replacement: upload fails visibly!
        with self.assertRaises(RuntimeError):
            args2.func(args2)

        # Critical verification: old source is PRESERVED intact and user source is PRESERVED intact!
        state_after_fail = self._read_state()
        after_ids = {s["id"]: s for s in state_after_fail["sources"]}
        self.assertIn(old_src_id, after_ids)
        self.assertEqual(after_ids[old_src_id]["title"], "02_src.md")
        self.assertEqual(after_ids[old_src_id]["status"], "ready")
        self.assertIn("user_doc_safeguard", after_ids)

    def test_staged_replacement_rename_failure_preserves_staged_and_manual_sources(self) -> None:
        # Step 1: Initial ingest
        (self.repo_dir / "README.md").write_text("# Test Repo\n", encoding="utf-8")
        src_dir = self.repo_dir / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text("def run(): pass\n", encoding="utf-8")
        self._commit("v1")

        parser = build_parser()
        args1 = parser.parse_args(
            ["sync", str(self.repo_dir), "--notebook", "my-project", "--out", str(self.out_dir)]
        )
        self.assertEqual(args1.func(args1), 0)

        # Locate old managed source for 00_overview.md
        state1 = self._read_state()
        old_src = next(s for s in state1["sources"] if s["title"] == "00_overview.md")
        old_src_id = old_src["id"]

        # Add manual user document to remote notebook
        manual_user_doc_id = "user_manual_doc_123"
        state1["sources"].append(
            {"id": manual_user_doc_id, "title": "my_personal_notes.txt", "status": "ready"}
        )
        self._write_state(state1)

        # Step 2: Modify app.py and trigger sync with simulated rename failure
        (src_dir / "app.py").write_text("def run(): print('v2 modified')\n", encoding="utf-8")
        self._commit("v2")

        st = self._read_state()
        st["simulate_fail_rename"] = True
        self._write_state(st)

        # 1) Execute sync via CLI argument dispatch and verify it raises RuntimeError
        args2 = parser.parse_args(
            ["sync", str(self.repo_dir), "--notebook", "my-project", "--out", str(self.out_dir)]
        )
        with self.assertRaises(RuntimeError) as ctx:
            args2.func(args2)

        err_msg = str(ctx.exception)
        # Verify error message contains staging source ID, intended canonical title, and manual recovery hint
        self.assertIn("00_overview.md", err_msg)
        self.assertIn("failed to rename staged source", err_msg)
        self.assertIn("The staged source remains ready and safe on remote", err_msg)
        self.assertIn("No data was lost", err_msg)
        self.assertIn("manually recover", err_msg)

        # 2) Also verify CLI process invocation exits non-zero with error output
        cmd = [
            sys.executable,
            str(ROOT / "repo2nlm"),
            "sync",
            str(self.repo_dir),
            "--notebook",
            "my-project",
            "--out",
            str(self.out_dir),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=os.environ)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("failed to rename staged source", proc.stderr)

        # 3) Verify remote state after failure:
        state_after = self._read_state()
        remote_sources_after = state_after["sources"]
        remote_ids_after = {s["id"]: s for s in remote_sources_after}

        # 3a. Manual user source survives and remains ready
        self.assertIn(manual_user_doc_id, remote_ids_after)
        self.assertEqual(remote_ids_after[manual_user_doc_id]["title"], "my_personal_notes.txt")
        self.assertEqual(remote_ids_after[manual_user_doc_id]["status"], "ready")

        # 3b. Old managed source was deleted
        self.assertNotIn(old_src_id, remote_ids_after)

        # 3c. Staged source survives, is ready, and is NOT deleted
        staging_sources = [
            s for s in remote_sources_after
            if s["title"].startswith("_staging_") and s["title"].endswith("_00_overview.md")
        ]
        self.assertTrue(len(staging_sources) >= 1)
        staged_src = staging_sources[0]
        self.assertEqual(staged_src["status"], "ready")
        self.assertIn(staged_src["id"], err_msg)


if __name__ == "__main__":
    unittest.main()
