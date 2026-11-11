"""Load pages, chat messages and tickets from JSON exports into plain records.

The loaders accept the common shapes of each export (a bare list, or an object
wrapping the list) and tolerate missing optional fields.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc
_DURATION = re.compile(r"^(\d+)\s*([mhdw])$")
_UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


class InputError(ValueError):
    """Raised for input the user can fix: bad file, bad timestamp, bad duration."""


def parse_duration(text: str) -> timedelta:
    m = _DURATION.match(text.strip().lower())
    if not m or int(m.group(1)) == 0:
        raise InputError(f"invalid duration {text!r}: use forms like 90m, 12h, 2d or 1w")
    return timedelta(**{_UNITS[m.group(2)]: int(m.group(1))})


def parse_time(value: Any) -> datetime | None:
    """Parse ISO 8601 text or epoch seconds (number or numeric string). Naive times are UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), UTC)
    text = str(value).strip()
    try:
        return datetime.fromtimestamp(float(text), UTC)
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise InputError(f"unrecognised timestamp {value!r}") from None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC)


@dataclass
class Page:
    id: str
    title: str
    service: str
    urgency: str  # high | low
    status: str  # triggered | acknowledged | resolved
    created: datetime
    resolved: datetime | None = None
    url: str = ""

    @property
    def open(self) -> bool:
        return self.status != "resolved"

    @property
    def minutes(self) -> float | None:
        return (self.resolved - self.created).total_seconds() / 60 if self.resolved else None


@dataclass
class Message:
    ts: datetime
    user: str
    text: str
    channel: str = ""
    thread: str = ""  # id of the thread root; equals own id for a root message
    url: str = ""


@dataclass
class Ticket:
    key: str
    title: str
    status: str
    priority: str = ""
    assignee: str = ""
    created: datetime | None = None
    updated: datetime | None = None
    url: str = ""

    @property
    def open(self) -> bool:
        return self.status.strip().lower() not in CLOSED_STATUSES

    @property
    def urgent(self) -> bool:
        return self.priority.strip().lower() in URGENT_PRIORITIES


CLOSED_STATUSES = {"done", "closed", "resolved", "cancelled", "canceled", "won't fix", "wont fix", "duplicate"}
URGENT_PRIORITIES = {"p0", "p1", "sev0", "sev1", "critical", "blocker", "highest", "urgent", "high"}


@dataclass
class Shift:
    pages: list[Page] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    tickets: list[Ticket] = field(default_factory=list)


def _records(path: Path, *keys: str) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc.strerror}") from None
    except json.JSONDecodeError as exc:
        raise InputError(f"{path} is not valid JSON: {exc}") from None
    if isinstance(data, dict):
        data = next((data[k] for k in keys if isinstance(data.get(k), list)), None)
    if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
        raise InputError(f"{path}: expected a JSON list of objects (or an object with one of: {', '.join(keys)})")
    return data


def _name(value: Any) -> str:
    """Exports often nest names: {"summary": "checkout-api"} or {"name": ...}."""
    if isinstance(value, dict):
        return str(value.get("summary") or value.get("name") or value.get("displayName") or "")
    return "" if value is None else str(value)


def _first(record: dict, *keys: str) -> Any:
    return next((record[k] for k in keys if record.get(k) not in (None, "")), None)


def load_pages(path: str | Path) -> list[Page]:
    pages = []
    for i, r in enumerate(_records(Path(path), "incidents", "pages")):
        created = parse_time(_first(r, "created_at", "created", "triggered_at"))
        if created is None:
            raise InputError(f"{path}: page #{i + 1} has no created_at")
        status = str(r.get("status") or "triggered").lower()
        resolved = parse_time(_first(r, "resolved_at", "resolved"))
        if status == "resolved" and resolved is None:
            resolved = parse_time(r.get("last_status_change_at"))
        pages.append(Page(
            id=str(_first(r, "id", "incident_number", "number") or i + 1),
            title=str(_first(r, "title", "summary", "description") or "(untitled page)"),
            service=_name(r.get("service")) or "unknown",
            urgency=str(r.get("urgency") or "high").lower(),
            status=status, created=created, resolved=resolved,
            url=str(_first(r, "html_url", "url") or ""),
        ))
    return sorted(pages, key=lambda p: p.created)


def load_messages(path: str | Path) -> list[Message]:
    messages = []
    for i, r in enumerate(_records(Path(path), "messages")):
        ts = parse_time(r.get("ts"))
        if ts is None:
            raise InputError(f"{path}: message #{i + 1} has no ts")
        messages.append(Message(
            ts=ts,
            user=str(_first(r, "user_name", "username", "user") or "unknown"),
            text=str(r.get("text") or "").strip(),
            channel=str(r.get("channel") or "").lstrip("#"),
            thread=str(r.get("thread_ts") or r.get("ts")),
            url=str(_first(r, "permalink", "url") or ""),
        ))
    return sorted(messages, key=lambda m: m.ts)


def load_tickets(path: str | Path) -> list[Ticket]:
    tickets = []
    for i, r in enumerate(_records(Path(path), "issues", "tickets")):
        r = {**r.get("fields", {}), **r} if isinstance(r.get("fields"), dict) else r
        tickets.append(Ticket(
            key=str(_first(r, "key", "id") or f"ticket-{i + 1}"),
            title=str(_first(r, "title", "summary") or "(untitled ticket)"),
            status=_name(r.get("status")) or "open",
            priority=_name(r.get("priority")),
            assignee=_name(r.get("assignee")),
            created=parse_time(_first(r, "created_at", "created")),
            updated=parse_time(_first(r, "updated_at", "updated")),
            url=str(_first(r, "url", "html_url") or ""),
        ))
    return tickets


def load_directory(path: str | Path) -> Shift:
    """Load ``pages.json``, ``slack.json`` and ``tickets.json`` from a directory; each is optional."""
    root = Path(path)
    if not root.is_dir():
        raise InputError(f"not a directory: {root}")
    shift = Shift()
    if (root / "pages.json").exists():
        shift.pages = load_pages(root / "pages.json")
    if (root / "slack.json").exists():
        shift.messages = load_messages(root / "slack.json")
    if (root / "tickets.json").exists():
        shift.tickets = load_tickets(root / "tickets.json")
    return shift
