from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from repo2nlm.cli import ingest
from repo2nlm.config import DEFAULT_MAX_GROUP_FILES, DEFAULT_MAX_GROUP_KB
from repo2nlm.renderers.books import (
    _clean_segment,
    _partition_directory,
    _path_slug,
    render_repobook,
)
from repo2nlm.types import FileRecord


def make_record(path: str, content: str = "print('hello')", commit: str = "c0ffee") -> FileRecord:
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


class AdaptivePartitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.td = tempfile.TemporaryDirectory(prefix="test_adaptive_")
        self.out_dir = Path(self.td.name)

    def tearDown(self) -> None:
        self.td.cleanup()

    def test_a_small_repo_backward_compatibility(self) -> None:
        """Test A: Small repo not exceeding threshold preserves exact v0.3.1 filenames."""
        files = [
            make_record("README.md", "# Test Repo\nSmall project"),
            make_record("src/main.py", "def run():\n    return 42\n"),
            make_record("tests/test_main.py", "def test_run():\n    assert run() == 42\n"),
        ]
        paths = render_repobook(
            out_dir=self.out_dir,
            repo_url="https://github.com/example/small.git",
            branch="main",
            commit="111111",
            files=files,
            entries=[],
            split_repobook=True,
            max_group_kb=512,
            max_group_files=40,
            adaptive_partition=True,
        )
        filenames = [p.name for p in paths]
        self.assertEqual(
            filenames,
            ["00_overview.md", "01_root.md", "02_src.md", "03_tests.md"],
        )

    def test_b_oversized_top_level_split(self) -> None:
        """Test B: Oversized top-level group splits by immediate subdirectories."""
        files = [
            make_record("src/a/foo.py", "x = 1\n" * 20),
            make_record("src/b/bar.py", "y = 2\n" * 20),
        ]
        # max_group_files=1 forces split of src/ (which has 2 files)
        paths = render_repobook(
            out_dir=self.out_dir,
            repo_url="https://github.com/example/split.git",
            branch="main",
            commit="222222",
            files=files,
            entries=[],
            split_repobook=True,
            max_group_kb=512,
            max_group_files=1,
            adaptive_partition=True,
        )
        filenames = [p.name for p in paths]
        self.assertIn("00_overview.md", filenames)
        self.assertIn("01_src__a.md", filenames)
        self.assertIn("01_src__b.md", filenames)
        self.assertNotIn("01_src.md", filenames)

    def test_c_recursive_split(self) -> None:
        """Test C: Recursive split when a subsystem is still oversized."""
        files = [
            make_record("src/router/a/route_a.py", "def a(): pass\n"),
            make_record("src/router/b/route_b.py", "def b(): pass\n"),
            make_record("src/client/client.py", "def c(): pass\n"),
        ]
        # max_group_files=1 forces recursive split into src__router__a, src__router__b, src__client
        paths = render_repobook(
            out_dir=self.out_dir,
            repo_url="https://github.com/example/recurse.git",
            branch="main",
            commit="333333",
            files=files,
            entries=[],
            split_repobook=True,
            max_group_kb=512,
            max_group_files=1,
            adaptive_partition=True,
        )
        filenames = [p.name for p in paths]
        self.assertIn("01_src__client.md", filenames)
        self.assertIn("01_src__router__a.md", filenames)
        self.assertIn("01_src__router__b.md", filenames)

    def test_d_leaf_fallback(self) -> None:
        """Test D: Flat leaf directory fallback chunks deterministically with part numbering."""
        files = [
            make_record(f"src/utils/tool_{i:02d}.py", f"def f{i}(): return {i}\n")
            for i in range(1, 11)
        ]
        # max_group_files=4 chunks 10 files into parts of size 4: part01 (4), part02 (4), part03 (2)
        paths = render_repobook(
            out_dir=self.out_dir,
            repo_url="https://github.com/example/flat.git",
            branch="main",
            commit="444444",
            files=files,
            entries=[],
            split_repobook=True,
            max_group_kb=512,
            max_group_files=4,
            adaptive_partition=True,
        )
        filenames = [p.name for p in paths]
        self.assertIn("01_src__utils__part01.md", filenames)
        self.assertIn("01_src__utils__part02.md", filenames)
        self.assertIn("01_src__utils__part03.md", filenames)

    def test_e_exactly_once_coverage(self) -> None:
        """Test E: Every text file is accounted for exactly once across all generated chapters."""
        files = [
            make_record("README.md", "# Readme"),
            make_record("src/index.py", "import router\n"),
            make_record("src/client/api.py", "class API: pass\n"),
            make_record("src/middleware/auth.py", "def auth(): pass\n"),
            make_record("src/middleware/log.py", "def log(): pass\n"),
            make_record("src/router/trie.py", "class Trie: pass\n"),
            make_record("src/router/radix.py", "class Radix: pass\n"),
            make_record("tests/test_api.py", "def test_api(): pass\n"),
        ]
        paths = render_repobook(
            out_dir=self.out_dir,
            repo_url="https://github.com/example/coverage.git",
            branch="main",
            commit="555555",
            files=files,
            entries=[],
            split_repobook=True,
            max_group_kb=512,
            max_group_files=2,
            adaptive_partition=True,
        )
        expected_paths = {f.path for f in files}
        seen_files: list[str] = []
        for p in paths:
            if p.name == "00_overview.md":
                continue
            text = p.read_text(encoding="utf-8")
            for line in text.splitlines():
                if line.startswith("## "):
                    candidate = line[3:].strip()
                    if candidate in expected_paths:
                        seen_files.append(candidate)

        expected = sorted(files_map.path for files_map in files)
        self.assertEqual(sorted(seen_files), expected)
        self.assertEqual(len(seen_files), len(set(seen_files)), "Duplicate files found across modules!")

    def test_f_body_only_churn_isolation(self) -> None:
        """Test F: Modifying a function body in one module leaves other modules byte-identical."""
        files_v1 = [
            make_record("src/client/fetch.py", "def fetch(url):\n    return http_get(url)\n"),
            make_record("src/router/trie.py", "def match(path):\n    return True\n"),
            make_record("src/utils/format.py", "def fmt(s):\n    return s.strip()\n"),
        ]
        out1 = self.out_dir / "v1"
        render_repobook(
            out_dir=out1,
            repo_url="https://github.com/example/churn.git",
            branch="main",
            commit="666666",
            files=files_v1,
            entries=[],
            split_repobook=True,
            max_group_kb=512,
            max_group_files=1,
            adaptive_partition=True,
        )
        v1_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (out1 / "RepoBook").glob("*.md")}

        # Modify only client/fetch.py body
        files_v2 = [
            make_record("src/client/fetch.py", "def fetch(url):\n    # mutated body\n    return http_get(url)\n"),
            make_record("src/router/trie.py", "def match(path):\n    return True\n"),
            make_record("src/utils/format.py", "def fmt(s):\n    return s.strip()\n"),
        ]
        out2 = self.out_dir / "v2"
        render_repobook(
            out_dir=out2,
            repo_url="https://github.com/example/churn.git",
            branch="main",
            commit="666666",
            files=files_v2,
            entries=[],
            split_repobook=True,
            max_group_kb=512,
            max_group_files=1,
            adaptive_partition=True,
        )
        v2_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (out2 / "RepoBook").glob("*.md")}

        self.assertNotEqual(v1_hashes["01_src__client.md"], v2_hashes["01_src__client.md"])
        self.assertEqual(v1_hashes["01_src__router.md"], v2_hashes["01_src__router.md"])
        self.assertEqual(v1_hashes["01_src__utils.md"], v2_hashes["01_src__utils.md"])

    def test_g_deterministic_build(self) -> None:
        """Test G: Two independent renders of the same files produce byte-identical artifacts."""
        files = [
            make_record("src/adapter/node.py", "def node(): pass\n"),
            make_record("src/adapter/deno.py", "def deno(): pass\n"),
            make_record("src/middleware/cors.py", "def cors(): pass\n"),
            make_record("src/index.py", "import adapter\n"),
        ]
        out1 = self.out_dir / "run1"
        out2 = self.out_dir / "run2"

        paths1 = render_repobook(
            out_dir=out1,
            repo_url="https://github.com/example/det.git",
            branch="main",
            commit="777777",
            files=files,
            entries=[],
            split_repobook=True,
            max_group_kb=512,
            max_group_files=1,
            adaptive_partition=True,
        )
        paths2 = render_repobook(
            out_dir=out2,
            repo_url="https://github.com/example/det.git",
            branch="main",
            commit="777777",
            files=files,
            entries=[],
            split_repobook=True,
            max_group_kb=512,
            max_group_files=1,
            adaptive_partition=True,
        )

        names1 = [p.name for p in paths1]
        names2 = [p.name for p in paths2]
        self.assertEqual(names1, names2)

        for n in names1:
            b1 = (out1 / "RepoBook" / n).read_bytes()
            b2 = (out2 / "RepoBook" / n).read_bytes()
            self.assertEqual(b1, b2, f"Artifact {n} differs between runs!")

    def test_h_no_split_repobook(self) -> None:
        """Test H: split_repobook=False generates single RepoBook.md even if oversized."""
        files = [
            make_record(f"src/file_{i}.py", f"x = {i}\n" * 50)
            for i in range(10)
        ]
        paths = render_repobook(
            out_dir=self.out_dir,
            repo_url="https://github.com/example/single.git",
            branch="main",
            commit="888888",
            files=files,
            entries=[],
            split_repobook=False,
            max_group_kb=1,
            max_group_files=1,
            adaptive_partition=True,
        )
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].name, "RepoBook.md")

    def test_i_stable_names_on_sibling_addition(self) -> None:
        """Test I: Adding a new alphabetically earlier sibling does not rename existing modules."""
        files_v1 = [
            make_record("src/router/trie.py", "class Trie: pass\n"),
            make_record("src/utils/string.py", "def upper(s): return s.upper()\n"),
        ]
        out1 = self.out_dir / "v1"
        render_repobook(
            out_dir=out1,
            repo_url="https://github.com/example/stable.git",
            branch="main",
            commit="999999",
            files=files_v1,
            entries=[],
            split_repobook=True,
            max_group_kb=512,
            max_group_files=1,
            adaptive_partition=True,
        )
        v1_names = {p.name for p in (out1 / "RepoBook").glob("*.md")}

        # Add alphabetically earlier sibling 'src/adapter/node.py'
        files_v2 = [
            make_record("src/adapter/node.py", "class Node: pass\n"),
            make_record("src/router/trie.py", "class Trie: pass\n"),
            make_record("src/utils/string.py", "def upper(s): return s.upper()\n"),
        ]
        out2 = self.out_dir / "v2"
        render_repobook(
            out_dir=out2,
            repo_url="https://github.com/example/stable.git",
            branch="main",
            commit="999999",
            files=files_v2,
            entries=[],
            split_repobook=True,
            max_group_kb=512,
            max_group_files=1,
            adaptive_partition=True,
        )
        v2_names = {p.name for p in (out2 / "RepoBook").glob("*.md")}

        # Existing module filenames must NOT change
        self.assertIn("01_src__router.md", v1_names)
        self.assertIn("01_src__utils.md", v1_names)
        self.assertIn("01_src__router.md", v2_names)
        self.assertIn("01_src__utils.md", v2_names)
        self.assertIn("01_src__adapter.md", v2_names)

    def test_j_slug_collision_fallback(self) -> None:
        """Test J: Distinct paths that produce the same base slug do not collide silently."""
        files = [
            make_record("src/foo-bar/a.py", "a = 1\n"),
            make_record("src/foo_bar/b.py", "b = 2\n"),
        ]
        paths = render_repobook(
            out_dir=self.out_dir,
            repo_url="https://github.com/example/collision.git",
            branch="main",
            commit="aaaaaa",
            files=files,
            entries=[],
            split_repobook=True,
            max_group_kb=512,
            max_group_files=1,
            adaptive_partition=True,
        )
        filenames = [p.name for p in paths if p.name != "00_overview.md"]
        # Exactly 2 chapters, distinct names, one clean and one with short hash suffix
        self.assertEqual(len(filenames), 2)
        self.assertEqual(len(set(filenames)), 2)
        self.assertTrue(any("__" in name for name in filenames))

    def test_direct_files_bucket(self) -> None:
        """Direct files in oversized directory go into <dir>__root."""
        files = [
            make_record("src/index.ts", "export * from './client'\n"),
            make_record("src/client/client.ts", "export class Client {}\n"),
        ]
        paths = render_repobook(
            out_dir=self.out_dir,
            repo_url="https://github.com/example/direct.git",
            branch="main",
            commit="bbbbbb",
            files=files,
            entries=[],
            split_repobook=True,
            max_group_kb=512,
            max_group_files=1,
            adaptive_partition=True,
        )
        filenames = [p.name for p in paths]
        self.assertIn("01_src__root.md", filenames)
        self.assertIn("01_src__client.md", filenames)

    def test_single_huge_file_preserved(self) -> None:
        """A single file exceeding max_group_kb is preserved intact as a single module."""
        huge_content = "def big():\n" + "    pass\n" * 30000  # ~300 KB
        files = [make_record("src/huge.py", huge_content)]
        paths = render_repobook(
            out_dir=self.out_dir,
            repo_url="https://github.com/example/huge.git",
            branch="main",
            commit="cccccc",
            files=files,
            entries=[],
            split_repobook=True,
            max_group_kb=10,  # 10 KB threshold, far exceeded by 300 KB file
            max_group_files=1,
            adaptive_partition=True,
        )
        # Should NOT split single file into parts
        filenames = [p.name for p in paths]
        self.assertIn("01_src.md", filenames)
        self.assertNotIn("01_src__part01.md", filenames)


    def test_leaf_partition_boundary_cascade_stability(self) -> None:
        """Leaf fallback stability: body edit in one file must not cascade partition boundaries of sibling files."""
        # 100 files in flat src/utils/, 10 KB each
        files_v1 = [
            make_record(f"src/utils/f_{i:02d}.py", "x" * 10000, commit="111111")
            for i in range(100)
        ]
        out1 = self.out_dir / "v1"
        render_repobook(
            out_dir=out1,
            repo_url="https://github.com/example/cascade.git",
            branch="main",
            commit="111111",
            files=files_v1,
            entries=[],
            split_repobook=True,
            max_group_kb=512,
            max_group_files=40,
            adaptive_partition=True,
        )

        # Mutate only f_00.py body (+60 KB)
        files_v2 = [
            make_record(
                f"src/utils/f_{i:02d}.py",
                "x" * 70000 if i == 0 else "x" * 10000,
                commit="222222" if i == 0 else "111111",
            )
            for i in range(100)
        ]
        out2 = self.out_dir / "v2"
        render_repobook(
            out_dir=out2,
            repo_url="https://github.com/example/cascade.git",
            branch="main",
            commit="222222",
            files=files_v2,
            entries=[],
            split_repobook=True,
            max_group_kb=512,
            max_group_files=40,
            adaptive_partition=True,
        )

        v1_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (out1 / "RepoBook").glob("*.md")}
        v2_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (out2 / "RepoBook").glob("*.md")}

        # Sibling partitions part02 and part03 MUST be byte-identical
        self.assertEqual(v1_hashes["01_src__utils__part02.md"], v2_hashes["01_src__utils__part02.md"])
        self.assertEqual(v1_hashes["01_src__utils__part03.md"], v2_hashes["01_src__utils__part03.md"])

    def test_sibling_part_stability_after_body_only_growth(self) -> None:
        """Unchanged sibling partitions maintain identical files even when a bucket is locally split."""
        # 60 files: files 00..39 in bucket 1, files 40..59 in bucket 2
        files = [
            make_record(f"src/handlers/h_{i:02d}.py", "y" * 5000, commit="aaaaaa")
            for i in range(60)
        ]
        out1 = self.out_dir / "b1"
        render_repobook(
            out_dir=out1,
            repo_url="https://github.com/example/sibling.git",
            branch="main",
            commit="aaaaaa",
            files=files,
            entries=[],
            split_repobook=True,
            max_group_kb=512,
            max_group_files=40,
            adaptive_partition=True,
        )
        b1_files = {p.name: p.read_text(encoding="utf-8") for p in (out1 / "RepoBook").glob("*.md")}
        self.assertIn("01_src__handlers__part01.md", b1_files)
        self.assertIn("01_src__handlers__part02.md", b1_files)

        # Mutate only h_00.py body
        files_mut = [
            make_record(
                f"src/handlers/h_{i:02d}.py",
                "y" * 20000 if i == 0 else "y" * 5000,
                commit="bbbbbb" if i == 0 else "aaaaaa",
            )
            for i in range(60)
        ]
        out2 = self.out_dir / "b2"
        render_repobook(
            out_dir=out2,
            repo_url="https://github.com/example/sibling.git",
            branch="main",
            commit="bbbbbb",
            files=files_mut,
            entries=[],
            split_repobook=True,
            max_group_kb=512,
            max_group_files=40,
            adaptive_partition=True,
        )
        b2_files = {p.name: p.read_text(encoding="utf-8") for p in (out2 / "RepoBook").glob("*.md")}
        # Part 2 is 100% byte identical
        self.assertEqual(
            hashlib.sha256(b1_files["01_src__handlers__part02.md"].encode("utf-8")).hexdigest(),
            hashlib.sha256(b2_files["01_src__handlers__part02.md"].encode("utf-8")).hexdigest(),
        )

    def test_deterministic_membership_across_independent_builds(self) -> None:
        """Independent builds with flat partitions produce byte-identical files."""
        files = [
            make_record(f"src/modules/m_{i:02d}.py", f"val = {i}\n", commit="111111")
            for i in range(50)
        ]
        out1 = self.out_dir / "det1"
        out2 = self.out_dir / "det2"
        paths1 = render_repobook(
            out_dir=out1,
            repo_url="https://github.com/example/det.git",
            branch="main",
            commit="111111",
            files=files,
            entries=[],
            split_repobook=True,
            max_group_kb=512,
            max_group_files=20,
            adaptive_partition=True,
        )
        paths2 = render_repobook(
            out_dir=out2,
            repo_url="https://github.com/example/det.git",
            branch="main",
            commit="111111",
            files=files,
            entries=[],
            split_repobook=True,
            max_group_kb=512,
            max_group_files=20,
            adaptive_partition=True,
        )
        h1 = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths1}
        h2 = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths2}
        self.assertEqual(h1, h2)

    def test_exactly_once_after_leaf_fallback(self) -> None:
        """Every text file is accounted for exactly once across flat leaf fallback partitions."""
        files = [
            make_record(f"src/data/d_{i:02d}.py", f"def d{i}(): pass\n", commit="333333")
            for i in range(35)
        ]
        out = self.out_dir / "exactly_once"
        paths = render_repobook(
            out_dir=out,
            repo_url="https://github.com/example/eo.git",
            branch="main",
            commit="333333",
            files=files,
            entries=[],
            split_repobook=True,
            max_group_kb=512,
            max_group_files=10,
            adaptive_partition=True,
        )
        # Verify exactly once coverage
        all_text = "".join(p.read_text(encoding="utf-8") for p in paths if p.name != "00_overview.md")
        for f in files:
            self.assertEqual(all_text.count(f"## {f.path}\n"), 1, f"Expected {f.path} exactly once!")


    def test_local_refinement_preserves_sibling_partition_names(self) -> None:
        """Local refinement of an oversized base bucket must not rename unrelated sibling base buckets."""
        # 100 files:
        # B1: files 00..39 (40 files, each 12,500 bytes = 500,000 bytes ~488 KB < 512 KB)
        # B2: files 40..79 (40 files, each 5,000 bytes = 200,000 bytes < 512 KB)
        # B3: files 80..99 (20 files, each 5,000 bytes = 100,000 bytes < 512 KB)
        files_v1 = [
            make_record(f"src/utils/f_{i:02d}.py", "x" * (12500 if i < 40 else 5000), "111111")
            for i in range(100)
        ]
        out1 = self.out_dir / "refine1"
        paths1 = render_repobook(
            out_dir=out1,
            repo_url="https://github.com/example/refine.git",
            branch="main",
            commit="111111",
            files=files_v1,
            entries=[],
            split_repobook=True,
            max_group_kb=512,
            max_group_files=40,
            adaptive_partition=True,
        )
        names1 = sorted([p.name for p in paths1 if p.name != "00_overview.md"])
        h1 = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths1 if p.name != "00_overview.md"}
        self.assertEqual(names1, ["01_src__utils__part01.md", "01_src__utils__part02.md", "01_src__utils__part03.md"])

        # Mutate only f_00.py: add 30,000 bytes -> B1 = 530,000 bytes > 512 * 1024 (524,288 bytes)
        # This triggers local refinement of B1 without touching B2 or B3
        files_v2 = [
            make_record(
                f"src/utils/f_{i:02d}.py",
                "x" * (42500 if i == 0 else (12500 if i < 40 else 5000)),
                "222222" if i == 0 else "111111",
            )
            for i in range(100)
        ]
        out2 = self.out_dir / "refine2"
        paths2 = render_repobook(
            out_dir=out2,
            repo_url="https://github.com/example/refine.git",
            branch="main",
            commit="222222",
            files=files_v2,
            entries=[],
            split_repobook=True,
            max_group_kb=512,
            max_group_files=40,
            adaptive_partition=True,
        )
        names2 = sorted([p.name for p in paths2 if p.name != "00_overview.md"])
        h2 = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths2 if p.name != "00_overview.md"}

        # B1 is locally refined into __sub01 and __sub02; B2 and B3 preserve exact names
        self.assertIn("01_src__utils__part01__sub01.md", names2)
        self.assertIn("01_src__utils__part01__sub02.md", names2)
        self.assertIn("01_src__utils__part02.md", names2)
        self.assertIn("01_src__utils__part03.md", names2)

        # Sibling partitions part02 and part03 are 100% byte identical
        self.assertEqual(h1["01_src__utils__part02.md"], h2["01_src__utils__part02.md"])
        self.assertEqual(h1["01_src__utils__part03.md"], h2["01_src__utils__part03.md"])

    def test_local_refinement_remote_churn_receipt(self) -> None:
        """Remote-churn semantic test: renamed unchanged source count must be exactly zero."""
        files_v1 = [
            make_record(f"src/utils/f_{i:02d}.py", "x" * (12500 if i < 40 else 5000), "111111")
            for i in range(100)
        ]
        out1 = self.out_dir / "churn1"
        paths1 = render_repobook(
            out_dir=out1, repo_url="https://github.com/example/churn.git",
            branch="main", commit="111111", files=files_v1, entries=[],
            split_repobook=True, max_group_kb=512, max_group_files=40, adaptive_partition=True,
        )

        files_v2 = [
            make_record(
                f"src/utils/f_{i:02d}.py",
                "x" * (42500 if i == 0 else (12500 if i < 40 else 5000)),
                "222222" if i == 0 else "111111",
            )
            for i in range(100)
        ]
        out2 = self.out_dir / "churn2"
        paths2 = render_repobook(
            out_dir=out2, repo_url="https://github.com/example/churn.git",
            branch="main", commit="222222", files=files_v2, entries=[],
            split_repobook=True, max_group_kb=512, max_group_files=40, adaptive_partition=True,
        )

        def map_files_to_source(out):
            m = {}
            for p in (out / "RepoBook").glob("*.md"):
                if p.name == "00_overview.md": continue
                text = p.read_text(encoding="utf-8")
                for line in text.splitlines():
                    if line.startswith("## "):
                        m[line[3:].strip()] = p.name
            return m

        m1 = map_files_to_source(out1)
        m2 = map_files_to_source(out2)

        # Unmodified sibling files (files 40..99)
        unmodified_files = [f"src/utils/f_{i:02d}.py" for i in range(40, 100)]
        renamed_unchanged_sources = [f for f in unmodified_files if m1[f] != m2.get(f)]
        self.assertEqual(len(renamed_unchanged_sources), 0)


if __name__ == "__main__":
    unittest.main()
