"""Turn a shift's raw records into the facts a handoff note needs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median

from .sources import Message, Page, Shift, Ticket

# Phrases that mark a chat message as something the next engineer should know.
WATCH_PATTERNS = [
    r"keep(ing)? an eye", r"\bwatch(ing)?\b", r"follow[- ]?up", r"\btodo\b", r"heads[- ]up",
    r"hand[- ]?(off|over)", r"next shift", r"\btomorrow\b", r"work[- ]?around", r"\btemp(orary|orarily)?\b",
    r"not (yet )?fixed", r"still (seeing|happening|failing|broken|open|investigating)", r"root cause (is )?unknown",
    r"\bsilenced?\b", r"\bsnoozed?\b", r"needs? (a )?(fix|review|restart|owner)",
]
_WATCH = re.compile("|".join(WATCH_PATTERNS), re.I)
_VARIABLE = re.compile(r"\b[0-9a-f]{8,}\b|\d+(\.\d+)*", re.I)
FLAP_MINUTES = 10
RECENT_WINDOW = timedelta(hours=2)


def alert_key(title: str) -> str:
    """Normalise a page title so repeats of one alert group together (ids and numbers removed)."""
    return re.sub(r"\s+", " ", _VARIABLE.sub("N", title)).strip().lower()


@dataclass
class FlakyAlert:
    service: str
    title: str
    count: int
    first: datetime
    last: datetime
    median_minutes: float | None
    flapping: bool  # most firings cleared within FLAP_MINUTES
    still_open: bool


@dataclass
class Thread:
    channel: str
    starter: str
    text: str
    replies: int
    participants: list[str]
    started: datetime
    url: str = ""


@dataclass
class Report:
    start: datetime
    end: datetime
    pages: list[Page] = field(default_factory=list)  # fired in the window
    carried_over: list[Page] = field(default_factory=list)  # fired earlier, still open
    open_pages: list[Page] = field(default_factory=list)
    open_tickets: list[Ticket] = field(default_factory=list)
    closed_tickets: list[Ticket] = field(default_factory=list)
    flaky: list[FlakyAlert] = field(default_factory=list)
    recently_resolved: list[Page] = field(default_factory=list)
    watch_messages: list[Message] = field(default_factory=list)
    threads: list[Thread] = field(default_factory=list)
    by_service: list[tuple[str, int]] = field(default_factory=list)
    median_minutes_to_resolve: float | None = None

    @property
    def quiet(self) -> bool:
        return not (self.pages or self.carried_over or self.open_tickets or self.closed_tickets
                    or self.watch_messages or self.threads)


def _in_window(ts: datetime | None, start: datetime, end: datetime) -> bool:
    return ts is not None and start <= ts <= end


def find_flaky(pages: list[Page], threshold: int) -> list[FlakyAlert]:
    groups: dict[tuple[str, str], list[Page]] = {}
    for p in pages:
        groups.setdefault((p.service, alert_key(p.title)), []).append(p)
    flaky = []
    for (service, _), group in groups.items():
        if len(group) < threshold:
            continue
        durations = [p.minutes for p in group if p.minutes is not None]
        quick = [d for d in durations if d <= FLAP_MINUTES]
        flaky.append(FlakyAlert(
            service=service, title=group[-1].title, count=len(group),
            first=group[0].created, last=group[-1].created,
            median_minutes=median(durations) if durations else None,
            flapping=len(quick) * 2 > len(group),
            still_open=any(p.open for p in group),
        ))
    return sorted(flaky, key=lambda f: (-f.count, f.service, f.title))


def find_threads(messages: list[Message], limit: int = 3) -> list[Thread]:
    grouped: dict[tuple[str, str], list[Message]] = {}
    for m in messages:
        grouped.setdefault((m.channel, m.thread), []).append(m)
    threads = []
    for (channel, _), msgs in grouped.items():
        if len(msgs) < 3:
            continue
        root = msgs[0]
        people = list(dict.fromkeys(m.user for m in msgs))
        threads.append(Thread(channel, root.user, root.text, len(msgs) - 1, people, root.ts, root.url))
    return sorted(threads, key=lambda t: (-t.replies, t.started))[:limit]


def analyze(shift: Shift, start: datetime, end: datetime, flaky_threshold: int = 2) -> Report:
    report = Report(start=start, end=end)
    report.pages = [p for p in shift.pages if _in_window(p.created, start, end)]
    report.carried_over = [p for p in shift.pages if p.created < start and p.open]
    report.open_pages = sorted(
        [p for p in report.carried_over + report.pages if p.open],
        key=lambda p: (p.urgency != "high", p.created),
    )
    touched = [t for t in shift.tickets
               if _in_window(t.updated, start, end) or _in_window(t.created, start, end)
               or (t.updated is None and t.created is None)]
    report.open_tickets = sorted((t for t in touched if t.open), key=lambda t: (not t.urgent, t.key))
    report.closed_tickets = sorted((t for t in touched if not t.open), key=lambda t: t.key)

    report.flaky = find_flaky(report.pages, max(2, flaky_threshold))
    flaky_keys = {(f.service, alert_key(f.title)) for f in report.flaky}
    report.recently_resolved = [
        p for p in report.pages
        if not p.open and p.urgency == "high" and p.resolved and p.resolved >= end - RECENT_WINDOW
        and (p.service, alert_key(p.title)) not in flaky_keys
    ]

    in_window = [m for m in shift.messages if _in_window(m.ts, start, end)]
    report.watch_messages = [m for m in in_window if m.text and _WATCH.search(m.text)]
    report.threads = find_threads(in_window)

    counts: dict[str, int] = {}
    for p in report.pages:
        counts[p.service] = counts.get(p.service, 0) + 1
    report.by_service = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    durations = [p.minutes for p in report.pages if p.minutes is not None]
    report.median_minutes_to_resolve = median(durations) if durations else None
    return report
