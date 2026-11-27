"""Isolated unit tests for plugin/dashboard/providers/spi.py and SPI-1 routing in api.py."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO_ROOT / "plugin"
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from core.registry import write_modules_registry  # noqa: E402
from dashboard import api  # noqa: E402
from dashboard.providers import spi  # noqa: E402


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in (
        "GRAVITY_HOME",
        "GRAVITY_CORE_HOME",
        "GRAVITY_WORKFLOW_HOME",
        "GRAVITY_METRICS_HOME",
        "GRAVITY_ARCHITECT_HOME",
        "GRAVITY_ARCHITECT_WORKSPACE",
    ):
        env.pop(key, None)
    return env


def _write_spi_plugin(
    plugins_root: Path,
    *,
    mod_id: str,
    plugin_name: str,
    script_body: str,
    views: list[str] | None = None,
    actions: list[str] | None = None,
    provider_script: str = "scripts/dashboard_provider.py",
    include_in_registry_entry: bool = False,
) -> tuple[Path, dict]:
    mod_dir = plugins_root / plugin_name
    (mod_dir / "config").mkdir(parents=True, exist_ok=True)
    (mod_dir / "scripts").mkdir(parents=True, exist_ok=True)

    manifest = {
        "name": plugin_name,
        "displayName": plugin_name.replace("-", " ").title(),
        "version": "0.3.0",
        "description": f"SPI test plugin {plugin_name}",
        "logo": "assets/logo.svg",
        "suggestedPrompts": ["One", "Two", "Three"],
        "author": {"name": "Gravity Contributors"},
        "homepage": f"https://github.com/BSourichanh/{plugin_name}",
        "repository": f"https://github.com/BSourichanh/{plugin_name}.git",
    }
    dash_cfg = {
        "provider_script": provider_script,
        "views": views if views is not None else [mod_id],
        "actions": actions if actions is not None else [],
    }
    contract = {
        "schema_version": 1,
        "id": mod_id,
        "plugin_name": plugin_name,
        "role": f"Role for {mod_id}",
        "storage": {
            "subdir": mod_id,
            "env_override": f"GRAVITY_{mod_id.upper().replace('-', '_')}_HOME",
        },
        "commands": [f"/{plugin_name}"],
        "capabilities": ["spi-1"],
        "ui": {"mode": "mcp-app", "target": "gravity"},
        "signals": {"produces": [], "consumes": []},
        "dashboard": dash_cfg,
    }
    (mod_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
    (mod_dir / "config" / "module.json").write_text(json.dumps(contract), encoding="utf-8", newline="\n")

    script_file = mod_dir / "scripts" / "dashboard_provider.py"
    script_file.write_text(script_body, encoding="utf-8", newline="\n")

    reg_entry = {
        "id": mod_id,
        "plugin_name": plugin_name,
        "display_name": manifest["displayName"],
        "version": manifest["version"],
        "valid": True,
        "errors": [],
        "storage": contract["storage"],
        "commands": contract["commands"],
        "capabilities": contract["capabilities"],
        "ui": contract["ui"],
        "signals": contract["signals"],
        "plugin_dir": str(mod_dir),
        "module_path": str(mod_dir / "config" / "module.json"),
        "manifest_path": str(mod_dir / "plugin.json"),
    }
    if include_in_registry_entry:
        reg_entry["dashboard"] = dash_cfg
    return mod_dir, reg_entry


_ECHO_PROVIDER_PY = """\
import argparse
import json
import sys

p = argparse.ArgumentParser()
p.add_argument("--view", default="")
p.add_argument("--since-signature", default="")
p.add_argument("--action", default="")
p.add_argument("--json", action="store_true")
args = p.parse_args()

payload = json.loads(sys.stdin.read() or "{}")
if args.view:
    if args.since_signature == "sig-1":
        print(json.dumps({"changed": False, "unchanged": True, "signature": "sig-1"}))
    else:
        print(json.dumps({
            "available": True,
            "changed": True,
            "unchanged": False,
            "signature": "sig-1",
            "view": args.view,
            "received": payload,
        }))
elif args.action:
    print(json.dumps({
        "ok": True,
        "action": args.action,
        "received": payload,
    }))
