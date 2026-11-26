"""Isolated unit tests for scripts/sync_shared.py (100% stdlib)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import sync_shared  # noqa: E402


def _make_fake_repos(root: Path, *, with_ssot: bool = True) -> Path:
    for repo in sync_shared.DEFAULT_REPOS:
        (root / repo / "plugin").mkdir(parents=True, exist_ok=True)
    ssot = root / "gravity" / "shared" / "gravity_shared"
    if with_ssot:
        ssot.mkdir(parents=True, exist_ok=True)
        (ssot / "__init__.py").write_bytes(b'"""init"""\r\n')
        (ssot / "atomic_io.py").write_bytes(b"\xef\xbb\xbf# atomic\r\nVALUE = 1\n")
        (ssot / "README.txt").write_text("ignored\n", encoding="utf-8")
        (ssot / "__pycache__").mkdir(exist_ok=True)
        (ssot / "__pycache__" / "junk.pyc").write_bytes(b"pyc")
    return ssot


class TestSyncShared(unittest.TestCase):
    def test_apply_idempotent_and_check_passes_for_all_4_repos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repos_root = Path(tmp)
            ssot = _make_fake_repos(repos_root)

            rep1 = sync_shared.sync_shared_plugins(ssot, repos_root, apply=True)
            self.assertTrue(rep1["ok"])
            self.assertEqual(rep1["mode"], "apply")
            self.assertEqual(sorted(rep1["files"].keys()), ["__init__.py", "atomic_io.py"])

            first_snapshots: dict[str, bytes] = {}
            for repo in sync_shared.DEFAULT_REPOS:
                manifest_p = repos_root / repo / "plugin" / ".shared_manifest.json"
                shared_dir = repos_root / repo / "plugin" / "_shared"
                self.assertTrue(manifest_p.is_file())
                self.assertFalse((shared_dir / "README.txt").exists())
                self.assertFalse((shared_dir / "__pycache__").exists())
                raw_manifest = manifest_p.read_bytes()
                self.assertFalse(raw_manifest.startswith(b"\xef\xbb\xbf"))
                self.assertNotIn(b"\r\n", raw_manifest)
                manifest = json.loads(raw_manifest.decode("utf-8"))
                self.assertEqual(manifest["schema_version"], 1)
                self.assertEqual(manifest["source_repo"], "gravity")
                self.assertEqual(manifest["source_path"], "shared/gravity_shared")
                self.assertEqual(list(manifest["files"].keys()), ["__init__.py", "atomic_io.py"])
                for fname, sha in manifest["files"].items():
                    fbytes = (shared_dir / fname).read_bytes()
                    self.assertNotIn(b"\r\n", fbytes)
                    self.assertFalse(fbytes.startswith(b"\xef\xbb\xbf"))
                    self.assertEqual(hashlib.sha256(fbytes).hexdigest(), sha)
                first_snapshots[repo] = raw_manifest

            # Second --apply must be bit-for-bit idempotent (preserving generated_at & zero rewrites)
            rep2 = sync_shared.sync_shared_plugins(ssot, repos_root, apply=True)
            self.assertTrue(rep2["ok"])
            for item in rep2["results"]:
                self.assertEqual(item["written"], [])
                self.assertEqual(item["removed"], [])
            for repo in sync_shared.DEFAULT_REPOS:
                manifest_p = repos_root / repo / "plugin" / ".shared_manifest.json"
                self.assertEqual(manifest_p.read_bytes(), first_snapshots[repo])

            # --check must pass
            chk = sync_shared.sync_shared_plugins(ssot, repos_root, check=True)
            self.assertTrue(chk["ok"])
            self.assertEqual(chk["mode"], "check")

    def test_check_detects_missing_hash_mismatch_extra_and_stale_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repos_root = Path(tmp)
            ssot = _make_fake_repos(repos_root)
            self.assertTrue(sync_shared.sync_shared_plugins(ssot, repos_root, apply=True)["ok"])

            # 1. Missing file -> MISSING
            (repos_root / "gravity" / "plugin" / "_shared" / "atomic_io.py").unlink()
            # 2. Modified file -> HASH_MISMATCH
            (repos_root / "gravity-workflow" / "plugin" / "_shared" / "__init__.py").write_text("# drift\n", encoding="utf-8")
            # 3. Extra stale file -> EXTRA_FILE
            (repos_root / "gravity-metrics" / "plugin" / "_shared" / "stale_mod.py").write_text("# extra\n", encoding="utf-8")
            # 4. Stale manifest -> MANIFEST_STALE
            m_arch = repos_root / "gravity-architect" / "plugin" / ".shared_manifest.json"
            m_data = json.loads(m_arch.read_text(encoding="utf-8"))
            m_data["files"]["atomic_io.py"] = "0" * 64
            m_arch.write_text(json.dumps(m_data), encoding="utf-8")

            chk = sync_shared.sync_shared_plugins(ssot, repos_root, check=True)
            self.assertFalse(chk["ok"])
            codes_by_repo = {
                item["repo"]: {iss["code"] for iss in item["issues"]}
                for item in chk["results"]
            }
            self.assertIn("MISSING", codes_by_repo["gravity"])
            self.assertIn("HASH_MISMATCH", codes_by_repo["gravity-workflow"])
            self.assertIn("EXTRA_FILE", codes_by_repo["gravity-metrics"])
            self.assertIn("MANIFEST_STALE", codes_by_repo["gravity-architect"])

            # Re-applying cleans up stale_mod.py and restores parity
            rep_fix = sync_shared.sync_shared_plugins(ssot, repos_root, apply=True)
            self.assertTrue(rep_fix["ok"])
            metrics_res = [r for r in rep_fix["results"] if r["repo"] == "gravity-metrics"][0]
            self.assertEqual(metrics_res["removed"], ["stale_mod.py"])
            self.assertTrue(sync_shared.sync_shared_plugins(ssot, repos_root, check=True)["ok"])

    def test_symlink_and_mocked_junction_rejected_in_check_and_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repos_root = Path(tmp)
            ssot = _make_fake_repos(repos_root)
            elsewhere = repos_root / "elsewhere"
            elsewhere.mkdir()
            os.symlink(elsewhere, repos_root / "gravity" / "plugin" / "_shared")

            chk = sync_shared.sync_shared_plugins(ssot, repos_root, repos=("gravity",), check=True)
            self.assertFalse(chk["ok"])
            self.assertEqual(chk["results"][0]["issues"][0]["code"], "SYMLINK_OR_JUNCTION")

            app = sync_shared.sync_shared_plugins(ssot, repos_root, repos=("gravity",), apply=True)
            self.assertFalse(app["ok"])
            self.assertEqual(app["results"][0]["issues"][0]["code"], "SYMLINK_OR_JUNCTION")

            manifest_wf = repos_root / "gravity-workflow" / "plugin" / ".shared_manifest.json"
            with mock.patch("sync_shared.is_symlink_or_junction", side_effect=lambda p: os.fspath(p) == os.fspath(manifest_wf)):
                j_chk = sync_shared.sync_shared_plugins(ssot, repos_root, repos=("gravity-workflow",), check=True)
                self.assertFalse(j_chk["ok"])
                self.assertEqual(j_chk["results"][0]["issues"][0]["code"], "SYMLINK_OR_JUNCTION")

    def test_cli_repos_filtering_and_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repos_root = Path(tmp)
            ssot = _make_fake_repos(repos_root)
            with mock.patch.object(sync_shared, "DEFAULT_SOURCE_DIR", ssot):
                with mock.patch("sys.stdout", new_callable=lambda: __import__("io").StringIO()) as out:
                    rc = sync_shared.main(["--apply", "--repos-root", str(repos_root), "--repos", "gravity", "--json"])
                self.assertEqual(rc, 0)
                payload = json.loads(out.getvalue())
                self.assertTrue(payload["ok"])
                self.assertEqual([r["repo"] for r in payload["results"]], ["gravity"])
                self.assertFalse((repos_root / "gravity-workflow" / "plugin" / "_shared").exists())
                self.assertFalse((repos_root / "gravity-metrics" / "plugin" / ".shared_manifest.json").exists())

                # Check subset exits 1 on drift in gravity-metrics while gravity passes
                with mock.patch("sys.stdout", new_callable=lambda: __import__("io").StringIO()) as out2:
                    rc2 = sync_shared.main(["--check", "--repos-root", str(repos_root), "--repos", "gravity,gravity-metrics", "--json"])
                self.assertEqual(rc2, 1)
                payload2 = json.loads(out2.getvalue())
                self.assertFalse(payload2["ok"])
                self.assertEqual([r["repo"] for r in payload2["results"]], ["gravity", "gravity-metrics"])
                self.assertTrue(payload2["results"][0]["ok"])
                self.assertFalse(payload2["results"][1]["ok"])


if __name__ == "__main__":
    unittest.main()
