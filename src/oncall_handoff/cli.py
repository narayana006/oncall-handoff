"""Command-line interface for oncall-handoff."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .analyze import analyze
from .render import to_dict, to_markdown, to_slack
from .slack import SlackError, http_transport, post_message
from .sources import InputError, Shift, load_directory, load_messages, load_pages, load_tickets, parse_duration, parse_time


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="oncall-handoff",
        description="Summarize an on-call shift from exported pages, chat messages and tickets.",
    )
    p.add_argument("--version", action="version", version=f"oncall-handoff {__version__}")
    src = p.add_argument_group("input (JSON exports)")
    src.add_argument("--input", metavar="DIR", help="directory with pages.json, slack.json and/or tickets.json")
    src.add_argument("--pages", metavar="FILE", help="pager incidents export")
    src.add_argument("--slack", metavar="FILE", help="chat messages export")
    src.add_argument("--tickets", metavar="FILE", help="tickets export")
    win = p.add_argument_group("time window")
    win.add_argument("--since", default="24h", help="how far back the shift goes, e.g. 12h, 24h, 7d (default 24h)")
    win.add_argument("--now", metavar="TIME", help="end of the shift as ISO 8601 (default: the current time)")
    out = p.add_argument_group("output")
    out.add_argument("--format", choices=["markdown", "json"], default="markdown")
    out.add_argument("--output", "-o", metavar="FILE", help="write the note to a file instead of stdout")
    out.add_argument("--title", default="On-call handoff")
    out.add_argument("--flaky-threshold", type=int, default=2, metavar="N",
                     help="an alert that fired at least N times in the window is flaky (default 2)")
    out.add_argument("--post", metavar="CHANNEL", help="Slack channel to post to; previews only unless --send")
    out.add_argument("--send", action="store_true",
                     help="with --post, really send the message (needs SLACK_BOT_TOKEN)")
    return p


def run(argv: list[str] | None = None, *, transport=http_transport, env=os.environ,
        stdout=None, stderr=None) -> int:
    stdout, stderr = stdout or sys.stdout, stderr or sys.stderr
    parser = build_parser()
    args = parser.parse_args(argv)
    if not (args.input or args.pages or args.slack or args.tickets):
        parser.error("no input: pass --input DIR or at least one of --pages, --slack, --tickets")
    if args.send and not args.post:
        parser.error("--send needs --post CHANNEL")
    try:
        end = parse_time(args.now) if args.now else datetime.now(timezone.utc)
        start = end - parse_duration(args.since)
        shift = load_directory(args.input) if args.input else Shift()
        if args.pages:
            shift.pages = load_pages(args.pages)
        if args.slack:
            shift.messages = load_messages(args.slack)
        if args.tickets:
            shift.tickets = load_tickets(args.tickets)
    except InputError as exc:
        print(f"oncall-handoff: {exc}", file=stderr)
        return 2

    report = analyze(shift, start, end, flaky_threshold=args.flaky_threshold)
    markdown = to_markdown(report, title=args.title)
    text = json.dumps(to_dict(report), indent=2) + "\n" if args.format == "json" else markdown

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Wrote {args.output}", file=stderr)
    elif not args.post:
        stdout.write(text)

    if args.post:
        slack_text = to_slack(markdown)
        if not args.send:
            print(f"Dry run: would post the following to {args.post}. Add --send to post it.\n", file=stderr)
            stdout.write(slack_text)
            return 0
        try:
            post_message(args.post, slack_text, env.get("SLACK_BOT_TOKEN", ""), transport)
        except SlackError as exc:
            print(f"oncall-handoff: {exc}", file=stderr)
            return 1
        print(f"Posted handoff note to {args.post}", file=stderr)
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
