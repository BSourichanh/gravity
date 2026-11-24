"""Isolated subprocess tests for plugin/hooks/pre_invocation_gravity.py."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_SCRIPT = REPO_ROOT / "plugin" / "hooks" / "pre_invocation_gravity.py"


def _run_hook(stdin_text: str, *, fake_home: Path, gravity_home: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["HOME"] = str(fake_home)
    env["USERPROFILE"] = str(fake_home)
    env["GRAVITY_HOME"] = str(gravity_home)
    for key in (
        "GRAVITY_CORE_HOME",
        "GRAVITY_WORKFLOW_HOME",
        "GRAVITY_METRICS_HOME",
        "GRAVITY_BRIDGE_HOME",
        "GRAVITY_ARCHITECT_HOME",
    ):
        env.pop(key, None)

    return subprocess.run(
        [sys.executable, "-B", str(HOOK_SCRIPT)],
        input=stdin_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=15,
        check=False,
    )


class TestPreInvocationGravityHook(unittest.TestCase):
    def test_bare_gravity_commands_return_terminate_and_zero_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "user-home"
            fake_home.mkdir()
            gravity_home = tmp_path / "uninitialized-gravity-home"

            cases = [
                {"lastUserInput": "/gravity"},
                {"lastUserInput": "/gravity:gravity", "invocationNum": 0},
                {
                    "userInput": (
                        "<USER_REQUEST>\n/GRAVITY\n</USER_REQUEST>\n"
                        "<ADDITIONAL_METADATA>time=now</ADDITIONAL_METADATA>\n"
                        "<USER_SETTINGS_CHANGE>off</USER_SETTINGS_CHANGE>"
                    ),
                    "invocationNum": None,
                },
                {"prompt": "  /gravity:gravity  "},
            ]
            for payload in cases:
                proc = _run_hook(json.dumps(payload), fake_home=fake_home, gravity_home=gravity_home)
                self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
                self.assertTrue(proc.stdout.isascii(), msg=f"Output must be ASCII-safe: {proc.stdout!r}")
                out = json.loads(proc.stdout.strip())
                self.assertEqual(out.get("terminationBehavior"), "terminate")
                steps = out.get("injectSteps") or []
                self.assertEqual(len(steps), 1)
                sys_msg = steps[0].get("systemMessage") or {}
                meta = sys_msg.get("metadata") or {}
                md = meta.get("user_markdown") or ""
                self.assertIn("Gravity Core", md)
                self.assertIn("Démarrage / Init", md)
                self.assertFalse(gravity_home.exists())

    def test_passthrough_for_nonzero_invocation_subcommands_and_invalid_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "user-home"
            fake_home.mkdir()
            gravity_home = tmp_path / "uninitialized-gravity-home"

            passthrough_inputs = [
                "",
                "{not-json",
                "[]",
                json.dumps({"lastUserInput": "/gravity", "invocationNum": 1}),
                json.dumps({"lastUserInput": "/gravity", "invocationNum": True}),
                json.dumps({"lastUserInput": "/gravity", "invocationNum": False}),
                json.dumps({"lastUserInput": "/gravity status"}),
                json.dumps({"lastUserInput": "/gravity init"}),
                json.dumps({"lastUserInput": "/gravity-metrics"}),
                json.dumps({"lastUserInput": "Bonjour Gravity"}),
            ]
            for raw in passthrough_inputs:
                proc = _run_hook(raw, fake_home=fake_home, gravity_home=gravity_home)
                self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
                self.assertEqual(json.loads(proc.stdout.strip()), {})
                self.assertFalse(gravity_home.exists())


if __name__ == "__main__":
    unittest.main()
