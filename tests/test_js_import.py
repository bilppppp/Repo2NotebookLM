from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from repo2nlm.graph_builder import _resolve_js_import


class JsImportResolutionTests(unittest.TestCase):
    def test_relative_current_directory_ts(self) -> None:
        file_set = {"src/a.ts", "src/utils/b.ts"}
        target, external = _resolve_js_import("src/a.ts", "./utils/b", file_set)
        self.assertEqual(target, "src/utils/b.ts")
        self.assertFalse(external)

    def test_relative_parent_directory_tsx(self) -> None:
        file_set = {"src/components/button.tsx", "src/utils/helpers.tsx"}
        target, external = _resolve_js_import("src/components/button.tsx", "../utils/helpers", file_set)
        self.assertEqual(target, "src/utils/helpers.tsx")
        self.assertFalse(external)

    def test_relative_js_and_jsx(self) -> None:
        file_set = {"src/index.js", "src/components/App.jsx"}
        target_jsx, ext_jsx = _resolve_js_import("src/index.js", "./components/App", file_set)
        self.assertEqual(target_jsx, "src/components/App.jsx")
        self.assertFalse(ext_jsx)

        target_js, ext_js = _resolve_js_import("src/components/App.jsx", "../index.js", file_set)
        self.assertEqual(target_js, "src/index.js")
        self.assertFalse(ext_js)

    def test_directory_index_resolution(self) -> None:
        file_set = {"src/main.ts", "src/routes/index.ts"}
        target, external = _resolve_js_import("src/main.ts", "./routes", file_set)
        self.assertEqual(target, "src/routes/index.ts")
        self.assertFalse(external)

    def test_ts_esm_import_js_extension_maps_to_ts(self) -> None:
        file_set = {"src/server.ts", "src/config.ts"}
        # In ESM TypeScript, code often writes import "./config.js"
        target, external = _resolve_js_import("src/server.ts", "./config.js", file_set)
        self.assertEqual(target, "src/config.ts")
        self.assertFalse(external)

    def test_external_package_import(self) -> None:
        file_set = {"src/a.ts"}
        target_react, ext_react = _resolve_js_import("src/a.ts", "react", file_set)
        self.assertEqual(target_react, "react")
        self.assertTrue(ext_react)

        target_scope, ext_scope = _resolve_js_import("src/a.ts", "@angular/core", file_set)
        self.assertEqual(target_scope, "@angular/core")
        self.assertTrue(ext_scope)

        target_sub, ext_sub = _resolve_js_import("src/a.ts", "lodash/get", file_set)
        self.assertEqual(target_sub, "lodash/get")
        self.assertTrue(ext_sub)

    def test_does_not_resolve_to_host_filesystem(self) -> None:
        # Verify that an import of "./setup.py" from "src/cli.ts" does not resolve to the host root /setup.py
        file_set = {"src/cli.ts"}
        target, external = _resolve_js_import("src/cli.ts", "./setup.py", file_set)
        self.assertFalse(target.startswith("/"))
        self.assertTrue(external)


if __name__ == "__main__":
    unittest.main()
