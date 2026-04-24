"""CLI entry point for token-usage command."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from token_monitor.context import analyze_context, context_report
from token_monitor.parser import (
    find_all_sessions,
    find_latest_session,
    find_project_log_dir,
    parse_last_turn,
    parse_session,
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="token-usage",
        description="Analyze Claude Code session token usage from JSONL logs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # session subcommand
    sp_session = subparsers.add_parser(
        "session", help="Analyze a single session"
    )
    sp_session.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Path to JSONL file (default: most recent in current project)",
    )
    sp_session.add_argument(
        "--no-log",
        action="store_true",
        help="Don't append to ~/.claude/token-usage-log.md",
    )

    # project subcommand
    sp_project = subparsers.add_parser(
        "project", help="Summarize all sessions in a project"
    )
    sp_project.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Path to project log directory (default: derived from CWD)",
    )

    # context subcommand
    sp_context = subparsers.add_parser(
        "context", help="Analyze current context window usage"
    )
    sp_context.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Path to JSONL file (default: most recent in current project)",
    )
    sp_context.add_argument(
        "-b",
        "--brief",
        action="store_true",
        help="Compact ~5-line output suitable for embedding in other tools",
    )

    args = parser.parse_args(argv)

    if args.command == "session":
        _cmd_session(args)
    elif args.command == "project":
        _cmd_project(args)
    elif args.command == "context":
        _cmd_context(args)


def _cmd_session(args: argparse.Namespace) -> None:
    from token_monitor.report import append_to_log, session_report

    jsonl_path = args.path

    if jsonl_path is None:
        log_dir = find_project_log_dir()
        if log_dir is None:
            print("Error: could not find project log directory for CWD.", file=sys.stderr)
            print("Provide an explicit path: token-usage session <path.jsonl>", file=sys.stderr)
            sys.exit(1)
        jsonl_path = find_latest_session(log_dir)
        if jsonl_path is None:
            print(f"Error: no JSONL files found in {log_dir}", file=sys.stderr)
            sys.exit(1)

    stats = parse_session(jsonl_path)
    print(session_report(stats))

    if not args.no_log:
        log_path = append_to_log(stats)
        print(f"Logged to {log_path}")


def _cmd_context(args: argparse.Namespace) -> None:
    jsonl_path = args.path

    if jsonl_path is None:
        log_dir = find_project_log_dir()
        if log_dir is None:
            print("Error: could not find project log directory for CWD.", file=sys.stderr)
            print("Provide an explicit path: token-usage context <path.jsonl>", file=sys.stderr)
            sys.exit(1)
        jsonl_path = find_latest_session(log_dir)
        if jsonl_path is None:
            print(f"Error: no JSONL files found in {log_dir}", file=sys.stderr)
            sys.exit(1)
        project_dir = log_dir
    else:
        project_dir = str(Path(jsonl_path).parent)

    usage = parse_last_turn(jsonl_path)
    snapshot = analyze_context(usage, project_dir, brief=args.brief)
    print(context_report(snapshot, brief=args.brief))


def _cmd_project(args: argparse.Namespace) -> None:
    from token_monitor.report import project_report

    log_dir = args.path

    if log_dir is None:
        log_dir = find_project_log_dir()
        if log_dir is None:
            print("Error: could not find project log directory for CWD.", file=sys.stderr)
            print("Provide an explicit path: token-usage project <path>", file=sys.stderr)
            sys.exit(1)

    session_paths = find_all_sessions(log_dir)
    if not session_paths:
        print(f"No sessions found in {log_dir}")
        return

    sessions = [parse_session(p) for p in session_paths]
    # Filter out sessions with no turns
    sessions = [s for s in sessions if s.turns]
    print(project_report(sessions))
