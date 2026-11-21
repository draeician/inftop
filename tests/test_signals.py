"""Clean exit on SIGINT/SIGTERM without traceback."""

from __future__ import annotations

import signal
import unittest
from unittest import mock

from inftop.cli import install_signal_handlers, main


class TestCleanExit(unittest.TestCase):
    def test_keyboard_interrupt_exits_zero(self):
        with mock.patch("inftop.cli.build_parser") as bp:
            args = mock.Mock(
                cmd=None,
                frames=None,
                dump=False,
                once=True,
                json=False,
                remote=None,
                strata_url=None,
                tz=None,
                d=None,
                init_config=False,
                force=False,
            )
            bp.return_value.parse_args.return_value = args
            with mock.patch("inftop.collector.Collector") as C:
                inst = C.return_value
                inst.collect.side_effect = KeyboardInterrupt()
                code = main([])
                self.assertEqual(code, 0)
                inst.close.assert_called()

    def test_sigterm_handler_raises_clean_exit(self):
        raised = []

        def boom(signum, frame):
            raised.append(signum)
            raise SystemExit(0)

        # install_signal_handlers should register callables that exit 0
        with mock.patch("signal.signal") as sig:
            install_signal_handlers()
            self.assertTrue(sig.called)
            # Invoke the registered handler for SIGTERM
            for call in sig.call_args_list:
                if call.args[0] == signal.SIGTERM:
                    handler = call.args[1]
                    with self.assertRaises(SystemExit) as cm:
                        handler(signal.SIGTERM, None)
                    self.assertEqual(cm.exception.code, 0)


class TestRemoteAlias(unittest.TestCase):
    def test_short_r_alias(self):
        from inftop.cli import build_parser

        args = build_parser().parse_args(["-r", "gpu-box", "--once"])
        self.assertEqual(args.remote, "gpu-box")
        self.assertTrue(args.once)


if __name__ == "__main__":
    unittest.main()
