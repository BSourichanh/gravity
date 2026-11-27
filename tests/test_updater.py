"""Isolated tests for plugin/core/updater.py (/gravity update engine, _shared sync check, & CLI wiring)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO_ROOT / "plugin"
INIT_SCRIPT = PLUGIN_ROOT / "scripts" / "init_env.py"
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from core import updater  # noqa: E402


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["LC_ALL"] = "C"
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=20,
        check=True,
    )


def _create_module_repo(
    repo_dir: Path,
    *,
    mod_id: str,
    plugin_name: str,
    version: str = "0.1.0",
    repository: str | None = None,
    with_init_env: bool = False,
) -> None:
    plugin_dir = repo_dir / "plugin"
    (plugin_dir / "config").mkdir(parents=True, exist_ok=True)
    repo_url = repository or f"https://github.com/BSourichanh/{plugin_name}.git"
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": plugin_name,
                "displayName": plugin_name.title(),
                "version": version,
                "description": "Test module",
                "logo": "assets/logo.svg",
                "suggestedPrompts": ["A", "B", "C"],
                "author": {"name": "Gravity Contributors"},
                "homepage": f"https://github.com/BSourichanh/{plugin_name}",
                "repository": repo_url,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (plugin_dir / "config" / "module.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": mod_id,
                "plugin_name": plugin_name,
                "role": f"Role {mod_id}",
                "storage": {"subdir": mod_id, "env_override": f"GRAVITY_{mod_id.upper()}_HOME"},
                "commands": [f"/{plugin_name}"],
                "capabilities": ["cap"],
                "ui": {"mode": "none", "target": "gravity"},
                "signals": {"produces": [], "consumes": []},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if with_init_env:
        (plugin_dir / "scripts").mkdir(parents=True, exist_ok=True)
        (plugin_dir / "scripts" / "init_env.py").write_text(
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "args = sys.argv[1:]\n"
            "gh = Path(args[args.index('--gravity-home') + 1])\n"
            "reg = gh / 'core' / 'modules.json'\n"
            "reg.parent.mkdir(parents=True, exist_ok=True)\n"
            "reg.write_text(json.dumps({'schema_version': 1, 'refreshed': True, 'modules': []}) + '\\n', encoding='utf-8')\n"
            "print(json.dumps({'ok': True, 'registry_path': str(reg), 'module_count': 2, 'valid_count': 2}))\n",
            encoding="utf-8",
            newline="\n",
        )

    installer_code = (
        "import json, os, shutil, sys\n"
        "from pathlib import Path\n"
        "repo_dir = Path(__file__).resolve().parent\n"
        "src_plugin = repo_dir / 'plugin'\n"
        "manifest = json.loads((src_plugin / 'plugin.json').read_text(encoding='utf-8'))\n"
        "pname = manifest['name']\n"
        "if '--target' in sys.argv:\n"
        "    target = Path(sys.argv[sys.argv.index('--target') + 1])\n"
        "else:\n"
        "    target = Path.home() / '.gemini' / 'config' / 'plugins' / pname\n"
        "if target.exists():\n"
        "    shutil.rmtree(target)\n"
        "shutil.copytree(src_plugin, target)\n"
        "log_env = os.environ.get('GRAVITY_TEST_INSTALL_ORDER_LOG')\n"
        "if log_env:\n"
        "    with Path(log_env).open('a', encoding='utf-8') as fh:\n"
        "        fh.write(json.dumps({'plugin': pname, 'cwd': str(Path.cwd()), 'args': sys.argv[1:]}) + '\\n')\n"
    )
    (repo_dir / "install.py").write_text(installer_code, encoding="utf-8", newline="\n")


def _init_git_with_remote(repo_dir: Path, bare_dir: Path, tmp_work: Path) -> str:
    subprocess.run(["git", "init", "--bare", str(bare_dir)], check=True, capture_output=True, text=True)
    _git(repo_dir, "init", "-b", "dev")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "Tester")
    _git(repo_dir, "add", ".")
    _git(repo_dir, "commit", "-m", "initial")
    _git(repo_dir, "remote", "add", "origin", str(bare_dir))
    _git(repo_dir, "push", "-u", "origin", "dev")
    sha = _git(repo_dir, "rev-parse", "HEAD").stdout.strip()
    if tmp_work.exists():
        shutil.rmtree(tmp_work)
    subprocess.run(["git", "clone", "-b", "dev", str(bare_dir), str(tmp_work)], check=True, capture_output=True, text=True)
    _git(tmp_work, "config", "user.email", "test@example.com")
    _git(tmp_work, "config", "user.name", "Tester")
    return sha


def _install_plugin_copy(repo_dir: Path, plugins_dir: Path) -> Path:
    manifest = json.loads((repo_dir / "plugin" / "plugin.json").read_text(encoding="utf-8"))
    dst = plugins_dir / manifest["name"]
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(repo_dir / "plugin", dst)
    return dst


def _seed_shared_snapshot(repo_dir: Path, *, with_ssot_sync: bool = False) -> None:
    plugin_dir = repo_dir / "plugin"
    shutil.copytree(REPO_ROOT / "plugin" / "_shared", plugin_dir / "_shared", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(REPO_ROOT / "plugin" / ".shared_manifest.json", plugin_dir / ".shared_manifest.json")
    if with_ssot_sync:
        shutil.copytree(REPO_ROOT / "shared", repo_dir / "shared", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (repo_dir / "scripts").mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / "scripts" / "sync_shared.py", repo_dir / "scripts" / "sync_shared.py")


class TestUpdater(unittest.TestCase):
    def test_link_repos_root_url_validation_and_modules_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            gravity_home = tmp_path / "gravity-home"
            plugins_dir = tmp_path / "plugins"
            repos_root = tmp_path / "repos"

            core_repo = repos_root / "gravity"
            comp_repo = repos_root / "gravity-alpha"
            _create_module_repo(core_repo, mod_id="core", plugin_name="gravity", version="0.3.0", with_init_env=True)
            _create_module_repo(comp_repo, mod_id="alpha", plugin_name="gravity-alpha", version="0.1.0")
            _install_plugin_copy(core_repo, plugins_dir)
            _install_plugin_copy(comp_repo, plugins_dir)

            wrong_repo = tmp_path / "wrong-alpha"
            _create_module_repo(
                wrong_repo,
                mod_id="alpha",
                plugin_name="gravity-alpha",
                repository="https://github.com/OtherOrg/wrong-repo.git",
            )
            with self.assertRaises(ValueError):
                updater.run_update(
                    gravity_home=gravity_home,
                    plugins_dirs=[plugins_dir],
                    link_paths=[wrong_repo],
                    check_only=True,
                )

            p_chk, rc_chk = updater.run_update(
                gravity_home=gravity_home,
                plugins_dirs=[plugins_dir],
                repos_root=repos_root,
                check_only=True,
            )
            self.assertEqual(rc_chk, 0)
            self.assertFalse((gravity_home / "core" / "sources.json").exists())
            self.assertEqual([r["status"] for r in p_chk["results"]], ["not_git_repo", "not_git_repo"])
            self.assertEqual([r["id"] for r in p_chk["results"]], ["alpha", "core"])

            p_lnk, rc_lnk = updater.run_update(
                gravity_home=gravity_home,
                plugins_dirs=[plugins_dir],
                link_paths=[core_repo],
                modules_csv="core",
            )
            self.assertEqual(rc_lnk, 0)
            self.assertTrue((gravity_home / "core" / "sources.json").is_file())
            self.assertTrue((gravity_home / "core" / "sources.lock").exists())
            sources_data = json.loads((gravity_home / "core" / "sources.json").read_text(encoding="utf-8"))
            self.assertEqual(Path(sources_data["sources"]["gravity"]["repo_dir"]), core_repo.resolve())
            self.assertEqual([r["id"] for r in p_lnk["results"]], ["core"])

            with self.assertRaises(ValueError):
                updater.run_update(
                    gravity_home=gravity_home,
                    plugins_dirs=[plugins_dir],
                    modules_csv="unknown-mod",
                    check_only=True,
                )

    def test_all_git_states_inspection_and_offline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            gravity_home = tmp_path / "gravity-home"
            plugins_dir = tmp_path / "plugins"
            repos_root = tmp_path / "repos"
            remotes = tmp_path / "remotes"
            pushers = tmp_path / "pushers"

            specs = [
                ("m_uptodate", "mod-uptodate"),
                ("m_behind", "mod-behind"),
                ("m_drift", "mod-drift"),
                ("m_dirty", "mod-dirty"),
                ("m_detached", "mod-detached"),
                ("m_noup", "mod-noup"),
                ("m_diverged", "mod-diverged"),
                ("m_ahead", "mod-ahead"),
                ("m_unlinked", "mod-unlinked"),
                ("m_missing", "mod-missing"),
                ("m_errfetch", "mod-errfetch"),
            ]
            sources: dict[str, dict] = {}
            shas: dict[str, str] = {}

            for mid, pname in specs:
                repo = repos_root / pname
                _create_module_repo(repo, mod_id=mid, plugin_name=pname, version="0.1.0")
                _install_plugin_copy(repo, plugins_dir)
                if mid == "m_unlinked":
                    continue
                if mid == "m_missing":
                    shutil.rmtree(repo)
                    sources[pname] = {"plugin_name": pname, "repo_dir": str(repo)}
                    continue
                sha = _init_git_with_remote(repo, remotes / f"{pname}.git", pushers / pname)
                shas[mid] = sha
                sources[pname] = {"plugin_name": pname, "repo_dir": str(repo), "git_sha": sha}

            p_behind = pushers / "mod-behind"
            (p_behind / "NEW.md").write_text("remote\n", encoding="utf-8")
            _git(p_behind, "add", "NEW.md")
            _git(p_behind, "commit", "-m", "remote commit")
            _git(p_behind, "push", "origin", "dev")

            r_drift = repos_root / "mod-drift"
            (r_drift / "LOCAL.md").write_text("drift\n", encoding="utf-8")
            _git(r_drift, "add", "LOCAL.md")
            _git(r_drift, "commit", "-m", "drift commit")
            _git(r_drift, "push", "origin", "dev")

            (repos_root / "mod-dirty" / "dirty.txt").write_text("dirty\n", encoding="utf-8")
            _git(repos_root / "mod-detached", "checkout", "--detach", shas["m_detached"])
            _git(repos_root / "mod-noup", "checkout", "-b", "topic-no-upstream")

            p_div = pushers / "mod-diverged"
            (p_div / "R.md").write_text("r\n", encoding="utf-8")
            _git(p_div, "add", "R.md")
            _git(p_div, "commit", "-m", "r")
            _git(p_div, "push", "origin", "dev")
            r_div = repos_root / "mod-diverged"
            (r_div / "L.md").write_text("l\n", encoding="utf-8")
            _git(r_div, "add", "L.md")
            _git(r_div, "commit", "-m", "l")

            r_ahead = repos_root / "mod-ahead"
            (r_ahead / "A.md").write_text("a\n", encoding="utf-8")
            _git(r_ahead, "add", "A.md")
            _git(r_ahead, "commit", "-m", "ahead")

            _git(repos_root / "mod-errfetch", "remote", "set-url", "origin", str(tmp_path / "nonexistent.git"))

            updater.write_sources_registry(gravity_home, {"sources": sources})

            payload, rc = updater.run_update(gravity_home=gravity_home, plugins_dirs=[plugins_dir], check_only=True)
            self.assertEqual(rc, 1)
            by_id = {r["id"]: r for r in payload["results"]}
            self.assertEqual(by_id["m_uptodate"]["status"], "up_to_date")
            self.assertEqual(by_id["m_behind"]["status"], "update_available")
            self.assertEqual(by_id["m_drift"]["status"], "local_drift")
            self.assertEqual(by_id["m_dirty"]["status"], "dirty")
            self.assertEqual(by_id["m_detached"]["status"], "detached")
            self.assertEqual(by_id["m_noup"]["status"], "no_upstream")
            self.assertEqual(by_id["m_diverged"]["status"], "diverged")
            self.assertEqual(by_id["m_ahead"]["status"], "ahead")
            self.assertEqual(by_id["m_unlinked"]["status"], "unlinked")
            self.assertEqual(by_id["m_missing"]["status"], "missing_repo")
            self.assertEqual(by_id["m_errfetch"]["status"], "error_fetch")
            self.assertFalse((repos_root / "mod-behind" / "NEW.md").exists())

            off_payload, off_rc = updater.run_update(
                gravity_home=gravity_home, plugins_dirs=[plugins_dir], check_only=True, offline=True
            )
            self.assertEqual(off_rc, 0)
            off_by_id = {r["id"]: r for r in off_payload["results"]}
            self.assertEqual(off_by_id["m_dirty"]["status"], "dirty")
            self.assertEqual(off_by_id["m_drift"]["status"], "local_drift")
            self.assertEqual(off_by_id["m_errfetch"]["status"], "up_to_date")

    def test_pull_targeted_reinstall_core_last_registry_refresh_and_mcp_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            gravity_home = tmp_path / "gravity-home"
            plugins_dir = tmp_path / "plugins"
            repos_root = tmp_path / "repos"
            remotes = tmp_path / "remotes"
            pushers = tmp_path / "pushers"
            order_log = tmp_path / "install_order.log"

            core_repo = repos_root / "gravity"
            comp_repo = repos_root / "gravity-companion"
            dirty_repo = repos_root / "gravity-dirty"
            _create_module_repo(core_repo, mod_id="core", plugin_name="gravity", version="0.3.0", with_init_env=True)
            _create_module_repo(comp_repo, mod_id="companion", plugin_name="gravity-companion", version="0.2.0")
            _create_module_repo(dirty_repo, mod_id="dirtymod", plugin_name="gravity-dirty", version="0.1.0")

            _install_plugin_copy(core_repo, plugins_dir)
            _install_plugin_copy(comp_repo, plugins_dir)
            _install_plugin_copy(dirty_repo, plugins_dir)

            core_sha = _init_git_with_remote(core_repo, remotes / "gravity.git", pushers / "gravity")
            comp_sha = _init_git_with_remote(comp_repo, remotes / "gravity-companion.git", pushers / "gravity-companion")
            dirty_sha = _init_git_with_remote(dirty_repo, remotes / "gravity-dirty.git", pushers / "gravity-dirty")

            for pname, new_ver in (("gravity", "0.3.1"), ("gravity-companion", "0.2.1")):
                p_dir = pushers / pname
                man_path = p_dir / "plugin" / "plugin.json"
                man = json.loads(man_path.read_text(encoding="utf-8"))
                man["version"] = new_ver
                man_path.write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
                _git(p_dir, "add", "plugin/plugin.json")
                _git(p_dir, "commit", "-m", f"bump to {new_ver}")
                _git(p_dir, "push", "origin", "dev")

            (dirty_repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

            updater.write_sources_registry(
                gravity_home,
                {
                    "sources": {
                        "gravity": {"plugin_name": "gravity", "repo_dir": str(core_repo), "git_sha": core_sha},
                        "gravity-companion": {"plugin_name": "gravity-companion", "repo_dir": str(comp_repo), "git_sha": comp_sha},
                        "gravity-dirty": {"plugin_name": "gravity-dirty", "repo_dir": str(dirty_repo), "git_sha": dirty_sha},
                    }
                },
            )

            old_env = os.environ.get("GRAVITY_TEST_INSTALL_ORDER_LOG")
            os.environ["GRAVITY_TEST_INSTALL_ORDER_LOG"] = str(order_log)
            try:
                payload, rc = updater.run_update(gravity_home=gravity_home, plugins_dirs=[plugins_dir])
            finally:
                if old_env is None:
                    os.environ.pop("GRAVITY_TEST_INSTALL_ORDER_LOG", None)
                else:
                    os.environ["GRAVITY_TEST_INSTALL_ORDER_LOG"] = old_env

            self.assertEqual(rc, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["updated_count"], 2)
            self.assertTrue(payload["restart_mcp_recommended"])
            self.assertTrue(any("gravity_dashboard" in w for w in payload["warnings"]))
            self.assertEqual(payload["registry_refresh"]["status"], "ok")
            self.assertTrue((gravity_home / "core" / "modules.json").is_file())

            calls = [json.loads(line) for line in order_log.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual([c["plugin"] for c in calls], ["gravity-companion", "gravity"])
            self.assertEqual(Path(calls[0]["cwd"]), comp_repo.resolve())
            self.assertEqual(Path(calls[1]["cwd"]), core_repo.resolve())
            self.assertIn("--force", calls[0]["args"])
            self.assertIn("--strict", calls[0]["args"])

            self.assertEqual(json.loads((plugins_dir / "gravity" / "plugin.json").read_text(encoding="utf-8"))["version"], "0.3.1")

            order_log.unlink()
            os.environ["GRAVITY_TEST_INSTALL_ORDER_LOG"] = str(order_log)
            try:
                p_force, rc_force = updater.run_update(
                    gravity_home=gravity_home, plugins_dirs=[plugins_dir], modules_csv="companion", force=True
                )
            finally:
                os.environ.pop("GRAVITY_TEST_INSTALL_ORDER_LOG", None)
            self.assertEqual(rc_force, 0)
            self.assertFalse(p_force["restart_mcp_recommended"])
            self.assertEqual(p_force["reinstalled_count"], 1)
            self.assertEqual(p_force["results"][0]["status"], "reinstalled")

    def test_post_update_shared_sync_verification_passes_and_fails_closed_on_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            gravity_home = tmp_path / "gravity-home"
            plugins_dir = tmp_path / "plugins"
            repos_root = tmp_path / "repos"
            remotes = tmp_path / "remotes"
            pushers = tmp_path / "pushers"

            core_repo = repos_root / "gravity"
            _create_module_repo(core_repo, mod_id="core", plugin_name="gravity", version="0.3.0", with_init_env=True)
            _seed_shared_snapshot(core_repo, with_ssot_sync=True)
            _install_plugin_copy(core_repo, plugins_dir)
            core_sha = _init_git_with_remote(core_repo, remotes / "gravity.git", pushers / "gravity")
            updater.write_sources_registry(
                gravity_home,
                {"sources": {"gravity": {"plugin_name": "gravity", "repo_dir": str(core_repo), "git_sha": core_sha}}},
            )

            # 1) Valid _shared + sync_shared.py --check passes with shared_sync_ok=True
            p_ok, rc_ok = updater.run_update(gravity_home=gravity_home, plugins_dirs=[plugins_dir], offline=True, force=True)
            self.assertEqual(rc_ok, 0, msg=p_ok)
            self.assertTrue(p_ok["ok"])
            self.assertIs(p_ok["results"][0]["shared_sync_ok"], True)

            # 2) Tamper installed _shared via broken installer -> fails closed (shared_sync_ok=False, status=error_install)
            comp_repo = repos_root / "gravity-tampered"
            _create_module_repo(comp_repo, mod_id="tamp", plugin_name="gravity-tampered", version="0.1.0")
            _seed_shared_snapshot(comp_repo, with_ssot_sync=False)
            _install_plugin_copy(comp_repo, plugins_dir)
            comp_repo.joinpath("install.py").write_text(
                "import shutil, sys\n"
                "from pathlib import Path\n"
                "src = Path(__file__).resolve().parent / 'plugin'\n"
                "dst = Path(sys.argv[sys.argv.index('--target') + 1])\n"
                "if dst.exists(): shutil.rmtree(dst)\n"
                "shutil.copytree(src, dst)\n"
                "(dst / '_shared' / 'atomic_io.py').write_text('# tampered\\n', encoding='utf-8')\n",
                encoding="utf-8",
                newline="\n",
            )
            comp_sha = _init_git_with_remote(comp_repo, remotes / "gravity-tampered.git", pushers / "gravity-tampered")
            updater.write_sources_registry(
                gravity_home,
                {
                    "sources": {
                        "gravity": {"plugin_name": "gravity", "repo_dir": str(core_repo), "git_sha": core_sha},
                        "gravity-tampered": {"plugin_name": "gravity-tampered", "repo_dir": str(comp_repo), "git_sha": comp_sha},
                    }
                },
            )
            p_bad, rc_bad = updater.run_update(
                gravity_home=gravity_home, plugins_dirs=[plugins_dir], modules_csv="tamp", offline=True, force=True
            )
            self.assertEqual(rc_bad, 1)
            self.assertFalse(p_bad["ok"])
            self.assertIs(p_bad["results"][0]["shared_sync_ok"], False)
            self.assertEqual(p_bad["results"][0]["status"], "error_install")
            self.assertIn("SHA-256 mismatch", p_bad["results"][0]["error"])

            # 3) Missing .shared_manifest.json in installed plugin -> fails closed
            (comp_repo / "install.py").write_text(
                "import shutil, sys\n"
                "from pathlib import Path\n"
                "src = Path(__file__).resolve().parent / 'plugin'\n"
                "dst = Path(sys.argv[sys.argv.index('--target') + 1])\n"
                "if dst.exists(): shutil.rmtree(dst)\n"
                "shutil.copytree(src, dst)\n"
                "(dst / '.shared_manifest.json').unlink()\n",
                encoding="utf-8",
                newline="\n",
            )
            _git(comp_repo, "add", "install.py")
            _git(comp_repo, "commit", "-m", "drop manifest on install")
            p_nom, rc_nom = updater.run_update(
                gravity_home=gravity_home, plugins_dirs=[plugins_dir], modules_csv="tamp", offline=True, force=True
            )
            self.assertEqual(rc_nom, 1)
            self.assertIs(p_nom["results"][0]["shared_sync_ok"], False)
            self.assertIn(".shared_manifest.json", p_nom["results"][0]["error"])

            # 4) Drift between shared/gravity_shared and plugin/_shared in gravity -> sync_shared.py --check fails closed
            (core_repo / "plugin" / "_shared" / "atomic_io.py").write_text("# drifted\n", encoding="utf-8")
            man_p = core_repo / "plugin" / ".shared_manifest.json"
            man_data = json.loads(man_p.read_text(encoding="utf-8"))
            man_data["files"]["atomic_io.py"] = hashlib.sha256(b"# drifted\n").hexdigest()
            man_p.write_text(json.dumps(man_data, indent=2) + "\n", encoding="utf-8")
            _git(core_repo, "add", "plugin/_shared/atomic_io.py", "plugin/.shared_manifest.json")
            _git(core_repo, "commit", "-m", "introduce SSOT drift")
            p_ssot, rc_ssot = updater.run_update(
                gravity_home=gravity_home, plugins_dirs=[plugins_dir], modules_csv="core", offline=True, force=True
            )
            self.assertEqual(rc_ssot, 1)
            self.assertIs(p_ssot["results"][0]["shared_sync_ok"], False)
            self.assertEqual(p_ssot["results"][0]["status"], "error_install")
            self.assertIn("sync_shared.py --check", p_ssot["results"][0]["error"])

    def test_init_env_cli_check_updates_and_update_wiring(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "user-home"
            fake_home.mkdir()
            plugins_dir = tmp_path / "plugins"
            shutil.copytree(REPO_ROOT / "plugin", plugins_dir / "gravity", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            gravity_home = tmp_path / "gravity-home"

            env = dict(os.environ)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["HOME"] = str(fake_home)
            env["USERPROFILE"] = str(fake_home)
            for key in ("GRAVITY_HOME", "GRAVITY_CORE_HOME", "GRAVITY_METRICS_HOME", "GRAVITY_ARCHITECT_HOME", "GRAVITY_WORKFLOW_HOME"):
                env.pop(key, None)

            p_chk = subprocess.run(
                [sys.executable, "-B", str(INIT_SCRIPT), "--gravity-home", str(gravity_home), "--plugins-dir", str(plugins_dir), "--check-updates", "--offline", "--json"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=20, check=False,
            )
            self.assertEqual(p_chk.returncode, 0, msg=p_chk.stderr or p_chk.stdout)
            out_chk = json.loads(p_chk.stdout)
            self.assertEqual(out_chk["mode"], "check-updates")
            self.assertTrue(out_chk["ok"])
            self.assertEqual(out_chk["results"][0]["status"], "unlinked")
            self.assertFalse(gravity_home.exists())

            p_upd = subprocess.run(
                [sys.executable, "-B", str(INIT_SCRIPT), "--gravity-home", str(gravity_home), "--plugins-dir", str(plugins_dir), "--update", "--offline", "--dry-run", "--force", "--modules", "core"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=20, check=False,
            )
            self.assertEqual(p_upd.returncode, 0, msg=p_upd.stderr or p_upd.stdout)
            self.assertIn("Gravity Core — Update", p_upd.stdout)
            self.assertIn("[unlinked] gravity", p_upd.stdout)


if __name__ == "__main__":
    unittest.main()
