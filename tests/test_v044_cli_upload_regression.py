from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from repo2nlm.cli import build_parser, main


class TestV044CliUploadRegression(unittest.TestCase):
    """Regression tests for v0.4.4 ensuring upload subcommand and entrypoints do not crash."""

    @patch("repo2nlm.cli.upload_to_notebooklm")
    def test_upload_subcommand_via_main_no_attribute_error(self, mock_upload: MagicMock) -> None:
        """Verify repo2nlm upload ./out --notebook test does not crash with AttributeError."""
        ret = main(["upload", "./out", "--notebook", "test"])
        self.assertEqual(ret, 0)
        mock_upload.assert_called_once_with(
            [Path("./out")],
            "test",
            create_if_missing=False,
            replace_existing=False,
        )

    @patch("repo2nlm.cli.upload_to_notebooklm")
    def test_upload_via_sys_argv(self, mock_upload: MagicMock) -> None:
        """Verify main() reading sys.argv directly executes upload without error."""
        with patch.object(sys, "argv", ["repo2nlm", "upload", "./out", "--notebook", "test"]):
            ret = main()
            self.assertEqual(ret, 0)
            mock_upload.assert_called_once_with(
                [Path("./out")],
                "test",
                create_if_missing=False,
                replace_existing=False,
            )

    @patch("repo2nlm.cli.upload_to_notebooklm")
    def test_upload_multiple_outs_with_flags(self, mock_upload: MagicMock) -> None:
        """Verify upload with multiple outputs, create-if-missing and replace-existing."""
        ret = main([
            "upload",
            "./out1",
            "./out2",
            "--notebook",
            "test-nb",
            "--create-if-missing",
            "--replace-existing",
        ])
        self.assertEqual(ret, 0)
        mock_upload.assert_called_once_with(
            [Path("./out1"), Path("./out2")],
            "test-nb",
            create_if_missing=True,
            replace_existing=True,
        )

    @patch("repo2nlm.cli.ingest")
    def test_ingest_entrypoint_safe(self, mock_ingest: MagicMock) -> None:
        """Verify ingest subcommand passes through main entrypoint safely."""
        mock_ingest.return_value = {"status": "ok"}
        ret = main(["ingest", "https://github.com/example/repo", "--out", "./out"])
        self.assertEqual(ret, 0)
        self.assertTrue(mock_ingest.called)
        _, kwargs = mock_ingest.call_args
        self.assertIsNone(kwargs.get("adaptive_partition"))

    @patch("repo2nlm.cli.ingest")
    def test_update_entrypoint_safe(self, mock_ingest: MagicMock) -> None:
        """Verify update subcommand passes through main entrypoint safely."""
        mock_ingest.return_value = {"status": "ok"}
        ret = main(["update", "https://github.com/example/repo", "--out", "./out"])
        self.assertEqual(ret, 0)
        self.assertTrue(mock_ingest.called)
        _, kwargs = mock_ingest.call_args
        self.assertIsNone(kwargs.get("adaptive_partition"))

    @patch("repo2nlm.cli.upload_to_notebooklm")
    @patch("repo2nlm.cli.ingest")
    def test_sync_entrypoint_default_partition(
        self, mock_ingest: MagicMock, mock_upload: MagicMock
    ) -> None:
        """Verify sync default passes adaptive_partition=None."""
        mock_ingest.return_value = {"status": "ok"}
        ret = main(["sync", "https://github.com/example/repo", "--notebook", "test", "--out", "./out"])
        self.assertEqual(ret, 0)
        self.assertTrue(mock_ingest.called)
        _, kwargs = mock_ingest.call_args
        self.assertIsNone(kwargs.get("adaptive_partition"))

    @patch("repo2nlm.cli.upload_to_notebooklm")
    @patch("repo2nlm.cli.ingest")
    def test_sync_entrypoint_adaptive_partition(
        self, mock_ingest: MagicMock, mock_upload: MagicMock
    ) -> None:
        """Verify sync with --adaptive-partition passes adaptive_partition=True."""
        mock_ingest.return_value = {"status": "ok"}
        ret = main([
            "sync",
            "https://github.com/example/repo",
            "--notebook",
            "test",
            "--out",
            "./out",
            "--adaptive-partition",
        ])
        self.assertEqual(ret, 0)
        self.assertTrue(mock_ingest.called)
        _, kwargs = mock_ingest.call_args
        self.assertTrue(kwargs.get("adaptive_partition"))

    @patch("repo2nlm.cli.upload_to_notebooklm")
    @patch("repo2nlm.cli.ingest")
    def test_sync_entrypoint_no_adaptive_partition(
        self, mock_ingest: MagicMock, mock_upload: MagicMock
    ) -> None:
        """Verify sync with --no-adaptive-partition passes adaptive_partition=False."""
        mock_ingest.return_value = {"status": "ok"}
        ret = main([
            "sync",
            "https://github.com/example/repo",
            "--notebook",
            "test",
            "--out",
            "./out",
            "--no-adaptive-partition",
        ])
        self.assertEqual(ret, 0)
        self.assertTrue(mock_ingest.called)
        _, kwargs = mock_ingest.call_args
        self.assertFalse(kwargs.get("adaptive_partition"))


if __name__ == "__main__":
    unittest.main()
