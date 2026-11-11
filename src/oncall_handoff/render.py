"""Render a report as Markdown, JSON-ready data, or Slack mrkdwn."""

from __future__ import annotations

import re
from dataclasses import asdict
from datetime import datetime

from .analyze import Report
from .sources import Page, Ticket


def _t(dt: datetime) -> str:
    return dt.strftime("%a %H:%M")


def _mins(minutes: float | None) -> str:
    if minutes is None:
        return "n/a"
    if minutes < 90:
        return f"{minutes:.0f} min"
    return f"{minutes / 60:.1f} h"


def _link(text: str, url: str) -> str:
    return f"[{text}]({url})" if url else text


def _short(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _page_line(p: Page, end: datetime, carried_over: bool = False) -> str:
    age = _mins((end - p.created).total_seconds() / 60)
    extra = ", carried over from before this shift" if carried_over else ""
    return (f"- **{p.service}**: {_link(p.title, p.url)} ({p.urgency} urgency, {p.status}, "
            f"open {age}, since {_t(p.created)}{extra})")


def _ticket_line(t: Ticket) -> str:
    bits = [b for b in (t.status, t.priority, f"assignee {t.assignee}" if t.assignee else "unassigned") if b]
    return f"- {_link(t.key, t.url)}: {t.title} ({', '.join(bits)})"


def to_markdown(report: Report, title: str = "On-call handoff") -> str:
    r = report
    out = [f"# {title}", "",
           f"Shift window: {r.start:%Y-%m-%d %H:%M} to {r.end:%Y-%m-%d %H:%M} UTC", ""]
    if r.quiet:
        out += ["Quiet shift: no pages, no ticket activity and nothing flagged in chat.", ""]
        return "\n".join(out)

    high = sum(p.urgency == "high" for p in r.pages)
    out += [f"**{len(r.pages)} pages** ({high} high urgency), **{len(r.open_pages)} still open**, "
            f"**{len(r.flaky)} flaky alert{'s' if len(r.flaky) != 1 else ''}**, "
            f"**{len(r.open_tickets)} open ticket{'s' if len(r.open_tickets) != 1 else ''}**.", ""]

    out += ["## Still open", ""]
    if r.open_pages or r.open_tickets:
        out += [_page_line(p, r.end, p in r.carried_over) for p in r.open_pages]
        out += [_ticket_line(t) for t in r.open_tickets]
    else:
        out.append("Nothing open. All pages are resolved and no tickets were left open.")
    out.append("")

    if r.flaky:
        out += ["## Flaky or noisy", ""]
        for f in r.flaky:
            notes = [f"fired {f.count} times between {_t(f.first)} and {_t(f.last)}",
                     f"median time to clear {_mins(f.median_minutes)}"]
            if f.flapping:
                notes.append("mostly self-clearing: likely flapping, consider tuning the threshold")
            if f.still_open:
                notes.append("currently firing")
            out.append(f"- **{f.service}**: {f.title} ({'; '.join(notes)})")
        out.append("")

    if r.watch_messages or r.recently_resolved:
        out += ["## Watch", ""]
        for p in r.recently_resolved:
            out.append(f"- **{p.service}**: {_link(p.title, p.url)} was resolved at {_t(p.resolved)}, "
                       "shortly before handoff. It may recur.")
        for m in r.watch_messages:
            where = f" in #{m.channel}" if m.channel else ""
            out.append(f"- {m.user}{where}, {_t(m.ts)}: {_link(_short(m.text), m.url)}")
        out.append("")

    resolved = [p for p in r.pages if not p.open]
    if resolved:
        out += ["## Resolved this shift", ""]
        out += [f"- {_t(p.created)} **{p.service}**: {_link(p.title, p.url)} (resolved in {_mins(p.minutes)})"
                for p in resolved]
        out.append("")

    if r.closed_tickets:
        out += ["## Tickets closed", ""] + [_ticket_line(t) for t in r.closed_tickets] + [""]

    if r.threads:
        out += ["## Busiest threads", ""]
        for th in r.threads:
            where = f"#{th.channel}, " if th.channel else ""
            out.append(f"- {where}{_t(th.started)}, {th.replies} replies from {len(th.participants)} people: "
                       f"{_link(_short(th.text, 120), th.url)}")
        out.append("")

    if r.pages:
        out += ["## Numbers", "",
                "- Pages by service: " + ", ".join(f"{s} {n}" for s, n in r.by_service),
                f"- Median time to resolve: {_mins(r.median_minutes_to_resolve)}", ""]
    return "\n".join(out)


def to_dict(report: Report) -> dict:
    def clean(value):
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(v) for v in value]
        return value

    return clean(asdict(report))


def to_slack(markdown: str) -> str:
    """Convert the note's Markdown subset to Slack mrkdwn."""
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<\2|\1>", markdown)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"^#{1,6}\s+(.*)$", r"*\1*", text, flags=re.M)
    text = re.sub(r"^- ", "• ", text, flags=re.M)
    return text.strip() + "\n"