"""


class TestDashboardSpiResolution(unittest.TestCase):
    def test_resolve_from_registry_and_config_module_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            plugins_root = tmp_path / "plugins"
            _, reg_direct = _write_spi_plugin(
                plugins_root,
                mod_id="metrics",
                plugin_name="gravity-metrics",
                script_body=_ECHO_PROVIDER_PY,
                views=["metrics", "session-detail"],
                actions=["record"],
                include_in_registry_entry=True,
            )
            _, reg_fallback = _write_spi_plugin(
                plugins_root,
                mod_id="architect",
                plugin_name="gravity-architect",
                script_body=_ECHO_PROVIDER_PY,
                views=["architect"],
                include_in_registry_entry=False,
            )
            write_modules_registry(g_home, [reg_direct, reg_fallback])

            res_direct = spi.resolve_dashboard_provider("metrics", gravity_home=g_home)
            self.assertTrue(res_direct["ok"])
            self.assertEqual(res_direct["views"], ["metrics", "session-detail"])
            self.assertEqual(res_direct["actions"], ["record"])

            res_fb = spi.resolve_dashboard_provider("architect", gravity_home=g_home)
            self.assertTrue(res_fb["ok"])
            self.assertEqual(res_fb["views"], ["architect"])
            self.assertTrue(Path(res_fb["script_path"]).is_file())

    def test_resolve_rejects_invalid_ids_traversal_and_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            plugins_root = tmp_path / "plugins"

            for bad_id in ("", "../etc", "BadUpper", "a/b"):
                res = spi.resolve_dashboard_provider(bad_id, gravity_home=g_home, plugin_roots=[plugins_root])
                self.assertFalse(res["ok"])

            for idx, bad_script in enumerate(
                ("../outside.py", "/etc/passwd", r"scripts\win.py", "scripts/bad\x00.py", "scripts/missing.py")
            ):
                mod_id = f"mod{idx}"
                _, reg = _write_spi_plugin(
                    plugins_root,
                    mod_id=mod_id,
                    plugin_name=f"gravity-{mod_id}",
                    script_body=_ECHO_PROVIDER_PY,
                    provider_script=bad_script,
                    include_in_registry_entry=True,
                )
                write_modules_registry(g_home, [reg])
                res = spi.resolve_dashboard_provider(mod_id, gravity_home=g_home)
                self.assertFalse(res["ok"], f"Expected rejection for {bad_script!r}")

    def test_resolve_rejects_symlinks_and_ntfs_junctions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            plugins_root = tmp_path / "plugins"
            mod_dir, reg = _write_spi_plugin(
                plugins_root,
                mod_id="workflow",
                plugin_name="gravity-workflow",
                script_body=_ECHO_PROVIDER_PY,
                include_in_registry_entry=True,
            )
            outside = tmp_path / "outside.py"
            outside.write_text(_ECHO_PROVIDER_PY, encoding="utf-8")
            script_path = mod_dir / "scripts" / "dashboard_provider.py"
            script_path.unlink()
            try:
                script_path.symlink_to(outside)
            except OSError:
                self.skipTest("Symlink creation requires elevated privileges on this OS.")

            write_modules_registry(g_home, [reg])
            res = spi.resolve_dashboard_provider("workflow", gravity_home=g_home)
            self.assertFalse(res["ok"])
            self.assertIn("symlink", res["error"].lower())

        # Also verify junction rejection on Windows via path_safety mock
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            plugins_root = tmp_path / "plugins"
            _, reg = _write_spi_plugin(
                plugins_root,
                mod_id="metrics",
                plugin_name="gravity-metrics",
                script_body=_ECHO_PROVIDER_PY,
                include_in_registry_entry=True,
            )
            write_modules_registry(g_home, [reg])
            with mock.patch("dashboard.providers.spi.is_symlink_or_junction", return_value=True):
                res = spi.resolve_dashboard_provider("metrics", gravity_home=g_home)
                self.assertFalse(res["ok"])
                self.assertIn("junction", res["error"].lower())


class TestDashboardSpiInvocation(unittest.TestCase):
    def test_invoke_view_action_since_signature_and_stdin_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            plugins_root = tmp_path / "plugins"
            _write_spi_plugin(
                plugins_root,
                mod_id="metrics",
                plugin_name="gravity-metrics",
                script_body=_ECHO_PROVIDER_PY,
                views=["metrics", "session-detail", "audit-detail"],
                actions=["record", "ignore"],
                include_in_registry_entry=False,
            )

            res = spi.invoke_dashboard_provider(
                "metrics",
                view="metrics",
                params={"project": "gravity", "limit": 25},
                ctx={"metrics_home": g_home / "metrics"},
                gravity_home=g_home,
                plugin_roots=[plugins_root],
            )
            self.assertTrue(res["available"])
            self.assertEqual(res["view"], "metrics")
            self.assertEqual(res["received"]["params"]["project"], "gravity")
            self.assertEqual(res["received"]["context"]["metrics_home"], str(g_home / "metrics"))

            unchanged = spi.invoke_dashboard_provider(
                "metrics",
                view="metrics",
                since_signature="sig-1",
                gravity_home=g_home,
                plugin_roots=[plugins_root],
            )
            self.assertEqual(unchanged, {"changed": False, "unchanged": True, "signature": "sig-1"})

            act = spi.invoke_dashboard_provider(
                "metrics",
                action="record",
                params={"target": "abc12345"},
                gravity_home=g_home,
                plugin_roots=[plugins_root],
            )
            self.assertTrue(act["ok"])
            self.assertEqual(act["action"], "record")
            self.assertEqual(act["received"]["params"]["target"], "abc12345")

            # Undeclared view / action fail closed without executing subprocess
            bad_view = spi.invoke_dashboard_provider(
                "metrics",
                view="secret-view",
                gravity_home=g_home,
                plugin_roots=[plugins_root],
            )
            self.assertFalse(bad_view["available"])
            self.assertTrue(bad_view["spi_fallback"])

            bad_act = spi.invoke_dashboard_provider(
                "metrics",
                action="delete-all",
                gravity_home=g_home,
                plugin_roots=[plugins_root],
            )
            self.assertFalse(bad_act["ok"])
            self.assertTrue(bad_act["spi_fallback"])

    def test_timeout_nonzero_invalid_json_and_payload_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            plugins_root = tmp_path / "plugins"

            _write_spi_plugin(
                plugins_root,
                mod_id="slow",
                plugin_name="gravity-slow",
                script_body="import time\ntime.sleep(2.0)\n",
                views=["slow"],
            )
            res_to = spi.invoke_dashboard_provider(
                "slow",
                view="slow",
                gravity_home=g_home,
                plugin_roots=[plugins_root],
                timeout_s=0.1,
            )
            self.assertFalse(res_to["available"])
            self.assertTrue(res_to["spi_fallback"])
            self.assertIn("timed out", res_to["error"].lower())

            _write_spi_plugin(
                plugins_root,
                mod_id="failing",
                plugin_name="gravity-failing",
                script_body="import sys\nsys.stderr.write('boom')\nsys.exit(2)\n",
                views=["failing"],
            )
            res_rc = spi.invoke_dashboard_provider(
                "failing",
                view="failing",
                gravity_home=g_home,
                plugin_roots=[plugins_root],
            )
            self.assertFalse(res_rc["available"])
            self.assertTrue(res_rc["spi_fallback"])
            self.assertEqual(res_rc["returncode"], 2)

            _write_spi_plugin(
                plugins_root,
                mod_id="badjson",
                plugin_name="gravity-badjson",
                script_body="print('not-json')\n",
                views=["badjson"],
            )
            res_json = spi.invoke_dashboard_provider(
                "badjson",
                view="badjson",
                gravity_home=g_home,
                plugin_roots=[plugins_root],
            )
            self.assertFalse(res_json["available"])
            self.assertTrue(res_json["spi_fallback"])

            _write_spi_plugin(
                plugins_root,
                mod_id="huge",
                plugin_name="gravity-huge",
                script_body=(
                    "import json\n"
                    "print(json.dumps({'available': True, 'records': [{'blob': 'x' * 4000} for _ in range(150)]}))\n"
                ),
                views=["huge"],
            )
            res_huge = spi.invoke_dashboard_provider(
                "huge",
                view="huge",
                gravity_home=g_home,
                plugin_roots=[plugins_root],
            )
            self.assertTrue(res_huge["available"])
            self.assertTrue(res_huge["truncated"])
            encoded_len = len(json.dumps(res_huge, ensure_ascii=False).encode("utf-8"))
            self.assertLess(encoded_len, spi.MAX_PAYLOAD_BYTES)

    def test_api_has_zero_static_companion_provider_imports_and_validates_inputs(self) -> None:
        api_path = PLUGIN_ROOT / "dashboard" / "api.py"
        tree = ast.parse(api_path.read_text(encoding="utf-8"), filename=str(api_path))
        top_level_imports: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_level_imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_level_imports.append(node.module)
        for forbidden in ("architect_provider", "metrics_provider", "workflow_provider", "bridge_provider"):
            self.assertFalse(
                any(forbidden in mod for mod in top_level_imports),
                f"Forbidden static import {forbidden} found in dashboard/api.py: {top_level_imports}",
            )

        self.assertEqual(spi.SPI_TIMEOUT_S, 15.0)
        self.assertEqual(spi.MAX_PAYLOAD_BYTES, 450_000)

        bad_act = api.run_metrics_cli_action("rm-rf", target="abc12345")
        self.assertFalse(bad_act["ok"])
        bad_tgt = api.run_metrics_cli_action("record", target="../escape")
        self.assertFalse(bad_tgt["ok"])
        bad_det = api.get_session_detail("../escape")
        self.assertFalse(bad_det["found"])
        bad_aud = api.read_metrics_audit("../code/secret.md")
        self.assertFalse(bad_aud["found"])
        code_aud = api.read_metrics_audit("code/secret.md")
        self.assertFalse(code_aud["found"])

        live_fb = api.get_live_session_state()
        self.assertIn("available", live_fb)
        self.assertIn("agents", live_fb)


if __name__ == "__main__":
    unittest.main()
