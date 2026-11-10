"""Bounded WinError 10055 accept-loop retry, source-bound negative QA.

The test calls the actual function from 003_web_server.py using the existing
phase7 service import path, not a duplicate guessed implementation.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, Mock

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("legal_kb_server_bounded_retry", HERE / "003_web_server.py")
SERVER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SERVER
SPEC.loader.exec_module(SERVER)


def win10055() -> OSError:
    problem = OSError("Windows socket buffer unavailable")
    problem.winerror = 10055
    return problem


class Socket10055BoundedRetryTests(unittest.TestCase):
    def test_public_windows_transient_two_failures_recovers(self):
        server = Mock()
        server.serve_forever.side_effect = [win10055(), win10055(), None]
        delays = []
        with patch.object(SERVER.os, "name", "nt"):
            SERVER._serve_with_bounded_public_win10055_retry(
                server, public_demo=True, pause=delays.append
            )
        self.assertEqual(server.serve_forever.call_count, 3)
        self.assertEqual(delays, [1, 2])

    def test_public_windows_permanent_resource_failure_is_bounded(self):
        server = Mock()
        server.serve_forever.side_effect = [win10055()] * 5
        delays = []
        with patch.object(SERVER.os, "name", "nt"):
            with self.assertRaises(OSError) as error:
                SERVER._serve_with_bounded_public_win10055_retry(
                    server, public_demo=True, pause=delays.append
                )
        self.assertEqual(getattr(error.exception, "winerror", None), 10055)
        self.assertEqual(server.serve_forever.call_count, 4)
        self.assertEqual(delays, [1, 2, 4])

    def test_private_runtime_does_not_retry(self):
        server = Mock()
        server.serve_forever.side_effect = win10055()
        delays = []
        with patch.object(SERVER.os, "name", "nt"):
            with self.assertRaises(OSError):
                SERVER._serve_with_bounded_public_win10055_retry(
                    server, public_demo=False, pause=delays.append
                )
        self.assertEqual(server.serve_forever.call_count, 1)
        self.assertEqual(delays, [])

    def test_non_windows_does_not_retry(self):
        server = Mock()
        server.serve_forever.side_effect = win10055()
        delays = []
        with patch.object(SERVER.os, "name", "posix"):
            with self.assertRaises(OSError):
                SERVER._serve_with_bounded_public_win10055_retry(
                    server, public_demo=True, pause=delays.append
                )
        self.assertEqual(delays, [])

    def test_unrelated_socket_error_not_swallowed(self):
        server = Mock()
        server.serve_forever.side_effect = OSError("different I/O error")
        delays = []
        with patch.object(SERVER.os, "name", "nt"):
            with self.assertRaises(OSError):
                SERVER._serve_with_bounded_public_win10055_retry(
                    server, public_demo=True, pause=delays.append
                )
        self.assertEqual(delays, [])

    def test_ctrl_c_propagates_for_existing_main_handler(self):
        server = Mock()
        server.serve_forever.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            SERVER._serve_with_bounded_public_win10055_retry(
                server, public_demo=True, pause=lambda _: None
            )
        self.assertEqual(server.serve_forever.call_count, 1)

    def test_clean_exit_does_not_delay_or_restart(self):
        server = Mock()
        server.serve_forever.return_value = None
        delays = []
        SERVER._serve_with_bounded_public_win10055_retry(
            server, public_demo=True, pause=delays.append
        )
        self.assertEqual(server.serve_forever.call_count, 1)
        self.assertEqual(delays, [])


if __name__ == "__main__":
    unittest.main()
