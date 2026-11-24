"""Isolated unit tests for plugin/core/registry.py (100% stdlib, TemporaryDirectory only)."""

from __future__ import annotations

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

from core.registry import (  # noqa: E402
    detect_legacy_homes,
    discover_modules,
    resolve_gravity_home,
    resolve_module_home,
    validate_module_contract,
    write_modules_registry,
)


def _valid_contract(mod_id: str = "sample", plugin_name: str = "gravity-sample") -> dict:
    return {
        "schema_version": 1,
        "id": mod_id,
        "plugin_name": plugin_name,
        "role": f"Role for {mod_id}",
        "storage": {
            "subdir": mod_id,
            "env_override": f"GRAVITY_{mod_id.upper()}_HOME",
        },
        "commands": [f"/{plugin_name}"],
        "capabilities": ["cap-a"],
        "ui": {"mode": "none", "target": "gravity"},
        "signals": {"produces": ["sig-out"], "consumes": []},
    }


def _valid_manifest(name: str = "gravity-sample", version: str = "0.1.0") -> dict:
    return {
        "name": name,
        "displayName": name.title(),
        "version": version,
        "description": "Test module plugin",
        "logo": "assets/logo.svg",
        "suggestedPrompts": ["One", "Two", "Three"],
        "author": {"name": "Gravity Contributors"},
        "homepage": f"https://github.com/BSourichanh/{name}",
        "repository": f"https://github.com/BSourichanh/{name}.git",
    }


