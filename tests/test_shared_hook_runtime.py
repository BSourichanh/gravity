"""Isolated unit tests for gravity_shared.hook_runtime."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_ROOT = REPO_ROOT / "shared"
if str(SHARED_ROOT) not in sys.path:
    sys.path.insert(0, str(SHARED_ROOT))

from gravity_shared.hook_runtime import (  # noqa: E402
    configure_utf8_stdio,
    emit_handoff_markdown,
    emit_json,
    emit_ok,
    emit_passthrough,
    emit_user_markdown,
    first_not_none,
    first_str_arg,
    is_initial_invocation,
    normalize_command,
    read_stdin_json,
    read_stdin_text,
    resolve_brain_dir,
    resolve_conversation_id,
    resolve_workspace_root,
)


class _ReconfStream(io.StringIO):
    def __init__(self, initial: str = "", *, is_tty: bool = False, fail_reconf: bool = False) -> None:
        super().__init__(initial)
        self._is_tty = is_tty
        self._fail_reconf = fail_reconf
        self.reconf_calls: list[tuple[str, str]] = []

    def isatty(self) -> bool:
        return self._is_tty

    def reconfigure(self, *, encoding: str, errors: str) -> None:
        if self._fail_reconf:
            raise OSError("cannot reconfigure")
        self.reconf_calls.append((encoding, errors))


class _HangingStdin:
    def __init__(self, release: threading.Event) -> None:
        self._release = release

    def isatty(self) -> bool:
        return False

    def read(self) -> str:
        self._release.wait(timeout=2.0)
        return '{"late": true}'


class TestHookRuntime(unittest.TestCase):
    def test_configure_utf8_stdio(self) -> None:
        s_in = _ReconfStream()
        s_out = _ReconfStream()
        s_err = _ReconfStream(fail_reconf=True)
        with mock.patch("sys.stdin", s_in), mock.patch("sys.stdout", s_out), mock.patch(
            "sys.stderr", s_err
        ):
            configure_utf8_stdio()
        self.assertEqual(s_in.reconf_calls, [("utf-8", "replace")])
        self.assertEqual(s_out.reconf_calls, [("utf-8", "replace")])

    def test_read_stdin_text_and_json_cases(self) -> None:
        with mock.patch("sys.stdin", _ReconfStream('  {"ok": true, "n": 2}  ')):
            self.assertEqual(read_stdin_json(), {"ok": True, "n": 2})

        with mock.patch("sys.stdin", _ReconfStream("[1, 2, 3]")):
            self.assertEqual(read_stdin_json(), {})

        with mock.patch("sys.stdin", _ReconfStream("{bad json")):
            self.assertEqual(read_stdin_json(), {})

        with mock.patch("sys.stdin", _ReconfStream("ignored", is_tty=True)):
            self.assertEqual(read_stdin_text(), "")
            self.assertEqual(read_stdin_json(), {})

        release = threading.Event()
        try:
            with mock.patch("sys.stdin", _HangingStdin(release)):
                self.assertEqual(read_stdin_text(timeout_s=0.02), "")
                self.assertEqual(read_stdin_json(timeout_s=0.02), {})
        finally:
            release.set()

    def test_emit_helpers(self) -> None:
        out = _ReconfStream()
        with mock.patch("sys.stdout", out):
            emit_json({"msg": "café"})
            emit_passthrough()
            emit_ok()
            emit_user_markdown("# Title", system_message="ro")
            emit_handoff_markdown("## Next", system_message="handoff")

        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 5)
        self.assertNotIn("café", lines[0])  # ensure_ascii=True
        self.assertEqual(json.loads(lines[0]), {"msg": "café"})
        self.assertEqual(json.loads(lines[1]), {})
        self.assertEqual(json.loads(lines[2]), {})

        user_payload = json.loads(lines[3])
        self.assertEqual(user_payload["terminationBehavior"], "terminate")
        self.assertEqual(
            user_payload["injectSteps"][0]["systemMessage"]["metadata"]["user_markdown"],
            "# Title",
        )

        handoff_payload = json.loads(lines[4])
        self.assertNotIn("terminationBehavior", handoff_payload)
        self.assertEqual(
            handoff_payload["injectSteps"][0]["systemMessage"]["metadata"]["user_markdown"],
            "## Next",
        )

    def test_arg_and_command_helpers(self) -> None:
        self.assertEqual(first_not_none(None, 0, 5), 0)
        self.assertIsNone(first_not_none(None, None))

        payload = {"empty": "   ", "command": "  ls -la  ", "cmd": "other"}
        self.assertEqual(first_str_arg(payload, "empty", "command", "cmd"), "ls -la")
        self.assertEqual(first_str_arg(payload, ("empty", "cmd")), "other")
        self.assertEqual(first_str_arg(None, "a"), "")

        raw_cmd = (
            "<USER_REQUEST>  /Gravity   "
            "<ADDITIONAL_METADATA>secret</ADDITIONAL_METADATA>"
            "<USER_SETTINGS_CHANGE>x</USER_SETTINGS_CHANGE></USER_REQUEST>"
        )
        self.assertEqual(normalize_command(raw_cmd), "/gravity")
        self.assertEqual(normalize_command(123), "")  # type: ignore[arg-type]

        self.assertTrue(is_initial_invocation({}))
        self.assertTrue(is_initial_invocation({"invocationNum": 0}))
        self.assertFalse(is_initial_invocation({"invocationNum": 1}))
        self.assertFalse(is_initial_invocation({"invocationNum": False}))
        self.assertFalse(is_initial_invocation({"invocationNum": True}))
        self.assertFalse(is_initial_invocation("not-a-dict"))

    def test_workspace_brain_and_conversation_resolution(self) -> None:
        with mock.patch.dict(os.environ, {"GRAVITY_WORKSPACE": "/ws/env"}, clear=True):
            self.assertEqual(resolve_workspace_root({"cwd": " /ws/cwd "}), Path("/ws/cwd"))
            self.assertEqual(
                resolve_workspace_root({"workspacePaths": ["/ws/list", "/ws/second"]}),
                Path("/ws/list"),
            )
            self.assertEqual(resolve_workspace_root({}), Path("/ws/env"))
            self.assertEqual(
                resolve_workspace_root({}, env_var="CUSTOM_WS", fallback_cwd=True),
                Path.cwd(),
            )
            self.assertIsNone(resolve_workspace_root({}, env_var="CUSTOM_WS", fallback_cwd=False))

        transcript = "/data/brain/conv-uuid-123/.system_generated/logs/transcript.jsonl"
        self.assertEqual(
            resolve_brain_dir({"transcriptPath": transcript}),
            Path("/data/brain"),
        )
        self.assertEqual(
            resolve_conversation_id({"transcript_path": transcript}),
            "conv-uuid-123",
        )
        self.assertEqual(
            resolve_conversation_id({"sessionId": "sess-9", "transcriptPath": transcript}),
            "sess-9",
        )
        with mock.patch.dict(os.environ, {"ANTIGRAVITY_BRAIN_DIR": "/env/brain"}, clear=True):
            self.assertEqual(resolve_brain_dir({}), Path("/env/brain"))
            self.assertIsNone(resolve_conversation_id({}))


if __name__ == "__main__":
    unittest.main()
