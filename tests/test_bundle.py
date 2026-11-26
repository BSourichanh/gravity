"""Isolated unit and CLI tests for plugin/core/bundle.py and init_env.py --export/--import/--set-drive-dir."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO_ROOT / "plugin"
INIT_SCRIPT = PLUGIN_ROOT / "scripts" / "init_env.py"
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from core import bundle  # noqa: E402


def _isolated_env(fake_home: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["HOME"] = str(fake_home)
    env["USERPROFILE"] = str(fake_home)
    for key in (
        "GRAVITY_HOME",
        "GRAVITY_CORE_HOME",
        "GRAVITY_METRICS_HOME",
        "GRAVITY_ARCHITECT_HOME",
        "GRAVITY_WORKFLOW_HOME",
    ):
        env.pop(key, None)
    return env


def _run_init_env(args: list[str], *, fake_home: Path, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(INIT_SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_isolated_env(fake_home),
        cwd=str(cwd) if cwd else None,
        timeout=20,
        check=False,
    )


class TestBundleExportImport(unittest.TestCase):
    def test_set_drive_dir_atomic_and_rejects_symlink_and_bad_combo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "user-home"
            fake_home.mkdir()
            gravity_home = tmp_path / "gravity-home"
            drive_dir = tmp_path / "GoogleDrive" / "Gravity"
            drive_dir.mkdir(parents=True)

            proc = _run_init_env(
                ["--gravity-home", str(gravity_home), "--set-drive-dir", str(drive_dir), "--json"],
                fake_home=fake_home,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["mode"], "set-drive-dir")
            sync_file = gravity_home / "core" / "sync.json"
            self.assertTrue(sync_file.is_file())
            raw = sync_file.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\r\n", raw)
            sync_data = json.loads(raw.decode("utf-8"))
            self.assertEqual(sync_data["schema_version"], 1)
            self.assertEqual(Path(sync_data["drive_dir"]), drive_dir.resolve())

            # Human output for --set-drive-dir
            human_proc = _run_init_env(
                ["--gravity-home", str(gravity_home), "--set-drive-dir", str(drive_dir)],
                fake_home=fake_home,
            )
            self.assertEqual(human_proc.returncode, 0, msg=human_proc.stderr or human_proc.stdout)
            self.assertIn("Drive Sync Config", human_proc.stdout)

            # Incompatible mode combination rejected
            bad_combo = _run_init_env(
                ["--gravity-home", str(gravity_home), "--set-drive-dir", str(drive_dir), "--status"],
                fake_home=fake_home,
            )
            self.assertEqual(bad_combo.returncode, 2)

            # Symlink drive_dir rejected (skip cleanly only if OS denies symlink creation)
            sym_drive = tmp_path / "sym-drive"
            try:
                sym_drive.symlink_to(drive_dir, target_is_directory=True)
            except (OSError, NotImplementedError):
                return
            sym_proc = _run_init_env(
                ["--gravity-home", str(gravity_home), "--set-drive-dir", str(sym_drive), "--json"],
                fake_home=fake_home,
            )
            self.assertEqual(sym_proc.returncode, 1)
            self.assertFalse(json.loads(sym_proc.stdout)["ok"])

    def test_export_active_wal_db_exclusions_and_include_atelier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "user-home"
            fake_home.mkdir()
            gravity_home = fake_home / ".gemini" / "gravity"
            plugins_dir = tmp_path / "plugins"
            (plugins_dir / "gdrive").mkdir(parents=True)
            (plugins_dir / "gdrive" / "plugin.json").write_text('{"name":"gdrive"}\n', encoding="utf-8")

            # Seed valid gravity_home files
            (gravity_home / "metrics" / "data").mkdir(parents=True)
            (gravity_home / "metrics" / "reports").mkdir(parents=True)
            (gravity_home / "metrics" / "data" / "history.jsonl").write_text('{"ok":1}\n', encoding="utf-8")
            (gravity_home / "metrics" / "reports" / "r1.json").write_text("{}\n", encoding="utf-8")
            (gravity_home / "metrics" / "METRICS.md").write_text("# Metrics\n", encoding="utf-8")
            (gravity_home / "metrics" / "ignored.json").write_text("[]\n", encoding="utf-8")
            (gravity_home / "workflow" / "workspaces" / "app-1").mkdir(parents=True)
            (gravity_home / "workflow" / "workspaces" / "app-1" / "profile.json").write_text('{"profile":"standard"}\n', encoding="utf-8")
            (gravity_home / "architect").mkdir(parents=True)
            (gravity_home / "architect" / "ateliers.json").write_text('{"ateliers":[]}\n', encoding="utf-8")

            # Seed strictly excluded files
            (gravity_home / "core").mkdir(parents=True)
            (gravity_home / "core" / "modules.json").write_text('{"modules":[]}\n', encoding="utf-8")
            (gravity_home / "core" / "sources.json").write_text('{"schema_version":1,"sources":{}}\n', encoding="utf-8")
            (gravity_home / "core" / "sync.lock").write_text("lock", encoding="utf-8")
            (gravity_home / "workflow" / "live_workspaces.json").write_text("{}\n", encoding="utf-8")
            (gravity_home / "metrics" / "session_meta.json").write_text("{}\n", encoding="utf-8")
            # Residual legacy WAL db / lock files must be tolerated and excluded cleanly
            (gravity_home / "metrics" / "legacy.db-wal").write_bytes(b"wal")
            (gravity_home / "metrics" / "legacy.db-shm").write_bytes(b"shm")
            (gravity_home / "bridge" / "logs").mkdir(parents=True)
            (gravity_home / "bridge" / "logs" / "relay.log").write_text("log\n", encoding="utf-8")

            db_path = gravity_home / "bridge" / "bridge.db"
            conn = sqlite3.connect(str(db_path))
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA wal_autocheckpoint=0")
                conn.execute("CREATE TABLE threads (id INTEGER PRIMARY KEY, subject TEXT)")
                conn.commit()
                conn.execute("INSERT INTO threads (subject) VALUES ('live-wal-row')")
                conn.commit()
                self.assertTrue((gravity_home / "bridge" / "bridge.db-wal").is_file())

                # Seed atelier
                atelier = fake_home / "ateliers" / "studio"
                for sub in ("specs", "tasks", "audits/code", "audits/agents", "tracking/projects", ".git", "__pycache__"):
                    (atelier / sub).mkdir(parents=True)
                (atelier / "ECOSYSTEM.md").write_text("# Eco\n", encoding="utf-8")
                (atelier / "projects.json").write_text('{"projects":[]}\n', encoding="utf-8")
                (atelier / "specs" / "s1.md").write_text("# Spec\n", encoding="utf-8")
                (atelier / "tasks" / "t1.md").write_text("# Task\n", encoding="utf-8")
                (atelier / "audits" / "code" / "c1.md").write_text("# Code Audit\n", encoding="utf-8")
                (atelier / "audits" / "agents" / "a1.md").write_text("# Agent Audit\n", encoding="utf-8")
                (atelier / "tracking" / "projects" / "p1.md").write_text("# Track\n", encoding="utf-8")
                (atelier / ".git" / "HEAD").write_text("ref: refs/heads/dev\n", encoding="utf-8")
                (atelier / "__pycache__" / "mod.pyc").write_bytes(b"pyc")
                (atelier / "tasks" / "tmp.lock").write_text("lock", encoding="utf-8")

                out_zip = tmp_path / "exports" / "my-backup.zip"
                proc = _run_init_env(
                    [
                        "--gravity-home", str(gravity_home),
                        "--plugins-dir", str(plugins_dir),
                        "--export",
                        "--out", str(out_zip),
                        "--include-atelier", str(atelier),
                        "--json",
                    ],
                    fake_home=fake_home,
                )
            finally:
                conn.close()

            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            res = json.loads(proc.stdout)
            self.assertTrue(res["ok"])
            self.assertTrue(res["gdrive_plugin_detected"])
            self.assertTrue(out_zip.is_file())

            with zipfile.ZipFile(out_zip, "r") as zf:
                names = set(zf.namelist())
                self.assertIn("manifest.json", names)
                self.assertIn("metrics/data/history.jsonl", names)
                self.assertIn("workflow/workspaces/app-1/profile.json", names)
                self.assertIn("ateliers/studio/ECOSYSTEM.md", names)
                self.assertIn("ateliers/studio/tasks/t1.md", names)
                self.assertIn("ateliers/studio/audits/code/c1.md", names)

                for forbidden in (
                    "core/modules.json",
                    "core/sources.json",
                    "core/sync.lock",
                    "workflow/live_workspaces.json",
                    "metrics/session_meta.json",
                    "metrics/legacy.db-wal",
                    "metrics/legacy.db-shm",
                    "bridge/bridge.db",
                    "bridge/logs/relay.log",
                    "bridge/bridge.db-wal",
                    "bridge/bridge.db-shm",
                    "ateliers/studio/audits/agents/a1.md",
                    "ateliers/studio/.git/HEAD",
                    "ateliers/studio/__pycache__/mod.pyc",
                    "ateliers/studio/tasks/tmp.lock",
                ):
                    self.assertNotIn(forbidden, names)

            restored_home = tmp_path / "restored-home"
            imp_proc = _run_init_env(
                ["--gravity-home", str(restored_home), "--import", str(out_zip), "--json"],
                fake_home=fake_home,
            )
            self.assertEqual(imp_proc.returncode, 0, msg=imp_proc.stderr or imp_proc.stdout)
            self.assertTrue((restored_home / "metrics" / "data" / "history.jsonl").is_file())
            self.assertFalse((restored_home / "bridge").exists())

            # Human-readable --export using configured drive_dir from sync.json
            drive_dir = tmp_path / "drive-sync"
            drive_dir.mkdir()
            bundle.set_drive_dir(drive_dir, gravity_home=gravity_home)
            exp_human = _run_init_env(["--gravity-home", str(gravity_home), "--export"], fake_home=fake_home)
            self.assertEqual(exp_human.returncode, 0, msg=exp_human.stderr or exp_human.stdout)
            self.assertIn("Bundle Export", exp_human.stdout)
            self.assertTrue(list(drive_dir.glob("gravity-backup-*.zip")))

    def test_import_dry_run_integrity_remapping_and_human_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src_user = tmp_path / "src-user"
            dst_user = tmp_path / "dst-user"
            src_user.mkdir()
            dst_user.mkdir()
            src_gravity = src_user / ".gemini" / "gravity"
            dst_gravity = dst_user / ".gemini" / "gravity"

            atelier = src_user / "work" / "my-atelier"
            atelier.mkdir(parents=True)
            (atelier / "ECOSYSTEM.md").write_text("# Eco\n", encoding="utf-8")
            (atelier / "projects.json").write_text(
                json.dumps(
                    {
                        "projects": [
                            {"id": "app1", "path": f"{src_user.as_posix()}/repos/app1"},
                            {"id": "ext", "path": "/opt/external/repo"},
                        ]
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (src_gravity / "architect").mkdir(parents=True)
            (src_gravity / "architect" / "ateliers.json").write_text(
                json.dumps(
                    {
                        "ateliers": [
                            {"workspace_name": "my-atelier", "workspace_path": str(atelier)},
                            {"workspace_name": "core-sub", "workspace_path": str(src_gravity) + "\\sub"},
                        ]
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (src_gravity / "metrics").mkdir(parents=True)
            (src_gravity / "metrics" / "METRICS.md").write_bytes(b"# M\n")

            (dst_user / "repos" / "app1").mkdir(parents=True)

            bundle_zip = tmp_path / "portable.zip"
            with mock.patch.object(Path, "home", return_value=src_user):
                exp = bundle.export_bundle(src_gravity, out=bundle_zip, include_ateliers=[atelier])
            self.assertTrue(exp["ok"])

            # Dry-run must not write anything
            dry_proc = _run_init_env(
                ["--gravity-home", str(dst_gravity), "--import", str(bundle_zip), "--dry-run", "--json"],
                fake_home=dst_user,
            )
            self.assertEqual(dry_proc.returncode, 0, msg=dry_proc.stderr or dry_proc.stdout)
            dry_res = json.loads(dry_proc.stdout)
            self.assertTrue(dry_res["dry_run"])
            self.assertEqual(dry_res["written_files"], [])
            self.assertFalse(dst_gravity.exists())

            # Real import (human text output)
            imp_proc = _run_init_env(
                ["--gravity-home", str(dst_gravity), "--import", str(bundle_zip)],
                fake_home=dst_user,
            )
            self.assertEqual(imp_proc.returncode, 0, msg=imp_proc.stderr or imp_proc.stdout)
            self.assertIn("Bundle Import (applied)", imp_proc.stdout)

            restored_ateliers = json.loads((dst_gravity / "architect" / "ateliers.json").read_text(encoding="utf-8"))
            self.assertEqual(Path(restored_ateliers["ateliers"][0]["workspace_path"]), (dst_user / "work" / "my-atelier"))
            self.assertEqual(Path(restored_ateliers["ateliers"][1]["workspace_path"]), (dst_gravity / "sub"))

            restored_projects = json.loads((dst_gravity / "ateliers" / "my-atelier" / "projects.json").read_text(encoding="utf-8"))
            self.assertEqual(Path(restored_projects["projects"][0]["path"]), dst_user / "repos" / "app1")
            self.assertEqual(restored_projects["projects"][1]["path"], "/opt/external/repo")

            # Tampered SHA-256 (same byte length) must fail on --dry-run and leave applied files untouched
            tampered_zip = tmp_path / "tampered.zip"
            with zipfile.ZipFile(bundle_zip, "r") as zin, zipfile.ZipFile(tampered_zip, "w") as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    if item.filename == "metrics/METRICS.md":
                        data = b"# X\n"
                    zout.writestr(item, data)
            bad_proc = _run_init_env(
                ["--gravity-home", str(dst_gravity), "--import", str(tampered_zip), "--dry-run", "--json"],
                fake_home=dst_user,
            )
            self.assertEqual(bad_proc.returncode, 1)
            self.assertIn("SHA-256 mismatch", json.loads(bad_proc.stdout)["error"])

            # Non-dry-run import of multi-entry ZIP where 2nd entry fails SHA-256 must perform 0 disk writes (EC-4)
            atomic_target = tmp_path / "ec4-atomic-target"
            with self.assertRaises(ValueError):
                bundle.import_bundle(tampered_zip, gravity_home=atomic_target)
            self.assertFalse(atomic_target.exists())

    def test_import_rejects_traversal_absolute_symlink_nul_and_bad_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            target_home = tmp_path / "target-home"

            bad_file = tmp_path / "not-a-zip.zip"
            bad_file.write_bytes(b"not a zip archive")
            with self.assertRaises(ValueError):
                bundle.import_bundle(bad_file, gravity_home=target_home)

            manifest = {"schema_version": 1, "entries": []}
            manifest_bytes = json.dumps(manifest).encode("utf-8")

            for idx, evil_name in enumerate(("../escape.txt", "/abs/escape.txt", "C:/evil.txt")):
                zpath = tmp_path / f"evil_{idx}.zip"
                with zipfile.ZipFile(zpath, "w") as zf:
                    zf.writestr("manifest.json", manifest_bytes)
                    zi = zipfile.ZipInfo()
                    zi.filename = evil_name
                    zf.writestr(zi, b"x")
                with self.assertRaises(ValueError, msg=f"Expected rejection for {evil_name!r}"):
                    bundle.import_bundle(zpath, gravity_home=target_home)
                self.assertFalse(target_home.exists())

            for idx, evil_rel in enumerate(("a\\b.txt", "a\x00b.txt")):
                bad_zip = tmp_path / f"evil_rel_{idx}.zip"
                bad_manifest = {
                    "schema_version": 1,
                    "entries": [{"arcname": "a/b.txt", "target_rel": evil_rel, "size": 1, "sha256": "0" * 64}],
                }
                with zipfile.ZipFile(bad_zip, "w") as zf:
                    zf.writestr("manifest.json", json.dumps(bad_manifest).encode("utf-8"))
                    zf.writestr("a/b.txt", b"x")
                with self.assertRaises(ValueError, msg=f"Expected rejection for target_rel {evil_rel!r}"):
                    bundle.import_bundle(bad_zip, gravity_home=target_home)
                self.assertFalse(target_home.exists())

            sym_zip = tmp_path / "symlink.zip"
            with zipfile.ZipFile(sym_zip, "w") as zf:
                zf.writestr("manifest.json", manifest_bytes)
                zi = zipfile.ZipInfo("metrics/link")
                zi.create_system = 3
                zi.external_attr = (stat.S_IFLNK | 0o777) << 16
                zf.writestr(zi, b"/etc/passwd")
            with self.assertRaises(ValueError):
                bundle.import_bundle(sym_zip, gravity_home=target_home)
            self.assertFalse(target_home.exists())


if __name__ == "__main__":
    unittest.main()
