"""Argument parsing and entry point for inftop."""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time

from inftop import __version__
from inftop.config import config_path, init_config, load_config_file, resolve_settings


def install_signal_handlers() -> None:
    """SIGINT/SIGTERM → SystemExit(0) so finally-blocks restore/cleanup cleanly."""

    def _handler(signum, frame):  # noqa: ARG001
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="inftop",
        description="Top-like monitor for Strata inference + AMD GPU",
    )
    p.add_argument(
        "-d",
        type=float,
        default=None,
        metavar="SECS",
        help="refresh interval (default 1, or config interval)",
    )
    p.add_argument("--once", action="store_true", help="single snapshot then exit")
    p.add_argument("--json", action="store_true", help="with --once, print JSON")
    p.add_argument(
        "-r",
        "--remote",
        default=None,
        metavar="HOST",
        help="run probes over persistent ssh ControlMaster to HOST",
    )
    p.add_argument(
        "--strata-url",
        default=None,
        metavar="URL",
        help="Strata HTTP base (default http://127.0.0.1:8080)",
    )
    p.add_argument(
        "--tz",
        default=None,
        metavar="ZONE",
        help="IANA timezone for displayed times (default: system local)",
    )
    p.add_argument(
        "--frames",
        type=int,
        metavar="N",
        help="collect N frames (for --dump)",
    )
    p.add_argument(
        "--dump",
        action="store_true",
        help="render frames as text without a TTY",
    )
    p.add_argument(
        "--init-config",
        action="store_true",
        help="write commented example config.toml and exit",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="with --init-config, overwrite an existing config file",
    )
    p.add_argument("--version", action="version", version=f"inftop {__version__}")

    sub = p.add_subparsers(dest="cmd")
    stats = sub.add_parser("stats", help="print SQLite history aggregates")
    stats.add_argument(
        "--since",
        default="24h",
        help="lookback window (e.g. 24h, 7d, 30m)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.init_config:
        dest = config_path()
        try:
            init_config(dest, force=args.force)
        except FileExistsError as e:
            print(str(e), file=sys.stderr)
            return 1
        print(f"Wrote {dest}")
        return 0

    if args.cmd == "stats":
        from inftop.history import print_stats

        return print_stats(since=args.since)

    settings = resolve_settings(
        cli={
            "strata_url": args.strata_url,
            "remote": args.remote,
            "tz": args.tz,
            "d": args.d,
        },
        env=dict(os.environ),
        config=load_config_file(),
    )

    from inftop.collector import Collector, snapshot_to_json
    from inftop.ui import dump_frames, run_curses

    install_signal_handlers()
    interval = max(0.2, float(settings["interval"]))
    collector = Collector(
        remote=settings["remote_host"],
        strata_url=settings["strata_url"],
        listen_port=settings["listen_port"],
        tz_name=settings["tz"],
        interval_s=interval,
        history_window=int(settings["history_window"]),
        ollama_url=settings["ollama_url"],
        container_name=settings["container_name"],
        api_key_file=settings["api_key_file"],
        alert_thresholds=settings["alerts"],
    )
    try:
        if args.frames is not None or args.dump:
            n = args.frames or 1
            snaps = []
            for i in range(n):
                snaps.append(collector.collect())
                if i + 1 < n:
                    time.sleep(max(0.1, interval))
            if args.dump or args.frames is not None:
                print(dump_frames(snaps, tz_name=settings["tz"]))
            return 0

        if args.once:
            snap = collector.collect()
            if args.json:
                print(snapshot_to_json(snap))
            else:
                print(dump_frames([snap], tz_name=settings["tz"]))
            return 0

        return run_curses(collector, interval=interval, tz_name=settings["tz"])
    except (KeyboardInterrupt, SystemExit) as e:
        # SystemExit(0) from signal handlers; KeyboardInterrupt as fallback.
        if isinstance(e, SystemExit):
            code = e.code
            if code is None or code == 0:
                return 0
            if isinstance(code, int):
                return code
            return 1
        return 0
    finally:
        collector.close()


if __name__ == "__main__":
    raise SystemExit(main())
