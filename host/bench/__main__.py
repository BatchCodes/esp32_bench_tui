#!/usr/bin/env python3
"""Command line entry point of the bench host tool.

Run from the repository with ./bench, or with python3 -m bench when host/ is
on the Python path.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

from bench.config import DEFAULT_BAUD, DEFAULT_CHIP, GENERIC_PREFIX, ConfigError, empty_project, list_boards, list_chips, load_board, load_project, with_all_inputs

DEFAULT_CONFIG = Path("bench.yaml")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="bench", description="Terminal UI for bench tests of ESP32 boards.")
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        help="project configuration file. Without it, bench.yaml if it exists, else open mode with no devices",
    )
    parser.add_argument("--board", help="board profile for open mode, for example olimex_esp32_poe_iso")
    parser.add_argument("--chip", choices=list_chips(), help="generic board of this chip for open mode")
    parser.add_argument(
        "--empty",
        action="store_true",
        help="open mode with no pins. Without it, open mode adds an input on each free GPIO",
    )
    parser.add_argument("--port", "-p", help="serial port, for example /dev/ttyUSB0")
    parser.add_argument(
        "--listen",
        action="store_true",
        help="log mode with no configuration: show the serial output of any firmware, send nothing",
    )
    parser.add_argument("--baud", type=int, help="baud rate (default: 115200, or the configuration value)")
    parser.add_argument("--sim", action="store_true", help="use a simulated board")
    parser.add_argument("--check", action="store_true", help="check the configuration, print the result and exit")
    parser.add_argument("--list-boards", action="store_true", help="list the board profiles and exit")
    return parser.parse_args(argv)


def print_boards() -> None:
    for name in list_boards():
        board = load_board(name)
        verified = "" if board.verified else "  (not verified)"
        print(f"{name:34} {board.title} [{board.chip.title}]{verified}")


class Cancelled(Exception):
    """The user quit the board picker."""


def choose_board(args: argparse.Namespace, purpose: str) -> tuple[str, bool]:
    """The board name, and True when the TUI follows the chip that the agent
    reports. Shows the board picker when no board is given and a terminal is
    there."""
    if args.board:
        return args.board, False
    if args.chip:
        return f"{GENERIC_PREFIX}{args.chip}", False
    if args.check or not (sys.stdin.isatty() and sys.stdout.isatty()):
        return f"{GENERIC_PREFIX}{DEFAULT_CHIP}", True

    from bench.tui.picker import board_from_choice, pick_board

    choice = pick_board(purpose)
    if choice is None:
        raise Cancelled
    return board_from_choice(choice)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.list_boards:
        print_boards()
        return 0
    auto_board = False
    try:
        if args.listen and args.config is None:
            board, _detect = choose_board(args, "listen mode")
            config = empty_project(board, DEFAULT_CONFIG, mode="log", baud=args.baud or DEFAULT_BAUD)
        elif args.config is not None:
            config = load_project(args.config)
        elif DEFAULT_CONFIG.exists() and not (args.board or args.chip):
            config = load_project(DEFAULT_CONFIG)
        else:
            board, auto_board = choose_board(args, "open mode")
            config = empty_project(board, DEFAULT_CONFIG)
            if not args.empty:
                config = with_all_inputs(config)
        if args.baud is not None and config.baud != args.baud:
            config = dataclasses.replace(config, baud=args.baud)
    except Cancelled:
        return 0
    except ConfigError as error:
        print(f"error: {error.source}:", file=sys.stderr)
        for line in error.errors:
            print(f"  - {line}", file=sys.stderr)
        return 1
    if args.check:
        print(f"{config.path}: OK, board {config.board.title}, mode {config.mode}, {len(config.devices)} devices")
        for warning in config.warnings:
            print(f"  warning: {warning}")
        return 0

    from bench.link import LinkError, create_link
    from bench.tui.app import BenchApp

    try:
        link = create_link(config, port=args.port, simulate=args.sim)
    except LinkError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    BenchApp(config, link, auto_board=auto_board, watch_all=not args.empty).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
