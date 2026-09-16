from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from repo2nlm.uploader import UploadSource, _delete_source, _plan_sync


class IncrementalSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.out_dir = Path(self._td.name)

    def tearDown(self) -> None:
        self._td.cleanup()

    def _make_spec(self, name: str, content: str) -> UploadSource:
        p = self.out_dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return UploadSource(
            out_dir=self.out_dir,
            namespace="",
            original_title=name,
            upload_path=p,
        )

    def _save_upload_map(self, items: list[dict]) -> None:
        payload = {
            "notebook_id": "test_nb_id",
            "items": items,
        }
        (self.out_dir / "upload_map.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_1_first_upload(self) -> None:
        s1 = self._make_spec("00_overview.md", "overview 1")
        s2 = self._make_spec("01_src.md", "src 1")

        # Remote has no sources yet, no previous upload_map
        plan = _plan_sync(
            out_dirs=[self.out_dir],
            upload_specs=[s1, s2],
            purge_titles=set(),
            remote_sources=[],
            replace_existing=False,
        )

        self.assertEqual(len(plan.to_upload), 2)
        self.assertEqual(len(plan.to_delete_ids), 0)
        self.assertEqual(len(plan.unchanged_titles), 0)

    def test_2_sync_again_no_changes(self) -> None:
        s1 = self._make_spec("00_overview.md", "overview 1")
        s2 = self._make_spec("01_src.md", "src 1")
        sha1 = hashlib.sha256(b"overview 1").hexdigest()
        sha2 = hashlib.sha256(b"src 1").hexdigest()

        self._save_upload_map(
            [
                {
                    "original": "00_overview.md",
                    "uploaded_titles": ["00_overview.md"],
                    "parts": [{"title": "00_overview.md", "local_sha256": sha1, "remote_source_id": "r1"}],
                    "remote_sources": [{"id": "r1", "status": "ready"}],
                },
                {
                    "original": "01_src.md",
                    "uploaded_titles": ["01_src.md"],
                    "parts": [{"title": "01_src.md", "local_sha256": sha2, "remote_source_id": "r2"}],
                    "remote_sources": [{"id": "r2", "status": "ready"}],
                },
            ]
        )

        remote_sources = [
            {"id": "r1", "title": "00_overview.md", "status": "ready"},
            {"id": "r2", "title": "01_src.md", "status": "ready"},
        ]

        plan = _plan_sync(
            out_dirs=[self.out_dir],
            upload_specs=[s1, s2],
            purge_titles=set(),
            remote_sources=remote_sources,
            replace_existing=False,
        )

        # Nothing changed -> 0 uploads, 0 deletions
        self.assertEqual(len(plan.to_upload), 0)
        self.assertEqual(len(plan.to_delete_ids), 0)
        self.assertEqual(plan.unchanged_titles, {"00_overview.md", "01_src.md"})

    def test_3_one_chapter_modified(self) -> None:
        s1 = self._make_spec("00_overview.md", "overview 1")
        s2 = self._make_spec("01_src.md", "src 2 modified!")
        sha1 = hashlib.sha256(b"overview 1").hexdigest()
        sha2_old = hashlib.sha256(b"src 1").hexdigest()

        self._save_upload_map(
            [
                {
                    "original": "00_overview.md",
                    "uploaded_titles": ["00_overview.md"],
                    "parts": [{"title": "00_overview.md", "local_sha256": sha1, "remote_source_id": "r1"}],
                    "remote_sources": [{"id": "r1", "status": "ready"}],
                },
                {
                    "original": "01_src.md",
                    "uploaded_titles": ["01_src.md"],
                    "parts": [{"title": "01_src.md", "local_sha256": sha2_old, "remote_source_id": "r2"}],
                    "remote_sources": [{"id": "r2", "status": "ready"}],
                },
            ]
        )

        remote_sources = [
            {"id": "r1", "title": "00_overview.md", "status": "ready"},
            {"id": "r2", "title": "01_src.md", "status": "ready"},
        ]

        plan = _plan_sync(
            out_dirs=[self.out_dir],
            upload_specs=[s1, s2],
            purge_titles=set(),
            remote_sources=remote_sources,
            replace_existing=False,
        )

        # 00_overview is unchanged, 01_src is modified
        self.assertEqual(plan.unchanged_titles, {"00_overview.md"})
        self.assertEqual([spec.upload_path.name for spec in plan.to_upload], ["01_src.md"])
        # In staged replacement, r2 is not deleted up front; it is staged for replacement after upload
        self.assertEqual(plan.to_delete_ids, set())
        self.assertEqual(plan.replacements, {"01_src.md": ["r2"]})

    def test_4_new_source_added(self) -> None:
        s1 = self._make_spec("00_overview.md", "overview 1")
        s2 = self._make_spec("01_src.md", "src 1")
        s3 = self._make_spec("02_docs.md", "docs 1")
        sha1 = hashlib.sha256(b"overview 1").hexdigest()
        sha2 = hashlib.sha256(b"src 1").hexdigest()

        self._save_upload_map(
            [
                {
                    "original": "00_overview.md",
                    "uploaded_titles": ["00_overview.md"],
                    "parts": [{"title": "00_overview.md", "local_sha256": sha1, "remote_source_id": "r1"}],
                    "remote_sources": [{"id": "r1", "status": "ready"}],
                },
                {
                    "original": "01_src.md",
                    "uploaded_titles": ["01_src.md"],
                    "parts": [{"title": "01_src.md", "local_sha256": sha2, "remote_source_id": "r2"}],
                    "remote_sources": [{"id": "r2", "status": "ready"}],
                },
            ]
        )

        remote_sources = [
            {"id": "r1", "title": "00_overview.md", "status": "ready"},
            {"id": "r2", "title": "01_src.md", "status": "ready"},
        ]

        plan = _plan_sync(
            out_dirs=[self.out_dir],
            upload_specs=[s1, s2, s3],
            purge_titles=set(),
            remote_sources=remote_sources,
            replace_existing=False,
        )

        self.assertEqual(plan.unchanged_titles, {"00_overview.md", "01_src.md"})
        self.assertEqual([spec.upload_path.name for spec in plan.to_upload], ["02_docs.md"])
        self.assertEqual(len(plan.to_delete_ids), 0)

    def test_5_source_deleted(self) -> None:
        s1 = self._make_spec("00_overview.md", "overview 1")
        sha1 = hashlib.sha256(b"overview 1").hexdigest()
        sha2 = hashlib.sha256(b"src 1").hexdigest()

        # Previous upload had 01_src.md, now it is gone
        self._save_upload_map(
            [
                {
                    "original": "00_overview.md",
                    "uploaded_titles": ["00_overview.md"],
                    "parts": [{"title": "00_overview.md", "local_sha256": sha1, "remote_source_id": "r1"}],
                    "remote_sources": [{"id": "r1", "status": "ready"}],
                },
                {
                    "original": "01_src.md",
                    "uploaded_titles": ["01_src.md"],
                    "parts": [{"title": "01_src.md", "local_sha256": sha2, "remote_source_id": "r2"}],
                    "remote_sources": [{"id": "r2", "status": "ready"}],
                },
            ]
        )

        remote_sources = [
            {"id": "r1", "title": "00_overview.md", "status": "ready"},
            {"id": "r2", "title": "01_src.md", "status": "ready"},
        ]

        plan = _plan_sync(
            out_dirs=[self.out_dir],
            upload_specs=[s1],
            purge_titles=set(),
            remote_sources=remote_sources,
            replace_existing=False,
        )

        self.assertEqual(plan.unchanged_titles, {"00_overview.md"})
        self.assertEqual(len(plan.to_upload), 0)
        # r2 (01_src.md) must be deleted
        self.assertEqual(plan.to_delete_ids, {"r2"})

    def test_6_user_manual_sources_not_deleted(self) -> None:
        s1 = self._make_spec("00_overview.md", "overview 1")
        sha1 = hashlib.sha256(b"overview 1").hexdigest()

        self._save_upload_map(
            [
                {
                    "original": "00_overview.md",
                    "uploaded_titles": ["00_overview.md"],
                    "parts": [{"title": "00_overview.md", "local_sha256": sha1, "remote_source_id": "r1"}],
                    "remote_sources": [{"id": "r1", "status": "ready"}],
                },
            ]
        )

        remote_sources = [
            {"id": "r1", "title": "00_overview.md", "status": "ready"},
            {"id": "user_doc_1", "title": "architecture_notes.pdf", "status": "ready"},
            {"id": "user_doc_2", "title": "Meeting_2026_09.txt", "status": "ready"},
        ]

        plan = _plan_sync(
            out_dirs=[self.out_dir],
            upload_specs=[s1],
            purge_titles=set(),
            remote_sources=remote_sources,
            replace_existing=False,
        )

        self.assertNotIn("user_doc_1", plan.to_delete_ids)
        self.assertNotIn("user_doc_2", plan.to_delete_ids)
        self.assertEqual(len(plan.to_delete_ids), 0)

    def test_7_stale_split_parts_cleaned(self) -> None:
        # Previously, 01_big.md was split into part01, part02, part03.
        # Now it shrank and only part01 and part02 exist.
        s1 = self._make_spec("01_big.part01.md", "part 1")
        s2 = self._make_spec("01_big.part02.md", "part 2")
        sha1 = hashlib.sha256(b"part 1").hexdigest()
        sha2 = hashlib.sha256(b"part 2").hexdigest()

        self._save_upload_map(
            [
                {
                    "original": "01_big.md",
                    "uploaded_titles": ["01_big.part01.md", "01_big.part02.md", "01_big.part03.md"],
                    "parts": [
                        {"title": "01_big.part01.md", "local_sha256": sha1, "remote_source_id": "part1_id"},
                        {"title": "01_big.part02.md", "local_sha256": sha2, "remote_source_id": "part2_id"},
                        {"title": "01_big.part03.md", "local_sha256": "old_sha", "remote_source_id": "part3_id"},
                    ],
                    "remote_sources": [
                        {"id": "part1_id", "status": "ready"},
                        {"id": "part2_id", "status": "ready"},
                        {"id": "part3_id", "status": "ready"},
                    ],
                }
            ]
        )

        remote_sources = [
            {"id": "part1_id", "title": "01_big.part01.md", "status": "ready"},
            {"id": "part2_id", "title": "01_big.part02.md", "status": "ready"},
            {"id": "part3_id", "title": "01_big.part03.md", "status": "ready"},
        ]

        plan = _plan_sync(
            out_dirs=[self.out_dir],
            upload_specs=[s1, s2],
            purge_titles={"01_big.md"},
            remote_sources=remote_sources,
            replace_existing=False,
        )

        # part01 and part02 are unchanged; part03 was removed and MUST be deleted
        self.assertEqual(plan.unchanged_titles, {"01_big.part01.md", "01_big.part02.md"})
        self.assertEqual(len(plan.to_upload), 0)
        self.assertEqual(plan.to_delete_ids, {"part3_id"})

    def test_8_replace_existing_forces_reupload(self) -> None:
        s1 = self._make_spec("00_overview.md", "overview 1")
        sha1 = hashlib.sha256(b"overview 1").hexdigest()

        self._save_upload_map(
            [
                {
                    "original": "00_overview.md",
                    "uploaded_titles": ["00_overview.md"],
                    "parts": [{"title": "00_overview.md", "local_sha256": sha1, "remote_source_id": "r1"}],
                    "remote_sources": [{"id": "r1", "status": "ready"}],
                },
            ]
        )

        remote_sources = [
            {"id": "r1", "title": "00_overview.md", "status": "ready"},
        ]

        plan = _plan_sync(
            out_dirs=[self.out_dir],
            upload_specs=[s1],
            purge_titles=set(),
            remote_sources=remote_sources,
            replace_existing=True,
        )

        self.assertEqual(plan.to_delete_ids, {"r1"})
        self.assertEqual(len(plan.to_upload), 1)
        self.assertEqual(len(plan.unchanged_titles), 0)

    def test_9_ownership_guard_title_collision(self) -> None:
        # A user manually uploaded a document named 01_src.md directly into NotebookLM.
        # Repo2NLM previously uploaded 01_src.md with ID r2.
        # When 01_src.md is modified, the user's manual document MUST NOT be deleted or targeted.
        s1 = self._make_spec("01_src.md", "new modified content")
        sha2_old = hashlib.sha256(b"old content").hexdigest()

        self._save_upload_map(
            [
                {
                    "original": "01_src.md",
                    "uploaded_titles": ["01_src.md"],
                    "parts": [{"title": "01_src.md", "local_sha256": sha2_old, "remote_source_id": "r2"}],
                    "remote_sources": [{"id": "r2", "status": "ready"}],
                },
            ]
        )

        remote_sources = [
            {"id": "r2", "title": "01_src.md", "status": "ready"},
            {"id": "user_manual_doc", "title": "01_src.md", "status": "ready"},
        ]

        plan = _plan_sync(
            out_dirs=[self.out_dir],
            upload_specs=[s1],
            purge_titles=set(),
            remote_sources=remote_sources,
            replace_existing=False,
        )

        # r2 is staged for replacement, user_manual_doc is completely untouched
        self.assertEqual(plan.replacements, {"01_src.md": ["r2"]})
        self.assertNotIn("user_manual_doc", plan.to_delete_ids)
        self.assertNotIn("user_manual_doc", plan.replacements.get("01_src.md", []))

    def test_10_ownership_guard_purge_title_collision(self) -> None:
        # A file 01_big.md is now split, so 01_big.md is in purge_titles.
        # Suppose a user also uploaded a personal file named 01_big.md (ID: user_big_note).
        # And previously Repo2NLM managed 01_big.md with ID r_managed_big.
        s1 = self._make_spec("01_big.part01.md", "part 1")
        s2 = self._make_spec("01_big.part02.md", "part 2")

        self._save_upload_map(
            [
                {
                    "original": "01_big.md",
                    "uploaded_titles": ["01_big.md"],
                    "parts": [{"title": "01_big.md", "local_sha256": "old_sha", "remote_source_id": "r_managed_big"}],
                    "remote_sources": [{"id": "r_managed_big", "status": "ready"}],
                },
            ]
        )

        remote_sources = [
            {"id": "r_managed_big", "title": "01_big.md", "status": "ready"},
            {"id": "user_big_note", "title": "01_big.md", "status": "ready"},
        ]

        plan = _plan_sync(
            out_dirs=[self.out_dir],
            upload_specs=[s1, s2],
            purge_titles={"01_big.md"},
            remote_sources=remote_sources,
            replace_existing=False,
        )

        # Only the managed source is deleted; the colliding user source is NEVER deleted
        self.assertIn("r_managed_big", plan.to_delete_ids)
        self.assertNotIn("user_big_note", plan.to_delete_ids)

    def test_11_delete_source_raises_permission_error_on_unmanaged_id(self) -> None:
        allowed = {"managed_1", "managed_2"}
        with self.assertRaises(PermissionError):
            _delete_source("dummy_cli", "nb_1", "user_unmanaged_doc", allowed_ids=allowed)


if __name__ == "__main__":
    unittest.main()
