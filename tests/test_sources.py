import json
from datetime import timedelta

import pytest

from conftest import utc
from oncall_handoff.sources import (InputError, load_directory, load_messages, load_pages, load_tickets,
                                    parse_duration, parse_time)


def write(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(data if isinstance(data, str) else json.dumps(data))
    return path


@pytest.mark.parametrize("text,expected", [
    ("90m", timedelta(minutes=90)), ("24h", timedelta(hours=24)), ("2d", timedelta(days=2)),
    (" 1W ", timedelta(weeks=1)),
])
def test_parse_duration(text, expected):
    assert parse_duration(text) == expected


@pytest.mark.parametrize("text", ["", "24", "h", "0h", "-3h", "1.5h", "yesterday"])
def test_parse_duration_rejects_bad_input(text):
    with pytest.raises(InputError):
        parse_duration(text)


def test_parse_time_accepts_iso_epoch_and_naive():
    expected = utc(2026, 3, 2, 10, 15)
    assert parse_time("2026-03-02T10:15:00Z") == expected
    assert parse_time("2026-03-02T11:15:00+01:00") == expected
    assert parse_time("2026-03-02 10:15:00") == expected  # naive is read as UTC
    assert parse_time("1772446500.000200").replace(microsecond=0) == expected
    assert parse_time(1772446500) == expected
    assert parse_time(None) is None and parse_time("") is None
    with pytest.raises(InputError):
        parse_time("last tuesday")


def test_load_pages_accepts_wrapped_and_flat_shapes(tmp_path):
    wrapped = write(tmp_path, "a.json", {"incidents": [
        {"incident_number": 7, "summary": "db down", "service": {"summary": "orders-db"}, "status": "resolved",
         "created_at": "2026-03-02T10:00:00Z", "last_status_change_at": "2026-03-02T10:30:00Z"}]})
    page = load_pages(wrapped)[0]
    assert (page.id, page.title, page.service, page.urgency) == ("7", "db down", "orders-db", "high")
    assert page.minutes == 30 and not page.open
    flat = write(tmp_path, "b.json", [
        {"id": "b", "title": "later", "service": "api", "created_at": "2026-03-02T12:00:00Z"},
        {"id": "a", "title": "earlier", "created_at": "2026-03-02T11:00:00Z", "urgency": "LOW"}])
    first, second = load_pages(flat)
    assert [first.id, second.id] == ["a", "b"]  # sorted by time
    assert first.service == "unknown" and first.urgency == "low" and first.open and first.minutes is None


def test_load_messages_and_threads(tmp_path):
    path = write(tmp_path, "s.json", {"messages": [
        {"ts": "1772446560", "user": "U2", "text": " reply ", "thread_ts": "1772446500", "channel": "#ops"},
        {"ts": "1772446500", "user_name": "priya", "text": "root", "channel": "ops"}]})
    root, reply = load_messages(path)
    assert (root.user, root.thread, root.channel) == ("priya", "1772446500", "ops")
    assert (reply.user, reply.text, reply.thread, reply.channel) == ("U2", "reply", "1772446500", "ops")


def test_load_tickets_handles_nested_fields(tmp_path):
    path = write(tmp_path, "t.json", {"issues": [
        {"key": "OPS-1", "fields": {"summary": "Fix it", "status": {"name": "In Progress"},
                                    "priority": {"name": "Highest"}, "assignee": {"displayName": "Lena"},
                                    "updated": "2026-03-02T10:00:00Z"}},
        {"id": 2, "title": "Old", "status": "Won't Fix"}]})
    nested, flat = load_tickets(path)
    assert (nested.title, nested.status, nested.assignee) == ("Fix it", "In Progress", "Lena")
    assert nested.open and nested.urgent and nested.updated == utc(2026, 3, 2, 10)
    assert flat.key == "2" and not flat.open and not flat.urgent


@pytest.mark.parametrize("content,match", [
    ("{not json", "not valid JSON"),
    ('{"other": []}', "expected a JSON list"),
    ('["just a string"]', "expected a JSON list"),
    ('[{"title": "no time"}]', "no created_at"),
    ('[{"created_at": "garbage"}]', "unrecognised timestamp"),
])
def test_bad_page_files_raise_input_error(tmp_path, content, match):
    with pytest.raises(InputError, match=match):
        load_pages(write(tmp_path, "bad.json", content))


def test_missing_file_and_directory(tmp_path):
    with pytest.raises(InputError, match="cannot read"):
        load_pages(tmp_path / "nope.json")
    with pytest.raises(InputError, match="not a directory"):
        load_directory(tmp_path / "nope")


def test_load_directory_files_are_optional(tmp_path, examples):
    assert load_directory(tmp_path).pages == []
    shift = load_directory(examples)
    assert (len(shift.pages), len(shift.messages), len(shift.tickets)) == (9, 10, 4)