class TestRegistry(unittest.TestCase):
    def test_resolve_gravity_home_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            explicit = tmp_path / "explicit"
            env_home = tmp_path / "from-env"
            fake_user = tmp_path / "user"

            with mock.patch.dict(os.environ, {"GRAVITY_HOME": str(env_home)}, clear=False):
                with mock.patch("pathlib.Path.home", return_value=fake_user):
                    self.assertEqual(resolve_gravity_home(explicit), explicit.resolve())
                    self.assertEqual(resolve_gravity_home(), env_home.resolve())

            with mock.patch.dict(os.environ, {"GRAVITY_HOME": "   "}, clear=False):
                with mock.patch("pathlib.Path.home", return_value=fake_user):
                    self.assertEqual(
                        resolve_gravity_home(),
                        (fake_user / ".gemini" / "gravity").resolve(),
                    )

    def test_resolve_module_home_precedence_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            mod_override = tmp_path / "override-metrics"

            with mock.patch.dict(os.environ, {"GRAVITY_METRICS_HOME": str(mod_override)}, clear=False):
                self.assertEqual(
                    resolve_module_home(
                        "metrics",
                        env_override="GRAVITY_METRICS_HOME",
                        gravity_home=g_home,
                    ),
                    mod_override.resolve(),
                )

            with mock.patch.dict(os.environ, {"GRAVITY_METRICS_HOME": ""}, clear=False):
                self.assertEqual(
                    resolve_module_home(
                        "metrics",
                        env_override="GRAVITY_METRICS_HOME",
                        gravity_home=g_home,
                    ),
                    (g_home / "metrics").resolve(),
                )

            for bad_id in ("", "../escape", "a/b", "InvalidUpper"):
                with self.assertRaises(ValueError):
                    resolve_module_home(bad_id, gravity_home=g_home)

    def test_validate_module_contract(self) -> None:
        self.assertEqual(validate_module_contract(_valid_contract()), [])

        self.assertTrue(validate_module_contract("not-a-dict"))

        bad_sv = _valid_contract()
        bad_sv["schema_version"] = True
        self.assertTrue(validate_module_contract(bad_sv))

        bad_sv["schema_version"] = 2
        self.assertTrue(validate_module_contract(bad_sv))

        bad_fields = _valid_contract()
        bad_fields["storage"] = {"subdir": "../bad", "env_override": ""}
        bad_fields["commands"] = [""]
        bad_fields["ui"] = {"mode": "", "target": None}
        bad_fields["signals"] = {"produces": "wrong", "consumes": [123]}
        errs = validate_module_contract(bad_fields)
        self.assertGreaterEqual(len(errs), 5)

    def test_discover_modules_sorted_and_resilient(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugins_root = Path(tmp) / "plugins"
            plugins_root.mkdir(parents=True)

            # Non-gravity third-party plugin (no config/module.json) should be ignored
            third_party = plugins_root / "other-plugin"
            third_party.mkdir()
            (third_party / "plugin.json").write_text('{"name": "other"}', encoding="utf-8")

            # Valid module 'zeta' and 'alpha' (created out of alphabetical order)
            for mod_id, pname in (("zeta", "gravity-zeta"), ("alpha", "gravity-alpha")):
                mod_dir = plugins_root / pname
                (mod_dir / "config").mkdir(parents=True)
                (mod_dir / "plugin.json").write_text(
                    json.dumps(_valid_manifest(pname)), encoding="utf-8"
                )
                (mod_dir / "config" / "module.json").write_text(
                    json.dumps(_valid_contract(mod_id, pname)), encoding="utf-8"
                )

            # Malformed JSON module
            broken = plugins_root / "broken-json"
            (broken / "config").mkdir(parents=True)
            (broken / "config" / "module.json").write_text("{not-json", encoding="utf-8")

            # Binary garbage module
            bin_mod = plugins_root / "binary-mod"
            (bin_mod / "config").mkdir(parents=True)
            (bin_mod / "config" / "module.json").write_bytes(b"\xff\xfe\x00\x01")

            # Mismatch plugin_name vs plugin.json name
            mismatch = plugins_root / "mismatch-mod"
            (mismatch / "config").mkdir(parents=True)
            (mismatch / "plugin.json").write_text(
                json.dumps(_valid_manifest("actual-name")), encoding="utf-8"
            )
            (mismatch / "config" / "module.json").write_text(
                json.dumps(_valid_contract("beta", "expected-name")), encoding="utf-8"
            )

            # Include non-existent root too
            found = discover_modules([plugins_root, Path(tmp) / "missing-root"])
            ids = [m["id"] for m in found]
            self.assertEqual(ids, ["alpha", "beta", "binary-mod", "broken-json", "zeta"])

            by_id = {m["id"]: m for m in found}
            self.assertTrue(by_id["alpha"]["valid"])
            self.assertEqual(by_id["alpha"]["errors"], [])
            self.assertTrue(by_id["zeta"]["valid"])
            self.assertFalse(by_id["broken-json"]["valid"])
            self.assertFalse(by_id["binary-mod"]["valid"])
            self.assertFalse(by_id["beta"]["valid"])
            self.assertTrue(any("does not match" in e for e in by_id["beta"]["errors"]))

    def test_detect_legacy_homes_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp) / "home"
            fake_home.mkdir()
            self.assertEqual(detect_legacy_homes(fake_home), [])

            legacy_targets = (
                fake_home / ".gemini" / "gravity-metrics",
                fake_home / ".gemini" / "gravity-workflow",
                fake_home / ".gravity",
            )
            sentinels: list[Path] = []
            for idx, ldir in enumerate(legacy_targets):
                ldir.mkdir(parents=True)
                sentinel = ldir / f"keep_{idx}.txt"
                sentinel.write_text(f"data-{idx}", encoding="utf-8")
                sentinels.append(sentinel)

            # Residual retired gravity-bridge directory must be ignored cleanly
            residual_bridge = fake_home / ".gemini" / "gravity-bridge"
            residual_bridge.mkdir(parents=True)
            (residual_bridge / "bridge.db").write_text("residual", encoding="utf-8")

            detected = detect_legacy_homes(fake_home)
            self.assertEqual(len(detected), 3)
            self.assertEqual(
                {item["name"] for item in detected},
                {"gravity-metrics", "gravity-workflow", "gravity"},
            )
            self.assertEqual((residual_bridge / "bridge.db").read_text(encoding="utf-8"), "residual")
            # Ensure strictly read-only: sentinels intact
            for idx, sentinel in enumerate(sentinels):
                self.assertTrue(sentinel.is_file())
                self.assertEqual(sentinel.read_text(encoding="utf-8"), f"data-{idx}")

    def test_write_modules_registry_atomic_utf8_no_bom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            g_home = Path(tmp) / "gravity-home"
            sample_modules = [{"id": "core", "plugin_name": "gravity", "valid": True, "errors": []}]
            reg_path = write_modules_registry(g_home, sample_modules)

            self.assertEqual(reg_path, (g_home / "core" / "modules.json").resolve())
            self.assertTrue(reg_path.is_file())
            raw = reg_path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\r\n", raw)

            data = json.loads(raw.decode("utf-8"))
            self.assertEqual(data["schema_version"], 1)
            self.assertEqual(data["module_count"], 1)
            self.assertEqual(data["modules"][0]["id"], "core")
            # No leftover .tmp files
            self.assertEqual([p.name for p in reg_path.parent.iterdir()], ["modules.json"])


if __name__ == "__main__":
    unittest.main()
